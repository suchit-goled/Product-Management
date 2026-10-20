import os
import json
from PIL import Image
import google.generativeai as genai

# ==========================
# Configure Gemini API
# ==========================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# Or directly:
# GEMINI_API_KEY = "YOUR_API_KEY"

genai.configure(api_key=GEMINI_API_KEY)

# ==========================
# Load Product Image
# ==========================

image_path = r"C:\Users\YourName\Pictures\product.jpg"   # Replace with your image path
image = Image.open(image_path)

# ==========================
# Load Gemini Model
# ==========================

model = genai.GenerativeModel("gemini-1.5-pro")

# ==========================
# Prompt
# ==========================

prompt = """
Extract product details from this image and return ONLY a valid JSON object.

Required fields:
{
    "product_name": "",
    "brand": "",
    "price": "",
    "features": [],
    "dimensions": ""
}

Rules:
1. If product name is missing, infer a likely name.
2. If brand is missing, infer if reasonably possible.
3. If price is missing, estimate based on similar products and mention it is estimated.
4. If dimensions are missing, estimate based on similar products.
5. Return at least four features.
6. Do not include markdown or explanation.
7. Return only JSON.
"""

# ==========================
# Send Image to Gemini
# ==========================

response = model.generate_content([prompt, image])

# ==========================
# Extract JSON
# ==========================

try:
    raw_output = response.text.strip()

    start = raw_output.find("{")
    end = raw_output.rfind("}") + 1

    json_text = raw_output[start:end]

    product_json = json.loads(json_text)

except Exception as e:
    print("Error parsing JSON:", e)
    product_json = {
        "error": "Gemini did not return valid JSON.",
        "raw_response": response.text
    }

# ==========================
# Save JSON
# ==========================

with open("product_data.json", "w", encoding="utf-8") as file:
    json.dump(product_json, file, indent=4, ensure_ascii=False)

# ==========================
# Print Output
# ==========================

print(json.dumps(product_json, indent=4, ensure_ascii=False))