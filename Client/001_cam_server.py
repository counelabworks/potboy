"""
Camera Server - Runs on Raspberry Pi

Features:
1. HTTP endpoint to trigger capture (for QR code scanning)
2. Optional face detection auto-capture
3. Sends image to server, receives receipt, prints it

Usage:
    python 001_cam_server.py                 # HTTP trigger only
    python 001_cam_server.py --face-detect   # Also enable face detection
"""

from escpos.printer import File
import cv2
import time
import asyncio
import websockets
import base64
import os
from datetime import datetime
from flask import Flask, jsonify
import threading

# ==============================
# CONFIG
# ==============================
PRINTER_DEVICE = "/dev/usb/lp0"

CAMERA_INDEX = 0
CAPTURE_DELAY = 5  # seconds for face detection mode

IMAGE_PATH = "capture.jpg"
RECEIPT_PATH = "received_images/receipt.jpg"
OUTPUT_FOLDER = "output"

FACE_CASCADE_PATH = "haarcascade_frontalface_default.xml"

WS_SERVER = "ws://192.168.0.116:8765"  # Change to your server IP
HTTP_PORT = 5001  # Port for receiving trigger commands

# ==============================
# GLOBAL STATE
# ==============================
capture_triggered = False
cap = None  # Camera object

app = Flask(__name__)

# ==============================
# PRINT FUNCTION
# ==============================
def print_image(image_path):
    """Print image to thermal printer."""
    try:
        p = File(PRINTER_DEVICE)
        p._raw(b'\x1B\x40')  # reset
        p.image(
            image_path,
            impl="bitImageRaster",
            high_density_vertical=True,
            high_density_horizontal=True,
            center=True
        )
        p.text("\n\n")
        p.cut()
        p.close()
        print("🖨️ Printed successfully")
        return True
    except Exception as e:
        print(f"❌ Print error: {e}")
        return False

# ==============================
# WEBSOCKET IMAGE SEND
# ==============================
async def ws_send_image(image_path):
    """Send image to server and receive receipt."""
    async with websockets.connect(WS_SERVER, max_size=10_000_000) as ws:
        print("🌐 Connected to WebSocket server")

        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read())

        await ws.send(encoded)
        print("📤 Image sent")

        response = await ws.recv()
        receipt_bytes = base64.b64decode(response)

        # Save to output folder
        os.makedirs(OUTPUT_FOLDER, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        receipt_path = f"{OUTPUT_FOLDER}/receipt_{timestamp}.png"
        
        with open(receipt_path, "wb") as f:
            f.write(receipt_bytes)

        print(f"📥 Receipt received: {receipt_path}")
        return receipt_path

def send_image_to_server(image_path):
    """Wrapper to run async function."""
    return asyncio.run(ws_send_image(image_path))

# ==============================
# CAPTURE FUNCTION
# ==============================
def do_capture():
    """Capture image, send to server, print receipt."""
    global cap
    
    if cap is None or not cap.isOpened():
        print("❌ Camera not available")
        return False
    
    # Capture frame
    ret, frame = cap.read()
    if not ret:
        print("❌ Failed to capture frame")
        return False
    
    # Save image
    cv2.imwrite(IMAGE_PATH, frame)
    print(f"📸 Image captured: {IMAGE_PATH}")
    
    try:
        # Send to server and get receipt
        print("🌐 Sending image to server...")
        receipt_path = send_image_to_server(IMAGE_PATH)
        
        # Print receipt
        print("🖨️ Printing receipt...")
        print_image(receipt_path)
        
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

# ==============================
# HTTP ENDPOINTS
# ==============================
@app.route('/health', methods=['GET'])
def health():
    """Health check."""
    return jsonify({'status': 'ok', 'camera': cap is not None and cap.isOpened()})

@app.route('/capture', methods=['POST', 'GET'])
def trigger_capture():
    """Trigger a capture."""
    global capture_triggered
    
    print("\n📱 Capture triggered via HTTP!")
    
    if capture_triggered:
        return jsonify({'success': False, 'error': 'Capture already in progress'}), 429
    
    capture_triggered = True
    
    try:
        success = do_capture()
        if success:
            return jsonify({'success': True, 'message': 'Captured and printed!'})
        else:
            return jsonify({'success': False, 'error': 'Capture failed'}), 500
    finally:
        capture_triggered = False

# ==============================
# FACE DETECTION LOOP
# ==============================
def face_detection_loop(face_cascade):
    """Run face detection in background."""
    global capture_triggered, cap
    
    detected_time = None
    
    print("👀 Face detection running...")
    
    while True:
        if capture_triggered:
            time.sleep(0.1)
            continue
        
        if cap is None or not cap.isOpened():
            time.sleep(0.5)
            continue
        
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            continue
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.3,
            minNeighbors=5,
            minSize=(80, 80)
        )
        
        if len(faces) > 0:
            if detected_time is None:
                detected_time = time.time()
                print("🙂 Person detected — countdown started")
            
            elapsed = time.time() - detected_time
            if elapsed >= CAPTURE_DELAY and not capture_triggered:
                print("⏰ Auto-capture triggered!")
                capture_triggered = True
                do_capture()
                capture_triggered = False
                detected_time = None
                time.sleep(3)  # Cooldown
        else:
            detected_time = None
        
        time.sleep(0.1)

# ==============================
# MAIN
# ==============================
def main():
    global cap, WS_SERVER
    
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--face-detect', action='store_true', help='Enable face detection')
    parser.add_argument('--server', type=str, default=WS_SERVER, help='WebSocket server URL')
    parser.add_argument('--port', type=int, default=HTTP_PORT, help='HTTP port')
    args = parser.parse_args()
    
    WS_SERVER = args.server
    
    print("=" * 50)
    print("📷 RASPBERRY PI CAMERA SERVER")
    print("=" * 50)
    print(f"WebSocket server: {WS_SERVER}")
    print(f"HTTP trigger port: {args.port}")
    print(f"Face detection: {'ON' if args.face_detect else 'OFF'}")
    print("=" * 50)
    
    # Initialize camera
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print("❌ Cannot open camera!")
        return
    print("📷 Camera opened")
    
    # Start face detection thread if enabled
    if args.face_detect:
        if os.path.exists(FACE_CASCADE_PATH):
            face_cascade = cv2.CascadeClassifier(FACE_CASCADE_PATH)
            face_thread = threading.Thread(target=face_detection_loop, args=(face_cascade,), daemon=True)
            face_thread.start()
        else:
            print(f"⚠️ Face cascade not found: {FACE_CASCADE_PATH}")
    
    # Get local IP
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        local_ip = "localhost"
    
    print(f"\n🌐 HTTP endpoint: http://{local_ip}:{args.port}/capture")
    print("\n📱 Create a QR code with: CAPTURE")
    print("   Scan it to trigger capture!\n")
    print("=" * 50)
    print("Waiting for triggers...\n")
    
    # Run Flask server
    app.run(host='0.0.0.0', port=args.port, debug=False)
    
    cap.release()

# ==============================
# START
# ==============================
if __name__ == "__main__":
    main()
