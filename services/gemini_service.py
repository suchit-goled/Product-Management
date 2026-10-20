"""
Suchit Catalog - AI Extraction and Multimodal Generation Service
Integrates with Google GenAI SDK (gemini-2.5-flash, gemini-2.0-flash, etc.)
with structured JSON output, OCR text verification, and reliable offline fallbacks.
"""
import os
import re
import json
import logging
from PIL import Image
from config import Config

logger = logging.getLogger(__name__)

DEFAULT_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash"
]

CATALOG_EXTRACTION_PROMPT = """
You are Suchit Catalog AI, an expert multimodal product cataloging engine.
Analyze the provided product image and extract structured product catalog data.

CRITICAL GUIDELINES:
1. ACCURACY & VERIFICATION:
   - Identify text printed on the product, box, packaging, or label (brand name, model, certifications, physical dimensions, visible ports, capacities).
   - If a specification or price is not directly visible on the item or packaging, estimate realistically based on the exact product type and append '(estimated)'.
   - DO NOT fabricate certifications (e.g. UL, CE, FCC), warranties, or compatibility claims if not visible.
   - List the fields you directly verified from packaging/label in 'verified_fields'.
   - List the fields you inferred or synthesized in 'suggested_fields'.

2. REQUIRED JSON SCHEMA (Return ONLY valid JSON):
{
    "product_name": "Clear, professional, marketable product title",
    "brand": "Identified brand name or 'Unspecified'",
    "model": "Model number or identifier if visible, else null",
    "category": "Primary product category (e.g., Electronics & Audio, Smartphones, Home & Kitchen, Apparel, Automotive, Jewelry & Accessories, Sports & Outdoors, Art & Decor)",
    "price": "Price with currency symbol (e.g., ₹1,499 or $799) if visible, or estimated price with '(estimated)'",
    "dimensions": "Dimensions with units if visible, or estimated dimensions with '(estimated)'",
    "short_description": "A crisp, high-impact 1-2 sentence product summary",
    "description": "A comprehensive, professional marketing description (2-3 paragraphs) highlighting materials, design, build quality, and intended user benefit",
    "features": [
        "Feature bullet 1 with key specification detail",
        "Feature bullet 2 with functional utility",
        "Feature bullet 3 with ergonomics or connectivity",
        "Feature bullet 4 with durability or aesthetics"
    ],
    "specifications": {
        "Key Attribute 1": "Value",
        "Connectivity / Interface": "Value",
        "Material / Finish": "Value",
        "Weight / Form Factor": "Value"
    },
    "selling_points": [
        "Key commercial USP 1",
        "Key commercial USP 2",
        "Key commercial USP 3"
    ],
    "tags": [
        "search-keyword-1",
        "search-keyword-2",
        "search-keyword-3",
        "category-tag"
    ],
    "seo_title": "SEO-friendly title under 60 characters",
    "seo_description": "SEO meta description between 140-160 characters",
    "verified_fields": ["product_name", "brand"],
    "suggested_fields": ["description", "selling_points", "tags"]
}
"""


def clean_json_text(text: str) -> str:
    """Extract clean JSON string from LLM response containing markdown or extra prose."""
    if not text:
        return ""
    text = text.strip()
    
    # Strip markdown code blocks ```json ... ```
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

    # Find boundaries of the outermost JSON object
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        return text[start:end+1]
        
    return text


def get_genai_client(api_key: str = None):
    """Instantiate and return google-genai Client safely."""
    key = (api_key or Config.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=key)
    except Exception as e:
        logger.warning(f"Failed to initialize GenAI client: {e}")
        return None


