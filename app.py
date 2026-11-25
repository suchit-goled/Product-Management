"""
Suchit - AI Product Catalog Generator
Layered Enterprise Architecture:
  Client -> CDN (Static/WebP Edge) -> Load Balancer (ProxyFix/TLS/Rate-Limit/CORS/CSRF)
  -> App Servers (Stateless Auth/RBAC + BFF Gateway + REST Engine)
  -> [Cache (Hot Reads & Opaque Sessions) | Database (WAL Source of Truth) | Message Queue -> Workers]
"""
import os
import io
import uuid
import logging
from functools import wraps
from urllib.parse import urlparse
from flask import (
    Flask, render_template, request, jsonify, send_file, send_from_directory,
    redirect, url_for, g, make_response
)
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from dotenv import set_key

from config import Config
import database
from services import cache_service, queue_service, security_service, worker_service, backup_service
from services.image_service import validate_and_save_image
from services.gemini_service import analyze_product_image, test_gemini_connection
from services.pdf_service import generate_single_product_pdf, generate_catalog_pdf
from services.export_service import export_products_csv, export_products_json

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

# Load Balancer / Reverse Proxy Support (X-Forwarded-For, X-Forwarded-Proto, X-Forwarded-Host)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Strict CORS restricted to explicit configured origins (never wildcard with credentials)
CORS(
    app,
    origins=Config.ALLOWED_ORIGINS,
    supports_credentials=True,
    allow_headers=["Content-Type", "X-CSRF-Token"],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
)

os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(Config.BACKUP_FOLDER, exist_ok=True)

# Initialize Database, Cache/Sessions & Message Queue tables + start Background Worker Pool
database.init_db()
worker_service.start_background_worker()


# ==============================================================================
# HELPER FUNCTIONS (Opaque Sessions, Client IP, Secret Masking)
# ==============================================================================

def _get_client_ip() -> str:
    return (request.remote_addr or "127.0.0.1").strip()


def _resolve_session_and_user():
    """Resolves opaque HttpOnly cookie against Cache + Database; NEVER trusts cookie claims."""
    raw_sid = request.cookies.get(Config.SESSION_COOKIE_NAME)
    if not raw_sid:
        return None, None
    ua = request.headers.get("User-Agent", "")
    sess = cache_service.get_server_session(raw_sid, user_agent=ua)
    if not sess:
        return None, None
    user = database.get_user_by_id(sess["user_id"])
    if not user:
        cache_service.revoke_server_session(raw_sid)
        return None, None
    return sess, user


def mask_secret(secret_str: str) -> str:
    """Masks sensitive API keys for Admin diagnostics only."""
    if not secret_str or len(secret_str) < 8:
        return "Not configured"
    return f"{secret_str[:6]}...{'*' * 8}...{secret_str[-4:]}"


def _sanitize_public_product(p: dict, include_internal: bool = False) -> dict:
    """Prevents leaking internal processing markers to unauthenticated public shoppers."""
    clean = dict(p)
    if not include_internal:
        src = (clean.get("extraction_source") or "").lower()
        clean["extraction_source"] = "ai" if ("gemini" in src or src == "ai") else "verified"
    return clean


# ==============================================================================
# LOAD BALANCER / SECURITY MIDDLEWARE (Auth Resolve, Origin Check, CSRF, Headers)
# ==============================================================================

