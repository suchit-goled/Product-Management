"""
Suchit - AI Product Catalog Generator
Flask Web Application with Multimodal Image Cataloging, Gemini AI Integration,
PDF/CSV/JSON Exports, and Resilient Storage.
"""
import os
import io
import json
import logging
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from dotenv import set_key

from config import Config
import database
from services.image_service import validate_and_save_image
from services.gemini_service import analyze_product_image, test_gemini_connection
from services.pdf_service import generate_single_product_pdf, generate_catalog_pdf
from services.export_service import export_products_csv, export_products_json

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("suchit.app")

# Determine templates and static folder
BASE_DIR = Config.BASE_DIR
template_folder = os.path.join(BASE_DIR, "templates")
if not os.path.exists(template_folder):
    template_folder = os.path.join(BASE_DIR, "my-project-folder", "templates")

static_folder = os.path.join(BASE_DIR, "static")
if not os.path.exists(static_folder):
    static_folder = os.path.join(BASE_DIR, "my-project-folder", "static")

app = Flask(
    __name__,
    template_folder=template_folder,
    static_folder=static_folder
)
app.config.from_object(Config)
CORS(app)

# Ensure upload directory exists
upload_dir = Config.UPLOAD_FOLDER
os.makedirs(upload_dir, exist_ok=True)

# Initialize database
database.init_db()


# ==============================================================================
# STATIC & MEDIA SERVING
# ==============================================================================

@app.route('/static/uploads/<path:filename>')
def serve_upload(filename):
    """Explicitly serve uploaded product media files."""
    return send_from_directory(Config.UPLOAD_FOLDER, filename)


# ==============================================================================
# UI ROUTES
# ==============================================================================

@app.route('/')
def home():
    """Serves the modernized Suchit Catalog Workspace SPA."""
    stats = database.get_catalog_stats()
    api_status = bool(Config.GEMINI_API_KEY and len(Config.GEMINI_API_KEY) > 10)
    return render_template(
        'index.html',
        app_name="Suchit Catalog",
        stats=stats,
        api_configured=api_status
    )


# ==============================================================================
# IMAGE UPLOAD & AI EXTRACTION
# ==============================================================================

@app.route('/upload', methods=['POST'])
def upload_image():
    """
    Primary image upload and AI extraction route.
    Accepts multipart form-data with 'image' file.
    Optional form fields:
      - save_immediately: 'true' (default, matches legacy upload.py) or 'false' (for interactive review)
      - model: Gemini model override
    """
    try:
        if 'image' not in request.files:
            return jsonify({"error": "No image uploaded"}), 400

        image_file = request.files['image']
        if not image_file or image_file.filename == '':
            return jsonify({"error": "No selected file"}), 400

        # Validate and sanitize image using Pillow with EXIF orientation correction
        relative_url, absolute_path, img_metadata, err = validate_and_save_image(
            image_file, Config.UPLOAD_FOLDER
        )
        if err:
            return jsonify({"error": err}), 400

        # Run AI Multimodal extraction or local fallback
        selected_model = request.form.get("model", "gemini-2.5-flash")
        extracted_data = analyze_product_image(absolute_path, model_name=selected_model)
        extracted_data["image_path"] = relative_url

        # Check whether to save immediately or return draft for review
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
    """
    Returns list of products, supporting search, category, brand, and sorting.
    """
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
# SYSTEM & CONFIGURATION APIS
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
    """Returns application health and configuration diagnostics."""
    has_key = bool(Config.GEMINI_API_KEY and len(Config.GEMINI_API_KEY) > 10)
    stats = database.get_catalog_stats()
    return jsonify({
        "status": "healthy",
        "app_name": "Suchit Product Catalog Generator",
        "version": "2.0.0",
        "database": {
            "status": "connected",
            "products_count": stats["total_products"]
        },
        "ai_engine": {
            "gemini_api_key_configured": has_key,
            "default_model": "gemini-2.5-flash"
        },
        "uploads": {
            "directory": Config.UPLOAD_FOLDER,
            "writable": os.access(Config.UPLOAD_FOLDER, os.W_OK)
        }
    })


@app.route('/api/settings/test-key', methods=['POST'])
def test_key_route():
    """Tests a provided API key or currently configured key."""
    try:
        data = request.get_json() or {}
        key = data.get("api_key") or Config.GEMINI_API_KEY
        result = test_gemini_connection(key)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/settings', methods=['POST'])
def update_settings():
    """Updates runtime configuration and persists to .env file safely."""
    try:
        data = request.get_json() or {}
        new_key = data.get("gemini_api_key")

        if new_key is not None:
            new_key = new_key.strip()
            Config.GEMINI_API_KEY = new_key
            # Persist to .env
            env_file = os.path.join(Config.BASE_DIR, ".env")
            try:
                set_key(env_file, "GEMINI_API_KEY", new_key)
            except Exception as env_err:
                logger.warning(f"Failed to persist to .env: {env_err}")

        return jsonify({
            "message": "Settings updated successfully",
            "gemini_api_key_configured": bool(Config.GEMINI_API_KEY)
        })
    except Exception as e:
        logger.error(f"Error updating settings: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Suchit Product Catalog Generator on http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
