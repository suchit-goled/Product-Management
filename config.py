"""
Suchit Catalog - Application Configuration Module
Handles environment variables, CSPRNG secret key provisioning, security policies,
database paths, cache/session TTLs, SMTP/domain email, analytics, and backups.
"""
import os
import secrets
import logging
from dotenv import load_dotenv, set_key

logger = logging.getLogger("suchit.config")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

WEAK_SECRET_PLACEHOLDERS = {
    "",
    "your_secret_key",
    "changeme",
    "secret",
    "dev",
    "suchit-catalog-secret-key-prod-2026",
}


def _load_or_generate_secret_key() -> str:
    """
    Loads a strong SECRET_KEY from environment/.env, or generates a persistent
    256-bit CSPRNG secret key on first run so cookies/HMACs never use defaults.
    """
    env_secret = os.getenv("SECRET_KEY", "").strip()
    if env_secret and env_secret not in WEAK_SECRET_PLACEHOLDERS and len(env_secret) >= 32:
        return env_secret

    secret_file = os.path.join(BASE_DIR, ".suchit_secret")
    if os.path.exists(secret_file):
        try:
            with open(secret_file, "r", encoding="utf-8") as f:
                file_secret = f.read().strip()
            if len(file_secret) >= 32:
                return file_secret
        except OSError:
            pass

    new_secret = secrets.token_hex(32)
    try:
        if os.path.exists(ENV_PATH):
            set_key(ENV_PATH, "SECRET_KEY", new_secret)
        else:
            with open(secret_file, "w", encoding="utf-8") as f:
                f.write(new_secret)
    except Exception as exc:
        logger.warning(f"Could not persist generated SECRET_KEY: {exc}")
    return new_secret


class Config:
    # Security & Stateless Session Config
    SECRET_KEY = _load_or_generate_secret_key()
    SESSION_COOKIE_NAME = "suchit_sid"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "False").lower() in ("true", "1", "yes")
    PERMANENT_SESSION_LIFETIME = 86400 * 7  # 7 days
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB strict upload boundary

    # Allowed Origins for CORS (comma-separated in .env; defaults strictly to same-origin local)
    RAW_ALLOWED_ORIGINS = os.getenv(
        "ALLOWED_ORIGINS",
        "http://127.0.0.1:5000,http://localhost:5000"
    )
    ALLOWED_ORIGINS = [o.strip() for o in RAW_ALLOWED_ORIGINS.split(",") if o.strip()]

    # AI Integration
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

    # Database & Storage
    _db_env = os.getenv("DATABASE", "products.db").strip()
    DATABASE = _db_env if os.path.isabs(_db_env) else os.path.join(BASE_DIR, _db_env)

    _up_env = os.getenv("UPLOAD_FOLDER", os.path.join("static", "uploads")).strip()
    UPLOAD_FOLDER = _up_env if os.path.isabs(_up_env) else os.path.join(BASE_DIR, _up_env)

    _bk_env = os.getenv("BACKUP_FOLDER", "backups").strip()
    BACKUP_FOLDER = _bk_env if os.path.isabs(_bk_env) else os.path.join(BASE_DIR, _bk_env)
    BASE_DIR = BASE_DIR

    # Cache & Rate Limiting
    CATALOG_CACHE_TTL_SECONDS = int(os.getenv("CATALOG_CACHE_TTL", "60"))
    CDN_STATIC_MAX_AGE = int(os.getenv("CDN_STATIC_MAX_AGE", "86400"))

    # Google Analytics 4 (GA4)
    GOOGLE_ANALYTICS_ID = os.getenv("GOOGLE_ANALYTICS_ID", "").strip()

    # WhatsApp Support
    WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER", "+919876543210").strip()
    WHATSAPP_MESSAGE = os.getenv(
        "WHATSAPP_MESSAGE",
        "Hello Suchit Catalog Support! I have a question regarding product cataloging."
    ).strip()

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
    APP_VERSION = "2.3.0"
