"""
Suchit Catalog - Application Configuration Module
Handles environment variables, security keys, database paths, SMTP/domain email,
Google Analytics, WhatsApp support, and backup configurations.
"""
import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Load .env from current directory
load_dotenv(os.path.join(BASE_DIR, ".env"))


class Config:
    # Security & Sessions
    SECRET_KEY = os.getenv("SECRET_KEY", "suchit-catalog-secret-key-prod-2026")
    SESSION_COOKIE_NAME = "suchit_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 86400 * 7  # 7 days

    # AI Integration
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

    # Database & Storage
    DATABASE = os.getenv("DATABASE", os.path.join(BASE_DIR, "products.db"))
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", os.path.join(BASE_DIR, "static", "uploads"))
    BACKUP_FOLDER = os.getenv("BACKUP_FOLDER", os.path.join(BASE_DIR, "backups"))
    BASE_DIR = BASE_DIR

    # Google Analytics 4 (GA4)
    GOOGLE_ANALYTICS_ID = os.getenv("GOOGLE_ANALYTICS_ID", "").strip()

    # WhatsApp Support
    WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER", "+919876543210").strip()
    WHATSAPP_MESSAGE = os.getenv("WHATSAPP_MESSAGE", "Hello Suchit Catalog Support! I have a question regarding product cataloging.").strip()

    # Domain Email & SMTP
    DOMAIN_EMAIL = os.getenv("DOMAIN_EMAIL", "support@suchitcatalog.com").strip()
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.suchitcatalog.com").strip()
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "True").lower() in ("true", "1", "yes")
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "support@suchitcatalog.com").strip()
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "").strip()
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "Suchit Catalog <support@suchitcatalog.com>").strip()

    # Application Branding
    APP_NAME = "Suchit Product Catalog Generator"
    APP_VERSION = "2.2.0"