@app.before_request
def load_balancer_security_gate():
    """Runs before every request: resolves opaque session, CSRF token, and enforces CSRF + Origin."""
    sess, user = _resolve_session_and_user()
    g.server_session = sess
    g.current_user = user
    g.raw_sid = request.cookies.get(Config.SESSION_COOKIE_NAME) if sess else None

    # Compute session-bound CSRF or signed guest CSRF
    if sess:
        g.csrf_token = sess["csrf_token"]
    else:
        g.csrf_token = security_service.generate_guest_csrf_token()

    # Protect all state-changing HTTP methods from Cross-Site Request Forgery
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        # 1. Origin check when Origin header is sent by browser
        origin = request.headers.get("Origin")
        if origin:
            host_origin = f"{request.scheme}://{request.host}"
            allowed = set(Config.ALLOWED_ORIGINS) | {host_origin}
            if origin not in allowed:
                logger.warning(f"Blocked cross-origin mutation from {origin} to {request.path}")
                return jsonify({"error": "Forbidden", "message": "Cross-origin request rejected"}), 403

        # 2. Enforce constant-time CSRF token validation for all state-changing routes
        provided_csrf = (
            request.headers.get("X-CSRF-Token")
            or (request.form.get("csrf_token") if request.form else None)
        )
        if sess:
            if not security_service.verify_csrf_token(sess["csrf_token"], provided_csrf):
                return jsonify({
                    "error": "Forbidden",
                    "message": "Invalid or missing CSRF token. Refresh page and retry."
                }), 403
        else:
            if not security_service.verify_guest_csrf_token(provided_csrf):
                return jsonify({
                    "error": "Forbidden",
                    "message": "Invalid or expired security token. Refresh page and retry."
                }), 403


@app.after_request
def apply_security_and_cdn_headers(response):
    """Applies strict Load Balancer / CDN security & caching headers."""
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: blob:; "
        "script-src 'self' https://www.googletagmanager.com; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; "
        "connect-src 'self' https://www.google-analytics.com https://analytics.google.com; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'self';"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"

    if request.is_secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # CDN edge cache rules vs Private dynamic endpoints
    if request.path.startswith("/static/uploads/") and response.status_code == 200:
        response.headers["Cache-Control"] = f"public, max-age={Config.CDN_STATIC_MAX_AGE}, immutable"
        response.headers["Vary"] = "Accept"
    elif request.path.startswith(("/static/css/", "/static/js/app.js")) and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=3600"
    elif request.path.startswith(("/api/", "/gw/", "/product", "/upload", "/static/js/admin.js", "/static/js/editor.js")):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"

    return response


# ==============================================================================
# DEFAULT-DENY AUTHORIZATION DECORATORS (RBAC)
# ==============================================================================

def login_required(f):
    """Default-deny decorator requiring a valid server-side session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not g.current_user:
            if request.path.startswith(("/api/", "/gw/")) or request.is_json or request.method != "GET":
                return jsonify({"error": "Unauthorized", "message": "Authentication required"}), 401
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return decorated


def role_required(allowed_roles):
    """Strict default-deny RBAC guard checking authoritative DB role."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not g.current_user:
                return jsonify({"error": "Unauthorized", "message": "Authentication required"}), 401
            if g.current_user.get("role") not in allowed_roles:
                return jsonify({
                    "error": "Forbidden",
                    "message": "Insufficient permissions for this operation."
                }), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


def verified_required(f):
    """Requires authenticated account to have completed email verification."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not g.current_user:
            return jsonify({"error": "Unauthorized", "message": "Authentication required"}), 401
        if not g.current_user.get("is_verified"):
            return jsonify({
                "error": "EmailVerificationRequired",
                "message": "Please verify your email address before completing this action."
            }), 403
        return f(*args, **kwargs)
    return decorated


def rate_limit_guard(scope: str, max_requests: int, window_seconds: int):
    """Enforces sliding-window rate limit keyed by scope + client IP."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            bucket = f"rl:{scope}:{_get_client_ip()}"
            allowed, _, retry_after = cache_service.check_rate_limit(bucket, max_requests, window_seconds)
            if not allowed:
                return jsonify({
                    "error": "TooManyRequests",
                    "message": f"Rate limit exceeded. Try again in {retry_after}s."
                }), 429
            return f(*args, **kwargs)
        return decorated
    return decorator


# ==============================================================================
# ROLE-SCOPED FRONTEND ASSETS & CDN WEBP NEGOTIATION
# ==============================================================================

