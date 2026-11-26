"""
Product Catalog
Layered Enterprise Architecture:
  Client -> CDN (Static/WebP Edge) -> Load Balancer (ProxyFix/TLS/Rate-Limit/CORS/CSRF)
  -> App Servers (Stateless Auth/RBAC + BFF Gateway + REST Engine)
  -> [Cache (Hot Reads & Opaque Sessions) | Database (WAL Source of Truth) | Message Queue -> Workers]
"""
import io
import os
import uuid
import logging
from functools import wraps
from urllib.parse import urlparse
from flask import (
    Flask, Response, render_template, request, jsonify, send_file, send_from_directory,
    redirect, url_for, g, make_response
)
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

from config import Config
import database
from services import cache_service, queue_service, security_service, worker_service, backup_service, groq_service
from services.image_service import validate_and_save_image
from services.gemini_service import analyze_product_image, generate_catalog_from_prompt_gemini
from services.pdf_service import generate_single_product_pdf, generate_catalog_pdf
from services.export_service import export_products_csv, export_products_json

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("product_catalog.app")

BASE_DIR = Config.BASE_DIR
template_folder = os.path.join(BASE_DIR, "templates")
static_folder = os.path.join(BASE_DIR, "static")

app = Flask(
    __name__,
    template_folder=template_folder,
    static_folder=static_folder
)
app.config.from_object(Config)

# Load Balancer / Reverse Proxy Support (strictly opt-in via TRUST_PROXY=True to prevent header spoofing)
if Config.TRUST_PROXY:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Strict CORS restricted to explicit configured origins (never wildcard with credentials)
CORS(
    app,
    origins=Config.ALLOWED_ORIGINS,
    supports_credentials=True,
    allow_headers=["Content-Type", "X-CSRF-Token"],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
)

for _dir in (Config.UPLOAD_FOLDER, Config.BACKUP_FOLDER):
    try:
        os.makedirs(_dir, exist_ok=True)
    except OSError as exc:
        logger.warning(f"Directory creation skipped for {_dir}: {exc}")

# Initialize Database, Cache/Sessions & Message Queue tables + start Background Worker Pool (non-serverless only)
database.init_db()
if not Config.IS_SERVERLESS:
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


def _sanitize_public_product(p: dict, include_internal: bool = False) -> dict:
    """Prevents leaking internal processing markers, statuses, and audit timestamps to public shoppers."""
    clean = dict(p)
    if not include_internal:
        for internal_field in ("extraction_source", "status", "created_at", "updated_at"):
            clean.pop(internal_field, None)
    return clean


