"""
Product Catalog - Database Management Module ("Database: Source of truth")
SQLite WAL-mode data layer with non-destructive auto-migration, strict input validation,
cryptographic OTP verification, brute-force account lockout, server-side checkout pricing,
L1/L2 Cache integration, and Message Queue job dispatching.
"""
import sqlite3
import json
import time
import logging
import secrets
import string
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

from config import Config
from services import cache_service, queue_service, security_service

logger = logging.getLogger("product_catalog.database")


def get_db_connection():
    """Returns a new WAL-enabled SQLite connection with foreign keys and Row factory."""
    conn = sqlite3.connect(Config.DATABASE, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _safe_add_columns(cursor, table_name: str, columns: list):
    """Adds columns non-destructively if missing."""
    cursor.execute(f"PRAGMA table_info({table_name});")
    existing = {row["name"] for row in cursor.fetchall()}
    for col_name, col_type in columns:
        if col_name not in existing:
            logger.info(f"Migrating {table_name}: adding column {col_name}")
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type};")


def init_db():
    """
    Initializes all authoritative tables, Cache & Message Queue tables,
    performs safe column migrations, and seeds verified initial accounts.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Products Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT NOT NULL,
        brand TEXT,
        price TEXT,
        features TEXT,
        dimensions TEXT
    )
    """)
    _safe_add_columns(cursor, "products", [
        ("category", "TEXT"),
        ("description", "TEXT"),
        ("short_description", "TEXT"),
        ("model", "TEXT"),
        ("specifications", "TEXT"),
        ("selling_points", "TEXT"),
        ("tags", "TEXT"),
        ("seo_title", "TEXT"),
        ("seo_description", "TEXT"),
        ("image_path", "TEXT"),
        ("extraction_source", "TEXT"),
        ("status", "TEXT"),
        ("created_at", "TEXT"),
        ("updated_at", "TEXT"),
    ])

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_id ON products(id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);")

    # 2. Users Table (Authentication, RBAC & Lockout)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'viewer',
        is_verified INTEGER DEFAULT 0,
        verification_token TEXT,
        verification_code TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)
    _safe_add_columns(cursor, "users", [
        ("verification_expires_at", "REAL DEFAULT 0"),
        ("verification_attempts", "INTEGER DEFAULT 0"),
        ("failed_login_attempts", "INTEGER DEFAULT 0"),
        ("locked_until", "REAL DEFAULT 0"),
        ("is_active", "INTEGER DEFAULT 1"),
    ])
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);")

    # 3. Contact Inquiries Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inquiries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        company TEXT,
        subject TEXT NOT NULL,
        category TEXT,
        message TEXT NOT NULL,
        status TEXT DEFAULT 'new',
        created_at TEXT
    )
    """)

    # 4. Orders / Commercial Checkout Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number TEXT UNIQUE NOT NULL,
        product_id INTEGER,
        product_name TEXT,
        customer_name TEXT NOT NULL,
        customer_email TEXT NOT NULL,
        amount TEXT NOT NULL,
        currency TEXT DEFAULT '₹',
        payment_method TEXT NOT NULL,
        status TEXT DEFAULT 'completed',
        billing_address TEXT,
        created_at TEXT
    )
    """)
    _safe_add_columns(cursor, "orders", [
        ("user_id", "INTEGER"),
        ("quantity", "INTEGER DEFAULT 1"),
        ("unit_price", "TEXT"),
        ("tax_amount", "TEXT"),
        ("card_last4", "TEXT"),
    ])

    conn.commit()
    conn.close()

    # Initialize Cache/Sessions and Message Queue tables
    cache_service.init_cache_tables()
    queue_service.init_queue_tables()

    # Seed initial accounts safely
    seed_default_users()
    logger.info("Database initialized (WAL mode), Cache & Message Queue verified.")