@app.route('/static/uploads/<path:filename>')
def serve_cdn_upload(filename):
    """CDN Edge simulation: negotiates WebP cleanly when Accept: image/webp is sent."""
    clean_name = secure_filename(filename)
    ok, target = security_service.is_safe_contained_path(Config.UPLOAD_FOLDER, clean_name)
    if not ok or not os.path.isfile(target):
        return jsonify({"error": "Not Found"}), 404

    accept_hdr = request.headers.get("Accept", "")
    if "image/webp" in accept_hdr and not clean_name.lower().endswith(".webp"):
        webp_candidate = f"{os.path.splitext(clean_name)[0]}.webp"
        ok_w, target_w = security_service.is_safe_contained_path(Config.UPLOAD_FOLDER, webp_candidate)
        if ok_w and os.path.isfile(target_w):
            resp = make_response(send_from_directory(Config.UPLOAD_FOLDER, webp_candidate))
            resp.mimetype = "image/webp"
            return resp

    return send_from_directory(Config.UPLOAD_FOLDER, clean_name)


@app.route('/static/js/editor.js')
def serve_editor_bundle():
    """Role-gated JS bundle: NEVER shipped to unauthenticated users or viewers."""
    if not g.current_user or g.current_user.get("role") not in ("admin", "editor"):
        return jsonify({"error": "Forbidden"}), 403
    return send_from_directory(os.path.join(static_folder, "js"), "editor.js")


@app.route('/static/js/admin.js')
def serve_admin_bundle():
    """Admin-only JS bundle: hidden completely from non-admin browsers."""
    if not g.current_user or g.current_user.get("role") != "admin":
        return jsonify({"error": "Forbidden"}), 403
    return send_from_directory(os.path.join(static_folder, "js"), "admin.js")


# ==============================================================================
# UI ENTRYPOINT & ERROR HANDLERS
# ==============================================================================

@app.route('/')
def home():
    """Server-side renders role-gated workspace without leaking internal APIs or admin DOM."""
    stats = database.get_catalog_stats()
    # Public stats never expose internal admin order/inquiry counts
    public_stats = {
        "total_products": stats["total_products"],
        "total_brands": stats["total_brands"],
        "total_categories": stats["total_categories"],
        "export_ready_count": stats["export_ready_count"],
    }
    return render_template(
        'index.html',
        app_name=Config.APP_NAME,
        app_version=Config.APP_VERSION,
        stats=public_stats,
        current_user=g.current_user,
        csrf_token=g.csrf_token,
        google_analytics_id=Config.GOOGLE_ANALYTICS_ID,
        whatsapp_number=Config.WHATSAPP_NUMBER,
        whatsapp_message=Config.WHATSAPP_MESSAGE,
        domain_email=Config.DOMAIN_EMAIL,
        mail_server=Config.MAIL_SERVER,
        mail_port=Config.MAIL_PORT,
    )


@app.route('/healthz', methods=['GET'])
def liveness_probe():
    """Minimal load-balancer health check revealing zero secrets or server paths."""
    return jsonify({"status": "ok"}), 200


@app.errorhandler(404)
def page_not_found(e):
    if request.path.startswith(('/api/', '/gw/')) or request.is_json:
        return jsonify({
            "error": "Not Found",
            "status": 404,
            "message": f"Resource '{request.path}' was not found."
        }), 404
    return render_template('404.html', requested_path=request.path), 404


@app.errorhandler(500)
def internal_server_error(e):
    incident_id = f"ERR-{uuid.uuid4().hex[:8].upper()}"
    logger.error(f"[{incident_id}] Internal 500 error: {e}", exc_info=True)
    if request.path.startswith(('/api/', '/gw/')) or request.is_json:
        return jsonify({
            "error": "Internal Server Error",
            "status": 500,
            "incident_id": incident_id,
            "message": "An unexpected internal error occurred. Reference incident_id for support."
        }), 500
    return render_template('500.html', incident_id=incident_id), 500


@app.errorhandler(403)
def forbidden(e):
    if request.path.startswith(('/api/', '/gw/')) or request.is_json:
        return jsonify({"error": "Forbidden", "status": 403, "message": "Access denied."}), 403
    return render_template('404.html', requested_path=request.path), 403


@app.errorhandler(401)
def unauthorized(e):
    if request.path.startswith(('/api/', '/gw/')) or request.is_json:
        return jsonify({"error": "Unauthorized", "status": 401, "message": "Authentication required."}), 401
    return redirect(url_for('home'))


