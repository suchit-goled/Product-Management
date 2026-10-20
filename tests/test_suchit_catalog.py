"""
Comprehensive Test Suite for Suchit Product Catalog Generator
Tests all REST API endpoints, image processing, AI fallback mechanisms,
database migrations, and export utilities.
"""
import unittest
import json
import io
import os
import sys
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
        # Create temp product
        temp_id = database.insert_product({"product_name": "Legacy Compat Item", "brand": "Test"})
        
        # Legacy update payload (as used in original put_update.py)
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
        # Check UTF-8 BOM prefix b'\xef\xbb\xbf'
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


if __name__ == '__main__':
    unittest.main()
