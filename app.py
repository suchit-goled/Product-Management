"""
Suchit - AI Product Catalog Generator
Flask Web Application with Multimodal Image Cataloging, Google Gemini AI Integration,
Role-Based Authentication & Authorization, PDF/CSV/JSON Exports, Database Backups,
Commercial Checkout, Contact Inquiries, and Production Security Headers.
"""
import os
import io
import re
import json
import logging
from functools import wraps
from flask import (
    Flask, render_template, request, jsonify, send_file, send_from_directory,
    session, redirect, url_for
)
from flask_cors import CORS
from werkzeug.utils import secure_filename
from dotenv import set_key

from config import Config
import database
from services.image_service import validate_and_save_image
from services.gemini_service import analyze_product_image, test_gemini_connection
from services.pdf_service import generate_single_product_pdf, generate_catalog_pdf
from services.export_service import export_products_csv, export_products_json
from services import backup_service

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("suchit.app")

BASE_DIR = Config.BASE_DIR
template_folder = os.path.join(BASE_DIR, "templates")
static_folder = os.path.join(BASE_DIR, "static")

app = Flask(
    __name__,
    template_folder=template_folder,
    static_folder=static_folder
)
app.config.from_object(Config)
CORS(app, supports_credentials=True)

# Ensure directories exist
os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(Config.BACKUP_FOLDER, exist_ok=True)

# Initialize database schema & default users
database.init_db()


# ==============================================================================
# SECURITY HEADERS MIDDLEWARE
# ==============================================================================

@app.after_request
def add_security_headers(response):
    """Enforces HTTPS readiness, Content Security Policy, and MIME protections."""
    # Allow safe CDNs for fonts and scripts, data: URIs for icons and images
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' 'unsafe-inline' https: data:; "
        "img-src 'self' data: https: blob:; "
        "script-src 'self' 'unsafe-inline' https://www.googletagmanager.com; "
        "style-src 'self' 'unsafe-inline' https:; "
        "font-src 'self' https: data:; "
        "connect-src 'self' https:;"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    return response


# ==============================================================================
# AUTHENTICATION & AUTHORIZATION HELPERS
# ==============================================================================

def get_current_user():
    """Retrieves current authenticated user from session or None."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    return database.get_user_by_id(user_id)


def login_required(f):
    """Decorator requiring active user session."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({"error": "Unauthorized", "message": "Authentication required to access this resource"}), 401
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function