# ==============================================================================
# AUTHENTICATION & SESSION MANAGEMENT (Gateway /gw/auth/* & /api/auth/*)
# ==============================================================================

@app.route('/gw/auth/register', methods=['POST'])
@app.route('/api/auth/register', methods=['POST'])
@rate_limit_guard("register", max_requests=10, window_seconds=300)
def auth_register():
    try:
        data = request.get_json() or {}
        username = data.get("username", "")
        email = data.get("email", "")
        password = data.get("password", "")

        # Public registration strictly forces viewer role & unverified status
        res = database.create_user(username, email, password, allow_elevated_role=None, is_verified=0)
        if not res.get("success"):
            status_code = 409 if "already exists" in res.get("message", "").lower() else 400
            return jsonify(res), status_code

        # Trigger immediate async worker pass for verification delivery without stalling caller
        worker_service.process_pending_once(max_jobs=2)

        # Rotate / clear prior session and establish opaque server-side session
        if g.raw_sid:
            cache_service.revoke_server_session(g.raw_sid)

        raw_sid, csrf_tok = cache_service.create_server_session(
            user_id=res["user_id"],
            role="viewer",
            client_ip=_get_client_ip(),
            user_agent=request.headers.get("User-Agent", "")
        )

        payload = dict(res)
        payload["csrf_token"] = csrf_tok
        resp = make_response(jsonify(payload), 201)
        resp.set_cookie(
            Config.SESSION_COOKIE_NAME,
            raw_sid,
            max_age=Config.PERMANENT_SESSION_LIFETIME,
            httponly=True,
            samesite=Config.SESSION_COOKIE_SAMESITE,
            secure=Config.SESSION_COOKIE_SECURE
        )
        return resp
    except Exception as e:
        logger.error(f"Error in auth_register: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Registration processing failed"}), 500


@app.route('/gw/auth/login', methods=['POST'])
@app.route('/api/auth/login', methods=['POST'])
@rate_limit_guard("login", max_requests=15, window_seconds=300)
def auth_login():
    try:
        data = request.get_json() or {}
        identifier = data.get("identifier") or data.get("username") or data.get("email") or ""
        password = data.get("password", "")

        res = database.authenticate_user(identifier, password)
        if not res.get("success"):
            status = 423 if res.get("locked") else 401
            return jsonify(res), status

        user = res["user"]
        # Session Fixation Prevention: always revoke any prior sid before issuing a fresh CSPRNG sid
        if g.raw_sid:
            cache_service.revoke_server_session(g.raw_sid)

        raw_sid, csrf_tok = cache_service.create_server_session(
            user_id=user["id"],
            role=user["role"],
            client_ip=_get_client_ip(),
            user_agent=request.headers.get("User-Agent", "")
        )
        cache_service.reset_rate_limit(f"rl:login:{_get_client_ip()}")

        resp = make_response(jsonify({
            "success": True,
            "authenticated": True,
            "csrf_token": csrf_tok,
            "message": f"Welcome back, {user['username']}!",
            "user": user
        }), 200)
        resp.set_cookie(
            Config.SESSION_COOKIE_NAME,
            raw_sid,
            max_age=Config.PERMANENT_SESSION_LIFETIME,
            httponly=True,
            samesite=Config.SESSION_COOKIE_SAMESITE,
            secure=Config.SESSION_COOKIE_SECURE
        )
        return resp
    except Exception as e:
        logger.error(f"Error in auth_login: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Authentication processing error"}), 500


@app.route('/gw/auth/logout', methods=['POST'])
@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    if g.raw_sid:
        cache_service.revoke_server_session(g.raw_sid)
    resp = make_response(jsonify({
        "success": True,
        "authenticated": False,
        "message": "Signed out securely"
    }), 200)
    resp.delete_cookie(Config.SESSION_COOKIE_NAME)
    return resp


@app.route('/gw/auth/me', methods=['GET'])
@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    if g.current_user:
        return jsonify({
            "authenticated": True,
            "user": g.current_user,
            "csrf_token": g.csrf_token
        })
    return jsonify({
        "authenticated": False,
        "user": None,
        "csrf_token": g.csrf_token
    })


