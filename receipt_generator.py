from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import io

def make_receipt(photo_bytes):
    # Load photo from bytes
    photo = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    photo = photo.resize((320, 240))

    # Create receipt
    receipt = Image.new("RGB", (400, 700), "white")
    draw = ImageDraw.Draw(receipt)

    receipt.paste(photo, (40, 80))

    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 28)
        font_text = ImageFont.truetype("DejaVuSans.ttf", 18)
    except:
        font_title = font_text = ImageFont.load_default()

    draw.text((90, 20), "Fortune Teller", fill="black", font=font_title)

    y = 360
    line_height = 28
    data = [
        ("Name", "hehe"),
        ("ID", "USR-2026-001"),
        ("Date", datetime.now().strftime("%d %b %Y %H:%M")),
    ]

    for k, v in data:
        draw.text((20, y), f"{k}:", fill="black", font=font_text)
        draw.text((150, y), v, fill="black", font=font_text)
        y += line_height

    draw.line((20, y + 10, 380, y + 10), fill="black", width=1)
    draw.text((20, y + 30), "Thank you!", fill="black", font=font_text)

    # Convert receipt to bytes
    buf = io.BytesIO()
    receipt.save(buf, format="JPEG", quality=90)
    return buf.getvalue()