def _public_user_projection(user: dict) -> dict:
    """Safe frontend user projection (never leaks email, internal numeric id, or hashes)."""
    if not user:
        return None
    return {
        "username": user.get("username"),
        "role": user.get("role"),
        "is_verified": bool(user.get("is_verified")),
    }


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
        host_origin = f"{request.scheme}://{request.host}"
        allowed = set(Config.ALLOWED_ORIGINS) | {host_origin}

        # 1. Origin / Referer check when sent by browser
        origin = request.headers.get("Origin")
        if origin:
            if origin not in allowed:
                logger.warning(f"Blocked cross-origin mutation from {origin} to {request.path}")
                return jsonify({"error": "Forbidden", "message": "Cross-origin request rejected"}), 403
        else:
            referer = request.headers.get("Referer")
            if referer:
                parsed_ref = urlparse(referer)
                ref_origin = f"{parsed_ref.scheme}://{parsed_ref.netloc}" if parsed_ref.scheme and parsed_ref.netloc else ""
                if ref_origin not in allowed:
                    logger.warning(f"Blocked cross-referer mutation from {ref_origin} to {request.path}")
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
    """Applies strict Load Balancer / CDN security & caching headers (zero external tracking)."""
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: blob:; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'self';"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"

    if request.is_secure or (Config.TRUST_PROXY and request.headers.get("X-Forwarded-Proto", "").lower() == "https"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # CDN edge cache rules vs Private dynamic endpoints & HTML containing CSRF/session state
    if request.path.startswith("/static/uploads/") and response.status_code == 200:
        response.headers["Cache-Control"] = f"public, max-age={Config.CDN_STATIC_MAX_AGE}, immutable"
        response.headers["Vary"] = "Accept"
    elif request.path == "/favicon.ico" and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=86400"
    elif request.path.startswith(("/static/css/", "/static/js/app.js")) and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=3600"
    elif (
        request.path == "/"
        or response.status_code >= 400
        or request.path.startswith(("/api/", "/gw/", "/product", "/upload", "/export/", "/static/js/admin.js", "/static/js/editor.js"))
    ):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

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

def _resolve_upload_asset(clean_name: str):
    """Finds an uploaded asset in runtime writable storage first, then bundled static uploads."""
    for folder in (Config.UPLOAD_FOLDER, Config.BUNDLED_UPLOAD_FOLDER):
        ok, target = security_service.is_safe_contained_path(folder, clean_name)
        if ok and os.path.isfile(target):
            return folder, target
    return None, None


_FAVICON_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
    "<rect width='100' height='100' rx='20' fill='#2563eb'/>"
    "<text x='50%' y='68%' font-size='60' font-weight='800' fill='white' "
    "text-anchor='middle' font-family='sans-serif'>P</text></svg>"
)


@app.route('/favicon.ico', methods=['GET'])
def favicon():
    """Serves brand icon cleanly across serverless/WSGI deployments (prevents 404/500 on browser icon fetch)."""
    return Response(_FAVICON_SVG, mimetype='image/svg+xml')


@app.route('/static/css/<path:filename>')
def serve_css_bundle(filename):
    """Explicit stylesheet route for serverless runtimes where Flask auto-static may be bypassed."""
    clean_name = secure_filename(filename)
    return send_from_directory(os.path.join(static_folder, "css"), clean_name)


@app.route('/static/js/app.js')
def serve_public_js_bundle():
    """Explicit public JS bundle route for serverless runtimes."""
    return send_from_directory(os.path.join(static_folder, "js"), "app.js")


@app.route('/static/uploads/<path:filename>')
def serve_cdn_upload(filename):
    """CDN Edge simulation: negotiates WebP cleanly when Accept: image/webp is sent."""
    clean_name = secure_filename(filename)
    base_folder, target = _resolve_upload_asset(clean_name)
    if not target:
        return jsonify({"error": "Not Found"}), 404

    accept_hdr = request.headers.get("Accept", "")
    if "image/webp" in accept_hdr and not clean_name.lower().endswith(".webp"):
        webp_candidate = f"{os.path.splitext(clean_name)[0]}.webp"
        webp_folder, target_w = _resolve_upload_asset(webp_candidate)
        if target_w:
            resp = make_response(send_from_directory(webp_folder, webp_candidate))
            resp.mimetype = "image/webp"
            return resp

    return send_from_directory(base_folder, clean_name)


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
    """Server-side renders role-gated workspace without leaking internal APIs, keys, SMTP, or PII."""
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
        current_user=_public_user_projection(g.current_user),
        csrf_token=g.csrf_token,
        whatsapp_number=Config.WHATSAPP_NUMBER,
        whatsapp_message=Config.WHATSAPP_MESSAGE,
        domain_email=Config.DOMAIN_EMAIL,
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
            "message": "The requested resource was not found."
        }), 404
    return render_template('404.html'), 404


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
    return render_template('404.html'), 403


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
            status_code = 409 if res.get("conflict") else 400
            return jsonify({"success": False, "message": res.get("message", "Registration failed")}), status_code

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

        # Never expose raw user_id or email PII back to frontend JSON
        payload = {
            "success": True,
            "username": res["username"],
            "role": res["role"],
            "is_verified": res["is_verified"],
            "message": res["message"],
            "csrf_token": csrf_tok,
        }
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
            "user": _public_user_projection(user)
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
    resp.delete_cookie(
        Config.SESSION_COOKIE_NAME,
        httponly=True,
        samesite=Config.SESSION_COOKIE_SAMESITE,
        secure=Config.SESSION_COOKIE_SECURE
    )
    return resp