def test_gemini_connection(api_key: str = None) -> dict:
    """Test connectivity and validity of a Gemini API key."""
    key = (api_key or Config.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        return {
            "success": False,
            "message": "No API key configured. Please enter your Gemini API key.",
            "code": "MISSING_KEY"
        }
    
    client = get_genai_client(key)
    if not client:
        return {
            "success": False,
            "message": "Unable to initialize Google GenAI SDK.",
            "code": "INIT_ERROR"
        }

    for model in DEFAULT_MODELS:
        try:
            response = client.models.generate_content(
                model=model,
                contents="Respond with ONLY the word PONG"
            )
            resp_text = (response.text or "").strip()
            return {
                "success": True,
                "message": f"Connected successfully to {model}!",
                "model": model,
                "response": resp_text
            }
        except Exception as e:
            err_msg = str(e)
            logger.debug(f"Test connection attempt with {model} failed: {err_msg}")
            # If invalid argument / key invalid, stop trying other models
            if "API_KEY_INVALID" in err_msg or "API key not valid" in err_msg:
                return {
                    "success": False,
                    "message": "API key is invalid or has expired. Please verify your Google AI Studio key.",
                    "code": "INVALID_KEY"
                }

    return {
        "success": False,
        "message": f"Could not connect to Gemini models: {err_msg}",
        "code": "MODEL_ERROR"
    }


def analyze_product_image(image_path: str, model_name: str = None, api_key: str = None) -> dict:
    """
    Analyzes a product image using Gemini Multimodal vision and returns
    structured catalog data. If the API key is missing or invalid,
    it falls back cleanly to a local image analysis draft.
    """
    if not os.path.exists(image_path):
        return _generate_offline_fallback(image_path, "Image file not found on disk")

    client = get_genai_client(api_key)
    if not client:
        logger.info("No Gemini API key available. Generating local inspection fallback.")
        return _generate_offline_fallback(
            image_path,
            "Gemini API key is not configured. A local catalog draft has been prepared. Configure your API key in Settings for AI auto-enrichment."
        )

    # Open image for PIL
    try:
        pil_img = Image.open(image_path)
    except Exception as e:
        return _generate_offline_fallback(image_path, f"Failed to load image with PIL: {e}")

    models_to_try = [model_name] if model_name else DEFAULT_MODELS

    last_error = None
    for model in models_to_try:
        if not model:
            continue
        try:
            logger.info(f"Analyzing product image with model: {model}")
            response = client.models.generate_content(
                model=model,
                contents=[CATALOG_EXTRACTION_PROMPT, pil_img]
            )

            raw_text = response.text or ""
            cleaned_json = clean_json_text(raw_text)
            
            try:
                data = json.loads(cleaned_json)
                return _normalize_catalog_data(data, image_path, source=f"gemini:{model}")
            except json.JSONDecodeError as jde:
                logger.warning(f"JSON decode failed for model {model}: {jde}. Raw: {raw_text[:200]}")
                last_error = f"Invalid JSON returned by {model}"
                continue

        except Exception as e:
            err_str = str(e)
            logger.warning(f"Gemini generation failed on model {model}: {err_str}")
            last_error = err_str
            # If invalid key, do not waste retries with other models
            if "API_KEY_INVALID" in err_str or "API key not valid" in err_str:
                break

    # If all model attempts failed, return high quality local fallback
    logger.warning(f"All Gemini model attempts failed. Error: {last_error}. Using local fallback.")
    return _generate_offline_fallback(
        image_path,
        f"AI service temporarily unavailable ({last_error}). Local catalog draft generated for review."
    )


def _generate_offline_fallback(image_path: str, reason: str) -> dict:
    """
    Generates a realistic, pre-populated catalog draft using local image metadata
    and file name heuristics so the user workflow is never blocked.
    """
    filename = os.path.basename(image_path) if image_path else "product_image.jpg"
    base_name = os.path.splitext(filename)[0]
    # Clean up name: remove 'suchit_prod_xxxx_' prefix if present
    clean_title = re.sub(r"^suchit_[a-f0-9]+_", "", base_name)
    clean_title = re.sub(r"[-_]+", " ", clean_title).strip().title()
    if not clean_title or clean_title.lower() in ("product", "image", "upload"):
        clean_title = "New Product Catalog Item"

    # Inspect image size if possible
    dims = "Not specified"
    specifications = {}
    if image_path and os.path.exists(image_path):
        try:
            with Image.open(image_path) as img:
                dims = f"{img.width} x {img.height} px (image resolution)"
                specifications["Image Resolution"] = f"{img.width}x{img.height}"
                specifications["Color Mode"] = img.mode
                specifications["File Format"] = img.format or "JPEG"
        except Exception:
            pass

    return {
        "product_name": clean_title,
        "brand": "Unspecified Brand",
        "model": None,
        "category": "General Merchandise",
        "price": "₹999 (estimated)",
        "dimensions": dims,
        "short_description": f"Catalog draft created for {clean_title}.",
        "description": f"This product catalog record was created from image '{filename}'. Please review and update product specifications, pricing, brand details, and marketing highlights to complete your Suchit catalog listing.",
        "features": [
            "Ergonomic and functional design",
            "High quality build and materials",
            "Inspected and ready for catalog publishing",
            "Customizable product specifications"
        ],
        "specifications": specifications if specifications else {
            "Status": "Draft Ready for Review",
            "Packaging": "Standard Retail"
        },
        "selling_points": [
            "Fast deployment to e-commerce and retail catalogs",
            "Comprehensive metadata and specification tracking",
            "Editable multi-channel catalog entry"
        ],
        "tags": [
            "catalog",
            "product",
            clean_title.lower().replace(" ", "-")
        ],
        "seo_title": f"{clean_title} | Suchit Product Catalog",
        "seo_description": f"Explore details and specifications for {clean_title} in the Suchit Product Catalog.",
        "verified_fields": [],
        "suggested_fields": ["product_name", "category", "features", "description", "selling_points"],
        "extraction_source": "offline_fallback",
        "warning": reason
    }


def _normalize_catalog_data(data: dict, image_path: str, source: str) -> dict:
    """Normalize and guarantee types for all catalog fields."""
    product_name = data.get("product_name") or "Unnamed Product"
    brand = data.get("brand") or "Unspecified Brand"
    category = data.get("category") or "General Merchandise"
    price = data.get("price") or "Not Available"
    dimensions = data.get("dimensions") or "Not Available"
    model = data.get("model")
    
    short_desc = data.get("short_description") or f"{product_name} by {brand}."
    desc = data.get("description") or short_desc
    
    # Normalize features
    raw_features = data.get("features", [])
    if isinstance(raw_features, list):
        features = [str(f).strip() for f in raw_features if str(f).strip()]
    elif isinstance(raw_features, str):
        features = [f.strip() for f in raw_features.split(",") if f.strip()]
    else:
        features = []
    if not features:
        features = ["High quality design and construction", "Ready for commercial distribution"]

    # Normalize specifications
    raw_specs = data.get("specifications", {})
    specifications = {}
    if isinstance(raw_specs, dict):
        for k, v in raw_specs.items():
            if k and v is not None:
                specifications[str(k).strip()] = str(v).strip()
    elif isinstance(raw_specs, list):
        for item in raw_specs:
            if isinstance(item, dict):
                specifications.update({str(k): str(v) for k, v in item.items()})

    # Normalize selling points
    raw_usp = data.get("selling_points", [])
    if isinstance(raw_usp, list):
        selling_points = [str(u).strip() for u in raw_usp if str(u).strip()]
    else:
        selling_points = []

    # Normalize tags
    raw_tags = data.get("tags", [])
    if isinstance(raw_tags, list):
        tags = [str(t).strip().lower() for t in raw_tags if str(t).strip()]
    elif isinstance(raw_tags, str):
        tags = [t.strip().lower() for t in raw_tags.split(",") if t.strip()]
    else:
        tags = []

    seo_title = data.get("seo_title") or f"{product_name} - {brand}"
    seo_desc = data.get("seo_description") or short_desc

    verified_fields = data.get("verified_fields") or []
    suggested_fields = data.get("suggested_fields") or []

    return {
        "product_name": product_name,
        "brand": brand,
        "model": model,
        "category": category,
        "price": price,
        "dimensions": dimensions,
        "short_description": short_desc,
        "description": desc,
        "features": features,
        "specifications": specifications,
        "selling_points": selling_points,
        "tags": tags,
        "seo_title": seo_title,
        "seo_description": seo_desc,
        "verified_fields": verified_fields,
        "suggested_fields": suggested_fields,
        "extraction_source": source
    }
