"""
Suchit Catalog - Database Management Module
SQLite database interaction layer with auto-migration, safe column additions,
indexed queries, and robust multi-type field parsing.
"""
import sqlite3
import json
import logging
from datetime import datetime
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
    to ensure all columns exist, preserving all legacy data.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Create base table
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

    # Inspect current schema
    cursor.execute("PRAGMA table_info(products);")
    existing_columns = {row['name'] for row in cursor.fetchall()}

    # Required modern schema columns
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

    # Create performance indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_id ON products(id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);")

    conn.commit()
    conn.close()
    logger.info("Database initialized and schema verified.")


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
        # Fallback to comma/newline split
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
    
    # Ensure sensible defaults for missing fields
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

    # Sorting
    if sort == "name_asc":
        query += " ORDER BY product_name ASC"
    elif sort == "name_desc":
        query += " ORDER BY product_name DESC"
    elif sort == "price_asc":
        query += " ORDER BY price ASC"
    elif sort == "price_desc":
        query += " ORDER BY price DESC"
    else:
        # Default newest first
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

    conn.close()

    return {
        "total_products": total_products,
        "total_brands": total_brands,
        "total_categories": total_categories,
        "categories": categories,
        "brands": brands,
        "ai_enriched_count": ai_enriched,
        "export_ready_count": total_products
    }
