"""
QR Code Generator - Creates QR codes for all images in received_images folder

Usage:
    python generate_qr_codes.py

This will create a 'qr_codes' folder with:
- Individual QR code images for each photo
- A printable sheet (qr_sheet.png) with all QR codes
"""

import os
import qrcode
from PIL import Image, ImageDraw, ImageFont

# ==========================================
# CONFIGURATION
# ==========================================

# Source folder with images
IMAGE_FOLDER = "received_images"

# Output folder for QR codes
QR_OUTPUT_FOLDER = "qr_codes"

# QR code size in pixels
QR_SIZE = 300

# ==========================================


def generate_qr_code(content, filename, output_folder):
    """Generate a QR code image for the given content."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(content)
    qr.make(fit=True)
    
    # Create QR image
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_img = qr_img.resize((QR_SIZE, QR_SIZE), Image.LANCZOS)
    
    # Add label below QR code
    label_height = 40
    final_img = Image.new('RGB', (QR_SIZE, QR_SIZE + label_height), 'white')
    final_img.paste(qr_img, (0, 0))
    
    # Draw label
    draw = ImageDraw.Draw(final_img)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except:
        font = ImageFont.load_default()
    
    # Center the text
    text = content[:30] + "..." if len(content) > 30 else content
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    x = (QR_SIZE - text_width) // 2
    draw.text((x, QR_SIZE + 10), text, fill="black", font=font)
    
    # Save
    output_path = os.path.join(output_folder, f"qr_{filename}.png")
    final_img.save(output_path)
    return output_path


def create_qr_sheet(qr_images, output_folder):
    """Create a printable sheet with all QR codes."""
    if not qr_images:
        return None
    
    # Calculate grid size
    cols = 4
    rows = (len(qr_images) + cols - 1) // cols
    
    cell_width = QR_SIZE + 20
    cell_height = QR_SIZE + 60
    
    sheet_width = cols * cell_width + 40
    sheet_height = rows * cell_height + 40
    
    sheet = Image.new('RGB', (sheet_width, sheet_height), 'white')
    
    for i, (qr_path, label) in enumerate(qr_images):
        row = i // cols
        col = i % cols
        
        x = 20 + col * cell_width
        y = 20 + row * cell_height
        
        qr_img = Image.open(qr_path)
        sheet.paste(qr_img, (x, y))
    
    sheet_path = os.path.join(output_folder, "qr_sheet.png")
    sheet.save(sheet_path)
    return sheet_path


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    image_folder = os.path.join(script_dir, IMAGE_FOLDER)
    output_folder = os.path.join(script_dir, QR_OUTPUT_FOLDER)
    
    # Create output folder
    os.makedirs(output_folder, exist_ok=True)
    
    # Get all images
    if not os.path.exists(image_folder):
        print(f"Image folder not found: {image_folder}")
        return
    
    images = [f for f in os.listdir(image_folder) 
              if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp'))]
    images.sort()
    
    if not images:
        print("No images found in received_images folder")
        return
    
    print(f"Found {len(images)} images")
    print(f"Generating QR codes...\n")
    
    qr_images = []
    
    for img_name in images:
        # QR code contains just the filename
        qr_path = generate_qr_code(img_name, img_name, output_folder)
        qr_images.append((qr_path, img_name))
        print(f"  ✅ {img_name} -> qr_{img_name}.png")
    
    # Create printable sheet
    print(f"\nCreating printable sheet...")
    sheet_path = create_qr_sheet(qr_images, output_folder)
    
    print(f"\n{'='*50}")
    print(f"✅ Generated {len(qr_images)} QR codes")
    print(f"📁 Output folder: {output_folder}")
    if sheet_path:
        print(f"📄 Printable sheet: {sheet_path}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