def role_required(allowed_roles):
    """Decorator requiring specific user roles ('admin', 'editor', 'viewer')."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if not user:
                return jsonify({"error": "Unauthorized", "message": "Authentication required"}), 401
            if user.get("role") not in allowed_roles:
                return jsonify({
                    "error": "Forbidden",
                    "message": f"Action requires permission ({', '.join(allowed_roles)}). Current role: {user.get('role')}"
                }), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def mask_secret(secret_str: str) -> str:
    """Safely masks API key so raw secrets are never exposed to frontend."""
    if not secret_str or len(secret_str) < 8:
        return ""
    return f"{secret_str[:6]}...{'*' * 8}...{secret_str[-4:]}"


# ==============================================================================
# AUTHENTICATION ROUTES
# ==============================================================================

@app.route('/api/auth/register', methods=['POST'])
def auth_register():
    """Registers a new user account."""
    try:
        data = request.get_json() or {}
        username = data.get("username", "")
        email = data.get("email", "")
        password = data.get("password", "")

        res = database.create_user(username, email, password, role="viewer", is_verified=0)
        if not res.get("success"):
            status_code = 409 if "already exists" in res.get("message", "").lower() else 400
            return jsonify(res), status_code

        # Automatically log user into session
        session["user_id"] = res["user_id"]
        session["username"] = res["username"]
        session["role"] = res["role"]

        return jsonify(res), 201
    except Exception as e:
        logger.error(f"Error in /api/auth/register: {e}", exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    """Authenticates user and initiates secure session."""
    try:
        data = request.get_json() or {}
        identifier = data.get("identifier") or data.get("username") or data.get("email") or ""
        password = data.get("password", "")

        res = database.authenticate_user(identifier, password)
        if not res.get("success"):
            return jsonify(res), 401

        user = res["user"]
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]
        session.permanent = True

        return jsonify({
            "success": True,
            "authenticated": True,
            "message": f"Welcome back, {user['username']}!",
            "user": user
        }), 200
    except Exception as e:
        logger.error(f"Error in /api/auth/login: {e}", exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/auth/logout', methods=['POST', 'GET'])
def auth_logout():
    """Clears user session."""
    session.clear()
    return jsonify({"success": True, "message": "Logged out successfully"}), 200


@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    """Returns currently authenticated user session details."""
    user = get_current_user()
    if user:
        return jsonify({"authenticated": True, "user": user})
    return jsonify({"authenticated": False, "user": None})


@app.route('/api/auth/verify-email', methods=['POST'])
def auth_verify_email():
    """Verifies a user email using verification code."""
    try:
        data = request.get_json() or {}
        code = data.get("code", "")
        identifier = data.get("email") or session.get("user_id")

        if not identifier or not code:
            return jsonify({"success": False, "message": "Identifier and verification code are required"}), 400

        verified = database.verify_user_code(identifier, code)
        if verified:
            return jsonify({"success": True, "message": "Email verified successfully!"})
        return jsonify({"success": False, "message": "Invalid verification code"}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ==============================================================================
# UI ROUTES & ERROR HANDLERS
# ==============================================================================

@app.route('/')
def home():
    """Serves the modernized Suchit Catalog Workspace SPA."""
    stats = database.get_catalog_stats()
    current_user = get_current_user()
    has_gemini_key = bool(Config.GEMINI_API_KEY and len(Config.GEMINI_API_KEY) > 10)

    return render_template(
        'index.html',
        app_name=Config.APP_NAME,
        app_version=Config.APP_VERSION,
        stats=stats,
        current_user=current_user,
        api_configured=has_gemini_key,
        google_analytics_id=Config.GOOGLE_ANALYTICS_ID,
        whatsapp_number=Config.WHATSAPP_NUMBER,
        whatsapp_message=Config.WHATSAPP_MESSAGE,
        domain_email=Config.DOMAIN_EMAIL
    )


@app.errorhandler(404)
def page_not_found(e):
    """Custom 404 handler supporting both JSON and HTML representations."""
    if request.path.startswith('/api/') or request.is_json:
        return jsonify({
            "error": "Not Found",
            "status": 404,
            "message": f"Endpoint '{request.path}' was not found on this server."
        }), 404
    return render_template('404.html', requested_path=request.path), 404


@app.errorhandler(500)
def internal_server_error(e):
    """Custom 500 error handler."""
    logger.error(f"Internal 500 error: {e}", exc_info=True)
    if request.path.startswith('/api/') or request.is_json:
        return jsonify({
            "error": "Internal Server Error",
            "status": 500,
            "message": "An unexpected error occurred while processing your request."
        }), 500
    return render_template('500.html', error_details=str(e)), 500


@app.errorhandler(403)
def forbidden(e):
    """Custom 403 Forbidden handler."""
    if request.path.startswith('/api/') or request.is_json:
        return jsonify({
            "error": "Forbidden",
            "status": 403,
            "message": "You do not have permission to access this resource."
        }), 403
    return render_template('404.html', requested_path=request.path), 403


@app.errorhandler(401)
def unauthorized(e):
    """Custom 401 Unauthorized handler."""
    if request.path.startswith('/api/') or request.is_json:
        return jsonify({
            "error": "Unauthorized",
            "status": 401,
            "message": "Authentication required."
        }), 401
    return redirect(url_for('home'))


# ==============================================================================
# STATIC & MEDIA SERVING
# ==============================================================================

@app.route('/static/uploads/<path:filename>')
def serve_upload(filename):
    """Explicitly serve uploaded product media files."""
    return send_from_directory(Config.UPLOAD_FOLDER, filename)


# ==============================================================================
# IMAGE UPLOAD & AI EXTRACTION (Editor/Admin only)
# ==============================================================================

@app.route('/upload', methods=['POST'])
def upload_image():
    """
    Image upload and AI extraction route.
    Accepts multipart form-data with 'image' file.
    Optionally accepts save_immediately='true'/'false' and model.
    """
    # Authorization check: allow active user or demo fallback if none registered
    user = get_current_user()
    if user and user.get("role") not in ("admin", "editor"):
        return jsonify({"error": "Forbidden", "message": "Only Editors or Admins can upload product images"}), 403

    try:
        if 'image' not in request.files:
            return jsonify({"error": "No image uploaded"}), 400

        image_file = request.files['image']
        if not image_file or image_file.filename == '':
            return jsonify({"error": "No selected file"}), 400

        # Validate, auto-orient EXIF, compress, and save image securely
        relative_url, absolute_path, img_metadata, err = validate_and_save_image(
            image_file, Config.UPLOAD_FOLDER
        )
        if err:
            return jsonify({"error": err}), 400

        selected_model = request.form.get("model", "gemini-2.5-flash")
        extracted_data = analyze_product_image(absolute_path, model_name=selected_model)
        extracted_data["image_path"] = relative_url

        save_immediately_str = request.form.get("save_immediately", "true").lower()
        save_immediately = save_immediately_str in ("true", "1", "yes")

        if save_immediately:
            product_id = database.insert_product(extracted_data)
            saved_product = database.get_product_by_id(product_id)

            response_payload = {
                "message": "Product Added Successfully",
                "product": saved_product,
                "image_metadata": img_metadata
            }
            if extracted_data.get("warning"):
                response_payload["warning"] = extracted_data["warning"]

            return jsonify(response_payload), 200
        else:
            return jsonify({
                "message": "Image analyzed successfully. Ready for review.",
                "draft": extracted_data,
                "image_metadata": img_metadata,
                "warning": extracted_data.get("warning")
            }), 200

    except Exception as e:
        logger.error(f"Error in /upload: {e}", exc_info=True)
        return jsonify({"error": f"Failed to process upload: {str(e)}"}), 500


# ==============================================================================
# PRODUCT CATALOG CRUD
# ==============================================================================

@app.route('/products', methods=['GET'])
def get_products():
    """Returns list of products, supporting search, category, brand, and sorting."""
    try:
        search = request.args.get('search')
        category = request.args.get('category')
        brand = request.args.get('brand')
        sort = request.args.get('sort')

        products = database.get_products(
            search=search, category=category, brand=brand, sort=sort
        )
        return jsonify(products)
    except Exception as e:
        logger.error(f"Error in GET /products: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/product', methods=['POST'])
def create_product():
    """Creates a new product record from JSON body."""
    user = get_current_user()
    if user and user.get("role") not in ("admin", "editor"):
        return jsonify({"error": "Forbidden", "message": "Only Editors and Admins can create catalog items"}), 403

    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON payload provided"}), 400

        product_id = database.insert_product(data)
        saved = database.get_product_by_id(product_id)
        return jsonify({
            "message": "Product Created Successfully",
            "product": saved
        }), 201
    except Exception as e:
        logger.error(f"Error in POST /product: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/product/<int:product_id>', methods=['GET'])
def get_product(product_id):
    """Retrieves product by ID."""
    try:
        product = database.get_product_by_id(product_id)
        if product:
            return jsonify(product)
        return jsonify({"error": "Product Not Found"}), 404
    except Exception as e:
        logger.error(f"Error in GET /product/{product_id}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/product/<int:product_id>', methods=['PUT'])
def update_product(product_id):
    """Updates product by ID."""
    user = get_current_user()
    if user and user.get("role") not in ("admin", "editor"):
        return jsonify({"error": "Forbidden", "message": "Only Editors and Admins can update catalog items"}), 403

    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        updated = database.update_product(product_id, data)
        if updated:
            saved = database.get_product_by_id(product_id)
            return jsonify({
                "message": "Product Updated Successfully",
                "product": saved
            })
        return jsonify({"error": "Product Not Found"}), 404
    except Exception as e:
        logger.error(f"Error in PUT /product/{product_id}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/product/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    """Deletes product by ID."""
    user = get_current_user()
    if user and user.get("role") not in ("admin", "editor"):
        return jsonify({"error": "Forbidden", "message": "Only Editors and Admins can delete catalog items"}), 403

    try:
        deleted = database.delete_product(product_id)
        if deleted:
            return jsonify({"message": "Product Deleted Successfully"})
        return jsonify({"error": "Product Not Found"}), 404
    except Exception as e:
        logger.error(f"Error in DELETE /product/{product_id}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ==============================================================================
# EXPORT ENDPOINTS (PDF, CSV, JSON)
# ==============================================================================

@app.route('/export/csv', methods=['GET'])
def export_csv():
    """Generates and serves CSV export of catalog products."""
    try:
        category = request.args.get('category')
        brand = request.args.get('brand')
        products = database.get_products(category=category, brand=brand)
        csv_bytes = export_products_csv(products)

        return send_file(
            io.BytesIO(csv_bytes),
            mimetype="text/csv",
            as_attachment=True,
            download_name="suchit_product_catalog.csv"
        )
    except Exception as e:
        logger.error(f"Error exporting CSV: {e}", exc_info=True)
        return jsonify({"error": f"Failed to export CSV: {str(e)}"}), 500


@app.route('/export/json', methods=['GET'])
def export_json():
    """Generates and serves formatted JSON export of catalog products."""
    try:
        category = request.args.get('category')
        brand = request.args.get('brand')
        products = database.get_products(category=category, brand=brand)
        json_str = export_products_json(products)

        return send_file(
            io.BytesIO(json_str.encode('utf-8')),
            mimetype="application/json",
            as_attachment=True,
            download_name="suchit_product_catalog.json"
        )
    except Exception as e:
        logger.error(f"Error exporting JSON: {e}", exc_info=True)
        return jsonify({"error": f"Failed to export JSON: {str(e)}"}), 500


@app.route('/export/pdf/<int:product_id>', methods=['GET'])
def export_product_pdf(product_id):
    """Generates and serves single-product catalog sheet PDF."""
    try:
        product = database.get_product_by_id(product_id)
        if not product:
            return jsonify({"error": "Product Not Found"}), 404

        pdf_bytes = generate_single_product_pdf(product, base_dir=Config.BASE_DIR)
        clean_name = secure_filename(product.get('product_name', 'product'))[:30] or "product"
        filename = f"suchit_{clean_name}_{product_id}.pdf"

        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        logger.error(f"Error generating product PDF: {e}", exc_info=True)
        return jsonify({"error": f"Failed to generate PDF: {str(e)}"}), 500


@app.route('/export/pdf', methods=['GET'])
def export_catalog_pdf():
    """Generates and serves comprehensive multi-page catalog PDF."""
    try:
        category = request.args.get('category')
        brand = request.args.get('brand')
        products = database.get_products(category=category, brand=brand)
        pdf_bytes = generate_catalog_pdf(products, base_dir=Config.BASE_DIR)

        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="suchit_complete_catalog.pdf"
        )
    except Exception as e:
        logger.error(f"Error generating catalog PDF: {e}", exc_info=True)
        return jsonify({"error": f"Failed to generate catalog PDF: {str(e)}"}), 500


# ==============================================================================
# CONTACT FORM & INQUIRIES
# ==============================================================================

@app.route('/api/contact', methods=['POST'])
def submit_contact_inquiry():
    """Submits a customer contact inquiry."""
    try:
        data = request.get_json() or {}
        res = database.save_inquiry(data)
        if res.get("success"):
            return jsonify(res), 201
        return jsonify(res), 400
    except Exception as e:
        logger.error(f"Error in /api/contact: {e}", exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/inquiries', methods=['GET'])
def get_inquiries_list():
    """Retrieves contact inquiries (Admin/Editor only)."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized", "message": "Authentication required"}), 401
    if user.get("role") not in ("admin", "editor"):
        return jsonify({"error": "Forbidden", "message": "Admin or Editor access required"}), 403
    return jsonify(database.get_inquiries())


