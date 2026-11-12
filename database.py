"""
Suchit Catalog - Database Management Module
SQLite database interaction layer with auto-migration, safe column additions,
indexed queries, user authentication & authorization, contact inquiries, and commercial orders.
"""
import sqlite3
import json
import logging
import random
import string
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config

logger = logging.getLogger(__name__)


def get_db_connection():
    """Returns a new SQLite connection with Row factory enabled."""
    conn = sqlite3.connect(Config.DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Initializes the database schema and performs non-destructive migrations
    to ensure all tables and columns exist, preserving all existing catalog data.
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

    cursor.execute("PRAGMA table_info(products);")
    existing_columns = {row['name'] for row in cursor.fetchall()}

    modern_columns = [
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
        ("updated_at", "TEXT")
    ]

    for col_name, col_type in modern_columns:
        if col_name not in existing_columns:
            logger.info(f"Adding missing column to products table: {col_name}")
            cursor.execute(f"ALTER TABLE products ADD COLUMN {col_name} {col_type};")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_id ON products(id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);")

    # 2. Users Table for Authentication & Authorization
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

    conn.commit()
    conn.close()

    # Seed initial default admin and editor accounts
    seed_default_users()
    logger.info("Database initialized, schema verified, and default users seeded.")


def seed_default_users():
    """Seeds default admin and editor accounts if they do not already exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Admin: admin@suchitcatalog.com / Admin@12345
    cursor.execute("SELECT id FROM users WHERE username = 'admin' OR email = 'admin@suchitcatalog.com'")
    if not cursor.fetchone():
        admin_hash = generate_password_hash("Admin@12345")
        cursor.execute("""
        INSERT INTO users (username, email, password_hash, role, is_verified, verification_code, created_at, updated_at)
        VALUES ('admin', 'admin@suchitcatalog.com', ?, 'admin', 1, '123456', ?, ?)
        """, (admin_hash, now_str, now_str))
        logger.info("Created default Admin account: admin / Admin@12345")

    # Editor: editor@suchitcatalog.com / Editor@12345
    cursor.execute("SELECT id FROM users WHERE username = 'editor' OR email = 'editor@suchitcatalog.com'")
    if not cursor.fetchone():
        editor_hash = generate_password_hash("Editor@12345")
        cursor.execute("""
        INSERT INTO users (username, email, password_hash, role, is_verified, verification_code, created_at, updated_at)
        VALUES ('editor', 'editor@suchitcatalog.com', ?, 'editor', 1, '654321', ?, ?)
        """, (editor_hash, now_str, now_str))
        logger.info("Created default Editor account: editor / Editor@12345")

    conn.commit()
    conn.close()


# ==============================================================================
# AUTHENTICATION & USER MANAGEMENT
# ==============================================================================

def create_user(username: str, email: str, password: str, role: str = "viewer", is_verified: int = 0) -> dict:
    """Creates a new user record with hashed password and verification code."""
    username = username.strip().lower()
    email = email.strip().lower()

    if not username or not email or not password:
        return {"success": False, "message": "Username, email, and password are required"}

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE username = ? OR email = ?", (username, email))
    if cursor.fetchone():
        conn.close()
        return {"success": False, "message": "A user with this username or email already exists"}

    password_hash = generate_password_hash(password)
    verification_code = "".join(random.choices(string.digits, k=6))
    verification_token = "".join(random.choices(string.ascii_letters + string.digits, k=32))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
    INSERT INTO users (username, email, password_hash, role, is_verified, verification_token, verification_code, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (username, email, password_hash, role, is_verified, verification_token, verification_code, now_str, now_str))

    user_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {
        "success": True,
        "user_id": user_id,
        "username": username,
        "email": email,
        "role": role,
        "is_verified": bool(is_verified),
        "verification_code": verification_code,
        "message": "User registered successfully"
    }


def authenticate_user(identifier: str, password: str) -> dict:
    """Verifies username or email against stored password hash."""
    identifier = identifier.strip().lower()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE username = ? OR email = ?", (identifier, identifier))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {"success": False, "message": "Invalid credentials. User not found."}

    user = dict(row)
    if not check_password_hash(user["password_hash"], password):
        return {"success": False, "message": "Invalid password. Please check your credentials."}

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
    """Retrieves safe user object by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, email, role, is_verified, created_at FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        u = dict(row)
        u["is_verified"] = bool(u["is_verified"])
        return u
    return None


def verify_user_code(user_id_or_email, code: str) -> bool:
    """Verifies user email with 6-digit verification code."""
    code = code.strip()
    conn = get_db_connection()
    cursor = conn.cursor()

    if isinstance(user_id_or_email, int) or (isinstance(user_id_or_email, str) and user_id_or_email.isdigit()):
        cursor.execute("SELECT id, verification_code FROM users WHERE id = ?", (int(user_id_or_email),))
    else:
        cursor.execute("SELECT id, verification_code FROM users WHERE email = ? OR username = ?", (str(user_id_or_email).lower(), str(user_id_or_email).lower()))

    row = cursor.fetchone()
    if not row:
        conn.close()
        return False

    stored_code = row["verification_code"]
    user_id = row["id"]

    if stored_code == code or code == "123456":  # Universal test bypass for testing
        cursor.execute("UPDATE users SET is_verified = 1 WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()
        return True

    conn.close()
    return False


# ==============================================================================
# CONTACT INQUIRIES & ORDERS
# ==============================================================================

def save_inquiry(data: dict) -> dict:
    """Saves a contact inquiry and returns reference ID."""
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    company = (data.get("company") or "").strip()
    subject = (data.get("subject") or "General Inquiry").strip()
    category = (data.get("category") or "General").strip()
    message = (data.get("message") or "").strip()

    if not name or not email or not message:
        return {"success": False, "message": "Name, email, and message are required fields"}

    if "@" not in email or "." not in email:
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

    ref_code = f"INQ-{inq_id:04d}"
    return {
        "success": True,
        "inquiry_id": inq_id,
        "reference_code": ref_code,
        "message": f"Thank you, {name}! Your inquiry ({ref_code}) has been received."
    }


def get_inquiries(limit: int = 50) -> list:
    """Retrieves recent contact inquiries."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inquiries ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_order(data: dict) -> dict:
    """Creates a commercial checkout order record."""
    product_id = data.get("product_id")
    product_name = data.get("product_name") or "Suchit Catalog License"
    customer_name = (data.get("customer_name") or "Valued Customer").strip()
    customer_email = (data.get("customer_email") or "").strip()
    amount = data.get("amount") or "₹1,499"
    currency = data.get("currency") or "₹"
    payment_method = data.get("payment_method") or "Credit Card"
    billing_address = data.get("billing_address") or "Standard Shipping"

    order_number = f"SUCHIT-ORD-{random.randint(100000, 999999)}"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO orders (
        order_number, product_id, product_name, customer_name, customer_email,
        amount, currency, payment_method, status, billing_address, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)
    """, (
        order_number, product_id, product_name, customer_name, customer_email,
        amount, currency, payment_method, billing_address, now_str
    ))

    order_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {
        "success": True,
        "order_id": order_id,
        "order_number": order_number,
        "product_name": product_name,
        "amount": amount,
        "status": "completed",
        "created_at": now_str,
        "message": f"Order {order_number} confirmed successfully!"
    }


def get_orders(limit: int = 50) -> list:
    """Retrieves recent commercial orders."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ==============================================================================
# PRODUCT CATALOG HELPERS & NORMALIZERS
# ==============================================================================

def normalize_list(val) -> list:
    """Safely converts string, JSON, or list into a clean list of strings."""
    if not val:
        return []
    if isinstance(val, list):
        return [str(item).strip() for item in val if str(item).strip()]
    if isinstance(val, str):
        val = val.strip()
        if val.startswith('[') and val.endswith(']'):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    return [str(p).strip() for p in parsed if str(p).strip()]
            except Exception:
                pass
        items = [p.strip() for p in val.replace('\n', ',').split(',') if p.strip()]
        return items
    return [str(val)]


def normalize_dict(val) -> dict:
    """Safely converts string, JSON, or dict into a clean dictionary."""
    if not val:
        return {}
    if isinstance(val, dict):
        return {str(k).strip(): str(v).strip() for k, v in val.items()}
    if isinstance(val, str):
        val = val.strip()
        if val.startswith('{') and val.endswith('}'):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, dict):
                    return {str(k).strip(): str(v).strip() for k, v in parsed.items()}
            except Exception:
                pass
    return {}


def format_product_row(row: sqlite3.Row) -> dict:
    """Converts a SQLite Row into a fully structured, JSON-ready dictionary."""
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
    """Fetches all products with optional search, category, brand filters and sorting."""
    conn = get_db_connection()
    cursor = conn.cursor()

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

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return [format_product_row(r) for r in rows]


def get_product_by_id(product_id: int):
    """Retrieves a single product by ID, or None if not found."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return format_product_row(row)
    return None


def insert_product(data: dict) -> int:
    """Inserts a new product into the database and returns the generated ID."""
    conn = get_db_connection()
    cursor = conn.cursor()

    product_name = data.get("product_name") or "Unnamed Product"
    brand = data.get("brand") or "Unspecified"
    price = data.get("price") or "Not Available"
    dimensions = data.get("dimensions") or "Not Available"
    category = data.get("category") or "General"
    model = data.get("model")
    short_desc = data.get("short_description") or ""
    desc = data.get("description") or short_desc
    image_path = data.get("image_path") or ""
    extraction_source = data.get("extraction_source") or "manual"
    status = data.get("status") or "active"

    features_json = json.dumps(normalize_list(data.get("features")), ensure_ascii=False)
    specs_json = json.dumps(normalize_dict(data.get("specifications")), ensure_ascii=False)
    usp_json = json.dumps(normalize_list(data.get("selling_points")), ensure_ascii=False)
    tags_json = json.dumps(normalize_list(data.get("tags")), ensure_ascii=False)
    seo_title = data.get("seo_title") or f"{product_name} - {brand}"
    seo_desc = data.get("seo_description") or short_desc

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
        image_path, extraction_source, status, now_str, now_str
    ))

    product_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return product_id


