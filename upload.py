import sys
import os
import requests
from PIL import Image

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Suchit Flask API URL
url = "http://127.0.0.1:5000/upload"

# Image file to upload (from command line argument or default)
image_path = sys.argv[1] if len(sys.argv) > 1 else None

temp_created = False
if not image_path or not os.path.exists(image_path):
    print("No image file specified or file does not exist. Creating temporary test image...")
    image_path = "temp_suchit_upload_sample.jpg"
    img = Image.new("RGB", (400, 400), color=(37, 99, 235))
    img.save(image_path, "JPEG")
    temp_created = True

print(f"Uploading image to Suchit Catalog API: {image_path}")

try:
    with open(image_path, "rb") as img_file:
        files = {"image": img_file}
        response = requests.post(url, files=files, data={"save_immediately": "true"})
        print(f"Response status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print("Extracted Product Details in Suchit Catalog:")
            prod = data.get("product", {})
            print(f"  ID:          #{prod.get('id')}")
            print(f"  Name:        {prod.get('product_name')}")
            print(f"  Brand:       {prod.get('brand')}")
            print(f"  Price:       {prod.get('price')}")
            print(f"  Category:    {prod.get('category')}")
            print(f"  Dimensions:  {prod.get('dimensions')}")
            print(f"  Image Path:  {prod.get('image_path')}")
            if data.get("warning"):
                print(f"  Notice:      {data.get('warning')}")
        else:
            print("Upload failed:", response.status_code, response.text)

finally:
    if temp_created and os.path.exists(image_path):
        os.remove(image_path)
