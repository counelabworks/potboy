from escpos.printer import Win32Raw
import sys

# ==========================================
# CONFIGURATION
# ==========================================
PRINTER_NAME = "POS-80"
IMAGE_PATH = "image.jpg"
MAX_WIDTH = 550  # Max dots for 80mm printer (usually 576, keeping safety margin)
# ==========================================


def print_image(printer_name, image_path):
    """
    Prints an image to the specified Windows thermal printer using python-escpos.
    """
    try:
        # Connect to the Windows printer
        p = Win32Raw(printer_name)

        # Initialize printer
        p._raw(b'\x1B\x40')  # ESC @ - Initialize

        # Center align the image
        p.set(align='center')

        # Print the image - escpos handles all the conversion automatically!
        # impl parameter can be: 'bitImageRaster', 'graphics', or 'bitImageColumn'
        # Try 'bitImageRaster' first, if it doesn't work try 'graphics'
        p.image(image_path, impl='bitImageRaster', high_density_vertical=True, high_density_horizontal=True)

        # Reset alignment
        p.set(align='left')

        # Feed and cut
        p.text("\n\n\n")
        p.cut()

        # Close connection
        p.close()

        print(f"Successfully sent image to printer: {printer_name}")

    except Exception as e:
        print(f"Error printing image to {printer_name}:")
        print(e)
        print("\nTroubleshooting:")
        print("1. Make sure the printer is turned on and connected.")
        print("2. Check if the image file exists:", image_path)
        print("3. Ensure you have 'python-escpos' and 'pillow' installed.")
        print("4. Try different 'impl' values: 'bitImageRaster', 'graphics', 'bitImageColumn'")


if __name__ == "__main__":
    # Allow passing printer name and image as arguments
    target_printer = sys.argv[1] if len(sys.argv) > 1 else PRINTER_NAME
    target_image = sys.argv[2] if len(sys.argv) > 2 else IMAGE_PATH

    print(f"Attempting to print image to: {target_printer}")
    print(f"Image: {target_image}")
    print_image(target_printer, target_image)