def seed_default_users():
    """Seeds initial admin and editor accounts if missing (never overwriting existing)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("SELECT id FROM users WHERE username = 'admin' OR email = 'admin@product-catalog.com'")
    if not cursor.fetchone():
        admin_hash = generate_password_hash("Admin@12345")
        cursor.execute("""
        INSERT INTO users (
            username, email, password_hash, role, is_verified, is_active, created_at, updated_at
        ) VALUES ('admin', 'admin@product-catalog.com', ?, 'admin', 1, 1, ?, ?)
        """, (admin_hash, now_str, now_str))
        logger.info("Seeded Admin account: admin@product-catalog.com")

    cursor.execute("SELECT id FROM users WHERE username = 'editor' OR email = 'editor@product-catalog.com'")
    if not cursor.fetchone():
        editor_hash = generate_password_hash("Editor@12345")
        cursor.execute("""
        INSERT INTO users (
            username, email, password_hash, role, is_verified, is_active, created_at, updated_at
        ) VALUES ('editor', 'editor@product-catalog.com', ?, 'editor', 1, 1, ?, ?)
        """, (editor_hash, now_str, now_str))
        logger.info("Seeded Editor account: editor@product-catalog.com")

    conn.commit()
    conn.close()


# ==============================================================================
# AUTHENTICATION & USER MANAGEMENT
# ==============================================================================

def create_user(username: str, email: str, password: str, allow_elevated_role: str = None, is_verified: int = 0) -> dict:
    """
    Creates a new user account with CSPRNG HMAC-hashed email OTP.
    Public signups ALWAYS enforce role='viewer' (role tampering from payload ignored).
    """
    clean_username = security_service.sanitize_text_field(username, 32).lower()
    clean_email = security_service.sanitize_text_field(email, 254).lower()

    if not security_service.validate_username(clean_username):
        return {"success": False, "message": "Username must be 3-32 characters (letters, numbers, _, ., -)"}
    if not security_service.validate_email_address(clean_email):
        return {"success": False, "message": "Please provide a valid email address"}

    ok_pw, msg_pw = security_service.validate_password_strength(password)
    if not ok_pw:
        return {"success": False, "message": msg_pw}

    role = allow_elevated_role if allow_elevated_role in ("admin", "editor", "viewer") else "viewer"

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = ? OR email = ?", (clean_username, clean_email))
    if cursor.fetchone():
        conn.close()
        return {"success": False, "conflict": True, "message": "Unable to register with the provided account details"}

    password_hash = generate_password_hash(password)
    raw_code = "".join(secrets.choice(string.digits) for _ in range(6))
    code_digest = security_service.hash_verification_code(clean_email, raw_code)
    expires_at = time.time() + 900  # 15 minutes
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
    INSERT INTO users (
        username, email, password_hash, role, is_verified, is_active,
        verification_token, verification_code, verification_expires_at,
        verification_attempts, failed_login_attempts, locked_until,
        created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, 1, NULL, ?, ?, 0, 0, 0, ?, ?)
    """, (
        clean_username, clean_email, password_hash, role, is_verified,
        code_digest, expires_at, now_str, now_str
    ))

    user_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Dispatch verification email asynchronously via Message Queue -> Email Worker
    if not is_verified:
        queue_service.enqueue_job("email.verification", {
            "user_id": user_id,
            "username": clean_username,
            "email": clean_email,
            "code": raw_code
        })

    # Notice: verification_code is intentionally omitted from API response to prevent OTP bypass!
    return {
        "success": True,
        "user_id": user_id,
        "username": clean_username,
        "email": clean_email,
        "role": role,
        "is_verified": bool(is_verified),
        "message": "Account created. A 6-digit verification code has been queued for email delivery."
    }


