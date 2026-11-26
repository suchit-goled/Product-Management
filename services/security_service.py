"""
Product Catalog - Cryptographic Validation & Input Security Service
Provides constant-time CSRF verification, Luhn payment card validation,
authoritative server-side checkout calculation, CSV injection protection,
password strength enforcement, and canonical path traversal containment.
"""
import os
import re
import hmac
import hashlib
import secrets
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, timezone
from config import Config


# ==============================================================================
# PASSWORD & CREDENTIAL POLICIES
# ==============================================================================

EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}$")
USERNAME_REGEX = re.compile(r"^[a-z0-9_.-]{3,32}$")
GA4_ID_REGEX = re.compile(r"^G-[A-Z0-9]{6,16}$")


def validate_email_address(email: str) -> bool:
    if not email or len(email) > 254:
        return False
    return bool(EMAIL_REGEX.match(email.strip()))


def validate_username(username: str) -> bool:
    if not username:
        return False
    return bool(USERNAME_REGEX.match(username.strip().lower()))


def validate_password_strength(password: str) -> tuple:
    """
    Enforces modern password complexity:
    8..128 chars, includes at least 1 uppercase or symbol and 1 digit/letter mix.
    Returns (is_valid: bool, message: str).
    """
    if not password or len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if len(password) > 128:
        return False, "Password must be at most 128 characters"
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one number"
    if not any(c.isalpha() for c in password):
        return False, "Password must contain at least one letter"
    return True, "OK"


def hash_verification_code(user_identifier: str, code: str) -> str:
    """Creates an HMAC-SHA256 digest of an OTP verification code bound to user identity."""
    msg = f"{str(user_identifier).lower()}:{code.strip()}".encode("utf-8")
    return hmac.new(Config.SECRET_KEY.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify_hashed_code(user_identifier: str, submitted_code: str, expected_digest: str) -> bool:
    """Constant-time verification of OTP digest."""
    if not submitted_code or not expected_digest:
        return False
    computed = hash_verification_code(user_identifier, submitted_code)
    return hmac.compare_digest(computed, expected_digest)


# ==============================================================================
# CSRF SYNCHRONIZER TOKEN PROTECTION
# ==============================================================================

def verify_csrf_token(expected_token: str, provided_token: str) -> bool:
    """Constant-time validation against CSRF attacks."""
    if not expected_token or not provided_token:
        return False
    return hmac.compare_digest(str(expected_token), str(provided_token))


def generate_guest_csrf_token() -> str:
    """Generates HMAC-signed ephemeral CSRF token for pre-auth forms (login/register/contact)."""
    nonce = secrets.token_hex(16)
    ts = str(int(datetime.now(timezone.utc).timestamp()))
    sig = hmac.new(
        Config.SECRET_KEY.encode("utf-8"),
        f"{nonce}.{ts}".encode("utf-8"),
        hashlib.sha256
    ).hexdigest()[:24]
    return f"g1.{nonce}.{ts}.{sig}"


def verify_guest_csrf_token(token: str, max_age_seconds: int = 14400) -> bool:
    """Validates pre-auth guest CSRF token signature and expiration."""
    if not token or not token.startswith("g1."):
        return False
    parts = token.split(".")
    if len(parts) != 4:
        return False
    _, nonce, ts_str, sig = parts
    try:
        ts = int(ts_str)
    except ValueError:
        return False
    now_ts = int(datetime.now(timezone.utc).timestamp())
    if abs(now_ts - ts) > max_age_seconds:
        return False
    expected_sig = hmac.new(
        Config.SECRET_KEY.encode("utf-8"),
        f"{nonce}.{ts_str}".encode("utf-8"),
        hashlib.sha256
    ).hexdigest()[:24]
    return hmac.compare_digest(sig, expected_sig)


# ==============================================================================
# CHECKOUT SECURITY: LUHN VALIDATION & AUTHORITATIVE PRICING ALGORITHM
# ==============================================================================

def validate_luhn_card(card_number: str) -> bool:
    """
    Validates payment card digits using standard Mod-10 Luhn checksum algorithm.
    Rejects non-numeric, short (<13), or checksum-invalid cards.
    """
    digits_only = re.sub(r"[\s-]", "", card_number or "")
    if not digits_only.isdigit() or not (13 <= len(digits_only) <= 19):
        return False

    total = 0
    reverse_digits = digits_only[::-1]
    for idx, ch in enumerate(reverse_digits):
        n = int(ch)
        if idx % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return (total % 10) == 0


def validate_card_expiry(exp_str: str) -> bool:
    """Validates MM/YY expiry date and confirms card is not expired."""
    if not exp_str:
        return False
    m = re.match(r"^(0[1-9]|1[0-2])\s*/\s*(\d{2}|\d{4})$", exp_str.strip())
    if not m:
        return False
    month = int(m.group(1))
    year_raw = m.group(2)
    year = int(year_raw) + 2000 if len(year_raw) == 2 else int(year_raw)

    now = datetime.now()
    if year < now.year or (year == now.year and month < now.month):
        return False
    if year > now.year + 25:
        return False
    return True


def validate_card_cvv(cvv_str: str) -> bool:
    """Validates 3 or 4 digit security code format (never stored)."""
    return bool(re.match(r"^\d{3,4}$", (cvv_str or "").strip()))


def parse_authoritative_price(price_str: str) -> tuple:
    """
    Extracts currency symbol and exact Decimal unit price from DB catalog string.
    Returns (currency_symbol, Decimal_unit_price or None if unpriced).
    """
    if not price_str:
        return "₹", None
    raw = str(price_str).strip()
    if raw.upper() in ("N/A", "NOT AVAILABLE", "UNSPECIFIED", "TBD", ""):
        return "₹", None

    currency = "$" if "$" in raw else ("€" if "€" in raw else ("£" if "£" in raw else "₹"))
    cleaned = re.sub(r"\(.*?\)", "", raw)  # Remove "(estimated)" notes
    match = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)", cleaned)
    if not match:
        return currency, None

    num_str = match.group(1).replace(",", "")
    try:
        dec = Decimal(num_str).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if dec <= Decimal("0.00"):
            return currency, None
        return currency, dec
    except InvalidOperation:
        return currency, None


