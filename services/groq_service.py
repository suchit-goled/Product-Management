"""
Product Catalog - Groq AI Multimodal & Text Catalog Generator Service
Integrates with Groq Chat Completions API (Llama 4 Scout Vision, Qwen 3.8 Vision,
Llama 3.3 70B Versatile) while keeping GROQ_API_KEY strictly server-side.
"""
import os
import io
import json
import base64
import logging
import requests
from PIL import Image

from config import Config
from services import security_service
from services.gemini_service import (
    CATALOG_EXTRACTION_PROMPT,
    clean_json_text,
    _normalize_catalog_data,
    _generate_offline_fallback,
)

logger = logging.getLogger("product_catalog.groq")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

GROQ_VISION_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "qwen/qwen3.8-27b",
]

GROQ_TEXT_MODELS = [
    "llama-3.3-70b-versatile",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "qwen/qwen3.8-27b",
]


def is_groq_configured() -> bool:
    """Returns True when a non-empty GROQ_API_KEY is configured server-side."""
    key = (Config.GROQ_API_KEY or os.getenv("GROQ_API_KEY") or "").strip()
    return len(key) > 10


def _get_groq_api_key() -> str:
    return (Config.GROQ_API_KEY or os.getenv("GROQ_API_KEY") or "").strip()


def _encode_image_for_groq(image_path: str, max_dim: int = 1280) -> str:
    """
    Loads local image, converts to RGB JPEG, and scales safely so the
    base64 payload remains well under Groq's 4MB base64 data URI limit.
    """
    with Image.open(image_path) as img:
        if img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            rgba = img.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[3])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"


