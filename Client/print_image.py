from escpos.printer import File
import sys

# ==========================================
# CONFIGURATION
# ==========================================

# Your printer is detected as USB Line Printer at /dev/usb/lp0
PRINTER_DEVICE = '/dev/usb/lp0'

# Image settings
IMAGE_PATH = "image.jpg"

# Printer width in pixels (80mm = 576, 58mm = 384)
PRINTER_WIDTH = 576

# ==========================================


def print_image(image_path):
    """
    Prints an image to the thermal printer using python-escpos.
    """
    try:
        # Connect to the printer via file device
        p = File(PRINTER_DEVICE)

        # Initialize printer
        p._raw(b'\x1B\x40')  # ESC @ - Initialize

        # Print the image - escpos handles all the conversion automatically!
        # impl parameter can be: 'bitImageRaster', 'graphics', or 'bitImageColumn'
        # center=True will center based on PRINTER_WIDTH
        p.image(image_path, impl='bitImageRaster', high_density_vertical=True, high_density_horizontal=True, center=True)

        # Feed and cut
        p.text("\n\n\n")
        p.cut()

        # Close connection
        p.close()

        print(f"Successfully printed image to {PRINTER_DEVICE}!")

    except Exception as e:
        print(f"Error printing image:")
        print(e)
        print("\nTroubleshooting:")
        print("1. Check if device exists: ls -la /dev/usb/lp0")
        print("2. Add permissions: sudo usermod -a -G lp $USER && sudo reboot")
        print("3. Try running with sudo: sudo python3 print_image.py")
        print("4. Try different 'impl' values: 'bitImageRaster', 'graphics', 'bitImageColumn'")


if __name__ == "__main__":
    # Allow passing image path as argument
    target_image = sys.argv[1] if len(sys.argv) > 1 else IMAGE_PATH

    print(f"Attempting to print image to {PRINTER_DEVICE}...")
    print(f"Image: {target_image}")
    print_image(target_image)