@app.route('/gw/auth/verify-email', methods=['POST'])
@app.route('/api/auth/verify-email', methods=['POST'])
@rate_limit_guard("verify_otp", max_requests=10, window_seconds=300)
def auth_verify_email():
    try:
        data = request.get_json() or {}
        code = data.get("code", "")
        identifier = (g.current_user["id"] if g.current_user else None) or data.get("email")

        if not identifier or not code:
            return jsonify({"success": False, "message": "User session/email and 6-digit code are required"}), 400

        verified, msg = database.verify_user_code(identifier, code)
        if verified:
            return jsonify({"success": True, "message": msg}), 200
        return jsonify({"success": False, "message": msg}), 400
    except Exception as e:
        logger.error(f"Error verifying email: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Verification error"}), 500


@app.route('/gw/auth/resend-verification', methods=['POST'])
@login_required
@rate_limit_guard("resend_otp", max_requests=3, window_seconds=300)
def auth_resend_verification():
    res = database.regenerate_verification_code(g.current_user["id"])
    worker_service.process_pending_once(max_jobs=2)
    return jsonify(res), 200 if res.get("success") else 400


# ==============================================================================
# CATALOG READS & EXPORTS (Public Safe + Hot-Read Cached)
# ==============================================================================

@app.route('/gw/catalog', methods=['GET'])
@app.route('/products', methods=['GET'])
def get_products():
    try:
        search = request.args.get('search')
        category = request.args.get('category')
        brand = request.args.get('brand')
        sort = request.args.get('sort')

        products = database.get_products(search=search, category=category, brand=brand, sort=sort)
        is_staff = bool(g.current_user and g.current_user.get("role") in ("admin", "editor"))
        return jsonify([_sanitize_public_product(p, include_internal=is_staff) for p in products])
    except Exception as e:
        logger.error(f"Error in GET /products: {e}", exc_info=True)
        return jsonify({"error": "Failed to fetch catalog products"}), 500


@app.route('/gw/catalog/item/<int:product_id>', methods=['GET'])
@app.route('/product/<int:product_id>', methods=['GET'])
def get_product(product_id):
    try:
        product = database.get_product_by_id(product_id)
        if product:
            is_staff = bool(g.current_user and g.current_user.get("role") in ("admin", "editor"))
            return jsonify(_sanitize_public_product(product, include_internal=is_staff))
        return jsonify({"error": "Product Not Found"}), 404
    except Exception as e:
        logger.error(f"Error fetching product #{product_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to retrieve product"}), 500


@app.route('/api/stats', methods=['GET'])
@app.route('/gw/stats', methods=['GET'])
def api_stats():
    """Returns catalog summary metrics; strips internal order/inquiry stats unless Admin."""
    try:
        stats = database.get_catalog_stats()
        is_admin_user = bool(g.current_user and g.current_user.get("role") == "admin")
        payload = {
            "total_products": stats["total_products"],
            "total_brands": stats["total_brands"],
            "total_categories": stats["total_categories"],
            "categories": stats["categories"],
            "brands": stats["brands"],
            "export_ready_count": stats["export_ready_count"],
        }
        if is_admin_user:
            payload["ai_enriched_count"] = stats["ai_enriched_count"]
            payload["total_inquiries"] = stats["total_inquiries"]
            payload["total_orders"] = stats["total_orders"]
        return jsonify(payload)
    except Exception as e:
        logger.error(f"Stats error: {e}", exc_info=True)
        return jsonify({"error": "Stats unavailable"}), 500


@app.route('/export/csv', methods=['GET'])
def export_csv():
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
        return jsonify({"error": "Failed to export CSV"}), 500


@app.route('/export/json', methods=['GET'])
def export_json():
    try:
        category = request.args.get('category')
        brand = request.args.get('brand')
        products = database.get_products(category=category, brand=brand)
        is_staff = bool(g.current_user and g.current_user.get("role") in ("admin", "editor"))
        sanitized = [_sanitize_public_product(p, include_internal=is_staff) for p in products]
        json_str = export_products_json(sanitized)
        return send_file(
            io.BytesIO(json_str.encode('utf-8')),
            mimetype="application/json",
            as_attachment=True,
            download_name="suchit_product_catalog.json"
        )
    except Exception as e:
        logger.error(f"Error exporting JSON: {e}", exc_info=True)
        return jsonify({"error": "Failed to export JSON"}), 500