def regenerate_verification_code(user_id: int) -> dict:
    """Issues a fresh 6-digit HMAC OTP for an existing unverified account."""
    conn = get_db_connection()
    cursor = conn.cursor()
    row = cursor.execute("SELECT id, username, email, is_verified FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        conn.close()
        return {"success": False, "message": "User not found"}
    if row["is_verified"]:
        conn.close()
        return {"success": True, "message": "Account email is already verified"}

    raw_code = "".join(secrets.choice(string.digits) for _ in range(6))
    code_digest = security_service.hash_verification_code(row["email"], raw_code)
    expires_at = time.time() + 900

    cursor.execute("""
    UPDATE users
    SET verification_code = ?, verification_expires_at = ?, verification_attempts = 0, updated_at = ?
    WHERE id = ?
    """, (code_digest, expires_at, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id))
    conn.commit()
    conn.close()

    queue_service.enqueue_job("email.verification", {
        "user_id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "code": raw_code
    })
    return {"success": True, "message": "A new verification code has been queued for delivery."}


def authenticate_user(identifier: str, password: str) -> dict:
    """Verifies credentials with timing consistency and progressive account lockout."""
    clean_id = (identifier or "").strip().lower()
    if not clean_id or not password:
        return {"success": False, "message": "Username/email and password are required."}

    conn = get_db_connection()
    cursor = conn.cursor()
    row = cursor.execute("SELECT * FROM users WHERE username = ? OR email = ?", (clean_id, clean_id)).fetchone()

    now_epoch = time.time()
    if not row:
        # Constant-time dummy hash check to prevent user enumeration via timing
        check_password_hash("scrypt:32768:8:1$dummySaltValue12$00000000000000000000000000000000", password)
        conn.close()
        return {"success": False, "message": "Invalid credentials."}

    user = dict(row)
    if not user.get("is_active", 1):
        conn.close()
        return {"success": False, "message": "Account has been deactivated. Contact administrator."}

    locked_until = float(user.get("locked_until") or 0)
    if locked_until > now_epoch:
        wait_secs = int(locked_until - now_epoch)
        conn.close()
        return {
            "success": False,
            "locked": True,
            "message": f"Account temporarily locked due to repeated failed logins. Try again in {wait_secs}s."
        }

    if not check_password_hash(user["password_hash"], password):
        attempts = int(user.get("failed_login_attempts") or 0) + 1
        new_lock = now_epoch + 300 if attempts >= 5 else 0
        cursor.execute(
            "UPDATE users SET failed_login_attempts = ?, locked_until = ? WHERE id = ?",
            (attempts, new_lock, user["id"])
        )
        conn.commit()
        conn.close()
        return {"success": False, "message": "Invalid credentials."}

    # Success: reset lockout counters
    cursor.execute(
        "UPDATE users SET failed_login_attempts = 0, locked_until = 0, updated_at = ? WHERE id = ?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user["id"])
    )
    conn.commit()
    conn.close()

    return {
        "success": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "role": user["role"],
            "is_verified": bool(user["is_verified"])
        }
    }


def get_user_by_id(user_id: int):
    """Retrieves safe user projection (never returning password_hash or verification_code)."""
    conn = get_db_connection()
    row = conn.execute("""
    SELECT id, username, email, role, is_verified, is_active, created_at
    FROM users WHERE id = ? AND is_active = 1
    """, (user_id,)).fetchone()
    conn.close()
    if row:
        u = dict(row)
        u["is_verified"] = bool(u["is_verified"])
        return u
    return None


