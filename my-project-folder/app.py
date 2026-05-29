from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from google import genai
import json
import sqlite3
from PIL import Image
import os

app = Flask(__name__)
CORS(app)

# =========================
# GEMINI API CONFIGURATION
# =========================

GEMINI_API_KEY = "YOUR_GEMINI_API_KEY"

client = genai.Client(api_key=GEMINI_API_KEY)

# =========================
# DATABASE CONFIGURATION
# =========================

DATABASE = "products.db"

def init_db():
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT,
            brand TEXT,
            price TEXT,
            features TEXT,
            dimensions TEXT
        )
        """)

        conn.commit()

init_db()

# =========================
# GEMINI PROMPT
# =========================

prompt = """
Extract product details from this image and return ONLY valid JSON.

Format:
{
    "product_name": "",
    "brand": "",
    "price": "",
    "features": [],
    "dimensions": ""
}
"""

# =========================
# DATABASE CONNECTION
# =========================

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# =========================
# HOME ROUTE
# =========================

@app.route('/')
def home():
    return render_template('index.html')

# =========================
# IMAGE UPLOAD ROUTE
# =========================

@app.route('/upload', methods=['POST'])
def upload_image():

    conn = None

    try:

        if 'image' not in request.files:
            return jsonify({"error": "No image uploaded"}), 400

        image_file = request.files['image']

        if image_file.filename == '':
            return jsonify({"error": "No selected file"}), 400

        # Open Image
        image = Image.open(image_file)

        # =========================
        # GEMINI AI PROCESS
        # =========================

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[prompt, image]
        )

        raw_output = response.text.strip()

        # =========================
        # JSON EXTRACTION
        # =========================

        try:
            product_data = json.loads(raw_output)

        except json.JSONDecodeError:

            start = raw_output.find('{')
            end = raw_output.rfind('}') + 1

            if start == -1:
                return jsonify({
                    "error": "Invalid JSON from AI",
                    "raw_output": raw_output
                }), 400

            product_data = json.loads(raw_output[start:end])

        # =========================
        # DEFAULT VALUES
        # =========================

        product_name = product_data.get("product_name", "Unknown Product")
        brand = product_data.get("brand", "Unknown Brand")
        price = product_data.get("price", "Not Available")
        features = product_data.get("features", [])
        dimensions = product_data.get("dimensions", "Not Available")

        # =========================
        # DATABASE INSERT
        # =========================

        conn = get_db_connection()

        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO products
        (product_name, brand, price, features, dimensions)
        VALUES (?, ?, ?, ?, ?)
        """, (
            product_name,
            brand,
            price,
            json.dumps(features),
            dimensions
        ))

        conn.commit()

        return jsonify({
            "message": "Product Added Successfully",
            "product": {
                "product_name": product_name,
                "brand": brand,
                "price": price,
                "features": features,
                "dimensions": dimensions
            }
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500

    finally:
        if conn:
            conn.close()

# =========================
# GET ALL PRODUCTS
# =========================

@app.route('/products', methods=['GET'])
def get_products():

    try:

        conn = get_db_connection()

        cursor = conn.cursor()

        cursor.execute("SELECT * FROM products")

        products = []

        for product in cursor.fetchall():

            product_dict = dict(product)

            product_dict["features"] = json.loads(product_dict["features"])

            products.append(product_dict)

        return jsonify(products)

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500

    finally:
        conn.close()

# =========================
# GET PRODUCT BY ID
# =========================

@app.route('/product/<int:product_id>', methods=['GET'])
def get_product(product_id):

    try:

        conn = get_db_connection()

        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM products WHERE id=?",
            (product_id,)
        )

        product = cursor.fetchone()

        if product:

            product_dict = dict(product)

            product_dict["features"] = json.loads(product_dict["features"])

            return jsonify(product_dict)

        else:
            return jsonify({
                "error": "Product Not Found"
            }), 404

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500

    finally:
        conn.close()

# =========================
# UPDATE PRODUCT
# =========================

@app.route('/product/<int:product_id>', methods=['PUT'])
def update_product(product_id):

    try:

        data = request.get_json()

        conn = get_db_connection()

        cursor = conn.cursor()

        cursor.execute("""
        UPDATE products
        SET product_name=?,
            brand=?,
            price=?,
            features=?,
            dimensions=?
        WHERE id=?
        """, (
            data.get("product_name"),
            data.get("brand"),
            data.get("price"),
            json.dumps(data.get("features", [])),
            data.get("dimensions"),
            product_id
        ))

        conn.commit()

        return jsonify({
            "message": "Product Updated Successfully"
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500

    finally:
        conn.close()

# =========================
# DELETE PRODUCT
# =========================

@app.route('/product/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):

    try:

        conn = get_db_connection()

        cursor = conn.cursor()

        cursor.execute(
            "DELETE FROM products WHERE id=?",
            (product_id,)
        )

        conn.commit()

        return jsonify({
            "message": "Product Deleted Successfully"
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500

    finally:
        conn.close()

# =========================
# RUN APP
# =========================

if __name__ == '__main__':

    if not os.path.exists("static/uploads"):
        os.makedirs("static/uploads")

    app.run(debug=True)
