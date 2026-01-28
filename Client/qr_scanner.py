"""
QR Code Scanner - Triggers print_image.py when a QR code is scanned

This script supports two modes:
1. USB Scanner Mode (--usb): For USB barcode/QR scanners that act like keyboards
2. Camera Mode (--camera): For webcam-based QR code scanning

Usage:
    python qr_scanner.py --usb              # USB scanner mode (default)
    python qr_scanner.py --camera           # Camera mode
    python qr_scanner.py --camera --device 1  # Use specific camera device

QR Code Format:
    The QR code should contain:
    - A filename (e.g., "photo.jpg") - will look in IMAGE_FOLDER
    - A full path (e.g., "/path/to/image.jpg")
    - A URL (e.g., "http://example.com/image.jpg") - will download first
"""

import sys
import os
import subprocess
import time
import argparse
import tempfile
import urllib.request
from pathlib import Path

# ==========================================
# CONFIGURATION
# ==========================================

# Folder where images are stored (relative paths will look here)
IMAGE_FOLDER = "../Server/received_images"

# Path to print_image.py script
PRINT_SCRIPT = "print_image.py"

# Delay between prints (seconds) - prevents duplicate scans
SCAN_COOLDOWN = 3.0

# ==========================================


def find_image(qr_content):
    """
    Resolves QR code content to an image path.
    
    Handles:
    - Full paths (/path/to/image.jpg)
    - Filenames (image.jpg) - looks in IMAGE_FOLDER
    - URLs (http://...) - downloads to temp file
    """
    qr_content = qr_content.strip()
    
    # Check if it's a URL
    if qr_content.startswith(('http://', 'https://')):
        print(f"Downloading image from URL: {qr_content}")
        try:
            # Download to temp file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
            urllib.request.urlretrieve(qr_content, temp_file.name)
            return temp_file.name
        except Exception as e:
            print(f"Failed to download image: {e}")
            return None
    
    # Check if it's an absolute path
    if os.path.isabs(qr_content):
        if os.path.exists(qr_content):
            return qr_content
        print(f"Image not found at absolute path: {qr_content}")
        return None
    
    # Treat as filename, look in IMAGE_FOLDER
    script_dir = os.path.dirname(os.path.abspath(__file__))
    image_folder = os.path.join(script_dir, IMAGE_FOLDER)
    image_path = os.path.join(image_folder, qr_content)
    
    if os.path.exists(image_path):
        return image_path
    
    # Also check current directory
    if os.path.exists(qr_content):
        return os.path.abspath(qr_content)
    
    print(f"Image not found: {qr_content}")
    print(f"Searched in: {image_folder}")
    return None


