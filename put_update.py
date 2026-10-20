import sys
import requests
import json

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Change this to an existing product ID you want to update
product_id = 3
url = f"http://127.0.0.1:5000/product/{product_id}"

updated_product_data = {
    "product_name": "boAt Airdopes 131 Pro",
    "brand": "boAt",
    "price": "₹1,499",
    "features": [
        "True Wireless Stereo",
        "ENx Environmental Noise Cancellation",
        "Up to 45 Hours Playback",
        "ASAP Fast Charge",
        "Bluetooth v5.3"
    ],
    "dimensions": "60 x 50 x 30 mm",
    "category": "Electronics & Audio"
}

response = requests.put(url, json=updated_product_data)

if response.status_code == 200:
    print(f"Product #{product_id} updated successfully in Suchit Catalog!")
    print(response.json())
else:
    print(f"Failed to update product. Status code: {response.status_code}, response: {response.text}")
