from escpos.printer import Win32Raw
import sys

# ==========================================
# CONFIGURATION
# ==========================================
# REPLACE THIS with the exact name of your printer from list_printers.py
PRINTER_NAME = "POS-80"
# ==========================================


def print_receipt(printer_name):
    """
    Sends a receipt to the specified Windows thermal printer using python-escpos.
    """
    try:
        # Connect to the Windows printer
        p = Win32Raw(printer_name)

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

        print(f"Successfully sent job to printer: {printer_name}")

    except Exception as e:
        print(f"Error printing to {printer_name}:")
        print(e)
        print("\nTroubleshooting:")
        print("1. Make sure the printer is turned on and connected.")
        print("2. Check if the PRINTER_NAME matches exactly what's in Windows Settings.")
        print("3. Ensure you have 'python-escpos' installed: pip install python-escpos")
        print("4. Try running as Administrator if you get permission errors.")


if __name__ == "__main__":
    # Allow passing printer name as argument, otherwise use default
    target_printer = sys.argv[1] if len(sys.argv) > 1 else PRINTER_NAME

    print(f"Attempting to print to: {target_printer}")
    print_receipt(target_printer)
