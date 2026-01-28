"""
Camera Server - Raspberry Pi with Face Detection

Features:
1. HTTP endpoint to trigger capture (QR code scan)
2. Capture only if a face is detected
3. Draw bounding boxes around faces on the image
4. Send image to WebSocket server, receive receipt, print
5. Auto-reconnect if WebSocket fails
6. Cooldown between captures
7. Open/close camera per capture to ensure fresh frame
"""

from escpos.printer import File
import cv2
import time
import asyncio
import websockets
import base64
import os
from datetime import datetime
from flask import Flask, jsonify, request
import socket
import argparse

# ==============================
# CONFIG
# ==============================
PRINTER_DEVICE = "/dev/usb/lp0"
CAMERA_INDEX = 0
CAPTURE_COOLDOWN = 5  # seconds cooldown between captures
FLUSH_FRAMES = 3       # optional flush before capture

IMAGE_PATH = "capture.jpg"
OUTPUT_FOLDER = "output"

FACE_CASCADE_PATH = "haarcascade_frontalface_default.xml"  # must be in same folder or full path

HTTP_PORT = 5001  # HTTP trigger port

# WebSocket reconnect config
WS_TIMEOUT = 5        # seconds per attempt
WS_RETRY_DELAY = 3    # seconds between retries
WS_MAX_RETRIES = 5    # None for infinite retries

# ==============================
# GLOBAL STATE
# ==============================
capture_triggered = False
last_capture_time = 0  # Timestamp of last capture

app = Flask(__name__)

# Load face cascade
if not os.path.exists(FACE_CASCADE_PATH):
    raise FileNotFoundError(f"{FACE_CASCADE_PATH} not found!")
face_cascade = cv2.CascadeClassifier(FACE_CASCADE_PATH)

# ==============================
# PRINT FUNCTION
# ==============================
def print_image(image_path):
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
async def ws_send_image(image_path, ws_server):
    attempt = 0
    while True:
        try:
            print(f"🌐 Connecting to WebSocket (attempt {attempt + 1})...")
            async with websockets.connect(
                ws_server,
                max_size=10_000_000,
                open_timeout=WS_TIMEOUT,
                close_timeout=WS_TIMEOUT
            ) as ws:

                print("✅ Connected to WebSocket server")
                with open(image_path, "rb") as f:
                    encoded = base64.b64encode(f.read())
                await ws.send(encoded)
                print("📤 Image sent")

                response = await ws.recv()
                receipt_bytes = base64.b64decode(response)

                # Save receipt
                os.makedirs(OUTPUT_FOLDER, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                receipt_path = f"{OUTPUT_FOLDER}/receipt_{timestamp}.png"
                with open(receipt_path, "wb") as f:
                    f.write(receipt_bytes)

                print(f"📥 Receipt received: {receipt_path}")
                return receipt_path

        except (OSError, asyncio.TimeoutError, websockets.exceptions.WebSocketException) as e:
            attempt += 1
            print(f"⚠️ WebSocket error: {e}")
            if WS_MAX_RETRIES is not None and attempt >= WS_MAX_RETRIES:
                print("❌ Max retries reached, giving up")
                return None
            print(f"🔁 Retrying in {WS_RETRY_DELAY}s...")
            await asyncio.sleep(WS_RETRY_DELAY)

def send_image_to_server(image_path, ws_server):
    return asyncio.run(ws_send_image(image_path, ws_server))

# ==============================
# CAPTURE FUNCTION WITH FACE DETECTION
# ==============================
def do_capture(ws_server):
    """Open camera, detect faces, capture image with bounding boxes, send to server, print, release camera."""
    global FLUSH_FRAMES, face_cascade

    # Open camera
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print("❌ Cannot open camera!")
        return False

    # Flush frames
    for _ in range(FLUSH_FRAMES):
        cap.read()
        time.sleep(0.05)

    ret, frame = cap.read()
    if not ret:
        print("❌ Failed to capture frame")
        cap.release()
        return False

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)

    if len(faces) == 0:
        print("⚠️ No faces detected, skipping capture")
        cap.release()
        return False

    # Draw bounding boxes
    for (x, y, w, h) in faces:
        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)

    cv2.imwrite(IMAGE_PATH, frame)
    print(f"📸 Image captured with {len(faces)} face(s): {IMAGE_PATH}")

    cap.release()
    print("🔌 Camera released")

    try:
        print("🌐 Sending image to server...")
        receipt_path = send_image_to_server(IMAGE_PATH, ws_server)
        if receipt_path:
            print("🖨️ Printing receipt...")
            print_image(receipt_path)
            return True
        else:
            print("❌ Failed to receive receipt from server")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

# ==============================
# HTTP ENDPOINTS
# ==============================
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

@app.route('/capture', methods=['POST', 'GET'])
def trigger_capture():
    global capture_triggered, last_capture_time

    qr_code = request.args.get('qr', 'manual')
    print(f"\n📱 Capture triggered: {qr_code}")

    if capture_triggered:
        return jsonify({'success': False, 'error': 'Capture already in progress'}), 429

    # Check cooldown
    time_since_last = time.time() - last_capture_time
    if time_since_last < CAPTURE_COOLDOWN:
        remaining = int(CAPTURE_COOLDOWN - time_since_last)
        return jsonify({
            'success': False,
            'error': f'Cooldown active. Wait {remaining}s'
        }), 429

    capture_triggered = True
    try:
        success = do_capture(app.config['WS_SERVER'])
        if success:
            last_capture_time = time.time()
            return jsonify({'success': True, 'message': 'Captured and printed!'})
        else:
            return jsonify({'success': False, 'error': 'No faces detected or capture failed'}), 500
    finally:
        capture_triggered = False

# ==============================
# MAIN
# ==============================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', type=str, default='ws://192.168.0.116:8765', help='WebSocket server URL')
    parser.add_argument('--port', type=int, default=HTTP_PORT, help='HTTP port')
    args = parser.parse_args()

    app.config['WS_SERVER'] = args.server

    print("=" * 50)
    print("📷 RASPBERRY PI CAMERA SERVER WITH FACE DETECTION")
    print("=" * 50)
    print(f"WebSocket server: {args.server}")
    print(f"HTTP trigger port: {args.port}")
    print(f"Capture cooldown: {CAPTURE_COOLDOWN}s")
    print("=" * 50)

    # Determine local IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except:
        local_ip = "localhost"

    print(f"\n🌐 HTTP endpoint: http://{local_ip}:{args.port}/capture")
    print("📱 Scan QR code to trigger capture!")
    print("=" * 50)
    print("Waiting for triggers...\n")

    # Start Flask server
    app.run(host='0.0.0.0', port=args.port, debug=False)

# ==============================
# START
# ==============================
if __name__ == "__main__":
    main()
















