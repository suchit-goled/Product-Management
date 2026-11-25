"""
Suchit Catalog - Image Processing, EXIF Stripping & Optimization Service
Validates magic bytes via Pillow, auto-rotates EXIF, strips sensitive EXIF metadata
(GPS/XSS payloads) on write, downscales safely, and creates WebP + primary copies.
"""
import os
import uuid
import logging
from PIL import Image, ImageOps
from werkzeug.utils import secure_filename

logger = logging.getLogger("suchit.image")

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'tiff'}
MAX_DIMENSION = 1920
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16 MB


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def validate_and_save_image(file_storage, upload_folder, max_dim=MAX_DIMENSION, compress_quality=88):
    """
    Validates uploaded image content, auto-orients EXIF, strips EXIF metadata
    for privacy/XSS safety, downscales oversized dimensions, and saves optimized assets.
    """
    if not file_storage or file_storage.filename == '':
        return None, None, None, "No file provided"

    orig_filename = secure_filename(file_storage.filename)
    if not allowed_file(orig_filename):
        return None, None, None, f"Unsupported file type. Allowed formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}"

    os.makedirs(upload_folder, exist_ok=True)

    try:
        # Check stream size strictly
        file_storage.stream.seek(0, os.SEEK_END)
        raw_size = file_storage.stream.tell()
        file_storage.stream.seek(0)
        if raw_size == 0:
            return None, None, None, "Uploaded image file is empty"
        if raw_size > MAX_FILE_SIZE:
            return None, None, None, "Image exceeds maximum 16MB file size limit"

        # Verify magic bytes / pixel decoding
        img = Image.open(file_storage.stream)
        img.verify()

        file_storage.stream.seek(0)
        img = Image.open(file_storage.stream)

        # Auto-rotate smartphone EXIF orientation
        try:
            img = ImageOps.exif_transpose(img)
        except Exception as e:
            logger.debug(f"EXIF transpose skipped: {e}")

        # Downscale cleanly if oversized (and block decompression bombs)
        orig_w, orig_h = img.size
        if orig_w * orig_h > 40_000_000:
            return None, None, None, "Image resolution exceeds 40 megapixels limit"

        if max(orig_w, orig_h) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

        # Re-render pixels onto fresh Image canvas to strip ALL embedded EXIF/XMP/comment payloads
        clean_mode = "RGBA" if (img.mode in ("RGBA", "LA", "P") and orig_filename.lower().endswith((".png", ".webp"))) else "RGB"
        if img.mode == "P" and clean_mode == "RGBA":
            img = img.convert("RGBA")
        elif clean_mode == "RGB" and img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            rgba = img.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[3])
            img = bg
        elif img.mode != clean_mode:
            img = img.convert(clean_mode)

        sanitized_img = Image.frombytes(img.mode, img.size, img.tobytes())

        unique_prefix = uuid.uuid4().hex[:10]
        ext = orig_filename.rsplit('.', 1)[1].lower() if '.' in orig_filename else 'jpg'
        if ext not in ALLOWED_EXTENSIONS:
            ext = 'jpg'

        save_filename = f"suchit_{unique_prefix}_{orig_filename}"
        if not save_filename.lower().endswith(f".{ext}"):
            save_filename = f"{save_filename}.{ext}"

        save_path = os.path.join(upload_folder, save_filename)
        save_format = 'PNG' if ext == 'png' else ('WEBP' if ext == 'webp' else 'JPEG')
        sanitized_img.save(save_path, format=save_format, quality=compress_quality, optimize=True)

        webp_filename = f"{os.path.splitext(save_filename)[0]}.webp"
        webp_path = os.path.join(upload_folder, webp_filename)
        if not os.path.exists(webp_path):
            try:
                sanitized_img.save(webp_path, format="WEBP", quality=compress_quality, method=6)
            except Exception as we:
                logger.debug(f"WebP compression optional: {we}")

        final_w, final_h = sanitized_img.size
        file_size = os.path.getsize(save_path)

        metadata = {
            "filename": save_filename,
            "original_filename": orig_filename,
            "width": final_w,
            "height": final_h,
            "aspect_ratio": round(final_w / max(final_h, 1), 2),
            "format": save_format,
            "exif_stripped": True,
            "file_size_bytes": file_size,
            "file_size_formatted": f"{file_size / 1024:.1f} KB" if file_size < 1024 * 1024 else f"{file_size / (1024 * 1024):.2f} MB",
            "webp_available": os.path.exists(webp_path)
        }

        relative_url = f"/static/uploads/{save_filename}"
        return relative_url, save_path, metadata, None

    except Exception as e:
        logger.error(f"Image processing failed: {e}", exc_info=True)
        return None, None, None, "Invalid or corrupted image file"