@app.route('/gw/auth/me', methods=['GET'])
@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    if g.current_user:
        return jsonify({
            "authenticated": True,
            "user": _public_user_projection(g.current_user),
            "csrf_token": g.csrf_token
        })
    return jsonify({
        "authenticated": False,
        "user": None,
        "csrf_token": g.csrf_token
    })


@app.route('/gw/auth/verify-email', methods=['POST'])
@app.route('/api/auth/verify-email', methods=['POST'])
@login_required
@rate_limit_guard("verify_otp", max_requests=10, window_seconds=300)
def auth_verify_email():
    try:
        data = request.get_json() or {}
        code = data.get("code", "")
        if not code:
            return jsonify({"success": False, "message": "6-digit verification code is required"}), 400

        verified, msg = database.verify_user_code(int(g.current_user["id"]), code)
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
        is_staff = bool(g.current_user and g.current_user.get("role") in ("admin", "editor"))
        sanitized = [_sanitize_public_product(p, include_internal=is_staff) for p in products]
        csv_bytes = export_products_csv(sanitized)
        return send_file(
            io.BytesIO(csv_bytes),
            mimetype="text/csv",
            as_attachment=True,
            download_name="product_catalog.csv"
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
            download_name="product_catalog.json"
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
        is_staff = bool(g.current_user and g.current_user.get("role") in ("admin", "editor"))
        sanitized = _sanitize_public_product(product, include_internal=is_staff)
        pdf_bytes = generate_single_product_pdf(sanitized, base_dir=Config.BASE_DIR)
        clean_name = secure_filename(product.get('product_name', 'product'))[:30] or "product"
        filename = f"product_{clean_name}_{product_id}.pdf"
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
        is_staff = bool(g.current_user and g.current_user.get("role") in ("admin", "editor"))
        sanitized = [_sanitize_public_product(p, include_internal=is_staff) for p in products]
        pdf_bytes = generate_catalog_pdf(sanitized, base_dir=Config.BASE_DIR)
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="product_catalog.pdf"
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

        allowed_vision_models = set(groq_service.GROQ_VISION_MODELS) | {
            "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"
        }
        default_model = Config.GROQ_VISION_MODEL if groq_service.is_groq_configured() else "gemini-3.8-flash"
        selected_model = request.form.get("model") or default_model
        if selected_model not in allowed_vision_models:
            selected_model = default_model

        if selected_model in groq_service.GROQ_VISION_MODELS:
            extracted_data = groq_service.analyze_product_image_groq(absolute_path, model_name=selected_model)
        else:
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


@app.route('/gw/studio/generate', methods=['POST'])
@app.route('/api/catalog/generate', methods=['POST'])
@role_required(["admin", "editor"])
@rate_limit_guard("generate", max_requests=25, window_seconds=300)
def generate_catalog_from_prompt():
    """Generates a structured catalog entry from a product brief using Groq (or Gemini fallback)."""
    try:
        data = request.get_json() or {}
        prompt_text = security_service.sanitize_text_field(data.get("prompt"), 2000)
        if not prompt_text or len(prompt_text) < 3:
            return jsonify({"error": "Please enter at least 3 characters describing the product."}), 400

        brand_hint = security_service.sanitize_text_field(data.get("brand"), 120)
        category_hint = security_service.sanitize_text_field(data.get("category"), 100)
        price_hint = security_service.sanitize_text_field(data.get("price"), 60)

        allowed_text_models = set(groq_service.GROQ_TEXT_MODELS) | {
            "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"
        }
        default_model = Config.GROQ_TEXT_MODEL
        selected_model = (data.get("model") or default_model).strip()
        if selected_model not in allowed_text_models:
            selected_model = default_model

        if selected_model.startswith("gemini-"):
            draft = generate_catalog_from_prompt_gemini(prompt_text, model_name=selected_model)
            if not draft:
                draft = groq_service.generate_catalog_from_prompt_groq(
                    prompt_text,
                    brand_hint=brand_hint,
                    category_hint=category_hint,
                    price_hint=price_hint,
                    model_name=Config.GROQ_TEXT_MODEL,
                )
        else:
            draft = groq_service.generate_catalog_from_prompt_groq(
                prompt_text,
                brand_hint=brand_hint,
                category_hint=category_hint,
                price_hint=price_hint,
                model_name=selected_model,
            )

        if brand_hint and (not draft.get("brand") or draft.get("brand") == "Unspecified Brand"):
            draft["brand"] = brand_hint
        if category_hint and (not draft.get("category") or draft.get("category") == "General Merchandise"):
            draft["category"] = category_hint
        if price_hint and (not draft.get("price") or draft.get("price") == "Not Available"):
            draft["price"] = price_hint

        save_immediately = bool(data.get("save_immediately", False))
        if save_immediately:
            product_id = database.insert_product(draft)
            saved_product = database.get_product_by_id(product_id)
            resp = {"message": "Product Generated & Added Successfully", "product": saved_product}
            if draft.get("warning"):
                resp["warning"] = draft["warning"]
            return jsonify(resp), 201

        return jsonify({
            "message": "Catalog draft generated successfully. Ready for review.",
            "draft": draft,
            "warning": draft.get("warning"),
        }), 200
    except Exception as e:
        logger.error(f"Error in generate_catalog_from_prompt: {e}", exc_info=True)
        return jsonify({"error": "Failed to generate catalog draft"}), 500


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
    """Users (including Editors) see strictly their own non-PII orders; Admins see redacted catalog order summaries."""
    role = g.current_user.get("role")
    if role == "admin":
        return jsonify(database.get_orders())
    return jsonify(database.get_orders(user_id=g.current_user["id"]))


# ==============================================================================
# ADMIN CONSOLE (STRICT Administrator Role ONLY - ZERO Keys or Raw PII Shipped)
# ==============================================================================

@app.route('/gw/admin/inquiries', methods=['GET'])
@app.route('/api/inquiries', methods=['GET'])
@role_required(["admin"])
def get_inquiries_list():
    """Returns redacted inquiry ticket metadata without leaking customer PII to frontend."""
    return jsonify(database.get_inquiries_summary())


@app.route('/gw/admin/outbox', methods=['GET'])
@role_required(["admin"])
def get_admin_outbox():
    """Returns queue metrics & redacted delivery status logs (never exposes recipient emails or bodies)."""
    return jsonify({
        "queue": queue_service.get_queue_metrics(),
        "outbox": queue_service.get_recent_outbox_summary(limit=25)
    })


@app.route('/gw/admin/backups', methods=['GET'])
@app.route('/api/backups', methods=['GET'])
@role_required(["admin"])
def list_backups_route():
    """Lists server-side snapshot metadata without exposing raw downloadable DB files."""
    backups = backup_service.list_backups()
    return jsonify([
        {
            "created_at": b.get("created_at"),
            "size_formatted": b.get("size_formatted"),
            "product_count": b.get("product_count"),
            "storage": "server_only",
        }
        for b in backups
    ])


@app.route('/gw/admin/backups/create', methods=['POST'])
@app.route('/api/backups/create', methods=['POST'])
@role_required(["admin"])
def create_backup_route():
    res = backup_service.create_backup(label="manual")
    if res.get("success"):
        return jsonify({
            "success": True,
            "size_formatted": res.get("size_formatted"),
            "product_count": res.get("product_count"),
            "created_at": res.get("created_at"),
            "message": "Server-side database snapshot created securely."
        }), 200
    return jsonify({"success": False, "message": "Backup creation failed"}), 500


@app.route('/gw/admin/backups/download/<path:filename>', methods=['GET'])
@app.route('/api/backups/download/<path:filename>', methods=['GET'])
@role_required(["admin"])
def download_backup_route(filename):
    """Path-checked and strictly disabled to prevent bulk credential/PII SQLite DB exfiltration over HTTP."""
    ok, backup_path = security_service.is_safe_contained_path(Config.BACKUP_FOLDER, filename)
    clean_filename = os.path.basename(filename or "")
    if not ok or not clean_filename.endswith(".db") or not os.path.isfile(backup_path):
        return jsonify({"error": "Backup file not found"}), 404
    return jsonify({
        "error": "Forbidden",
        "message": "Raw database downloads are disabled from the web frontend for data privacy."
    }), 403


@app.route('/gw/admin/backups/restore/<path:filename>', methods=['POST'])
@app.route('/api/backups/restore/<path:filename>', methods=['POST'])
@role_required(["admin"])
def restore_backup_route(filename):
    return jsonify({
        "success": False,
        "error": "Forbidden",
        "message": "Database restore is disabled from the web frontend."
    }), 403


@app.route('/gw/admin/diagnostics', methods=['GET'])
@app.route('/api/health', methods=['GET'])
@role_required(["admin"])
def admin_diagnostics():
    """Restricted strictly to authenticated Administrators; reveals zero API key characters or secrets."""
    has_gemini = bool(Config.GEMINI_API_KEY and len(Config.GEMINI_API_KEY) > 10)
    has_groq = groq_service.is_groq_configured()
    stats = database.get_catalog_stats()
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
        "groq": {
            "configured": has_groq,
            "vision_model": Config.GROQ_VISION_MODEL,
            "text_model": Config.GROQ_TEXT_MODEL
        },
        "gemini": {
            "configured": has_gemini,
            "model": "gemini-3.8-flash"
        },
        "security": {
            "https_ready": True,
            "ssl_encryption": "256-Bit TLS",
            "csp_enforced": True,
            "csrf_enforced": True,
            "opaque_sessions": True,
            "frontend_secrets_exposed": False
        }
    })