def update_product(product_id: int, data: dict) -> bool:
    """Updates an existing product with new data."""
    existing = get_product_by_id(product_id)
    if not existing:
        return False

    conn = get_db_connection()
    cursor = conn.cursor()

    product_name = data.get("product_name", existing["product_name"])
    brand = data.get("brand", existing["brand"])
    price = data.get("price", existing["price"])
    dimensions = data.get("dimensions", existing["dimensions"])
    category = data.get("category", existing.get("category", "General"))
    model = data.get("model", existing.get("model"))
    short_desc = data.get("short_description", existing.get("short_description", ""))
    desc = data.get("description", existing.get("description", ""))
    image_path = data.get("image_path", existing.get("image_path", ""))
    status = data.get("status", existing.get("status", "active"))

    features = data.get("features")
    features_json = json.dumps(normalize_list(features), ensure_ascii=False) if features is not None else json.dumps(existing["features"], ensure_ascii=False)

    specs = data.get("specifications")
    specs_json = json.dumps(normalize_dict(specs), ensure_ascii=False) if specs is not None else json.dumps(existing["specifications"], ensure_ascii=False)

    usp = data.get("selling_points")
    usp_json = json.dumps(normalize_list(usp), ensure_ascii=False) if usp is not None else json.dumps(existing["selling_points"], ensure_ascii=False)

    tags = data.get("tags")
    tags_json = json.dumps(normalize_list(tags), ensure_ascii=False) if tags is not None else json.dumps(existing["tags"], ensure_ascii=False)

    seo_title = data.get("seo_title", existing.get("seo_title", ""))
    seo_desc = data.get("seo_description", existing.get("seo_description", ""))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
    UPDATE products SET
        product_name = ?,
        brand = ?,
        model = ?,
        category = ?,
        price = ?,
        dimensions = ?,
        short_description = ?,
        description = ?,
        features = ?,
        specifications = ?,
        selling_points = ?,
        tags = ?,
        seo_title = ?,
        seo_description = ?,
        image_path = ?,
        status = ?,
        updated_at = ?
    WHERE id = ?
    """, (
        product_name, brand, model, category, price, dimensions,
        short_desc, desc, features_json, specs_json,
        usp_json, tags_json, seo_title, seo_desc,
        image_path, status, now_str, product_id
    ))

    conn.commit()
    conn.close()
    return True


def delete_product(product_id: int) -> bool:
    """Deletes a product by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    return rows_affected > 0


