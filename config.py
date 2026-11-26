"""
Product Catalog - Application Configuration Module
Handles environment variables, CSPRNG secret key provisioning, security policies,
database paths, cache/session TTLs, SMTP/domain email, and backups.
"""
import os
import shutil
import secrets
import tempfile
import logging
from dotenv import load_dotenv, set_key

logger = logging.getLogger("product_catalog.config")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

IS_SERVERLESS = bool(
    os.getenv("VERCEL") or os.getenv("VERCEL_ENV") or os.getenv("AWS_LAMBDA_FUNCTION_NAME")
)

WEAK_SECRET_PLACEHOLDERS = {
    "",
    "your_secret_key",
    "changeme",
    "secret",
    "dev",
    "product-catalog-secret-key-prod-2026",
}


def _is_dir_writable(dir_path: str) -> bool:
    try:
        return bool(dir_path and os.path.isdir(dir_path) and os.access(dir_path, os.W_OK))
    except OSError:
        return False


def _load_or_generate_secret_key() -> str:
    """
    Loads a strong SECRET_KEY from environment/.env, or generates a persistent
    256-bit CSPRNG secret key on first run so cookies/HMACs never use defaults.
    """
    env_secret = os.getenv("SECRET_KEY", "").strip()
    if env_secret and env_secret not in WEAK_SECRET_PLACEHOLDERS and len(env_secret) >= 32:
        return env_secret

    if IS_SERVERLESS or not _is_dir_writable(BASE_DIR):
        logger.warning(
            "SECRET_KEY is not configured in serverless environment; using ephemeral /tmp fallback. "
            "Set SECRET_KEY in Vercel Environment Variables for persistent multi-instance sessions."
        )
        secret_file = os.path.join(tempfile.gettempdir(), ".catalog_secret")
    else:
        secret_file = os.path.join(BASE_DIR, ".catalog_secret")

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
        if not IS_SERVERLESS and _is_dir_writable(BASE_DIR) and os.path.exists(ENV_PATH):
            set_key(ENV_PATH, "SECRET_KEY", new_secret)
        else:
            with open(secret_file, "w", encoding="utf-8") as f:
                f.write(new_secret)
    except Exception as exc:
        logger.warning(f"Could not persist generated SECRET_KEY: {exc}")
    return new_secret


def _is_under_base(path: str) -> bool:
    try:
        base_real = os.path.realpath(BASE_DIR)
        target_real = os.path.realpath(path)
        return target_real == base_real or target_real.startswith(base_real + os.sep)
    except OSError:
        return True


def _resolve_writable_dir(env_key: str, default_rel: str, tmp_subdir: str) -> str:
    raw = os.getenv(env_key, "").strip()
    if raw:
        candidate = raw if os.path.isabs(raw) else os.path.join(BASE_DIR, raw)
        if not IS_SERVERLESS and _is_dir_writable(os.path.dirname(candidate) or BASE_DIR):
            return candidate
        if IS_SERVERLESS and not _is_under_base(candidate) and _is_dir_writable(os.path.dirname(candidate)):
            return candidate
    if IS_SERVERLESS or not _is_dir_writable(BASE_DIR):
        return os.path.join(tempfile.gettempdir(), tmp_subdir)
    return os.path.join(BASE_DIR, default_rel)


def _resolve_database_path() -> str:
    db_env = os.getenv("DATABASE", "products.db").strip()
    candidate = db_env if os.path.isabs(db_env) else os.path.join(BASE_DIR, db_env)
    parent = os.path.dirname(candidate) or BASE_DIR

    if not IS_SERVERLESS and _is_dir_writable(parent):
        return candidate
    if IS_SERVERLESS and not _is_under_base(candidate) and _is_dir_writable(parent):
        return candidate

    # Serverless / read-only deployment bundle: seed writable SQLite runtime copy into temp dir
    runtime_db = os.path.join(tempfile.gettempdir(), "product_catalog_runtime.db")
    if not os.path.exists(runtime_db) and os.path.isfile(candidate):
        try:
            shutil.copyfile(candidate, runtime_db)
            os.chmod(runtime_db, 0o644)
            logger.info(f"Seeded writable runtime SQLite DB in temp dir from {candidate}")
        except OSError as exc:
            logger.warning(f"Could not copy bundled database to temp dir: {exc}")
    return runtime_db


def _build_allowed_origins() -> list:
    raw = os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:5000,http://localhost:5000")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    for env_host_key in ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
        host = os.getenv(env_host_key, "").strip()
        if host:
            origin = host if host.startswith(("http://", "https://")) else f"https://{host}"
            if origin not in origins:
                origins.append(origin)
    return origins


class Config:
    IS_SERVERLESS = IS_SERVERLESS

    # Security & Stateless Session Config
    SECRET_KEY = _load_or_generate_secret_key()
    SESSION_COOKIE_NAME = "catalog_sid"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv(
        "SESSION_COOKIE_SECURE",
        "True" if IS_SERVERLESS else "False"
    ).lower() in ("true", "1", "yes")
    PERMANENT_SESSION_LIFETIME = 86400 * 7  # 7 days
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB strict upload boundary

    # Allowed Origins for CORS (comma-separated in .env; auto-includes Vercel deployment URLs)
    RAW_ALLOWED_ORIGINS = os.getenv(
        "ALLOWED_ORIGINS",
        "http://127.0.0.1:5000,http://localhost:5000"
    )
    ALLOWED_ORIGINS = _build_allowed_origins()
    TRUST_PROXY = os.getenv(
        "TRUST_PROXY",
        "True" if IS_SERVERLESS else "False"
    ).lower() in ("true", "1", "yes")

    # AI Integration (Strictly server-side environment variables; never exposed to frontend)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
    GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct").strip()
    GROQ_TEXT_MODEL = os.getenv("GROQ_TEXT_MODEL", "llama-3.3-70b-versatile").strip()

    # Database & Storage
    DATABASE = _resolve_database_path()
    BUNDLED_UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
    UPLOAD_FOLDER = _resolve_writable_dir("UPLOAD_FOLDER", os.path.join("static", "uploads"), "catalog_uploads")
    BACKUP_FOLDER = _resolve_writable_dir("BACKUP_FOLDER", "backups", "catalog_backups")
    BASE_DIR = BASE_DIR

    # Cache & Rate Limiting
    CATALOG_CACHE_TTL_SECONDS = int(os.getenv("CATALOG_CACHE_TTL", "60"))
    CDN_STATIC_MAX_AGE = int(os.getenv("CDN_STATIC_MAX_AGE", "86400"))

    # Google Analytics 4 (GA4)
    GOOGLE_ANALYTICS_ID = os.getenv("GOOGLE_ANALYTICS_ID", "").strip()

    # Optional Public Support Contact (disabled unless explicitly configured)
    WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER", "").strip()
    WHATSAPP_MESSAGE = os.getenv(
        "WHATSAPP_MESSAGE",
        "Hello Product Catalog Support! I have a question regarding product listings."
    ).strip()

    # Domain Email & SMTP
    DOMAIN_EMAIL = os.getenv("DOMAIN_EMAIL", "support@product-catalog.com").strip()
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.product-catalog.com").strip()
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "True").lower() in ("true", "1", "yes")
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "support@product-catalog.com").strip()
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "").strip()
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "Product Catalog <support@product-catalog.com>").strip()

    # Application Branding
    APP_NAME = "Product Catalog"
    APP_VERSION = "2.3.0"
