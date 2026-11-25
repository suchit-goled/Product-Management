"""
Suchit Product Catalog Generator — Comprehensive Security, Architecture & Functional Test Suite
Tests: Layered architecture (CDN, Load Balancer/CSRF/CORS, Stateless Opaque Auth, Cache, DB, Queue/Workers),
API hiding on frontend, Role-Based Access Control, Frontend tampering prevention, Luhn & server-side pricing,
EXIF/CSV/Path-traversal sanitization, complete database enrichment, and 100% media delivery.
"""
import unittest
import json
import io
import os
import re
import sys
import uuid
import sqlite3
from PIL import Image

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from app import app
from config import Config
import database
from services import queue_service, worker_service, export_service


class SuchitSecurityAndArchitectureTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        database.init_db()
        cls.app = app

    def _new_client(self):
        return self.app.test_client()

    def _get_guest_csrf(self, client):
        res = client.get('/gw/auth/me')
        return res.json.get('csrf_token', '')

    def _login(self, client, username, password):
        csrf = self._get_guest_csrf(client)
        res = client.post(
            '/gw/auth/login',
            json={'identifier': username, 'password': password},
            headers={'X-CSRF-Token': csrf}
        )
        self.assertEqual(res.status_code, 200, f"Login failed for {username}: {res.get_json()}")
        return res.json['csrf_token'], res.json['user']

    # ------------------------------------------------------------------
    # 1. API EXPOSURE & ROLE-GATED FRONTEND TESTS
    # ------------------------------------------------------------------

    def test_01_public_home_hides_apis_and_admin_dom(self):
        """Verify guest home HTML hides all internal APIs, docs, editor studio, and admin console."""
        c = self._new_client()
        res = c.get('/')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        self.assertIn("Suchit", html)
        self.assertIn('name="csrf-token"', html)
        # Ensure zero API docs, admin panels, or internal paths leak to unauthenticated DOM
        self.assertNotIn("API & Docs", html)
        self.assertNotIn("Developer API Reference", html)
        self.assertNotIn('id="settingsSection"', html)
        self.assertNotIn('id="aiStudio"', html)
        self.assertNotIn('id="backupsListContainer"', html)
        self.assertNotIn('/static/js/editor.js', html)
        self.assertNotIn('/static/js/admin.js', html)
        # Strict CSP hygiene: no inline event handlers
        self.assertNotIn('onclick=', html)
        self.assertNotIn('onsubmit=', html)

    def test_02_role_gated_js_bundles(self):
        """Verify role-scoped JS files return 403 to unauthorized roles and 200 only to authorized roles."""
        c = self._new_client()
        self.assertEqual(c.get('/static/js/editor.js').status_code, 403)
        self.assertEqual(c.get('/static/js/admin.js').status_code, 403)

        # Editor can load editor.js (and sees aiStudio in HTML), NOT admin.js
        self._login(c, 'editor', 'Editor@12345')
        self.assertEqual(c.get('/static/js/editor.js').status_code, 200)
        self.assertEqual(c.get('/static/js/admin.js').status_code, 403)
        editor_html = c.get('/').data.decode('utf-8')
        self.assertIn('id="aiStudio"', editor_html)
        self.assertNotIn('id="settingsSection"', editor_html)

        # Admin can load both
        c2 = self._new_client()
        self._login(c2, 'admin', 'Admin@12345')
        self.assertEqual(c2.get('/static/js/editor.js').status_code, 200)
        self.assertEqual(c2.get('/static/js/admin.js').status_code, 200)
        admin_html = c2.get('/').data.decode('utf-8')
        self.assertIn('id="settingsSection"', admin_html)

    def test_03_public_healthz_minimal_and_admin_diagnostics(self):
        """Public /healthz exposes zero secrets/paths; diagnostics strictly Admin-only."""
        c = self._new_client()
        hz = c.get('/healthz')
        self.assertEqual(hz.status_code, 200)
        self.assertEqual(hz.json, {"status": "ok"})

        self.assertEqual(c.get('/api/health').status_code, 401)
        self.assertEqual(c.get('/gw/admin/diagnostics').status_code, 401)

        self._login(c, 'editor', 'Editor@12345')
        self.assertEqual(c.get('/api/health').status_code, 403)

        c_admin = self._new_client()
        self._login(c_admin, 'admin', 'Admin@12345')
        diag = c_admin.get('/gw/admin/diagnostics')
        self.assertEqual(diag.status_code, 200)
        self.assertIn("********", diag.json["gemini"]["api_key_masked"])
        raw_key = Config.GEMINI_API_KEY
        if len(raw_key) > 10:
            self.assertNotIn(raw_key, diag.data.decode('utf-8'))

    def test_04_public_stats_strips_internal_telemetry(self):
        """Verify public stats hide internal orders and inquiries counts."""
        c = self._new_client()
        pub_stats = c.get('/api/stats').json
        self.assertIn("total_products", pub_stats)
        self.assertNotIn("total_orders", pub_stats)
        self.assertNotIn("total_inquiries", pub_stats)

    # ------------------------------------------------------------------
    # 2. DATABASE INTEGRITY & COMPLETE PRODUCT MEDIA (CDN + WEBP)
    # ------------------------------------------------------------------

    def test_05_database_completeness_and_image_assets(self):
        """Check that every product (#3..#12) has complete fields and crisp JPG+WEBP image files."""
        c = self._new_client()
        products = c.get('/products').json
        self.assertGreaterEqual(len(products), 10)

        for p in products:
            self.assertTrue(p.get("product_name"), f"Missing name on #{p['id']}")
            self.assertTrue(p.get("short_description"), f"Missing short_description on #{p['id']}")
            self.assertTrue(p.get("description"), f"Missing description on #{p['id']}")
            self.assertTrue(p.get("specifications"), f"Missing specifications dict on #{p['id']}")
            self.assertTrue(p.get("selling_points"), f"Missing selling_points on #{p['id']}")
            self.assertTrue(p.get("tags"), f"Missing tags on #{p['id']}")
            self.assertTrue(p.get("image_path", "").startswith("/static/uploads/"), f"Bad image_path on #{p['id']}")

            # Verify JPEG & WEBP assets exist on disk and are served by CDN endpoint
            jpg_res = c.get(p["image_path"])
            self.assertEqual(jpg_res.status_code, 200, f"Image missing on CDN for #{p['id']}")
            self.assertEqual(jpg_res.mimetype, "image/jpeg")
            jpg_res.close()

            webp_res = c.get(p["image_path"], headers={"Accept": "image/webp"})
            self.assertEqual(webp_res.status_code, 200)
            self.assertEqual(webp_res.mimetype, "image/webp")
            webp_res.close()

    # ------------------------------------------------------------------
    # 3. CSRF, CROSS-ORIGIN & RBAC AUTHORIZATION ENFORCEMENT
    # ------------------------------------------------------------------

    def test_06_csrf_and_cross_origin_enforcement(self):
        """All mutating endpoints must fail closed (403) on missing CSRF or cross-origin Origin."""
        c = self._new_client()
        # Missing CSRF token
        res_no_csrf = c.post('/gw/contact', json={"name": "A", "email": "a@b.com", "subject": "Hi", "message": "Hello"})
        self.assertEqual(res_no_csrf.status_code, 403)

        # Valid CSRF but cross-origin Origin
        csrf = self._get_guest_csrf(c)
        res_evil_origin = c.post(
            '/gw/contact',
            json={"name": "A", "email": "a@b.com", "subject": "Hi", "message": "Hello"},
            headers={"X-CSRF-Token": csrf, "Origin": "https://attacker.evil.com"}
        )
        self.assertEqual(res_evil_origin.status_code, 403)

    def test_07_default_deny_rbac_across_endpoints(self):
        """Ensure ZERO unauthenticated or under-privileged mutation/admin bypasses exist."""
        c = self._new_client()
        csrf = self._get_guest_csrf(c)

        # Unauthenticated requests -> 401
        self.assertEqual(c.post('/upload', data={}, headers={'X-CSRF-Token': csrf}).status_code, 401)
        self.assertEqual(c.post('/product', json={"product_name": "Hack"}, headers={'X-CSRF-Token': csrf}).status_code, 401)
        self.assertEqual(c.put('/product/3', json={"price": "₹1"}, headers={'X-CSRF-Token': csrf}).status_code, 401)
        self.assertEqual(c.delete('/product/3', headers={'X-CSRF-Token': csrf}).status_code, 401)
        self.assertEqual(c.post('/api/settings', json={"gemini_api_key": "x"}, headers={'X-CSRF-Token': csrf}).status_code, 401)
        self.assertEqual(c.post('/api/settings/test-key', json={}, headers={'X-CSRF-Token': csrf}).status_code, 401)
        self.assertEqual(c.post('/api/settings/analytics', json={}, headers={'X-CSRF-Token': csrf}).status_code, 401)
        self.assertEqual(c.post('/api/settings/email', json={}, headers={'X-CSRF-Token': csrf}).status_code, 401)
        self.assertEqual(c.get('/api/backups').status_code, 401)
        self.assertEqual(c.get('/api/inquiries').status_code, 401)

        # Editor cannot perform Admin actions -> 403
        csrf_ed, _ = self._login(c, 'editor', 'Editor@12345')
        self.assertEqual(c.get('/api/backups').status_code, 403)
        self.assertEqual(c.post('/api/backups/create', headers={'X-CSRF-Token': csrf_ed}).status_code, 403)
        self.assertEqual(c.post('/api/settings', json={"gemini_api_key": "x"}, headers={'X-CSRF-Token': csrf_ed}).status_code, 403)
        self.assertEqual(c.get('/api/inquiries').status_code, 403)

    # ------------------------------------------------------------------
    # 4. REGISTRATION ROLE TAMPERING, NO OTP LEAK, OPAQUE SESSION ROTATION
    # ------------------------------------------------------------------

    def test_08_registration_security_and_no_otp_bypass(self):
        """Registration rejects role tampering, never leaks OTP, and rejects hardcoded 123456."""
        c = self._new_client()
        csrf = self._get_guest_csrf(c)
        uname = f"secviewer_{uuid.uuid4().hex[:6]}"
        email = f"{uname}@example.com"

        try:
            # Attempt privilege escalation via "role": "admin" and "is_verified": 1
            reg_res = c.post(
                '/gw/auth/register',
                json={"username": uname, "email": email, "password": "UserPass2026!", "role": "admin", "is_verified": 1},
                headers={'X-CSRF-Token': csrf}
            )
            self.assertEqual(reg_res.status_code, 201)
            body = reg_res.json
            self.assertEqual(body["role"], "viewer")
            self.assertFalse(body["is_verified"])
            self.assertNotIn("verification_code", body)
            new_csrf = body["csrf_token"]

            # Viewer cannot create products -> 403
            self.assertEqual(c.post('/product', json={"product_name": "ViewerHack"}, headers={'X-CSRF-Token': new_csrf}).status_code, 403)

            # Universal test code 123456 MUST FAIL
            bad_otp = c.post('/gw/auth/verify-email', json={"code": "123456"}, headers={'X-CSRF-Token': new_csrf})
            self.assertEqual(bad_otp.status_code, 400)

            # Duplicate username rejected with 409
            c2 = self._new_client()
            csrf2 = self._get_guest_csrf(c2)
            dup = c2.post(
                '/gw/auth/register',
                json={"username": uname, "email": email, "password": "UserPass2026!"},
                headers={'X-CSRF-Token': csrf2}
            )
            self.assertEqual(dup.status_code, 409)
        finally:
            conn = database.get_db_connection()
            conn.execute("DELETE FROM users WHERE username = ?", (uname,))
            conn.commit()
            conn.close()

    def test_09_opaque_session_and_rotation(self):
        """Cookies must be opaque (no plain claims) and rotate on re-login."""
        c = self._new_client()
        self._login(c, 'editor', 'Editor@12345')
        sid_cookie_1 = c.get_cookie(Config.SESSION_COOKIE_NAME)
        self.assertIsNotNone(sid_cookie_1)
        self.assertTrue(sid_cookie_1.http_only)
        self.assertNotIn("editor", sid_cookie_1.value)

        # Re-login rotates cookie and revokes previous token
        self._login(c, 'admin', 'Admin@12345')
        sid_cookie_2 = c.get_cookie(Config.SESSION_COOKIE_NAME)
        self.assertNotEqual(sid_cookie_1.value, sid_cookie_2.value)
        me = c.get('/gw/auth/me').json
        self.assertEqual(me["user"]["role"], "admin")

    # ------------------------------------------------------------------
    # 5. SERVER-SIDE AUTHORITATIVE CHECKOUT & TAMPER RESISTANCE
    # ------------------------------------------------------------------

    def test_10_checkout_price_tampering_and_luhn_rejected(self):
        """Client cannot spoof price/amount/product_name; invalid Luhn cards rejected; price computed on server."""
        c = self._new_client()
        csrf_g = self._get_guest_csrf(c)

        # Unauthenticated checkout blocked (401)
        res_unauth = c.post('/gw/checkout', json={"product_id": 3}, headers={'X-CSRF-Token': csrf_g})
        self.assertEqual(res_unauth.status_code, 401)

        csrf_u, _ = self._login(c, 'editor', 'Editor@12345')

        # 1. Invalid Luhn card rejected
        res_bad_card = c.post('/gw/checkout', json={
            "product_id": 3,
            "quantity": 1,
            "customer_name": "Tester",
            "customer_email": "tester@suchitcatalog.com",
            "billing_address": "123 Secure St",
            "payment_method": "Credit Card",
            "card_number": "4111 1111 1111 1112",
            "card_expiry": "12/28",
            "card_cvv": "123"
        }, headers={'X-CSRF-Token': csrf_u})
        self.assertEqual(res_bad_card.status_code, 400)

        # 2. Expired card rejected
        res_exp_card = c.post('/gw/checkout', json={
            "product_id": 3,
            "quantity": 1,
            "customer_name": "Tester",
            "customer_email": "tester@suchitcatalog.com",
            "billing_address": "123 Secure St",
            "payment_method": "Credit Card",
            "card_number": "4242 4242 4242 4242",
            "card_expiry": "01/20",
            "card_cvv": "123"
        }, headers={'X-CSRF-Token': csrf_u})
        self.assertEqual(res_exp_card.status_code, 400)

        # 3. Attempt price & product_name tampering on Product #3 (DB Price: ₹1,499)
        res_ok = c.post('/gw/checkout', json={
            "product_id": 3,
            "quantity": 2,
            "amount": "₹0.01",
            "product_name": "Hack Free Override",
            "customer_name": "Authorized Buyer",
            "customer_email": "buyer@suchitcatalog.com",
            "billing_address": "42 Corporate Ave, Bengaluru",
            "payment_method": "Credit Card",
            "card_number": "4242 4242 4242 4242",
            "card_expiry": "12/28",
            "card_cvv": "123"
        }, headers={'X-CSRF-Token': csrf_u})
        self.assertEqual(res_ok.status_code, 200)
        order = res_ok.json
        # 2 * 1499 = 2998 + 18% tax (539.64) = 3537.64
        self.assertEqual(order["product_name"], "boAt Airdopes 131 Pro")
        self.assertEqual(order["amount"], "₹3,537.64")
        self.assertEqual(order["card_last4"], "•••• 4242")

        # Cleanup test order
        conn = database.get_db_connection()
        conn.execute("DELETE FROM orders WHERE order_number = ?", (order["order_number"],))
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # 6. INJECTION, PATH TRAVERSAL & EXPORTS
    # ------------------------------------------------------------------

    def test_11_path_traversal_and_xss_image_uri_blocked(self):
        """Reject javascript: URIs and path traversal in product image_path and backup download."""
        c = self._new_client()
        csrf_ed, _ = self._login(c, 'editor', 'Editor@12345')

        for bad_img in ("javascript:alert(1)", "/static/uploads/../../app.py", "https://evil.com/x.png"):
            res = c.post(
                '/product',
                json={"product_name": "XSS Check", "image_path": bad_img},
                headers={'X-CSRF-Token': csrf_ed}
            )
            self.assertEqual(res.status_code, 400, f"Allowed unsafe image_path: {bad_img}")

        c_adm = self._new_client()
        self._login(c_adm, 'admin', 'Admin@12345')
        self.assertEqual(c_adm.get('/gw/admin/backups/download/../../.env').status_code, 404)

    def test_12_csv_formula_injection_mitigated(self):
        """Verify leading formula characters (=, +, -, @) are prefixed safely on CSV export."""
        csv_bytes = export_service.export_products_csv([{
            "id": 999,
            "product_name": "=CMD|' /C calc'!A0",
            "brand": "+Malicious",
            "price": "₹1,499"
        }])
        csv_text = csv_bytes.decode('utf-8-sig')
        self.assertIn("\"'=CMD", csv_text)
        self.assertIn("\"'+Malicious", csv_text)
        self.assertIn("\"₹1,499\"", csv_text)

    def test_13_authenticated_crud_upload_cache_and_exports(self):
        """Test full Editor upload + CRUD lifecycle, Cache invalidation, PDF & JSON exports."""
        c = self._new_client()
        csrf, _ = self._login(c, 'editor', 'Editor@12345')

        img_io = io.BytesIO()
        Image.new('RGB', (320, 240), color=(90, 140, 210)).save(img_io, format='PNG')
        img_io.seek(0)

        up_res = c.post(
            '/upload',
            data={'image': (img_io, 'secure_widget.png'), 'save_immediately': 'true'},
            content_type='multipart/form-data',
            headers={'X-CSRF-Token': csrf}
        )
        self.assertEqual(up_res.status_code, 200)
        prod = up_res.json["product"]
        pid = prod["id"]
        self.assertTrue(prod["image_path"].startswith("/static/uploads/"))
        self.assertTrue(up_res.json["image_metadata"]["exif_stripped"])

        # Cache must be invalidated immediately so item shows in GET /products
        all_ids = [item["id"] for item in c.get('/products').json]
        self.assertIn(pid, all_ids)

        # Single & Catalog PDFs work cleanly (including XML-unsafe chars '&', '<')
        put_res = c.put(
            f'/product/{pid}',
            json={"product_name": "Widget & Pro <2026>", "price": "₹2,000"},
            headers={'X-CSRF-Token': csrf}
        )
        self.assertEqual(put_res.status_code, 200)
        pdf_res = c.get(f'/export/pdf/{pid}')
        self.assertEqual(pdf_res.status_code, 200)
        self.assertTrue(pdf_res.data.startswith(b'%PDF'))

        full_pdf = c.get('/export/pdf')
        self.assertEqual(full_pdf.status_code, 200)
        self.assertTrue(full_pdf.data.startswith(b'%PDF'))

        # Delete & remove uploaded file artifact
        del_res = c.delete(f'/product/{pid}', headers={'X-CSRF-Token': csrf})
        self.assertEqual(del_res.status_code, 200)
        disk_path = os.path.join(Config.BASE_DIR, prod["image_path"].lstrip("/"))
        if os.path.exists(disk_path):
            os.remove(disk_path)
        webp_disk = os.path.splitext(disk_path)[0] + ".webp"
        if os.path.exists(webp_disk):
            os.remove(webp_disk)

    def test_14_queue_worker_and_admin_backups(self):
        """Test Message Queue/Worker execution and Admin online SQLite backups."""
        c = self._new_client()
        csrf, _ = self._login(c, 'admin', 'Admin@12345')

        # Create backup
        bk_res = c.post('/gw/admin/backups/create', headers={'X-CSRF-Token': csrf})
        self.assertEqual(bk_res.status_code, 200)
        fname = bk_res.json["filename"]
        self.assertTrue(fname.endswith(".db"))

        # Download backup
        dl_res = c.get(f'/gw/admin/backups/download/{fname}')
        self.assertEqual(dl_res.status_code, 200)
        dl_res.close()

        # Enqueue & verify worker outbox monitoring
        queue_service.enqueue_job("email.contact_ack", {
            "email": "monitor@suchitcatalog.com",
            "name": "Monitor",
            "reference_code": "INQ-9999"
        })
        processed = worker_service.process_pending_once(max_jobs=5)
        self.assertGreaterEqual(processed, 1)

        outbox = c.get('/gw/admin/outbox').json
        self.assertGreater(outbox["queue"]["outbox_total"], 0)

        # Clean up test backup file created by test run
        test_bk_path = os.path.join(Config.BACKUP_FOLDER, fname)
        if os.path.exists(test_bk_path):
            os.remove(test_bk_path)

    def test_15_contact_inquiry_and_404_pages(self):
        """Verify contact validation/persistence and branded 404 HTML/JSON."""
        c = self._new_client()
        csrf = self._get_guest_csrf(c)

        bad_inq = c.post('/gw/contact', json={"name": "X", "email": "bad-email", "subject": "Hi", "message": "Test"}, headers={'X-CSRF-Token': csrf})
        self.assertEqual(bad_inq.status_code, 400)

        good_inq = c.post('/gw/contact', json={"name": "QA Lead", "email": "qa@enterprise.org", "subject": "Audit", "message": "Catalog audit inquiry."}, headers={'X-CSRF-Token': csrf})
        self.assertEqual(good_inq.status_code, 201)
        inq_id = good_inq.json["inquiry_id"]

        # Clean up test inquiry
        conn = database.get_db_connection()
        conn.execute("DELETE FROM inquiries WHERE id = ?", (inq_id,))
        conn.commit()
        conn.close()

        r404_html = c.get('/nonexistent-route-xyz')
        self.assertEqual(r404_html.status_code, 404)
        self.assertIn("Page Not Found", r404_html.data.decode('utf-8'))

        r404_json = c.get('/gw/nonexistent-endpoint')
        self.assertEqual(r404_json.status_code, 404)
        self.assertEqual(r404_json.json["error"], "Not Found")

    def test_16_strict_csp_and_cache_headers(self):
        """Ensure strict CSP (no unsafe-inline in script-src), no-store on APIs, CDN headers on uploads."""
        c = self._new_client()
        home_res = c.get('/')
        csp = home_res.headers.get("Content-Security-Policy", "")
        self.assertIn("script-src 'self'", csp)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", csp)
        self.assertEqual(home_res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(home_res.headers.get("X-Frame-Options"), "SAMEORIGIN")

        api_res = c.get('/gw/auth/me')
        self.assertIn("no-store", api_res.headers.get("Cache-Control", ""))

        img_res = c.get('/static/uploads/suchit_asset_3_boat.jpg')
        self.assertIn("public, max-age=", img_res.headers.get("Cache-Control", ""))
        img_res.close()


if __name__ == '__main__':
    unittest.main()