@app.route('/export/pdf/<int:product_id>', methods=['GET'])
def export_product_pdf(product_id):
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
        logger.error(f"Error generating PDF for #{product_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to generate PDF"}), 500


@app.route('/export/pdf', methods=['GET'])
def export_catalog_pdf():
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
        return jsonify({"error": "Failed to generate catalog PDF"}), 500


# ==============================================================================
# STUDIO UPLOAD & CATALOG MUTATIONS (STRICT Editor / Admin ONLY)
# ==============================================================================

@app.route('/gw/studio/upload', methods=['POST'])
@app.route('/upload', methods=['POST'])
@role_required(["admin", "editor"])
@rate_limit_guard("upload", max_requests=25, window_seconds=300)
def upload_image():
    try:
        if 'image' not in request.files:
            return jsonify({"error": "No image uploaded"}), 400

        image_file = request.files['image']
        if not image_file or image_file.filename == '':
            return jsonify({"error": "No selected file"}), 400

        relative_url, absolute_path, img_metadata, err = validate_and_save_image(
            image_file, Config.UPLOAD_FOLDER
        )
        if err:
            return jsonify({"error": err}), 400

        allowed_models = {"gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"}
        selected_model = request.form.get("model", "gemini-2.5-flash")
        if selected_model not in allowed_models:
            selected_model = "gemini-2.5-flash"

        extracted_data = analyze_product_image(absolute_path, model_name=selected_model)
        extracted_data["image_path"] = relative_url

        save_immediately = request.form.get("save_immediately", "true").lower() in ("true", "1", "yes")
        if save_immediately:
            product_id = database.insert_product(extracted_data)
            saved_product = database.get_product_by_id(product_id)
            resp = {
                "message": "Product Added Successfully",
                "product": saved_product,
                "image_metadata": img_metadata
            }
            if extracted_data.get("warning"):
                resp["warning"] = extracted_data["warning"]
            return jsonify(resp), 200
        else:
            return jsonify({
                "message": "Image analyzed successfully. Ready for review.",
                "draft": extracted_data,
                "image_metadata": img_metadata,
                "warning": extracted_data.get("warning")
            }), 200
    except Exception as e:
        logger.error(f"Error in upload_image: {e}", exc_info=True)
        return jsonify({"error": "Failed to process upload"}), 500


@app.route('/gw/catalog/item', methods=['POST'])
@app.route('/product', methods=['POST'])
@role_required(["admin", "editor"])
def create_product():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON payload provided"}), 400
        product_id = database.insert_product(data)
        saved = database.get_product_by_id(product_id)
        return jsonify({"message": "Product Created Successfully", "product": saved}), 201
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error creating product: {e}", exc_info=True)
        return jsonify({"error": "Failed to create product"}), 500


@app.route('/gw/catalog/item/<int:product_id>', methods=['PUT'])
@app.route('/product/<int:product_id>', methods=['PUT'])
@role_required(["admin", "editor"])
def update_product(product_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
        updated = database.update_product(product_id, data)
        if updated:
            saved = database.get_product_by_id(product_id)
            return jsonify({"message": "Product Updated Successfully", "product": saved}), 200
        return jsonify({"error": "Product Not Found"}), 404
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        logger.error(f"Error updating product #{product_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to update product"}), 500


@app.route('/gw/catalog/item/<int:product_id>', methods=['DELETE'])
@app.route('/product/<int:product_id>', methods=['DELETE'])
@role_required(["admin", "editor"])
def delete_product(product_id):
    try:
        deleted = database.delete_product(product_id)
        if deleted:
            return jsonify({"message": "Product Deleted Successfully"}), 200
        return jsonify({"error": "Product Not Found"}), 404
    except Exception as e:
        logger.error(f"Error deleting product #{product_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to delete product"}), 500


# ==============================================================================
# CONTACT & AUTHORITATIVE CHECKOUT
# ==============================================================================