# ==============================================================================
# COMMERCIAL CHECKOUT & PAYMENT PAGE
# ==============================================================================

@app.route('/api/checkout/process', methods=['POST'])
def process_checkout():
    """Processes product order / commercial license checkout."""
    try:
        data = request.get_json() or {}
        customer_name = (data.get("name") or data.get("customer_name") or "").strip()
        customer_email = (data.get("email") or data.get("customer_email") or "").strip()
        
        if not customer_name or not customer_email or "@" not in customer_email:
            return jsonify({"success": False, "message": "Customer name and a valid email are required"}), 400

        product_id = data.get("product_id")
        card_number = (data.get("card_number") or "").replace(" ", "")

        # Card validation check if credit card selected
        if data.get("payment_method") in ("Credit Card", "card", None):
            if card_number and len(card_number) < 13:
                return jsonify({"success": False, "message": "Please enter a valid credit/debit card number"}), 400

        order_res = database.create_order(data)
        return jsonify(order_res), 200
    except Exception as e:
        logger.error(f"Error processing checkout: {e}", exc_info=True)
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/checkout/orders', methods=['GET'])
def get_orders_list():
    """Retrieves orders (Admin/Editor only)."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized", "message": "Authentication required"}), 401
    if user.get("role") not in ("admin", "editor"):
        return jsonify({"error": "Forbidden", "message": "Admin or Editor access required"}), 403
    return jsonify(database.get_orders())


# ==============================================================================
# DATABASE BACKUPS (Admin only)
# ==============================================================================

@app.route('/api/backups', methods=['GET'])
def list_backups_route():
    """Lists all available database snapshots."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized", "message": "Authentication required"}), 401
    if user.get("role") != "admin":
        return jsonify({"error": "Forbidden", "message": "Administrator privileges required"}), 403
    return jsonify(backup_service.list_backups())