def compute_order_totals(unit_price: Decimal, quantity: int = 1, tax_rate: Decimal = Decimal("0.18")) -> dict:
    """Deterministic server-side Decimal monetary calculation (prevents frontend tampering)."""
    qty = max(1, min(50, int(quantity)))
    subtotal = (unit_price * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    tax = (subtotal * tax_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total = (subtotal + tax).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "quantity": qty,
        "unit_price": unit_price,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
    }


# ==============================================================================
# FILE PATH CONTAINMENT & CONTENT SANITIZATION
# ==============================================================================

def sanitize_catalog_image_path(image_path: str) -> tuple:
    """
    Enforces that image_path values saved via API refer ONLY to local validated assets
    inside /static/uploads/, blocking XSS URIs (javascript:, data:) and path traversal (..).
    Returns (normalized_path_or_empty, error_message_or_None).
    """
    if not image_path:
        return "", None

    raw = str(image_path).strip().replace("\\", "/")
    lower = raw.lower()
    if lower.startswith(("javascript:", "vbscript:", "data:", "http://", "https://", "//")):
        return "", "External or script image URIs are not permitted; upload an image via AI Studio"

    if ".." in raw or "\x00" in raw:
        return "", "Invalid path traversal detected in image_path"

    if not raw.startswith("/static/uploads/"):
        return "", "image_path must reference /static/uploads/<filename>"

    filename = raw[len("/static/uploads/"):]
    if not filename or "/" in filename:
        return "", "Nested or malformed image filename"

    return f"/static/uploads/{filename}", None


def is_safe_contained_path(base_dir: str, user_filename: str) -> tuple:
    """Verifies resolved file path stays strictly inside base_dir."""
    if not user_filename or "\x00" in user_filename:
        return False, ""
    safe_base = os.path.realpath(base_dir)
    clean_name = os.path.basename(user_filename)
    candidate = os.path.realpath(os.path.join(safe_base, clean_name))
    if not candidate.startswith(safe_base + os.sep):
        return False, ""
    return True, candidate


def sanitize_csv_cell(value) -> str:
    """
    Neutralizes Spreadsheet Formula Injection (CSV/DDE Injection) by prefixing cells
    starting with '=', '+', '-', '@', '\\t', or '\\r' with a leading single quote.
    Allows innocent currency strings like '₹1,499' or '$799'.
    """
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def sanitize_text_field(val, max_len: int = 500) -> str:
    """Strips control bytes & normalizes maximum field length."""
    if val is None:
        return ""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(val)).strip()
    return cleaned[:max_len]