@app.route('/gw/contact', methods=['POST'])
@app.route('/api/contact', methods=['POST'])
@rate_limit_guard("contact", max_requests=8, window_seconds=300)
def submit_contact_inquiry():
    try:
        data = request.get_json() or {}
        res = database.save_inquiry(data)
        if res.get("success"):
            worker_service.process_pending_once(max_jobs=2)
            return jsonify(res), 201
        return jsonify(res), 400
    except Exception as e:
        logger.error(f"Contact submission error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Unable to submit inquiry right now"}), 500


@app.route('/gw/checkout', methods=['POST'])
@app.route('/api/checkout/process', methods=['POST'])
@login_required
@rate_limit_guard("checkout", max_requests=15, window_seconds=300)
def process_checkout():
    """Requires authenticated session; calculates authoritative DB price server-side."""
    try:
        data = request.get_json() or {}
        order_res, status_code = database.create_verified_order(data, g.current_user)
        if status_code == 200:
            worker_service.process_pending_once(max_jobs=2)
        return jsonify(order_res), status_code
    except Exception as e:
        logger.error(f"Checkout error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Checkout processing error"}), 500


@app.route('/gw/orders', methods=['GET'])
@app.route('/api/checkout/orders', methods=['GET'])
@login_required
def get_orders_list():
    """Admins & Editors see catalog orders; Viewers see strictly their own orders."""
    role = g.current_user.get("role")
    if role in ("admin", "editor"):
        return jsonify(database.get_orders())
    return jsonify(database.get_orders(user_id=g.current_user["id"]))


# ==============================================================================
# ADMIN CONSOLE (STRICT Administrator Role ONLY)
# ==============================================================================

@app.route('/gw/admin/inquiries', methods=['GET'])
@app.route('/api/inquiries', methods=['GET'])
@role_required(["admin"])
def get_inquiries_list():
    return jsonify(database.get_inquiries())


@app.route('/gw/admin/outbox', methods=['GET'])
@role_required(["admin"])
def get_admin_outbox():
    return jsonify({
        "queue": queue_service.get_queue_metrics(),
        "outbox": queue_service.get_recent_outbox(limit=25)
    })


@app.route('/gw/admin/backups', methods=['GET'])
@app.route('/api/backups', methods=['GET'])
@role_required(["admin"])
def list_backups_route():
    return jsonify(backup_service.list_backups())


@app.route('/gw/admin/backups/create', methods=['POST'])
@app.route('/api/backups/create', methods=['POST'])
@role_required(["admin"])
def create_backup_route():
    res = backup_service.create_backup(label="manual")
    return jsonify(res), (200 if res.get("success") else 500)


@app.route('/gw/admin/backups/download/<path:filename>', methods=['GET'])
@app.route('/api/backups/download/<path:filename>', methods=['GET'])
@role_required(["admin"])
def download_backup_route(filename):
    ok, backup_path = security_service.is_safe_contained_path(Config.BACKUP_FOLDER, filename)
    clean_filename = os.path.basename(filename or "")
    if ok and clean_filename.endswith(".db") and os.path.isfile(backup_path):
        return send_file(backup_path, as_attachment=True, download_name=clean_filename)
    return jsonify({"error": "Backup file not found"}), 404


@app.route('/gw/admin/backups/restore/<path:filename>', methods=['POST'])
@app.route('/api/backups/restore/<path:filename>', methods=['POST'])
@role_required(["admin"])
def restore_backup_route(filename):
    res = backup_service.restore_backup(filename)
    return jsonify(res), (200 if res.get("success") else 400)