def _call_groq_chat(model: str, messages: list, api_key: str) -> dict:
    """
    Calls Groq OpenAI-compatible Chat Completions API with JSON mode and safe error handling.
    Returns parsed JSON dict or raises RuntimeError with non-secret message.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_completion_tokens": 2048,
        "response_format": {"type": "json_object"},
    }

    resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=35)

    # Retry once without response_format if a specific model rejects json_object
    if resp.status_code == 400 and "response_format" in resp.text.lower():
        payload.pop("response_format", None)
        resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=35)

    if resp.status_code == 401:
        raise PermissionError("GROQ_AUTH_FAILED")
    if resp.status_code == 429:
        raise RuntimeError("GROQ_RATE_LIMITED")
    if not resp.ok:
        logger.warning(f"Groq API error status={resp.status_code} model={model}")
        raise RuntimeError(f"GROQ_HTTP_{resp.status_code}")

    body = resp.json()
    content = (
        body.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    cleaned = clean_json_text(content)
    return json.loads(cleaned)


def analyze_product_image_groq(image_path: str, model_name: str = None) -> dict:
    """
    Analyzes a product image using Groq Vision (Llama 4 Scout / Qwen 3.8)
    and returns normalized catalog fields. Falls back cleanly if unconfigured or unavailable.
    """
    if not os.path.exists(image_path):
        return _generate_offline_fallback(image_path, "Uploaded image file could not be read.")

    api_key = _get_groq_api_key()
    if not api_key:
        return _generate_offline_fallback(
            image_path,
            "Groq API key is not configured on the server. A local catalog draft has been prepared for review."
        )

    try:
        data_uri = _encode_image_for_groq(image_path)
    except Exception as exc:
        logger.warning(f"Failed to encode image for Groq Vision: {exc}")
        return _generate_offline_fallback(
            image_path,
            "Unable to decode uploaded image for AI inspection. Local draft generated."
        )

    models_to_try = [model_name] if model_name in GROQ_VISION_MODELS else list(GROQ_VISION_MODELS)
    for model in models_to_try:
        try:
            logger.info(f"Analyzing product image with Groq model: {model}")
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": CATALOG_EXTRACTION_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ]
            parsed = _call_groq_chat(model, messages, api_key)
            return _normalize_catalog_data(parsed, image_path, source=f"groq:{model}")
        except PermissionError:
            logger.warning("Groq API key rejected (401 Unauthorized).")
            return _generate_offline_fallback(
                image_path,
                "Groq API authentication failed on server. Local catalog draft generated for review."
            )
        except Exception as exc:
            logger.warning(f"Groq vision generation failed on {model}: {exc}")
            continue

    return _generate_offline_fallback(
        image_path,
        "Groq AI service temporarily unavailable. Local catalog draft generated for review."
    )


def _generate_prompt_offline_fallback(
    prompt_text: str,
    brand_hint: str = "",
    category_hint: str = "",
    price_hint: str = "",
    reason: str = "",
) -> dict:
    """Produces a clean structured catalog draft from prompt hints when AI APIs are unavailable."""
    clean_prompt = security_service.sanitize_text_field(prompt_text, 400)
    short_title = (clean_prompt.split("\n")[0].split(",")[0].strip() or "Catalog Product")[:80]
    brand = security_service.sanitize_text_field(brand_hint, 100) or "Unspecified Brand"
    category = security_service.sanitize_text_field(category_hint, 100) or "General Merchandise"
    price = security_service.sanitize_text_field(price_hint, 60) or "₹999 (estimated)"

    return {
        "product_name": short_title,
        "brand": brand,
        "model": None,
        "category": category,
        "price": price,
        "dimensions": "Not specified",
        "short_description": f"{short_title} — {clean_prompt[:140]}",
        "description": f"Catalog listing generated from product brief: {clean_prompt}. Review and refine technical specifications before publishing.",
        "features": [
            "Commercial-grade specification profile",
            "Structured catalog metadata ready for export",
            "Multi-channel listing compatibility",
            "Verified summary and search tagging",
        ],
        "specifications": {
            "Category": category,
            "Brand": brand,
            "Catalog Status": "Draft Ready for Review",
        },
        "selling_points": [
            "Structured specification overview",
            "Ready for PDF, CSV, and JSON catalog distribution",
            "Consistent retail presentation",
        ],
        "tags": [
            "catalog",
            category.lower().replace(" ", "-"),
            short_title.lower().replace(" ", "-")[:32],
        ],
        "seo_title": f"{short_title} | {brand}"[:60],
        "seo_description": f"Explore specifications and commercial details for {short_title} by {brand}."[:160],
        "verified_fields": [],
        "suggested_fields": ["product_name", "description", "features", "specifications", "selling_points", "tags"],
        "extraction_source": "offline_fallback",
        "image_path": "",
        "warning": reason,
    }


def generate_catalog_from_prompt_groq(
    prompt_text: str,
    brand_hint: str = "",
    category_hint: str = "",
    price_hint: str = "",
    model_name: str = None,
) -> dict:
    """
    Generates a complete structured product catalog draft from a text brief/prompt
    using Groq LLMs (Llama 3.3 70B / Llama 4 Scout / Qwen 3.8).
    """
    clean_prompt = security_service.sanitize_text_field(prompt_text, 2000)
    clean_brand = security_service.sanitize_text_field(brand_hint, 120)
    clean_cat = security_service.sanitize_text_field(category_hint, 100)
    clean_price = security_service.sanitize_text_field(price_hint, 60)

    api_key = _get_groq_api_key()
    if not api_key:
        return _generate_prompt_offline_fallback(
            clean_prompt,
            clean_brand,
            clean_cat,
            clean_price,
            "Groq API key is not configured on the server. A local catalog draft has been prepared for review.",
        )

    hints = []
    if clean_brand:
        hints.append(f"Brand hint: {clean_brand}")
    if clean_cat:
        hints.append(f"Category hint: {clean_cat}")
    if clean_price:
        hints.append(f"Price hint: {clean_price}")
    hints_block = ("\nAdditional structured hints:\n- " + "\n- ".join(hints)) if hints else ""

    text_prompt = (
        f"{CATALOG_EXTRACTION_PROMPT}\n\n"
        f"PRODUCT BRIEF / INPUT TEXT (generate a realistic, accurate, market-ready catalog JSON record from this brief; "
        f"if a specification or price is missing, estimate realistically and append '(estimated)'):\n"
        f"{clean_prompt}{hints_block}\n\nReturn ONLY a valid JSON object matching the required schema."
    )

    models_to_try = [model_name] if model_name in GROQ_TEXT_MODELS else list(GROQ_TEXT_MODELS)
    for model in models_to_try:
        try:
            logger.info(f"Generating catalog record from text prompt with Groq model: {model}")
            messages = [
                {
                    "role": "system",
                    "content": "You are Product Catalog AI. Output ONLY valid JSON matching the requested schema.",
                },
                {"role": "user", "content": text_prompt},
            ]
            parsed = _call_groq_chat(model, messages, api_key)
            normalized = _normalize_catalog_data(parsed, "", source=f"groq:{model}")
            normalized["image_path"] = ""
            return normalized
        except PermissionError:
            logger.warning("Groq API key rejected (401 Unauthorized) during text generation.")
            return _generate_prompt_offline_fallback(
                clean_prompt,
                clean_brand,
                clean_cat,
                clean_price,
                "Groq API authentication failed on server. Local catalog draft generated for review.",
            )
        except Exception as exc:
            logger.warning(f"Groq text generation failed on {model}: {exc}")
            continue

    return _generate_prompt_offline_fallback(
        clean_prompt,
        clean_brand,
        clean_cat,
        clean_price,
        "Groq AI service temporarily unavailable. Local catalog draft generated for review.",
    )