@app.route('/gw/admin/settings/test-key', methods=['POST'])
@app.route('/api/settings/test-key', methods=['POST'])
@role_required(["admin"])
def test_key_route():
    return jsonify({
        "success": False,
        "error": "Forbidden",
        "message": "API key testing and management are disabled from the web frontend."
    }), 403


@app.route('/gw/admin/settings/key', methods=['POST'])
@app.route('/api/settings', methods=['POST'])
@role_required(["admin"])
def update_settings():
    return jsonify({
        "success": False,
        "error": "Forbidden",
        "message": "API keys cannot be read or modified from the web frontend. Configure GEMINI_API_KEY in server environment."
    }), 403


@app.route('/gw/admin/settings/analytics', methods=['POST'])
@app.route('/api/settings/analytics', methods=['POST'])
@role_required(["admin"])
def update_analytics_settings():
    return jsonify({
        "success": False,
        "error": "Forbidden",
        "message": "Third-party analytics tracking is disabled for user data privacy."
    }), 403


@app.route('/gw/admin/settings/email', methods=['POST'])
@app.route('/api/settings/email', methods=['POST'])
@role_required(["admin"])
def update_email_settings():
    return jsonify({
        "success": False,
        "error": "Forbidden",
        "message": "SMTP and domain email routing cannot be modified from the web frontend."
    }), 403


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "127.0.0.1")
    debug_mode = os.environ.get("FLASK_DEBUG", "False").lower() in ("true", "1")
    print(f"Starting Product Catalog on http://{host}:{port} (debug={debug_mode})")
    app.run(host=host, port=port, debug=debug_mode)