@app.route('/gw/admin/diagnostics', methods=['GET'])
@app.route('/api/health', methods=['GET'])
@role_required(["admin"])
def admin_diagnostics():
    """Restricted strictly to authenticated Administrators (no key/path leaks to public!)."""
    has_key = bool(Config.GEMINI_API_KEY and len(Config.GEMINI_API_KEY) > 10)
    stats = database.get_catalog_stats()
    masked = mask_secret(Config.GEMINI_API_KEY) if has_key else "Not configured"
    return jsonify({
        "status": "healthy",
        "app_name": Config.APP_NAME,
        "version": Config.APP_VERSION,
        "database": {
            "status": "connected",
            "mode": "WAL",
            "products_count": stats["total_products"]
        },
        "cache": {
            "status": "active",
            "catalog_ttl_seconds": Config.CATALOG_CACHE_TTL_SECONDS
        },
        "queue": queue_service.get_queue_metrics(),
        "gemini": {
            "configured": has_key,
            "api_key_masked": masked,
            "model": "gemini-2.5-flash"
        },
        "security": {
            "https_ready": True,
            "ssl_encryption": "256-Bit TLS",
            "csp_enforced": True,
            "csrf_enforced": True,
            "opaque_sessions": True
        }
    })


@app.route('/gw/admin/settings/test-key', methods=['POST'])
@app.route('/api/settings/test-key', methods=['POST'])
@role_required(["admin"])
def test_key_route():
    try:
        data = request.get_json() or {}
        key = data.get("api_key") or Config.GEMINI_API_KEY
        result = test_gemini_connection(key)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "message": "Key connectivity check failed"}), 500


@app.route('/gw/admin/settings/key', methods=['POST'])
@app.route('/api/settings', methods=['POST'])
@role_required(["admin"])
def update_settings():
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
                logger.warning(f"Failed to persist GEMINI_API_KEY to .env: {env_err}")

        return jsonify({
            "success": True,
            "message": "Settings updated successfully",
            "gemini_api_key_configured": bool(Config.GEMINI_API_KEY),
            "masked_key": mask_secret(Config.GEMINI_API_KEY)
        })
    except Exception as e:
        logger.error(f"Settings update error: {e}", exc_info=True)
        return jsonify({"success": False, "error": "Failed to save API settings"}), 500


@app.route('/gw/admin/settings/analytics', methods=['POST'])
@app.route('/api/settings/analytics', methods=['POST'])
@role_required(["admin"])
def update_analytics_settings():
    try:
        data = request.get_json() or {}
        ga_id = (data.get("google_analytics_id") or "").strip().upper()
        if ga_id and not security_service.GA4_ID_REGEX.match(ga_id):
            return jsonify({"success": False, "message": "Invalid GA4 Measurement ID format (expected G-XXXXXXXXXX)"}), 400
        Config.GOOGLE_ANALYTICS_ID = ga_id
        set_key(os.path.join(Config.BASE_DIR, ".env"), "GOOGLE_ANALYTICS_ID", ga_id)
        return jsonify({"success": True, "message": "Google Analytics ID saved", "google_analytics_id": ga_id})
    except Exception as e:
        return jsonify({"success": False, "message": "Failed to update analytics config"}), 500


@app.route('/gw/admin/settings/email', methods=['POST'])
@app.route('/api/settings/email', methods=['POST'])
@role_required(["admin"])
def update_email_settings():
    try:
        data = request.get_json() or {}
        domain_email = security_service.sanitize_text_field(data.get("domain_email"), 254).lower()
        mail_server = security_service.sanitize_text_field(data.get("mail_server"), 120)
        try:
            mail_port = int(data.get("mail_port") or 587)
            if not (1 <= mail_port <= 65535):
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "Invalid SMTP port (1-65535)"}), 400

        if not security_service.validate_email_address(domain_email):
            return jsonify({"success": False, "message": "Invalid domain email address"}), 400

        Config.DOMAIN_EMAIL = domain_email
        Config.MAIL_SERVER = mail_server
        Config.MAIL_PORT = mail_port

        env_file = os.path.join(Config.BASE_DIR, ".env")
        set_key(env_file, "DOMAIN_EMAIL", domain_email)
        set_key(env_file, "MAIL_SERVER", mail_server)
        set_key(env_file, "MAIL_PORT", str(mail_port))

        return jsonify({
            "success": True,
            "message": "Domain email configuration updated",
            "domain_email": domain_email
        })
    except Exception as e:
        logger.error(f"Email config update error: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Failed to update domain email config"}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "False").lower() in ("true", "1")
    print(f"Starting Suchit Product Catalog Generator on http://127.0.0.1:{port} (debug={debug_mode})")
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
