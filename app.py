import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, and_
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timedelta
import stripe
import json
import requests
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
stripe_public_key = os.getenv('STRIPE_PUBLIC_KEY')

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-here')

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///mental_health.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Initialize extensions
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Models
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(100))
    specialization = db.Column(db.String(100))
    photo = db.Column(db.String(255))  # Store the photo filename
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Appointments where user is the patient
    patient_appointments = db.relationship('Appointment',
                                         foreign_keys='Appointment.patient_id',
                                         backref='patient',
                                         lazy=True)
    
    # Appointments where user is the doctor
    doctor_appointments = db.relationship('Appointment',
                                        foreign_keys='Appointment.doctor_id',
                                        backref='doctor',
                                        lazy=True)
    
    # Mood entries relationship
    mood_entries = db.relationship('MoodEntry', backref='mood_user', lazy=True)

    # Doctor feedbacks relationship
    doctor_feedbacks = db.relationship('DoctorFeedback', foreign_keys='DoctorFeedback.doctor_id', backref='feedback_as_doctor', lazy=True)
    given_feedbacks = db.relationship('DoctorFeedback', foreign_keys='DoctorFeedback.patient_id', backref='feedback_as_patient', lazy=True)

class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.String(10), nullable=False)  # Format: YYYY-MM-DD
    time = db.Column(db.String(5), nullable=False)   # Format: HH:MM
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # pending, confirmed, cancelled, completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class MoodEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    mood_level = db.Column(db.Integer, nullable=False)  # 1-5 scale
    activities = db.Column(db.String(200))  # Comma-separated activities
    notes = db.Column(db.Text)
    triggers = db.Column(db.String(200))  # Potential triggers
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow().date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class DoctorFeedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5 stars
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    doctor = db.relationship('User', foreign_keys=[doctor_id], backref='feedback_as_doctor')
    patient = db.relationship('User', foreign_keys=[patient_id], backref='feedback_as_patient')