def trigger_print(image_path):
    """Calls print_image.py with the given image path."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    print_script = os.path.join(script_dir, PRINT_SCRIPT)
    
    print(f"\n{'='*50}")
    print(f"PRINTING: {image_path}")
    print(f"{'='*50}\n")
    
    try:
        result = subprocess.run(
            [sys.executable, print_script, image_path],
            capture_output=True,
            text=True,
            cwd=script_dir
        )
        print(result.stdout)
        if result.stderr:
            print(f"Errors: {result.stderr}")
        return result.returncode == 0
    except Exception as e:
        print(f"Failed to run print script: {e}")
        return False


def usb_scanner_mode():
    """
    USB Scanner Mode - Reads input from USB barcode/QR scanner.
    
    USB scanners act like keyboards - they "type" the scanned content
    followed by Enter. This mode reads stdin and triggers prints.
    """
    print("="*60)
    print("USB QR SCANNER MODE")
    print("="*60)
    print("Waiting for QR code scans...")
    print("The scanner will type the QR content + Enter")
    print("Press Ctrl+C to exit")
    print("-"*60)
    
    last_scan_time = 0
    last_scan_content = ""
    
    try:
        while True:
            # Read line from scanner (blocks until Enter is pressed)
            scanned = input().strip()
            
            if not scanned:
                continue
            
            current_time = time.time()
            
            # Prevent duplicate scans
            if (scanned == last_scan_content and 
                current_time - last_scan_time < SCAN_COOLDOWN):
                print(f"Duplicate scan ignored (cooldown: {SCAN_COOLDOWN}s)")
                continue
            
            print(f"\n[SCANNED] {scanned}")
            
            # Find the image
            image_path = find_image(scanned)
            
            if image_path:
                trigger_print(image_path)
                last_scan_time = current_time
                last_scan_content = scanned
            
            print("\nWaiting for next scan...")
            
    except KeyboardInterrupt:
        print("\nExiting...")


def camera_scanner_mode(device=0):
    """
    Camera Mode - Uses webcam to scan QR codes.
    
    Requires: opencv-python, pyzbar
    Install: pip install opencv-python pyzbar
    """
    try:
        import cv2
        from pyzbar import pyzbar
    except ImportError as e:
        print("Camera mode requires additional packages.")
        print("Install them with:")
        print("  pip install opencv-python pyzbar")
        print("\nOn Linux, you may also need:")
        print("  sudo apt-get install libzbar0")
        sys.exit(1)
    
    print("="*60)
    print("CAMERA QR SCANNER MODE")
    print("="*60)
    print(f"Opening camera device: {device}")
    print("Point QR codes at the camera to scan")
    print("Press 'q' to quit")
    print("-"*60)
    
    cap = cv2.VideoCapture(device)
    
    if not cap.isOpened():
        print(f"Error: Could not open camera device {device}")
        print("Try a different device number with --device N")
        sys.exit(1)
    
    last_scan_time = 0
    last_scan_content = ""
    
    try:
        while True:
            ret, frame = cap.read()
            
            if not ret:
                print("Error reading from camera")
                break
            
            # Detect QR codes
            decoded_objects = pyzbar.decode(frame)
            
            for obj in decoded_objects:
                scanned = obj.data.decode('utf-8').strip()
                current_time = time.time()
                
                # Prevent duplicate scans
                if (scanned == last_scan_content and 
                    current_time - last_scan_time < SCAN_COOLDOWN):
                    continue
                
                print(f"\n[SCANNED] {scanned}")
                
                # Draw rectangle around QR code
                points = obj.polygon
                if len(points) == 4:
                    pts = [(p.x, p.y) for p in points]
                    for i in range(4):
                        cv2.line(frame, pts[i], pts[(i+1)%4], (0, 255, 0), 3)
                
                # Find and print the image
                image_path = find_image(scanned)
                
                if image_path:
                    trigger_print(image_path)
                    last_scan_time = current_time
                    last_scan_content = scanned
            
            # Display the frame
            cv2.imshow('QR Scanner - Press Q to quit', frame)
            
            # Check for quit key
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
                
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(
        description='QR Code Scanner - Triggers image printing on scan',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python qr_scanner.py --usb              # USB scanner mode
  python qr_scanner.py --camera           # Camera mode (default camera)
  python qr_scanner.py --camera --device 1  # Use camera device 1

QR Code Content:
  The QR code should contain one of:
  - A filename: "photo.jpg" (looks in received_images folder)
  - A full path: "/home/user/images/photo.jpg"
  - A URL: "http://example.com/image.jpg"
        """
    )
    
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument('--usb', action='store_true', 
                           help='USB scanner mode (reads keyboard input)')
    mode_group.add_argument('--camera', action='store_true',
                           help='Camera mode (uses webcam)')
    
    parser.add_argument('--device', type=int, default=0,
                       help='Camera device number (default: 0)')
    
    args = parser.parse_args()
    
    # Default to USB mode if neither specified
    if args.camera:
        camera_scanner_mode(args.device)
    else:
        usb_scanner_mode()


if __name__ == "__main__":
    main()
