"""
Camera Server - Raspberry Pi with Face Detection + LED/Buzzer (gpiozero)

Features:
1. HTTP endpoint to trigger capture (QR code scan)
2. Capture only if a face is detected
3. Draw bounding boxes around faces on the image
4. Send image to WebSocket server, receive receipt, print
5. Auto-reconnect if WebSocket fails
6. Cooldown between captures
7. Open/close camera per capture to ensure fresh frame
8. LED (GPIO24) + Buzzer (GPIO23) status indicators
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
import threading

# ✅ gpiozero (NEW)
from gpiozero import LED, Buzzer

# ==============================
# CONFIG
# ==============================
PRINTER_DEVICE = "/dev/usb/lp0"
CAMERA_INDEX = 0
CAPTURE_COOLDOWN = 5
FLUSH_FRAMES = 3

IMAGE_PATH = "capture.jpg"
OUTPUT_FOLDER = "output"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FACE_CASCADE_PATH = os.path.join(BASE_DIR, "haarcascade_frontalface_default.xml")

HTTP_PORT = 5001

WS_TIMEOUT = 5
WS_RETRY_DELAY = 3
WS_MAX_RETRIES = None  # None = infinite retries

LED_PIN = 24
BUZZER_PIN = 23

# ==============================
# GLOBAL STATE
# ==============================
capture_triggered = False
last_capture_time = 0

led_buzzer_thread = None
led_buzzer_stop = threading.Event()

app = Flask(__name__)

# ==============================
# GPIOZERO SETUP
# ==============================
led = LED(LED_PIN)
buzzer = Buzzer(BUZZER_PIN)

led.off()
buzzer.off()

# ==============================
# LED & BUZZER CONTROL
# ==============================
def led_buzzer_blink(blink_interval=0.5):
    while not led_buzzer_stop.is_set():
        led.on()
        buzzer.on()
        time.sleep(blink_interval)
        led.off()
        buzzer.off()
        time.sleep(blink_interval)

def start_blinking(blink_interval=0.5):
    global led_buzzer_thread
    led_buzzer_stop.clear()
    led_buzzer_thread = threading.Thread(
        target=led_buzzer_blink,
        args=(blink_interval,),
        daemon=True
    )
    led_buzzer_thread.start()

def stop_blinking():
    led_buzzer_stop.set()
    if led_buzzer_thread and led_buzzer_thread.is_alive():
        led_buzzer_thread.join()
    led.off()
    buzzer.off()

# ==============================
# LOAD FACE CASCADE
# ==============================
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
# WEBSOCKET SEND
# ==============================
async def ws_send_image(image_path, ws_server):
    attempt = 0
    while True:
        try:
            print(f"🌐 WebSocket connect attempt {attempt + 1}")
            async with websockets.connect(
                ws_server,
                max_size=10_000_000,
                open_timeout=WS_TIMEOUT,
                close_timeout=WS_TIMEOUT
            ) as ws:

                with open(image_path, "rb") as f:
                    encoded = base64.b64encode(f.read())

                await ws.send(encoded)
                print("📤 Image sent")

                response = await ws.recv()
                receipt_bytes = base64.b64decode(response)

                os.makedirs(OUTPUT_FOLDER, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                receipt_path = f"{OUTPUT_FOLDER}/receipt_{ts}.png"

                with open(receipt_path, "wb") as f:
                    f.write(receipt_bytes)

                print(f"📥 Receipt saved: {receipt_path}")
                return receipt_path

        except Exception as e:
            attempt += 1
            print(f"⚠️ WebSocket error: {e}")
            if WS_MAX_RETRIES and attempt >= WS_MAX_RETRIES:
                return None
            await asyncio.sleep(WS_RETRY_DELAY)

def send_image_to_server(image_path, ws_server):
    return asyncio.run(ws_send_image(image_path, ws_server))

# ==============================
# CAPTURE FUNCTION
# ==============================
def do_capture(ws_server):
    start_blinking(0.5)
    time.sleep(2)

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print("❌ Camera open failed")
        stop_blinking()
        start_blinking(0.1)
        time.sleep(2)
        stop_blinking()
        return False

    for _ in range(FLUSH_FRAMES):
        cap.read()
        time.sleep(0.05)

    ret, frame = cap.read()
    if not ret:
        cap.release()
        stop_blinking()
        return False

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, 1.1, 5)

    if len(faces) == 0:
        print("⚠️ No face detected")
        cap.release()
        stop_blinking()
        return False

    for (x, y, w, h) in faces:
        cv2.rectangle(frame, (x, y), (x+w, y+h), (255, 255, 255), 3)

    cv2.imwrite(IMAGE_PATH, frame)
    cap.release()
    stop_blinking()

    receipt = send_image_to_server(IMAGE_PATH, ws_server)
    if receipt:
        print_image(receipt)
        return True

    start_blinking(0.1)
    time.sleep(2)
    stop_blinking()
    return False

# ==============================
# HTTP ENDPOINTS
# ==============================
@app.route('/health')
def health():
    return jsonify({"status": "ok"})

@app.route('/capture', methods=['GET', 'POST'])
def capture():
    global capture_triggered, last_capture_time

    if capture_triggered:
        return jsonify({"error": "busy"}), 429

    if time.time() - last_capture_time < CAPTURE_COOLDOWN:
        return jsonify({"error": "cooldown"}), 429

    capture_triggered = True
    try:
        ok = do_capture(app.config['WS_SERVER'])
        if ok:
            last_capture_time = time.time()
            return jsonify({"success": True})
        return jsonify({"success": False}), 500
    finally:
        capture_triggered = False

# ==============================
# MAIN
# ==============================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', default='ws://172.20.10.2:8765')
    parser.add_argument('--port', type=int, default=HTTP_PORT)
    args = parser.parse_args()

    app.config['WS_SERVER'] = args.server

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except:
        ip = "localhost"

    print(f"🌐 http://{ip}:{args.port}/capture")
    app.run(host='0.0.0.0', port=args.port, debug=False)

# ==============================
# START
# ==============================
if __name__ == "__main__":
    main()
