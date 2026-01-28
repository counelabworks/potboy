  GNU nano 8.4                                                                                                                                                                print_receipt.py
from escpos.printer import File
import sys

# ==========================================
# CONFIGURATION
# ==========================================

# Your printer is detected as USB Line Printer at /dev/usb/lp0
PRINTER_DEVICE = '/dev/usb/lp0'

# ==========================================


def print_receipt():
    """
    Sends a receipt to the thermal printer using python-escpos.
    """
    try:
        # Connect to the printer via file device
        p = File(PRINTER_DEVICE)

        # Initialize printer
        p._raw(b'\x1B\x40')  # ESC @ - Initialize

        # Header - Centered and Bold
        p.set(align='center', bold=True)
        p.text("TEST RECEIPT\n")
        p.text("STORE NAME\n")
        p.set(bold=False)
        p.text("\n")

        # Body - Left aligned
        p.set(align='left')
        p.text("Item 1              $10.00\n")
        p.text("Item 2              $20.00\n")
        p.text("--------------------------\n")

        # Footer - Centered
        p.set(align='center', bold=True)
        p.text("TOTAL: $30.00\n")
        p.set(bold=False)
        p.text("\n")
        p.text("Thank you for shopping!\n")
        p.text("\n\n\n")

        # Cut paper
        p.cut()

        # Close connection
        p.close()

        print(f"Successfully printed receipt to {PRINTER_DEVICE}!")

    except Exception as e:
        print(f"Error printing receipt:")
        print(e)
        print("\nTroubleshooting:")
        print("1. Check if device exists: ls -la /dev/usb/lp0")
        print("2. Add permissions: sudo usermod -a -G lp $USER && sudo reboot")
        print("3. Try running with sudo: sudo python3 print_receipt.py")


if __name__ == "__main__":
    print(f"Attempting to print to {PRINTER_DEVICE}...")
    print_receipt()