def verify_user_code(user_id: int, code: str) -> tuple:
    """
    Verifies a user's 6-digit OTP via HMAC-SHA256 with TTL (15m) & max 5 attempt enforcement.
    Bound strictly to authenticated integer user_id; returns uniform errors to prevent enumeration.
    """
    clean_code = (code or "").strip()
    if not isinstance(user_id, int) or isinstance(user_id, bool):
        return False, "Invalid or expired verification code."
    if not clean_code or len(clean_code) != 6 or not clean_code.isdigit():
        return False, "Verification code must be a 6-digit number"

    conn = get_db_connection()
    cursor = conn.cursor()

    row = cursor.execute(
        "SELECT id, email, verification_code, verification_expires_at, verification_attempts, is_verified FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    if not row:
        conn.close()
        return False, "Invalid or expired verification code."

    if row["is_verified"]:
        conn.close()
        return True, "Email is already verified"

    attempts = int(row["verification_attempts"] or 0)
    if attempts >= 5:
        conn.close()
        return False, "Invalid or expired verification code."

    expires_at = float(row["verification_expires_at"] or 0)
    if time.time() > expires_at:
        conn.close()
        return False, "Invalid or expired verification code."

    stored_digest = row["verification_code"] or ""
    if security_service.verify_hashed_code(row["email"], clean_code, stored_digest):
        cursor.execute("""
        UPDATE users
        SET is_verified = 1, verification_code = NULL, verification_expires_at = 0,
            verification_attempts = 0, updated_at = ?
        WHERE id = ?
        """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row["id"]))
        conn.commit()
        conn.close()
        return True, "Email verified successfully!"

    cursor.execute(
        "UPDATE users SET verification_attempts = verification_attempts + 1 WHERE id = ?",
        (row["id"],)
    )
    conn.commit()
    conn.close()
    return False, "Invalid or expired verification code."


# ==============================================================================
# CONTACT INQUIRIES & SERVER-AUTHORITATIVE ORDERS
# ==============================================================================

def save_inquiry(data: dict) -> dict:
    """Validates, sanitizes, persists customer inquiry, and queues confirmation email."""
    name = security_service.sanitize_text_field(data.get("name"), 120)
    email = security_service.sanitize_text_field(data.get("email"), 254).lower()
    company = security_service.sanitize_text_field(data.get("company"), 120)
    subject = security_service.sanitize_text_field(data.get("subject") or "General Inquiry", 200)
    category = security_service.sanitize_text_field(data.get("category") or "General", 80)
    message = security_service.sanitize_text_field(data.get("message"), 3000)

    if not name or not email or not message or not subject:
        return {"success": False, "message": "Name, email, subject, and message are required fields"}

    if not security_service.validate_email_address(email):
        return {"success": False, "message": "Please provide a valid email address"}

    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
    INSERT INTO inquiries (name, email, company, subject, category, message, status, created_at)
    VALUES (?, ?, ?, ?, ?, ?, 'new', ?)
    """, (name, email, company, subject, category, message, now_str))

    inq_id = cursor.lastrowid
    conn.commit()
    conn.close()

    cache_service.cache_invalidate_prefix("catalog:stats")
    ref_code = f"INQ-{inq_id:04d}"

    queue_service.enqueue_job("email.contact_ack", {
        "email": email,
        "name": name,
        "reference_code": ref_code
    })

    return {
        "success": True,
        "inquiry_id": inq_id,
        "reference_code": ref_code,
        "message": f"Thank you, {name}! Your inquiry ({ref_code}) has been received."
    }


def get_inquiries_summary(limit: int = 50) -> list:
    """Returns redacted inquiry ticket metadata without exposing customer PII to frontend."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id, category, status, created_at FROM inquiries ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [
        {
            "reference_code": f"INQ-{r['id']:04d}",
            "category": r["category"] or "General",
            "status": r["status"] or "new",
            "created_at": r["created_at"] or "",
        }
        for r in rows
    ]


