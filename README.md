# Mental Health Portal

A web application for booking mental health appointments and accessing a supportive chatbot for mental health inquiries.

## Features

- Book appointments with mental health professionals
- Chat with an AI assistant about mental health concerns
- User-friendly interface
- Secure data handling

## Setup Instructions

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the project root and add your OpenAI API key:
```
OPENAI_API_KEY=your_api_key_here
```

4. Run the application:
```bash
python app.py
```

5. Open your browser and navigate to `http://localhost:5000`

## Security Note

This is a basic implementation. For production use, please ensure:
- Proper authentication and authorization
- HTTPS encryption
- HIPAA compliance measures
- Secure database configuration
- Input validation and sanitization

## Technologies Used

- Backend: Flask
- Database: SQLite with SQLAlchemy
- Frontend: HTML, CSS (Bootstrap), JavaScript
- AI: OpenAI GPT-3.5 for chatbot functionality
