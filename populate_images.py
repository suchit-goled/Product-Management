"""
Script to generate high-resolution, beautifully styled product showcase images
for existing catalog products and link them in products.db.
"""
import os
import sqlite3
import math
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)
DB_PATH = os.path.join(BASE_DIR, "products.db")


def draw_rounded_rect(draw, bbox, radius, fill=None, outline=None, width=1):
    x0, y0, x1, y1 = bbox
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill, outline=outline, width=width)


def create_product_artwork(prod_id, title, brand, category, theme_colors, icon_type):
    width, height = 800, 600
    bg_main, bg_grad, accent, card_bg, text_color = theme_colors

    img = Image.new("RGB", (width, height), color=bg_main)
    draw = ImageDraw.Draw(img)

    # Background subtle gradient effect
    for y in range(height):
        ratio = y / height
        r = int(bg_main[0] * (1 - ratio * 0.4) + bg_grad[0] * (ratio * 0.4))
        g = int(bg_main[1] * (1 - ratio * 0.4) + bg_grad[1] * (ratio * 0.4))
        b = int(bg_main[2] * (1 - ratio * 0.4) + bg_grad[2] * (ratio * 0.4))
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Inner decorative border
    draw_rounded_rect(draw, [25, 25, width - 25, height - 25], radius=24, outline=accent, width=2)
    draw_rounded_rect(draw, [29, 29, width - 29, height - 29], radius=20, outline=(accent[0]//2, accent[1]//2, accent[2]//2), width=1)

    # Top Brand / Category Bar
    draw_rounded_rect(draw, [50, 48, 260, 84], radius=18, fill=accent)
    draw.text((65, 57), f"SUCHIT CATALOG", fill=(255, 255, 255))
    draw.text((width - 240, 57), f"{category[:20].upper()}", fill=accent)

    # Center Showcase Stage Card
    stage_box = [160, 115, 640, 435]
    draw_rounded_rect(draw, stage_box, radius=24, fill=card_bg, outline=accent, width=2)

    # Subtle ambient glow
    cx, cy = 400, 275

    # Render category specific illustration / silhouettes
    if icon_type == "audio":
        # Earbuds case and twin buds
        # Charging case
        draw_rounded_rect(draw, [cx - 90, cy - 60, cx + 90, cy + 80], radius=45, fill=(40, 45, 60), outline=accent, width=3)
        draw.line([cx - 85, cy + 5, cx + 85, cy + 5], fill=accent, width=2)
        # LED indicator
        draw.ellipse([cx - 4, cy + 30, cx + 4, cy + 38], fill=(34, 197, 94))
        # Left earbud
        draw.ellipse([cx - 150, cy - 80, cx - 110, cy - 40], fill=accent)
        draw_rounded_rect(draw, [cx - 138, cy - 50, cx - 122, cy + 10], radius=8, fill=(200, 210, 230))
        # Right earbud
        draw.ellipse([cx + 110, cy - 80, cx + 150, cy - 40], fill=accent)
        draw_rounded_rect(draw, [cx + 122, cy - 50, cx + 138, cy + 10], radius=8, fill=(200, 210, 230))
        # Sound waves
        for r in range(120, 190, 25):
            draw.arc([cx - r, cy - r + 10, cx + r, cy + r + 10], start=-35, end=35, fill=accent, width=2)
            draw.arc([cx - r, cy - r + 10, cx + r, cy + r + 10], start=145, end=215, fill=accent, width=2)

    elif icon_type == "phone":
        # Smartphone body
        phone_box = [cx - 75, cy - 130, cx + 75, cy + 130]
        draw_rounded_rect(draw, phone_box, radius=28, fill=(15, 23, 42), outline=(148, 163, 184), width=4)
        # Screen area
        draw_rounded_rect(draw, [cx - 68, cy - 122, cx + 68, cy + 122], radius=22, fill=(30, 41, 59))
        # Screen vibrant display wallpaper gradient
        for y in range(cy - 120, cy + 120):
            ratio = (y - (cy - 120)) / 240
            r = int(59 * (1 - ratio) + 236 * ratio)
            g = int(130 * (1 - ratio) + 72 * ratio)
            b = int(246 * (1 - ratio) + 153 * ratio)
            draw.line([(cx - 66, y), (cx + 66, y)], fill=(r, g, b))
        # Notch / Dynamic island
        draw_rounded_rect(draw, [cx - 24, cy - 118, cx + 24, cy - 104], radius=7, fill=(15, 23, 42))

    elif icon_type == "auto":
        # Luxury Supercar Silhouette
        # Body aerodynamic contour
        pts = [
            (cx - 180, cy + 45),
            (cx - 150, cy + 10),
            (cx - 80, cy - 15),
            (cx - 20, cy - 50),
            (cx + 60, cy - 50),
            (cx + 120, cy - 10),
            (cx + 175, cy + 15),
            (cx + 190, cy + 45),
            (cx + 150, cy + 45),
            (cx + 120, cy + 15),
            (cx + 80, cy + 15),
            (cx + 50, cy + 45),
            (cx - 60, cy + 45),
            (cx - 90, cy + 15),
            (cx - 130, cy + 15),
            (cx - 155, cy + 45)
        ]
        draw.polygon(pts, fill=accent, outline=(255, 255, 255))
        # Windows / cockpit
        cockpit = [(cx - 20, cy - 42), (cx + 50, cy - 42), (cx + 90, cy - 10), (cx - 50, cy - 10)]
        draw.polygon(cockpit, fill=(15, 23, 42))
        # Wheels
        draw.ellipse([cx - 130, cy + 20, cx - 80, cy + 70], fill=(15, 23, 42), outline=accent, width=4)
        draw.ellipse([cx + 80, cy + 20, cx + 130, cy + 70], fill=(15, 23, 42), outline=accent, width=4)
        draw.ellipse([cx - 110, cy + 40, cx - 100, cy + 50], fill=(220, 220, 220))
        draw.ellipse([cx + 100, cy + 40, cx + 110, cy + 50], fill=(220, 220, 220))

    elif icon_type == "jewelry":
        # Artisan Jhumka earrings
        for ox in [-80, 80]:
            jx = cx + ox
            # Stud flower
            draw.ellipse([jx - 25, cy - 100, jx + 25, cy - 50], fill=(226, 232, 240), outline=accent, width=2)
            draw.ellipse([jx - 8, cy - 83, jx + 8, cy - 67], fill=accent)
            # Connecting loop
            draw.line([jx, cy - 50, jx, cy - 30], fill=(200, 200, 210), width=3)
            # Bell dome (jhumka bell)
            draw.pieslice([jx - 55, cy - 35, jx + 55, cy + 45], start=0, end=180, fill=(203, 213, 225), outline=accent, width=2)
            draw.line([jx - 55, cy + 5, jx + 55, cy + 5], fill=accent, width=2)
            # Hanging pearl droplets
            for px in range(int(jx - 45), int(jx + 55), 18):
                draw.line([px, cy + 5, px, cy + 25], fill=(200, 200, 210), width=2)
                draw.ellipse([px - 5, cy + 25, px + 5, cy + 35], fill=(255, 255, 255), outline=accent, width=1)

    elif icon_type == "lanyard":
        # Campus Lanyard ribbon
        draw.line([cx - 90, cy - 120, cx - 30, cy + 20], fill=accent, width=16)
        draw.line([cx + 90, cy - 120, cx + 30, cy + 20], fill=accent, width=16)
        draw.line([cx - 30, cy + 20, cx, cy + 50], fill=accent, width=16)
        draw.line([cx + 30, cy + 20, cx, cy + 50], fill=accent, width=16)
        # Metal clasp
        draw_rounded_rect(draw, [cx - 15, cy + 50, cx + 15, cy + 75], radius=6, fill=(148, 163, 184), outline=(100, 116, 139), width=2)
        # ID Card pouch
        card_rect = [cx - 65, cy + 75, cx + 65, cy + 140]
        draw_rounded_rect(draw, card_rect, radius=8, fill=(248, 250, 252), outline=(148, 163, 184), width=2)
        draw.rectangle([cx - 55, cy + 85, cx - 25, cy + 120], fill=accent)
        draw.line([cx - 15, cy + 90, cx + 45, cy + 90], fill=(71, 85, 105), width=3)
        draw.line([cx - 15, cy + 105, cx + 35, cy + 105], fill=(148, 163, 184), width=2)
        draw.line([cx - 15, cy + 118, cx + 40, cy + 118], fill=(148, 163, 184), width=2)

    elif icon_type == "sculpture":
        # Monumental Brain Modern Art Piece on Pedestal
        # Pedestal
        draw_rounded_rect(draw, [cx - 120, cy + 60, cx + 120, cy + 130], radius=8, fill=(71, 85, 105), outline=accent, width=3)
        draw.text((cx - 55, cy + 85), "EXHIBIT GALLERY", fill=(203, 213, 225))
        # Brain hemisphere folds
        draw.ellipse([cx - 95, cy - 110, cx + 95, cy + 60], fill=(180, 83, 9), outline=accent, width=3)
        for offset in range(-60, 70, 30):
            draw.arc([cx - 70, cy - 80 + offset//2, cx + 70, cy + 30 + offset//2], start=20, end=160, fill=(245, 158, 11), width=4)
            draw.arc([cx - 60 + offset, cy - 90, cx + 60 + offset, cy + 40], start=80, end=280, fill=(251, 191, 36), width=3)

    # Bottom Information Plate
    draw_rounded_rect(draw, [50, 460, width - 50, 560], radius=16, fill=(15, 23, 42), outline=accent, width=2)
    # Brand and Product Title
    draw.text((75, 478), f"{brand.upper()}", fill=accent)
    draw.text((75, 508), f"{title[:42]}", fill=(255, 255, 255))
    # Security / Quality Emblem
    draw_rounded_rect(draw, [width - 240, 485, width - 75, 535], radius=10, fill=(30, 41, 59), outline=accent, width=1)
    draw.text((width - 225, 500), "ORIGINAL ASSET", fill=(34, 197, 94))

    # Save both WebP and JPEG compressed versions
    slug = f"suchit_asset_{prod_id}_{brand.lower().replace(' ', '_')}"
    jpg_filename = f"{slug}.jpg"
    webp_filename = f"{slug}.webp"

    jpg_path = os.path.join(UPLOADS_DIR, jpg_filename)
    webp_path = os.path.join(UPLOADS_DIR, webp_filename)

    img.save(jpg_path, "JPEG", quality=90, optimize=True)
    img.save(webp_path, "WEBP", quality=90, method=6)

    return f"/static/uploads/{jpg_filename}"


def populate_all_images():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    products_spec = [
        (3, "boAt Airdopes 131 Pro", "boAt", "Electronics & Audio",
         ((15, 23, 42), (30, 58, 138), (37, 99, 235), (24, 33, 56), (255, 255, 255)), "audio"),
        (4, "boAt Airdopes", "boAt", "Electronics & Audio",
         ((15, 23, 42), (30, 58, 138), (14, 165, 233), (24, 33, 56), (255, 255, 255)), "audio"),
        (5, "boAt Airdopes Twin", "boAt", "Electronics & Audio",
         ((15, 23, 42), (30, 58, 138), (99, 102, 241), (24, 33, 56), (255, 255, 255)), "audio"),
        (6, "boAt Airdopes True Wireless Earbuds", "boAt", "Electronics & Audio",
         ((15, 23, 42), (30, 58, 138), (16, 185, 129), (24, 33, 56), (255, 255, 255)), "audio"),
        (7, "Apple iPhone 13", "Apple", "Smartphones & Electronics",
         ((17, 24, 39), (55, 65, 81), (59, 130, 246), (31, 41, 55), (255, 255, 255)), "phone"),
        (8, "Lamborghini Huracán", "Lamborghini", "Automotive & Luxury",
         ((24, 24, 27), (69, 10, 10), (239, 68, 68), (39, 39, 42), (255, 255, 255)), "auto"),
        (9, "Acharya Institute Lanyard", "Acharya Institutes", "Office & School Supplies",
         ((12, 74, 110), (3, 105, 161), (245, 158, 11), (15, 23, 42), (255, 255, 255)), "lanyard"),
        (10, "Silver Oxidized Jhumka Earrings with Clear Stones", "Unknown", "Jewelry & Accessories",
         ((30, 27, 75), (88, 28, 135), (192, 132, 252), (46, 16, 101), (255, 255, 255)), "jewelry"),
        (11, "Giant Brain Sculpture", "Unknown", "Art & Decor",
         ((41, 37, 36), (87, 83, 78), (217, 119, 6), (68, 64, 60), (255, 255, 255)), "sculpture"),
        (12, "Oxidized Silver Jhumka Earrings with CZ and Pearls", "Unknown", "Jewelry & Accessories",
         ((15, 23, 42), (76, 29, 149), (168, 85, 247), (30, 27, 75), (255, 255, 255)), "jewelry")
    ]

    for pid, title, brand, category, theme, icon_type in products_spec:
        img_rel_path = create_product_artwork(pid, title, brand, category, theme, icon_type)
        cursor.execute("UPDATE products SET image_path = ?, product_name = ? WHERE id = ?", (img_rel_path, title, pid))
        print(f"Product #{pid} '{title}' linked to image: {img_rel_path}")

    conn.commit()
    conn.close()
    print("All product images generated and database updated successfully!")


if __name__ == "__main__":
    populate_all_images()