# Create all database tables
with app.app_context():
    try:
        # Drop all tables and recreate
        db.drop_all()
        db.create_all()
        
        # Create initial admin user
        admin_user = User(
            username='admin',
            email='admin@example.com',
            password=generate_password_hash('admin123'),
            role='admin'
        )
        
        # Create default doctor
        doctor_user = User(
            username='Dr. Smith',
            email='smith@example.com',
            password=generate_password_hash('doctor123'),
            role='doctor',
            specialization='Clinical Psychology'
        )
        
        db.session.add(admin_user)
        db.session.add(doctor_user)
        db.session.commit()
        print("Database initialized with admin and doctor users successfully!")
    except Exception as e:
        print("Error initializing database:", str(e))

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in first.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Admin required decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'role' not in session or session['role'] != 'admin':
            flash('Admin access required.', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# Doctor required decorator
def doctor_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'role' not in session or session['role'] != 'doctor':
            flash('Doctor access required.', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def auto_complete_past_appointments():
    """Automatically mark past confirmed appointments as completed."""
    today = datetime.now().strftime('%Y-%m-%d')
    past_confirmed = Appointment.query.filter(
        Appointment.status == 'confirmed',
        Appointment.date < today
    ).all()
    
    for appointment in past_confirmed:
        appointment.status = 'completed'
    
    if past_confirmed:
        db.session.commit()

@app.before_request
def before_request():
    if not request.path.startswith('/static'):
        auto_complete_past_appointments()

# Routes
@app.route('/')
def home():
    # Initialize session if not exists
    if 'user_id' not in session:
        session['user_id'] = None
        session['role'] = None
        session['username'] = None
    
    if session['user_id']:
        user = User.query.get(session['user_id'])
        return render_template('index.html', user=user)
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            session['user_id'] = user.id
            session['role'] = user.role
            session['username'] = user.name or user.username  # Use name if available, otherwise username
            flash('Logged in successfully!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid username or password.', 'danger')
    
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        role = request.form.get('role', 'patient')
        name = request.form.get('name', username)  # Use username as default name if not provided
        
        if not all([username, email, password, confirm_password]):
            flash('Please fill in all fields', 'error')
            return redirect(url_for('signup'))
        
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return redirect(url_for('signup'))
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return redirect(url_for('signup'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return redirect(url_for('signup'))
        
        hashed_password = generate_password_hash(password)
        new_user = User(
            username=username,
            email=email,
            password=hashed_password,
            role=role,
            name=name
        )
        
        try:
            db.session.add(new_user)
            db.session.commit()
            flash('Account created successfully! Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash('Error creating account. Please try again.', 'error')
            print(f"Error: {str(e)}")
    
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully!', 'success')
    return redirect(url_for('home'))

@app.route('/appointments')
@login_required
def appointments():
    auto_complete_past_appointments()
    today = datetime.now().strftime('%Y-%m-%d')
    
    if session.get('role') == 'patient':
        doctors = User.query.filter_by(role='doctor').all()
        current_appointments = Appointment.query.filter_by(
            patient_id=session['user_id']
        ).filter(
            Appointment.status.in_(['pending', 'confirmed'])
        ).order_by(Appointment.date.asc()).all()
        
        past_appointments = Appointment.query.filter_by(
            patient_id=session['user_id']
        ).filter(
            Appointment.status.in_(['completed', 'cancelled'])
        ).order_by(Appointment.date.desc()).all()
        
        return render_template('appointments.html', 
                             doctors=doctors,
                             current_appointments=current_appointments,
                             past_appointments=past_appointments,
                             today=today)
    else:
        appointments = Appointment.query.filter_by(
            doctor_id=session['user_id']
        ).filter(
            Appointment.status.in_(['pending', 'confirmed'])
        ).order_by(Appointment.date.asc()).all()
        
        return render_template('appointments.html', 
                             appointments=appointments,
                             today=today)

@app.route('/appointments/create', methods=['POST'])
@login_required
def create_appointment():
    try:
        doctor_id = request.form.get('doctor_id')
        date = request.form.get('date')
        time = request.form.get('time')
        notes = request.form.get('notes')

        if not all([doctor_id, date, time]):
            flash('Please fill in all required fields', 'error')
            return redirect(url_for('appointments'))

        # Create new appointment
        new_appointment = Appointment(
            patient_id=session['user_id'],
            doctor_id=doctor_id,
            date=date,
            time=time,
            notes=notes,
            status='confirmed'
        )
        db.session.add(new_appointment)
        db.session.commit()

        flash('Appointment booked successfully!', 'success')
        return redirect(url_for('appointments'))

    except Exception as e:
        flash(f'Error booking appointment: {str(e)}', 'error')
        return redirect(url_for('appointments'))

@app.route('/appointments/<int:appointment_id>/cancel', methods=['POST'])
@login_required
def cancel_appointment(appointment_id):
    try:
        appointment = Appointment.query.get_or_404(appointment_id)
        
        # Verify the appointment belongs to the current user
        if appointment.patient_id != session['user_id']:
            flash('Unauthorized access', 'error')
            return redirect(url_for('appointments'))

        db.session.delete(appointment)
        db.session.commit()
        flash('Appointment cancelled successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error cancelling appointment. Please try again.', 'error')
        print(f"Error: {str(e)}")

    return redirect(url_for('appointments'))

@app.route('/self_help')
def self_help():
    if not session.get('user_id'):
        flash('Please log in to access self-help resources', 'info')
        return redirect(url_for('login'))
    return render_template('self_help.html')

@app.route('/self_help/sleep')
def sleep_hygiene():
    return render_template('sleep_hygiene.html')

@app.route('/self_help/stress')
def stress():
    return render_template('stress.html')

@app.route('/self_help/exercise')
def exercise():
    return render_template('exercise.html')

@app.route('/self_help/anxiety')
def anxiety():
    return render_template('anxiety.html')

@app.route('/meditation')
@login_required
def meditation():
    return render_template('meditation.html')

@app.route('/admin')
@login_required
@admin_required
def admin():
    users = User.query.all()
    appointments = Appointment.query.all()
    return render_template('admin.html', users=users, appointments=appointments)

@app.route('/make_admin/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def make_admin(user_id):
    user = User.query.get_or_404(user_id)
    user.role = 'admin'
    db.session.commit()
    flash(f'User {user.username} is now an admin', 'success')
    return redirect(url_for('admin'))

@app.route('/make_doctor/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def make_doctor(user_id):
    user = User.query.get_or_404(user_id)
    user.role = 'doctor'
    db.session.commit()
    flash(f'User {user.username} is now a doctor', 'success')
    return redirect(url_for('admin'))

@app.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    if user_id == session.get('user_id'):
        flash('Cannot delete your own account', 'error')
        return redirect(url_for('admin'))
    
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash(f'User {user.username} has been deleted', 'success')
    return redirect(url_for('admin'))

@app.route('/doctor/dashboard')
@login_required
@doctor_required
def doctor_dashboard():
    # Double check role for security
    if session.get('role') != 'doctor':
        flash('Access denied. Only doctors can view this page.', 'danger')
        return redirect(url_for('home'))
    
    # Get today's date
    today = datetime.now().strftime('%Y-%m-%d')
    
    # Get today's appointments
    today_appointments = Appointment.query.filter_by(
        doctor_id=session['user_id'],
        date=today
    ).order_by(Appointment.time).all()
    
    # Get upcoming appointments (excluding today)
    upcoming_appointments = Appointment.query.filter(
        Appointment.doctor_id == session['user_id'],
        Appointment.date > today
    ).order_by(Appointment.date, Appointment.time).all()
    
    # Count unique patients
    total_patients = db.session.query(
        db.func.count(db.distinct(Appointment.patient_id))
    ).filter_by(doctor_id=session['user_id']).scalar()
    
    return render_template('doctor_dashboard.html',
                         today_appointments=today_appointments,
                         upcoming_appointments=upcoming_appointments,
                         total_patients=total_patients)

@app.route('/appointment/confirm/<int:appointment_id>', methods=['POST'])
@login_required
@doctor_required
def confirm_appointment(appointment_id):
    # Double check role and ownership
    if session.get('role') != 'doctor':
        flash('Access denied. Only doctors can confirm appointments.', 'danger')
        return redirect(url_for('home'))
        
    appointment = Appointment.query.get_or_404(appointment_id)
    
    # Verify the appointment belongs to this doctor
    if appointment.doctor_id != session['user_id']:
        flash('Access denied. This appointment belongs to another doctor.', 'danger')
        return redirect(url_for('doctor_dashboard'))
    
    appointment.status = 'confirmed'
    db.session.commit()
    flash('Appointment confirmed successfully!', 'success')
    return redirect(url_for('doctor_dashboard'))

@app.route('/appointment/complete/<int:appointment_id>', methods=['POST'])
@login_required
@doctor_required
def mark_completed(appointment_id):
    # Double check role and ownership
    if session.get('role') != 'doctor':
        flash('Access denied. Only doctors can mark appointments as completed.', 'danger')
        return redirect(url_for('home'))
        
    appointment = Appointment.query.get_or_404(appointment_id)
    
    # Verify the appointment belongs to this doctor
    if appointment.doctor_id != session['user_id']:
        flash('Access denied. This appointment belongs to another doctor.', 'danger')
        return redirect(url_for('doctor_dashboard'))
    
    # Only confirmed appointments can be marked as completed
    if appointment.status != 'confirmed':
        flash('Only confirmed appointments can be marked as completed.', 'warning')
        return redirect(url_for('doctor_dashboard'))
    
    appointment.status = 'completed'
    db.session.commit()
    flash('Appointment marked as completed.', 'success')
    return redirect(url_for('doctor_dashboard'))

@app.route('/mood')
@login_required
def mood_tracker():
    # Get user's mood entries for the last 7 days
    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=6)
    
    mood_entries = MoodEntry.query.filter(
        MoodEntry.user_id == session['user_id'],
        MoodEntry.date >= start_date,
        MoodEntry.date <= end_date
    ).order_by(MoodEntry.date.desc()).all()
    
    # Calculate mood statistics
    if mood_entries:
        avg_mood = sum(entry.mood_level for entry in mood_entries) / len(mood_entries)
        most_common_triggers = {}
        for entry in mood_entries:
            if entry.triggers:
                for trigger in entry.triggers.split(','):
                    trigger = trigger.strip()
                    most_common_triggers[trigger] = most_common_triggers.get(trigger, 0) + 1
        top_triggers = sorted(most_common_triggers.items(), key=lambda x: x[1], reverse=True)[:3]
    else:
        avg_mood = 0
        top_triggers = []
    
    return render_template('mood_tracker.html', 
                         mood_entries=mood_entries,
                         avg_mood=avg_mood,
                         top_triggers=top_triggers)

@app.route('/mood/add', methods=['POST'])
@login_required
def add_mood_entry():
    mood_level = request.form.get('mood_level', type=int)
    activities = request.form.get('activities')
    notes = request.form.get('notes')
    triggers = request.form.get('triggers')
    
    if not mood_level or mood_level < 1 or mood_level > 5:
        flash('Please select a valid mood level (1-5)', 'error')
        return redirect(url_for('mood_tracker'))
    
    new_entry = MoodEntry(
        user_id=session['user_id'],
        mood_level=mood_level,
        activities=activities,
        notes=notes,
        triggers=triggers
    )
    
    db.session.add(new_entry)
    db.session.commit()
    
    flash('Mood entry added successfully!', 'success')
    return redirect(url_for('mood_tracker'))

@app.route('/forms_dashboard')
@login_required
def forms_dashboard():
    if session.get('role') != 'doctor':
        flash('Access denied. Only doctors can view form results.', 'error')
        return redirect(url_for('home'))
    return render_template('forms_dashboard.html')

@app.route('/submit_feedback/<int:doctor_id>', methods=['POST'])
@login_required
def submit_feedback(doctor_id):
    if request.method == 'POST':
        rating = request.form.get('rating')
        comment = request.form.get('comment')
        
        if not rating or not rating.isdigit() or int(rating) < 1 or int(rating) > 5:
            flash('Please provide a valid rating between 1 and 5 stars.', 'error')
            return redirect(url_for('appointments'))
        
        # Check if user has an appointment with this doctor
        appointment = Appointment.query.filter_by(
            patient_id=session['user_id'],
            doctor_id=doctor_id
        ).first()
        
        if not appointment:
            flash('You can only provide feedback for doctors you have had appointments with.', 'error')
            return redirect(url_for('appointments'))
        
        # Check if user already gave feedback
        existing_feedback = DoctorFeedback.query.filter_by(
            patient_id=session['user_id'],
            doctor_id=doctor_id
        ).first()
        
        if existing_feedback:
            flash('You have already provided feedback for this doctor.', 'error')
            return redirect(url_for('appointments'))
        
        feedback = DoctorFeedback(
            doctor_id=doctor_id,
            patient_id=session['user_id'],
            rating=int(rating),
            comment=comment
        )
        
        db.session.add(feedback)
        db.session.commit()
        
        flash('Thank you for your feedback!', 'success')
        return redirect(url_for('appointments'))

@app.route('/view_feedback')
@admin_required
def view_feedback():
    doctor_feedback = {}
    feedbacks = DoctorFeedback.query.all()
    
    for feedback in feedbacks:
        if feedback.doctor not in doctor_feedback:
            doctor_feedback[feedback.doctor] = {
                'feedbacks': [],
                'total_reviews': 0,
                'avg_rating': 0
            }
        
        doctor_feedback[feedback.doctor]['feedbacks'].append(feedback)
        doctor_feedback[feedback.doctor]['total_reviews'] += 1
        
        # Calculate average rating
        total_rating = sum(f.rating for f in doctor_feedback[feedback.doctor]['feedbacks'])
        doctor_feedback[feedback.doctor]['avg_rating'] = total_rating / doctor_feedback[feedback.doctor]['total_reviews']
    
    return render_template('view_feedback.html', doctor_feedback=doctor_feedback)

@app.route('/patient/feedback/<int:appointment_id>')
@login_required
def patient_feedback(appointment_id):
    if session.get('role') != 'patient':
        flash('Access denied.', 'danger')
        return redirect(url_for('home'))
        
    appointment = Appointment.query.get_or_404(appointment_id)
    
    # Check if this is the patient's appointment and it's completed
    if appointment.patient_id != session.get('user_id') or appointment.status != 'completed':
        flash('Invalid appointment or not completed yet.', 'danger')
        return redirect(url_for('appointments'))
        
    return render_template('patient_feedback.html', doctor=appointment.doctor)

@app.route('/upload_photo', methods=['POST'])
@login_required
def upload_photo():
    if current_user.role != 'doctor':
        flash('Only doctors can upload photos', 'error')
        return redirect(url_for('profile'))

    try:
        if 'photo' not in request.files:
            flash('No photo uploaded', 'error')
            return redirect(url_for('profile'))

        photo = request.files['photo']
        if photo.filename == '':
            flash('No photo selected', 'error')
            return redirect(url_for('profile'))

        if photo and allowed_file(photo.filename):
            # Secure the filename
            filename = secure_filename(photo.filename)
            # Add timestamp to make filename unique
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            # Create uploads directory if it doesn't exist
            os.makedirs(os.path.join(app.static_folder, 'uploads'), exist_ok=True)
            # Save the file
            photo.save(os.path.join(app.static_folder, 'uploads', filename))
            
            # Update user's photo in database
            current_user.photo = filename
            db.session.commit()
            
            flash('Photo uploaded successfully!', 'success')
        else:
            flash('Invalid file type. Please upload an image file (jpg, jpeg, png, gif)', 'error')
            
        return redirect(url_for('profile'))
        
    except Exception as e:
        flash(f'Error uploading photo: {str(e)}', 'error')
        return redirect(url_for('profile'))

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
