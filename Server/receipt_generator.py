from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import io

def make_receipt(photo_bytes):
    # Load photo from bytes
    photo = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    photo = photo.resize((480, 360))

    # Create receipt - compact layout
    receipt = Image.new("RGB", (540, 580), "white")
    draw = ImageDraw.Draw(receipt)

    try:
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 36)
        font_text = ImageFont.truetype("DejaVuSans.ttf", 24)
    except:
        font_title = font_text = ImageFont.load_default()

    # Title at top
    draw.text((120, 20), "Fortune Teller", fill="black", font=font_title)

    # Photo below title
    receipt.paste(photo, (30, 70))

    # Text below photo
    y = 450
    line_height = 35
    data = [
        ("Name", "hehe"),
        ("ID", "USR-2026-001"),
        ("Date", datetime.now().strftime("%d %b %Y %H:%M")),
    ]

    for k, v in data:
        draw.text((30, y), f"{k}:", fill="black", font=font_text)
        draw.text((150, y), v, fill="black", font=font_text)
        y += line_height

    # Line and thank you
    draw.line((30, y + 5, 510, y + 5), fill="black", width=1)
    draw.text((200, y + 15), "Thank you!", fill="black", font=font_text)

    # Convert receipt to bytes
    buf = io.BytesIO()
    receipt.save(buf, format="JPEG", quality=90)
    return buf.getvalue()
