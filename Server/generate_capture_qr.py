"""
Generate a single QR code for triggering capture.
"""

import qrcode
from PIL import Image, ImageDraw, ImageFont
import os

def generate_capture_qr():
    # Create QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=15,
        border=2,
    )
    qr.add_data("CAPTURE")
    qr.make(fit=True)
    
    # Create QR image and convert to RGB
    qr_img = qr.make_image(fill_color="black", back_color="white").convert('RGB')
    qr_size = qr_img.size[0]
    
    # Add label
    label_height = 60
    final_img = Image.new('RGB', (qr_size, qr_size + label_height), 'white')
    final_img.paste(qr_img, (0, 0, qr_size, qr_size))
    
    # Draw label
    draw = ImageDraw.Draw(final_img)
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except:
        font = ImageFont.load_default()
    
    text = "CAPTURE"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    x = (qr_size - text_width) // 2
    draw.text((x, qr_size + 15), text, fill="black", font=font)
    
    # Save
    output_path = "capture_qr.png"
    final_img.save(output_path)
    print(f"✅ QR code saved: {output_path}")
    print(f"\n📱 Scan this QR code to trigger capture on Raspberry Pi")
    
    return output_path

if __name__ == "__main__":
    generate_capture_qr()
