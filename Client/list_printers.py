import win32print


def list_printers():
    """
    Lists all installed printers on the Windows system.
    """
    try:
        # PRINTER_ENUM_LOCAL: Enumerates local printers.
        # PRINTER_ENUM_CONNECTIONS: Enumerates network connections.
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        printers = win32print.EnumPrinters(flags)

        print(f"Found {len(printers)} printers:")
        print("-" * 40)
        for printer in printers:
            # printer structure: (flags, description, name, comment)
            # We usually just want the name (index 2)
            printer_name = printer[2]
            print(f" - {printer_name}")
        print("-" * 40)
        print("\nUse the exact name above in your print scripts.")
        print("\nTo test printing, run:")
        print('  python print_receipt.py "PRINTER_NAME"')
        print('  python print_image.py "PRINTER_NAME" "image.jpg"')

    except Exception as e:
        print(f"Error listing printers: {e}")


if __name__ == "__main__":
    # Redirect output to file to ensure we capture it
    import sys
    original_stdout = sys.stdout
    with open("printers_list.txt", "w", encoding="utf-8") as f:
        sys.stdout = f
        list_printers()
        sys.stdout = original_stdout

    # Also print to console
    list_printers()
