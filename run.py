"""
Entry point to launch the AnswerWeave AI Chatbot server.
"""

import sys
import uvicorn
import os

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Starting AnswerWeave AI Engine...")
    print("📍 Dashboard & Admin Console: http://127.0.0.1:8000")
    print("🌐 External Website Widget Demo: http://127.0.0.1:8000/demo")
    print("📄 API Documentation (Swagger):  http://127.0.0.1:8000/docs")
    print("=" * 60)
    
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