def create_verified_order(data: dict, authenticated_user: dict) -> tuple:
    """
    Authoritative server-side order creation algorithm:
    - Looks up product strictly from Database (ignores client amount/product_name!)
    - Validates quantity (1..50), email, address, payment method, and Luhn/Expiry/CVV card checks
    - Computes deterministic Decimal subtotal + 18% tax + total server-side
    - Masks card details to last 4 digits only
    - Enqueues async order receipt email
    Returns (response_dict, http_status_code).
    """
    raw_pid = data.get("product_id")
    try:
        product_id = int(raw_pid)
    except (TypeError, ValueError):
        return {"success": False, "message": "Valid product selection (product_id) is required"}, 400

    product = get_product_by_id(product_id)
    if not product:
        return {"success": False, "message": "Selected product does not exist in catalog"}, 404

    currency, unit_price = security_service.parse_authoritative_price(product.get("price"))
    if unit_price is None:
        return {
            "success": False,
            "message": f"'{product['product_name']}' is priced by custom quote. Please use Contact Support."
        }, 400

    try:
        qty = int(data.get("quantity", 1))
    except (TypeError, ValueError):
        qty = 1
    if qty < 1 or qty > 50:
        return {"success": False, "message": "Quantity must be between 1 and 50"}, 400

    customer_name = security_service.sanitize_text_field(
        data.get("customer_name") or data.get("name"), 120
    )
    customer_email = security_service.sanitize_text_field(
        data.get("customer_email") or data.get("email") or (authenticated_user or {}).get("email"), 254
    ).lower()
    billing_address = security_service.sanitize_text_field(
        data.get("billing_address") or data.get("address"), 300
    )

    if not customer_name or not security_service.validate_email_address(customer_email):
        return {"success": False, "message": "Customer name and a valid email address are required"}, 400
    if not billing_address or len(billing_address) < 5:
        return {"success": False, "message": "Valid billing/shipping address is required"}, 400

    allowed_methods = {"Credit Card", "UPI", "Net Banking", "Corporate Invoice"}
    raw_method = security_service.sanitize_text_field(data.get("payment_method") or "Credit Card", 40)
    # Normalize alias "card" -> "Credit Card"
    payment_method = "Credit Card" if raw_method.lower() == "card" else raw_method
    if payment_method not in allowed_methods:
        return {"success": False, "message": "Unsupported payment method"}, 400

    card_last4 = ""
    if payment_method == "Credit Card":
        card_number = data.get("card_number") or ""
        card_expiry = data.get("card_expiry") or data.get("card_exp") or ""
        card_cvv = data.get("card_cvv") or data.get("card_cvc") or ""

        if not security_service.validate_luhn_card(card_number):
            return {"success": False, "message": "Card validation failed (invalid number or checksum)"}, 400
        if not security_service.validate_card_expiry(card_expiry):
            return {"success": False, "message": "Invalid or expired card expiration date (MM/YY)"}, 400
        if not security_service.validate_card_cvv(card_cvv):
            return {"success": False, "message": "Invalid card security code (CVV)"}, 400

        digits = "".join(c for c in card_number if c.isdigit())
        card_last4 = digits[-4:]

    # Authoritative monetary totals calculated solely server-side
    totals = security_service.compute_order_totals(unit_price, quantity=qty)
    formatted_unit = f"{currency}{totals['unit_price']:,.2f}"
    formatted_tax = f"{currency}{totals['tax']:,.2f}"
    formatted_total = f"{currency}{totals['total']:,.2f}"

    order_number = f"PC-ORD-{secrets.randbelow(900000) + 100000}"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    user_id = authenticated_user["id"] if authenticated_user else None

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO orders (
        order_number, product_id, product_name, user_id, quantity, unit_price, tax_amount,
        customer_name, customer_email, amount, currency, payment_method, card_last4,
        status, billing_address, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)
    """, (
        order_number, product_id, product["product_name"], user_id, totals["quantity"],
        formatted_unit, formatted_tax, customer_name, customer_email, formatted_total,
        currency, payment_method, card_last4, billing_address, now_str
    ))
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()

    cache_service.cache_invalidate_prefix("catalog:stats")
    queue_service.enqueue_job("email.order_receipt", {
        "order_number": order_number,
        "product_name": product["product_name"],
        "amount": formatted_total,
        "customer_email": customer_email
    })

    return {
        "success": True,
        "order_id": order_id,
        "order_number": order_number,
        "product_id": product_id,
        "product_name": product["product_name"],
        "quantity": totals["quantity"],
        "unit_price": formatted_unit,
        "tax_amount": formatted_tax,
        "amount": formatted_total,
        "payment_method": payment_method,
        "card_last4": f"•••• {card_last4}" if card_last4 else "",
        "status": "completed",
        "created_at": now_str,
        "message": f"Order {order_number} confirmed successfully!"
    }, 200


def get_orders(limit: int = 50, user_id: int = None) -> list:
    """Retrieves privacy-safe order summaries (never returning email, name, or billing_address to frontend)."""
    conn = get_db_connection()
    base_cols = (
        "order_number, product_id, product_name, quantity, unit_price, "
        "tax_amount, amount, currency, payment_method, card_last4, status, created_at"
    )
    if user_id is not None:
        rows = conn.execute(
            f"SELECT {base_cols} FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
    else:
        rows = conn.execute(f"SELECT {base_cols} FROM orders ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    results = []
    for r in rows:
        item = dict(r)
        if item.get("card_last4"):
            item["card_last4"] = f"•••• {item['card_last4'][-4:]}"
        results.append(item)
    return results


# ==============================================================================
# PRODUCT CATALOG HELPERS & NORMALIZERS
# ==============================================================================

def normalize_list(val) -> list:
    if not val:
        return []
    if isinstance(val, list):
        return [security_service.sanitize_text_field(item, 240) for item in val if str(item).strip()]
    if isinstance(val, str):
        val = val.strip()
        if val.startswith('[') and val.endswith(']'):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    return [security_service.sanitize_text_field(p, 240) for p in parsed if str(p).strip()]
            except Exception:
                pass
        return [security_service.sanitize_text_field(p, 240) for p in val.replace('\n', ',').split(',') if p.strip()]
    return [security_service.sanitize_text_field(val, 240)]


def normalize_dict(val) -> dict:
    if not val:
        return {}
    if isinstance(val, dict):
        return {
            security_service.sanitize_text_field(k, 80): security_service.sanitize_text_field(v, 240)
            for k, v in val.items() if str(k).strip()
        }
    if isinstance(val, str):
        val = val.strip()
        if val.startswith('{') and val.endswith('}'):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, dict):
                    return {
                        security_service.sanitize_text_field(k, 80): security_service.sanitize_text_field(v, 240)
                        for k, v in parsed.items() if str(k).strip()
                    }
            except Exception:
                pass
    return {}


def format_product_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["features"] = normalize_list(d.get("features"))
    d["specifications"] = normalize_dict(d.get("specifications"))
    d["selling_points"] = normalize_list(d.get("selling_points"))
    d["tags"] = normalize_list(d.get("tags"))

    if not d.get("category"):
        d["category"] = "General"
    if not d.get("short_description"):
        d["short_description"] = f"{d.get('product_name', '')} by {d.get('brand', '')}."
    if not d.get("description"):
        d["description"] = d["short_description"]
    return d


def get_products(search: str = None, category: str = None, brand: str = None, sort: str = None) -> list:
    """Fetches products, leveraging hot-read Cache for unfiltered standard views."""
    cache_key = None
    if not search and (not category or category == "all") and (not brand or brand == "all"):
        sort_key = sort or "default"
        cache_key = f"catalog:list:{sort_key}"
        cached = cache_service.cache_get(cache_key)
        if cached is not None:
            return cached

    conn = get_db_connection()
    query = "SELECT * FROM products WHERE 1=1"
    params = []

    if search:
        search_pattern = f"%{search.strip()}%"
        query += " AND (product_name LIKE ? OR brand LIKE ? OR category LIKE ? OR description LIKE ? OR tags LIKE ?)"
        params.extend([search_pattern, search_pattern, search_pattern, search_pattern, search_pattern])

    if category and category != 'all':
        query += " AND category = ?"
        params.append(category)

    if brand and brand != 'all':
        query += " AND brand = ?"
        params.append(brand)

    if sort == "name_asc":
        query += " ORDER BY product_name ASC"
    elif sort == "name_desc":
        query += " ORDER BY product_name DESC"
    elif sort == "price_asc":
        query += " ORDER BY price ASC"
    elif sort == "price_desc":
        query += " ORDER BY price DESC"
    else:
        query += " ORDER BY id DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    products = [format_product_row(r) for r in rows]
    if cache_key:
        cache_service.cache_set(cache_key, products)
    return products


def get_product_by_id(product_id: int):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    conn.close()
    return format_product_row(row) if row else None


def insert_product(data: dict) -> int:
    """Validates allowlisted fields, inserts product, and invalidates Cache."""
    product_name = security_service.sanitize_text_field(data.get("product_name"), 200) or "Unnamed Product"
    brand = security_service.sanitize_text_field(data.get("brand"), 120) or "Unspecified"
    price = security_service.sanitize_text_field(data.get("price"), 60) or "Not Available"
    dimensions = security_service.sanitize_text_field(data.get("dimensions"), 120) or "Not Available"
    category = security_service.sanitize_text_field(data.get("category"), 100) or "General"
    model = security_service.sanitize_text_field(data.get("model"), 100) or None
    short_desc = security_service.sanitize_text_field(data.get("short_description"), 500)
    desc = security_service.sanitize_text_field(data.get("description"), 5000) or short_desc
    extraction_source = security_service.sanitize_text_field(data.get("extraction_source") or "manual", 60)
    status = "active" if data.get("status") in (None, "", "active", "draft") else "active"

    safe_img_path, img_err = security_service.sanitize_catalog_image_path(data.get("image_path") or "")
    if img_err:
        raise ValueError(img_err)

    features_json = json.dumps(normalize_list(data.get("features")), ensure_ascii=False)
    specs_json = json.dumps(normalize_dict(data.get("specifications")), ensure_ascii=False)
    usp_json = json.dumps(normalize_list(data.get("selling_points")), ensure_ascii=False)
    tags_json = json.dumps(normalize_list(data.get("tags")), ensure_ascii=False)
    seo_title = security_service.sanitize_text_field(data.get("seo_title"), 120) or f"{product_name} - {brand}"
    seo_desc = security_service.sanitize_text_field(data.get("seo_description"), 300) or short_desc
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO products (
        product_name, brand, model, category, price, dimensions,
        short_description, description, features, specifications,
        selling_points, tags, seo_title, seo_description,
        image_path, extraction_source, status, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        product_name, brand, model, category, price, dimensions,
        short_desc, desc, features_json, specs_json,
        usp_json, tags_json, seo_title, seo_desc,
        safe_img_path, extraction_source, status, now_str, now_str
    ))
    product_id = cursor.lastrowid
    conn.commit()
    conn.close()

    cache_service.cache_invalidate_prefix("catalog:")
    return product_id


def update_product(product_id: int, data: dict) -> bool:
    """Updates allowlisted product attributes with validation and cache invalidation."""
    existing = get_product_by_id(product_id)
    if not existing:
        return False

    product_name = security_service.sanitize_text_field(data.get("product_name", existing["product_name"]), 200) or existing["product_name"]
    brand = security_service.sanitize_text_field(data.get("brand", existing["brand"]), 120)
    price = security_service.sanitize_text_field(data.get("price", existing["price"]), 60)
    dimensions = security_service.sanitize_text_field(data.get("dimensions", existing["dimensions"]), 120)
    category = security_service.sanitize_text_field(data.get("category", existing.get("category", "General")), 100)
    model_val = data.get("model", existing.get("model"))
    model = security_service.sanitize_text_field(model_val, 100) if model_val else None
    short_desc = security_service.sanitize_text_field(data.get("short_description", existing.get("short_description", "")), 500)
    desc = security_service.sanitize_text_field(data.get("description", existing.get("description", "")), 5000)

    if "image_path" in data:
        safe_img_path, img_err = security_service.sanitize_catalog_image_path(data.get("image_path") or "")
        if img_err:
            raise ValueError(img_err)
    else:
        safe_img_path = existing.get("image_path", "")

    status = data.get("status", existing.get("status", "active"))
    if status not in ("active", "draft", "archived"):
        status = "active"

    features = data.get("features")
    features_json = json.dumps(normalize_list(features), ensure_ascii=False) if features is not None else json.dumps(existing["features"], ensure_ascii=False)

    specs = data.get("specifications")
    specs_json = json.dumps(normalize_dict(specs), ensure_ascii=False) if specs is not None else json.dumps(existing["specifications"], ensure_ascii=False)

    usp = data.get("selling_points")
    usp_json = json.dumps(normalize_list(usp), ensure_ascii=False) if usp is not None else json.dumps(existing["selling_points"], ensure_ascii=False)

    tags = data.get("tags")
    tags_json = json.dumps(normalize_list(tags), ensure_ascii=False) if tags is not None else json.dumps(existing["tags"], ensure_ascii=False)

    seo_title = security_service.sanitize_text_field(data.get("seo_title", existing.get("seo_title", "")), 120)
    seo_desc = security_service.sanitize_text_field(data.get("seo_description", existing.get("seo_description", "")), 300)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    conn.execute("""
    UPDATE products SET
        product_name = ?, brand = ?, model = ?, category = ?, price = ?, dimensions = ?,
        short_description = ?, description = ?, features = ?, specifications = ?,
        selling_points = ?, tags = ?, seo_title = ?, seo_description = ?,
        image_path = ?, status = ?, updated_at = ?
    WHERE id = ?
    """, (
        product_name, brand, model, category, price, dimensions,
        short_desc, desc, features_json, specs_json,
        usp_json, tags_json, seo_title, seo_desc,
        safe_img_path, status, now_str, product_id
    ))
    conn.commit()
    conn.close()

    cache_service.cache_invalidate_prefix("catalog:")
    return True


def delete_product(product_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    if rows_affected > 0:
        cache_service.cache_invalidate_prefix("catalog:")
    return rows_affected > 0


def get_catalog_stats() -> dict:
    """Computes real catalog statistics via Cache + Database."""
    cached = cache_service.cache_get("catalog:stats")
    if cached is not None:
        return cached

    conn = get_db_connection()
    cursor = conn.cursor()

    total_products = cursor.execute("SELECT count(*) FROM products").fetchone()[0]
    total_brands = cursor.execute("SELECT count(DISTINCT brand) FROM products WHERE brand IS NOT NULL AND brand != '' AND brand != 'Unspecified'").fetchone()[0]
    total_categories = cursor.execute("SELECT count(DISTINCT category) FROM products WHERE category IS NOT NULL AND category != ''").fetchone()[0]
    categories = [r[0] for r in cursor.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL ORDER BY category ASC").fetchall() if r[0]]
    brands = [r[0] for r in cursor.execute("SELECT DISTINCT brand FROM products WHERE brand IS NOT NULL AND brand != 'Unspecified' ORDER BY brand ASC").fetchall() if r[0]]
    ai_enriched = cursor.execute("SELECT count(*) FROM products WHERE extraction_source LIKE 'gemini%' OR extraction_source = 'ai'").fetchone()[0]
    total_inquiries = cursor.execute("SELECT count(*) FROM inquiries").fetchone()[0]
    total_orders = cursor.execute("SELECT count(*) FROM orders").fetchone()[0]

    conn.close()

    stats = {
        "total_products": total_products,
        "total_brands": total_brands,
        "total_categories": total_categories,
        "categories": categories,
        "brands": brands,
        "ai_enriched_count": ai_enriched,
        "export_ready_count": total_products,
        "total_inquiries": total_inquiries,
        "total_orders": total_orders
    }
    cache_service.cache_set("catalog:stats", stats)
    return stats