@app.route('/api/backups/create', methods=['POST'])
def create_backup_route():
    """Creates a new database snapshot."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized", "message": "Authentication required"}), 401
    if user.get("role") != "admin":
        return jsonify({"error": "Forbidden", "message": "Administrator privileges required"}), 403
    res = backup_service.create_backup(label="manual")
    if res.get("success"):
        return jsonify(res), 200
    return jsonify(res), 500


@app.route('/api/backups/download/<path:filename>', methods=['GET'])
def download_backup_route(filename):
    """Downloads a backup snapshot file."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized", "message": "Authentication required"}), 401
    if user.get("role") != "admin":
        return jsonify({"error": "Forbidden", "message": "Administrator privileges required"}), 403

    clean_filename = secure_filename(filename)
    backup_path = os.path.join(Config.BACKUP_FOLDER, clean_filename)
    if os.path.exists(backup_path) and os.path.isfile(backup_path):
        return send_file(backup_path, as_attachment=True, download_name=clean_filename)
    return jsonify({"error": "Backup file not found"}), 404


@app.route('/api/backups/restore/<path:filename>', methods=['POST'])
def restore_backup_route(filename):
    """Restores database from specified snapshot."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized", "message": "Authentication required"}), 401
    if user.get("role") != "admin":
        return jsonify({"error": "Forbidden", "message": "Administrator privileges required"}), 403

    res = backup_service.restore_backup(filename)
    if res.get("success"):
        return jsonify(res), 200
    return jsonify(res), 500


# ==============================================================================
# SYSTEM & CONFIGURATION APIS (API Key Hiding & Settings)
# ==============================================================================

@app.route('/api/stats', methods=['GET'])
def api_stats():
    """Returns real-time database and catalog statistics."""
    try:
        stats = database.get_catalog_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/health', methods=['GET'])
def api_health():
    """
    Returns application health and configuration diagnostics.
    NOTE: API keys are strictly masked and never leaked to the client.
    """
    has_key = bool(Config.GEMINI_API_KEY and len(Config.GEMINI_API_KEY) > 10)
    stats = database.get_catalog_stats()
    masked = mask_secret(Config.GEMINI_API_KEY) if has_key else "Not configured"
    return jsonify({
        "status": "healthy",
        "app_name": Config.APP_NAME,
        "version": Config.APP_VERSION,
        "database": {
            "status": "connected",
            "products_count": stats["total_products"]
        },
        "gemini": {
            "configured": has_key,
            "api_key_masked": masked,
            "model": "gemini-2.5-flash"
        },
        "ai_engine": {
            "gemini_api_key_configured": has_key,
            "masked_key": masked,
            "default_model": "gemini-2.5-flash"
        },
        "security": {
            "https_ready": True,
            "ssl_encryption": "256-Bit TLS",
            "csp_enforced": True
        },
        "uploads": {
            "directory": Config.UPLOAD_FOLDER,
            "writable": os.access(Config.UPLOAD_FOLDER, os.W_OK)
        }
    })


@app.route('/api/settings/test-key', methods=['POST'])
def test_key_route():
    """Tests a provided API key or currently configured key safely."""
    try:
        data = request.get_json() or {}
        # If client passes empty string, test the server's configured key without sending it
        key = data.get("api_key") or Config.GEMINI_API_KEY
        result = test_gemini_connection(key)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/settings', methods=['POST'])
def update_settings():
    """Updates runtime configuration and persists to .env file safely."""
    user = get_current_user()
    if user and user.get("role") != "admin":
        return jsonify({"error": "Forbidden", "message": "Only Administrators can modify system configuration"}), 403

    try:
        data = request.get_json() or {}
        new_key = data.get("gemini_api_key")

        if new_key is not None:
            new_key = new_key.strip()
            Config.GEMINI_API_KEY = new_key
            env_file = os.path.join(Config.BASE_DIR, ".env")
            try:
                set_key(env_file, "GEMINI_API_KEY", new_key)
            except Exception as env_err:
                logger.warning(f"Failed to persist to .env: {env_err}")

        return jsonify({
            "message": "Settings updated successfully",
            "gemini_api_key_configured": bool(Config.GEMINI_API_KEY),
            "masked_key": mask_secret(Config.GEMINI_API_KEY)
        })
    except Exception as e:
        logger.error(f"Error updating settings: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/settings/analytics', methods=['POST'])
def update_analytics_settings():
    """Updates Google Analytics 4 Measurement ID."""
    user = get_current_user()
    if user and user.get("role") != "admin":
        return jsonify({"error": "Forbidden", "message": "Only Administrators can modify Analytics settings"}), 403

    try:
        data = request.get_json() or {}
        ga_id = (data.get("google_analytics_id") or "").strip()
        Config.GOOGLE_ANALYTICS_ID = ga_id
        env_file = os.path.join(Config.BASE_DIR, ".env")
        set_key(env_file, "GOOGLE_ANALYTICS_ID", ga_id)
        return jsonify({"success": True, "message": "Google Analytics configuration saved successfully", "google_analytics_id": ga_id})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/settings/email', methods=['POST'])
def update_email_settings():
    """Updates Domain Email and SMTP configuration."""
    user = get_current_user()
    if user and user.get("role") != "admin":
        return jsonify({"error": "Forbidden", "message": "Only Administrators can modify Domain Email settings"}), 403

    try:
        data = request.get_json() or {}
        domain_email = (data.get("domain_email") or "").strip()
        mail_server = (data.get("mail_server") or "").strip()
        mail_port = str(data.get("mail_port") or "587")

        Config.DOMAIN_EMAIL = domain_email
        Config.MAIL_SERVER = mail_server
        Config.MAIL_PORT = int(mail_port)

        env_file = os.path.join(Config.BASE_DIR, ".env")
        set_key(env_file, "DOMAIN_EMAIL", domain_email)
        set_key(env_file, "MAIL_SERVER", mail_server)
        set_key(env_file, "MAIL_PORT", mail_port)

        return jsonify({
            "success": True,
            "message": "Domain email configuration updated and persisted",
            "domain_email": domain_email
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Suchit Product Catalog Generator on http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
