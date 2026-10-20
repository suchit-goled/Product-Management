import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Load .env from current directory or parent directory if present
load_dotenv(os.path.join(BASE_DIR, ".env"))

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "suchit-catalog-secret-key-2026")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    DATABASE = os.getenv("DATABASE", os.path.join(BASE_DIR, "products.db"))
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", os.path.join(BASE_DIR, "static", "uploads"))
    BASE_DIR = BASE_DIR