def get_catalog_stats() -> dict:
    """Computes real catalog statistics from the database."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT count(*) FROM products")
    total_products = cursor.fetchone()[0]

    cursor.execute("SELECT count(DISTINCT brand) FROM products WHERE brand IS NOT NULL AND brand != '' AND brand != 'Unspecified'")
    total_brands = cursor.fetchone()[0]

    cursor.execute("SELECT count(DISTINCT category) FROM products WHERE category IS NOT NULL AND category != ''")
    total_categories = cursor.fetchone()[0]

    cursor.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL ORDER BY category ASC")
    categories = [r[0] for r in cursor.fetchall() if r[0]]

    cursor.execute("SELECT DISTINCT brand FROM products WHERE brand IS NOT NULL AND brand != 'Unspecified' ORDER BY brand ASC")
    brands = [r[0] for r in cursor.fetchall() if r[0]]

    cursor.execute("SELECT count(*) FROM products WHERE extraction_source LIKE 'gemini%'")
    ai_enriched = cursor.fetchone()[0]

    cursor.execute("SELECT count(*) FROM inquiries")
    total_inquiries = cursor.fetchone()[0]

    cursor.execute("SELECT count(*) FROM orders")
    total_orders = cursor.fetchone()[0]

    conn.close()

    return {
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
