"""
Comprehensive Test Suite for Suchit Product Catalog Generator
Tests all REST API endpoints, image processing, AI fallback mechanisms,
database migrations, export utilities, authentication, authorization,
error handling, contact form, checkout, and backups.
"""
import unittest
import json
import io
import os
import sys
import uuid
from PIL import Image

# Ensure promothon-main is in path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from app import app
import database


class SuchitCatalogTestSuite(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        database.init_db()
        cls.client = app.test_client()

    def test_01_home_page_branding(self):
        """Test home page renders with 'Suchit' branding and status 200."""
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn("Suchit", html)
        self.assertIn("Catalog Generator", html)
        self.assertIn("AI Studio", html)
        self.assertIn("Export Center", html)

    def test_02_health_endpoint(self):
        """Test /api/health returns system diagnostics."""
        res = self.client.get('/api/health')
        self.assertEqual(res.status_code, 200)
        data = res.json
        self.assertEqual(data["status"], "healthy")
        self.assertIn("Suchit", data["app_name"])
        self.assertEqual(data["database"]["status"], "connected")
        self.assertIn("uploads", data)

    def test_03_stats_endpoint(self):
        """Test /api/stats returns accurate database metrics."""
        res = self.client.get('/api/stats')
        self.assertEqual(res.status_code, 200)
        data = res.json
        self.assertIn("total_products", data)
        self.assertIn("total_brands", data)
        self.assertIn("total_categories", data)
        self.assertIn("categories", data)
        self.assertGreaterEqual(data["total_products"], 1)

    def test_04_get_all_products(self):
        """Test GET /products returns a valid list of catalog items."""
        res = self.client.get('/products')
        self.assertEqual(res.status_code, 200)
        products = res.json
        self.assertIsInstance(products, list)
        self.assertGreater(len(products), 0)
        
        # Verify first product structure
        p = products[0]
        self.assertIn("id", p)
        self.assertIn("product_name", p)
        self.assertIn("brand", p)
        self.assertIn("price", p)
        self.assertIn("features", p)
        self.assertIsInstance(p["features"], list)
        self.assertIn("specifications", p)
        self.assertIsInstance(p["specifications"], dict)

    def test_05_search_and_filter_products(self):
        """Test searching and filtering via query parameters."""
        res = self.client.get('/products?search=boAt')
        self.assertEqual(res.status_code, 200)
        products = res.json
        for p in products:
            text = f"{p['product_name']} {p['brand']} {p.get('description', '')}".lower()
            self.assertIn('boat', text)

    def test_06_sorting_products(self):
        """Test sorting products by name ascending."""
        res = self.client.get('/products?sort=name_asc')
        self.assertEqual(res.status_code, 200)
        products = res.json
        names = [p['product_name'] for p in products]
        self.assertEqual(names, sorted(names))

    def test_07_crud_lifecycle(self):
        """Test full Create -> Read -> Update -> Delete lifecycle."""
        # 1. CREATE
        new_prod = {
            "product_name": "Suchit Test Headset X1",
            "brand": "Suchit Audio",
            "model": "SX-100",
            "category": "Electronics & Audio",
            "price": "₹3,999",
            "dimensions": "180 x 170 x 80 mm",
            "short_description": "Premium wireless noise-cancelling headset.",
            "description": "Engineered for pure audio immersion with high-definition drivers and comfortable memory foam ear cushions.",
            "features": ["Active Noise Cancellation", "40-hour Battery Life", "Bluetooth 5.3", "Built-in Microphone"],
            "specifications": {"Driver Size": "40mm", "Weight": "250g", "Battery": "800mAh"},
            "selling_points": ["Crystal clear calls", "All-day comfort", "Ultra-fast charging"],
            "tags": ["audio", "headset", "wireless", "suchit"]
        }
        create_res = self.client.post('/product', json=new_prod)
        self.assertEqual(create_res.status_code, 201)
        created = create_res.json["product"]
        pid = created["id"]
        self.assertEqual(created["product_name"], "Suchit Test Headset X1")

        # 2. READ
        get_res = self.client.get(f'/product/{pid}')
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json["brand"], "Suchit Audio")
        self.assertEqual(len(get_res.json["features"]), 4)

        # 3. UPDATE
        update_payload = {
            "price": "₹3,499",
            "features": ["Active Noise Cancellation", "50-hour Battery Life", "Bluetooth 5.3", "Fast Charging"]
        }
        put_res = self.client.put(f'/product/{pid}', json=update_payload)
        self.assertEqual(put_res.status_code, 200)
        
        verify_res = self.client.get(f'/product/{pid}')
        self.assertEqual(verify_res.json["price"], "₹3,499")
        self.assertIn("50-hour Battery Life", verify_res.json["features"])

        # 4. DELETE
        del_res = self.client.delete(f'/product/{pid}')
        self.assertEqual(del_res.status_code, 200)

        # Verify not found
        get_deleted = self.client.get(f'/product/{pid}')
        self.assertEqual(get_deleted.status_code, 404)

    def test_08_backward_compatible_update(self):
        """Test PUT with legacy comma-separated string features."""
        temp_id = database.insert_product({"product_name": "Legacy Compat Item", "brand": "Test"})
        legacy_data = {
            "product_name": "Legacy Compat Item Updated",
            "brand": "Test",
            "price": "$50",
            "features": "Feature One, Feature Two, Feature Three",
            "dimensions": "10x10"
        }
        res = self.client.put(f'/product/{temp_id}', json=legacy_data)
        self.assertEqual(res.status_code, 200)

        fetched = database.get_product_by_id(temp_id)
        self.assertEqual(fetched["features"], ["Feature One", "Feature Two", "Feature Three"])
        
        # Cleanup
        database.delete_product(temp_id)

    def test_09_export_csv(self):
        """Test CSV export generates valid RFC-compliant CSV with UTF-8 BOM."""
        res = self.client.get('/export/csv')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'text/csv')
        self.assertTrue(res.data.startswith(b'\xef\xbb\xbf'))
        content = res.data.decode('utf-8-sig')
        self.assertIn("Product Name", content)
        self.assertIn("Brand", content)

    def test_10_export_json(self):
        """Test JSON export returns valid catalog feed."""
        res = self.client.get('/export/json')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data.decode('utf-8'))
        self.assertEqual(data["catalog_name"], "Suchit Product Catalog")
        self.assertIn("products", data)
        self.assertIsInstance(data["products"], list)

    def test_11_export_pdf_single(self):
        """Test single product PDF generation."""
        products = database.get_products()
        self.assertTrue(len(products) > 0)
        pid = products[0]["id"]
        res = self.client.get(f'/export/pdf/{pid}')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'application/pdf')
        self.assertTrue(res.data.startswith(b'%PDF'))

    def test_12_export_pdf_full_catalog(self):
        """Test full catalog PDF book generation."""
        res = self.client.get('/export/pdf')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'application/pdf')
        self.assertTrue(res.data.startswith(b'%PDF'))
        self.assertGreater(len(res.data), 5000)

    def test_13_upload_validation_no_image(self):
        """Test upload endpoint returns 400 when no image is provided."""
        res = self.client.post('/upload', data={})
        self.assertEqual(res.status_code, 400)
        self.assertIn("error", res.json)

    def test_14_upload_with_synthetic_image(self):
        """Test uploading a synthetic image with Pillow processing and safe fallback."""
        img_io = io.BytesIO()
        test_img = Image.new('RGB', (320, 240), color=(120, 160, 200))
        test_img.save(img_io, format='PNG')
        img_io.seek(0)

        res = self.client.post(
            '/upload',
            data={'image': (img_io, 'sample_widget.png'), 'save_immediately': 'true'},
            content_type='multipart/form-data'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json
        self.assertIn("product", data)
        uploaded_id = data["product"]["id"]
        self.assertIn("Sample Widget", data["product"]["product_name"])
        self.assertTrue(data["product"]["image_path"].startswith("/static/uploads/"))

        # Cleanup uploaded test item
        database.delete_product(uploaded_id)

    def test_15_api_key_masked_in_health(self):
        """Test that API keys are strictly masked and never leaked to frontend."""
        res = self.client.get('/api/health')
        self.assertEqual(res.status_code, 200)
        data = res.json
        gemini_info = data.get("gemini", {})
        key_masked = gemini_info.get("api_key_masked")
        self.assertIsNotNone(key_masked)
        self.assertIn("********", key_masked)
        raw_key = os.environ.get("GEMINI_API_KEY", "")
        if len(raw_key) > 10:
            self.assertNotIn(raw_key, res.data.decode('utf-8'))

    def test_16_custom_404_html_and_json(self):
        """Test proper 404 responses for both HTML and API JSON requests."""
        # HTML 404
        res_html = self.client.get('/nonexistent-page-path-12345')
        self.assertEqual(res_html.status_code, 404)
        html_str = res_html.data.decode('utf-8')
        self.assertIn("404", html_str)
        self.assertIn("Page Not Found", html_str)

        # JSON 404
        res_json = self.client.get('/api/nonexistent-endpoint-54321')
        self.assertEqual(res_json.status_code, 404)
        self.assertTrue(res_json.is_json)
        self.assertEqual(res_json.json.get("error"), "Not Found")
        self.assertIn("not found", res_json.json.get("message", "").lower())

    def test_17_auth_login_logout_and_session(self):
        """Test authentication login, session inspection, and logout."""
        # 1. Login with bad credentials
        bad_res = self.client.post('/api/auth/login', json={"username": "admin", "password": "WrongPassword!"})
        self.assertEqual(bad_res.status_code, 401)

        # 2. Login with valid seeded admin
        login_res = self.client.post('/api/auth/login', json={"username": "admin", "password": "Admin@12345"})
        self.assertEqual(login_res.status_code, 200)
        self.assertTrue(login_res.json.get("authenticated"))
        self.assertEqual(login_res.json["user"]["role"], "admin")

        # 3. Check /api/auth/me with active session
        me_res = self.client.get('/api/auth/me')
        self.assertEqual(me_res.status_code, 200)
        self.assertTrue(me_res.json.get("authenticated"))
        self.assertEqual(me_res.json["user"]["username"], "admin")

        # 4. Logout
        logout_res = self.client.post('/api/auth/logout')
        self.assertEqual(logout_res.status_code, 200)
        self.assertFalse(logout_res.json.get("authenticated"))

        # 5. Check /api/auth/me after logout
        me_after = self.client.get('/api/auth/me')
        self.assertEqual(me_after.status_code, 200)
        self.assertFalse(me_after.json.get("authenticated"))

    def test_18_auth_registration(self):
        """Test user registration with validation and duplicate prevention."""
        uname = f"testuser_{uuid.uuid4().hex[:6]}"
        reg_payload = {
            "username": uname,
            "email": f"{uname}@example.com",
            "password": "StrongPassword123!",
            "full_name": "Test Tester"
        }
        res = self.client.post('/api/auth/register', json=reg_payload)
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.json.get("success"))

        # Duplicate username attempt
        dup_res = self.client.post('/api/auth/register', json=reg_payload)
        self.assertEqual(dup_res.status_code, 409)

    def test_19_rbac_authorization_guards(self):
        """Test role-based access control protecting administrative endpoints."""
        # Log out any existing session
        self.client.post('/api/auth/logout')

        # Attempt to access backup API without logging in (should be 401)
        res = self.client.get('/api/backups')
        self.assertEqual(res.status_code, 401)

        # Attempt to create backup without logging in (should be 401)
        res_post = self.client.post('/api/backups/create')
        self.assertEqual(res_post.status_code, 401)

        # Login as editor (editor is not admin, so backup access should be 403 Forbidden)
        self.client.post('/api/auth/login', json={"username": "editor", "password": "Editor@12345"})
        res_forbidden = self.client.get('/api/backups')
        self.assertEqual(res_forbidden.status_code, 403)

        # Logout editor and login as admin (admin is authorized)
        self.client.post('/api/auth/logout')
        self.client.post('/api/auth/login', json={"username": "admin", "password": "Admin@12345"})
        res_admin = self.client.get('/api/backups')
        self.assertEqual(res_admin.status_code, 200)
        self.client.post('/api/auth/logout')

    def test_20_contact_inquiry_submission(self):
        """Test contact form endpoint validation, sanitization, and DB storage."""
        # Invalid email
        bad_contact = {
            "name": "Jane Doe",
            "email": "not-an-email",
            "subject": "Demo",
            "message": "Hello there"
        }
        res_bad = self.client.post('/api/contact', json=bad_contact)
        self.assertEqual(res_bad.status_code, 400)

        # Valid contact inquiry
        good_contact = {
            "name": "Jane Enterprise",
            "email": "jane@enterprise.com",
            "subject": "Commercial Licensing",
            "message": "Interested in deploying Suchit for 25,000 SKUs."
        }
        res_good = self.client.post('/api/contact', json=good_contact)
        self.assertEqual(res_good.status_code, 201)
        data = res_good.json
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("reference_code", "").startswith("INQ-"))

    def test_21_commercial_checkout_processing(self):
        """Test checkout / commercial tier licensing workflow."""
        # Missing fields test
        res_invalid = self.client.post('/api/checkout/process', json={})
        self.assertEqual(res_invalid.status_code, 400)

        # Complete test checkout
        order_payload = {
            "plan": "pro",
            "name": "Jane Director",
            "email": "jane@company.com",
            "company": "Suchit Partner Corp",
            "billing_cycle": "annual",
            "payment_method": "card",
            "card_number": "4242 4242 4242 4242",
            "card_exp": "12/28",
            "card_cvc": "123"
        }
        res_order = self.client.post('/api/checkout/process', json=order_payload)
        self.assertEqual(res_order.status_code, 200)
        data = res_order.json
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("order_number", "").startswith("SUCHIT-ORD-"))
        self.assertIsNotNone(data.get("amount"))

    def test_22_backup_creation_and_listing(self):
        """Test creating and listing database backups with admin credentials."""
        # Log in as admin
        self.client.post('/api/auth/login', json={"username": "admin", "password": "Admin@12345"})

        # Create backup
        create_res = self.client.post('/api/backups/create')
        self.assertEqual(create_res.status_code, 200)
        self.assertTrue(create_res.json.get("success"))
        filename = create_res.json.get("filename", "")
        self.assertTrue(filename.endswith(".db"))

        # List backups
        list_res = self.client.get('/api/backups')
        self.assertEqual(list_res.status_code, 200)
        backups = list_res.json
        if isinstance(backups, dict):
            backups = backups.get("backups", [])
        self.assertGreaterEqual(len(backups), 1)

        # Clean up session
        self.client.post('/api/auth/logout')

    def test_23_security_headers_present(self):
        """Test that HTTP security headers (nosniff, X-Frame-Options, etc.) are injected."""
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertEqual(res.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertIn("Content-Security-Policy", res.headers)

    def test_24_static_image_asset_delivery(self):
        """Test that generated compressed image assets exist and are served with 200."""
        res = self.client.get('/static/uploads/suchit_asset_3_boat.jpg')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'image/jpeg')
        self.assertGreater(len(res.data), 1000)


if __name__ == '__main__':
    unittest.main()
