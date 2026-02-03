"""
Camera Server - Raspberry Pi with Face Detection + Live Preview

Uses pure OpenCV for camera capture and face detection.

Features:
1. HTTP endpoint to trigger capture (QR code scan)
2. Live preview with face detection (--preview flag)
3. Capture only if a face is detected
4. Draw bounding boxes around faces on the image
5. Send image to WebSocket server, receive receipt, print
6. Auto-reconnect if WebSocket fails
7. Cooldown between captures
8. LED (GPIO24) + Buzzer (GPIO23) status indicators (optional)

Usage:
    python 007_arducam_qr_system.py
    python 007_arducam_qr_system.py --preview
    python 007_arducam_qr_system.py --server ws://192.168.0.116:8765 --preview

Requirements:
    pip install flask websockets python-escpos pillow opencv-python
"""

import os
import subprocess

# Check if display is available BEFORE importing cv2
DISPLAY_AVAILABLE = False
if os.environ.get('DISPLAY'):
    try:
        result = subprocess.run(['xdpyinfo'], capture_output=True, timeout=2)
        DISPLAY_AVAILABLE = (result.returncode == 0)
    except:
        pass

# Set Qt to offscreen if no display (prevents crash)
if not DISPLAY_AVAILABLE:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from escpos.printer import File
import cv2
import time
import asyncio
import websockets
import base64
from datetime import datetime
from flask import Flask, jsonify, request
import socket
import argparse
import threading

# ==============================
# CONFIG (edit these directly)
# ==============================
PRINTER_DEVICE = '/dev/usb/lp0'
CAMERA_INDEX = 0
CAPTURE_COOLDOWN = 5
FLUSH_FRAMES = 3

IMAGE_PATH = "capture.jpg"
OUTPUT_FOLDER = "output"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FACE_CASCADE_PATH = os.path.join(BASE_DIR, "haarcascade_frontalface_default.xml")

HTTP_PORT = 5001
WS_SERVER_DEFAULT = 'ws://172.20.10.2:8765'

WS_TIMEOUT = 5
WS_RETRY_DELAY = 3
WS_MAX_RETRIES = None  # None = infinite retries

LED_PIN = 24
BUZZER_PIN = 23

# Camera resolution
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720

# ==============================
# GLOBAL STATE
# ==============================
capture_triggered = False
last_capture_time = 0
preview_running = False
preview_frame = None
preview_lock = threading.Lock()

led_buzzer_thread = None
led_buzzer_stop = threading.Event()

app = Flask(__name__)

# ==============================
# GPIOZERO SETUP (Optional)
# ==============================
led = None
buzzer = None
GPIO_ENABLED = False

try:
    from gpiozero import LED, Buzzer
    led = LED(LED_PIN)
    buzzer = Buzzer(BUZZER_PIN)
    led.off()
    buzzer.off()
    GPIO_ENABLED = True
    print("✅ GPIO enabled (LED + Buzzer)")
except Exception as e:
    print(f"⚠️ GPIO disabled: {e}")

# ==============================
# LED & BUZZER CONTROL
# ==============================
def led_buzzer_blink(blink_interval=0.5):
    if not GPIO_ENABLED:
        return
    while not led_buzzer_stop.is_set():
        led.on()
        buzzer.on()
        time.sleep(blink_interval)
        led.off()
        buzzer.off()
        time.sleep(blink_interval)

def start_blinking(blink_interval=0.5):
    if not GPIO_ENABLED:
        return
    global led_buzzer_thread
    led_buzzer_stop.clear()
    led_buzzer_thread = threading.Thread(
        target=led_buzzer_blink,
        args=(blink_interval,),
        daemon=True
    )
    led_buzzer_thread.start()

def stop_blinking():
    if not GPIO_ENABLED:
        return
    led_buzzer_stop.set()
    if led_buzzer_thread and led_buzzer_thread.is_alive():
        led_buzzer_thread.join()
    led.off()
    buzzer.off()

def countdown_beep_async(seconds=5):
    """Countdown with beeps (runs in background)."""
    def beep_thread():
        print(f"⏱️ Countdown: {seconds} seconds...")
        for i in range(seconds, 0, -1):
            print(f"   {i}...")
            if GPIO_ENABLED:
                led.on()
                buzzer.on()
                time.sleep(0.1)
                led.off()
                buzzer.off()
            time.sleep(0.9)
        
        print("   📸 CAPTURE!")
        if GPIO_ENABLED:
            led.on()
            buzzer.on()
            time.sleep(0.3)
            led.off()
            buzzer.off()
    
    t = threading.Thread(target=beep_thread, daemon=True)
    t.start()
    return t

# ==============================
# LOAD FACE CASCADE
# ==============================
face_cascade = None
if os.path.exists(FACE_CASCADE_PATH):
    face_cascade = cv2.CascadeClassifier(FACE_CASCADE_PATH)
    print("✅ Face detection enabled")
else:
    print(f"⚠️ Face cascade not found: {FACE_CASCADE_PATH}")
    print("   Face detection disabled")

# ==============================
# CHECK CAMERA TYPE
# ==============================
USE_RPICAM = False

def check_rpicam():
    """Check if rpicam-still is available (for libcamera/Arducam)."""
    try:
        result = subprocess.run(['rpicam-still', '--version'], 
                              capture_output=True, text=True, timeout=5)
        return result.returncode == 0 or 'rpicam-still' in result.stderr
    except:
        return False

def check_v4l2_camera():
    """Check if V4L2 camera (USB webcam) is available."""
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if cap.isOpened():
        ret, _ = cap.read()
        cap.release()
        return ret
    return False

# Detect camera type
if check_rpicam():
    USE_RPICAM = True
    print("✅ Camera: rpicam (libcamera/Arducam)")
elif check_v4l2_camera():
    USE_RPICAM = False
    print("✅ Camera: V4L2 (USB webcam)")
else:
    print("❌ No camera detected!")

def capture_with_rpicam(output_path, width=None, height=None, autofocus_time=5000):
    """Capture image using rpicam-still command."""
    try:
        cmd = [
            'rpicam-still',
            '-o', output_path,
            '-t', str(autofocus_time),
            '-n',  # No preview
            '--autofocus-mode', 'auto',  # Enable autofocus
        ]
        # Add resolution if specified
        if width and height:
            cmd.extend(['--width', str(width), '--height', str(height)])
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and os.path.exists(output_path):
            return True
        print(f"❌ rpicam-still error: {result.stderr}")
        return False
    except subprocess.TimeoutExpired:
        print("❌ rpicam-still timeout")
        return False
    except Exception as e:
        print(f"❌ rpicam-still error: {e}")
        return False

# ==============================
# PRINT FUNCTION
# ==============================
# Printer paper width in pixels (80mm = 576, 58mm = 384)
PRINTER_PAPER_WIDTH = 576  # Full paper width
PRINTER_IMAGE_WIDTH = 500  # Image width (smaller for margins)

def print_image(image_path):
    try:
        from PIL import Image
        
        print(f"🖨️ Attempting to print: {image_path}")
        
        # Check if file exists
        if not os.path.exists(image_path):
            print(f"❌ File not found: {image_path}")
            return False
        
        # Load and resize image for printer
        img = Image.open(image_path).convert('L')  # Convert to grayscale
        print(f"📐 Original size: {img.width}x{img.height}")
        
        # Resize to fit printer width
        if img.width > PRINTER_IMAGE_WIDTH:
            ratio = PRINTER_IMAGE_WIDTH / img.width
            new_height = int(img.height * ratio)
            img = img.resize((PRINTER_IMAGE_WIDTH, new_height), Image.LANCZOS)
        
        # Center the image by adding white padding on both sides
        padding_left = (PRINTER_PAPER_WIDTH - img.width) // 2
        centered_img = Image.new('L', (PRINTER_PAPER_WIDTH, img.height), 255)  # White background
        centered_img.paste(img, (padding_left, 0))
        
        # Save centered image
        resized_path = "/tmp/print_resized.bmp"
        centered_img.save(resized_path)
        print(f"📏 Centered: {img.width}x{img.height} on {PRINTER_PAPER_WIDTH}px paper")
        
        print(f"🖨️ Sending to printer...")
        
        p = File(PRINTER_DEVICE)
        p._raw(b'\x1B\x40')  # reset
        p.image(
            resized_path,
            impl="bitImageRaster",
            high_density_vertical=True,
            high_density_horizontal=True
        )
        p.text("\n\n\n")
        p.cut()
        p.close()
        print("🖨️ Print command sent!")
        return True
    except Exception as e:
        print(f"❌ Print error: {e}")
        import traceback
        traceback.print_exc()
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
    global preview_frame
    
    # Step 1: Quick face detection check (no countdown yet)
    if face_cascade is not None and USE_RPICAM:
        print("👀 Quick face check...")
        check_path = "/tmp/face_check.jpg"
        
        # Quick capture for face detection (2 seconds)
        if not capture_with_rpicam(check_path, width=1280, height=960, autofocus_time=2000):
            print("❌ Face check capture failed")
            stop_blinking()
            return False
        
        check_frame = cv2.imread(check_path)
        try:
            os.remove(check_path)
        except:
            pass
        
        if check_frame is None:
            print("❌ Failed to load check image")
            stop_blinking()
            return False
        
        # Check for face (more lenient settings)
        gray = cv2.cvtColor(check_frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=3,      # More lenient (was 5)
            minSize=(30, 30)     # Detect smaller faces
        )
        
        if len(faces) == 0:
            # Save debug image to see what camera captured
            cv2.imwrite("/tmp/face_debug.jpg", check_frame)
            print("⚠️ No face detected (debug image saved to /tmp/face_debug.jpg)")
            stop_blinking()
            return False
        
        print(f"✅ Face detected ({len(faces)}), get ready!")
    
    # Step 2: Capture full quality image (with countdown during autofocus)
    if USE_RPICAM:
        # Start countdown in background (5 seconds = matches autofocus time)
        countdown_thread = countdown_beep_async(5)
        
        # Capture at good quality (4624x3472 = 16MP) - autofocus runs during countdown
        if not capture_with_rpicam(IMAGE_PATH, width=4624, height=3472, autofocus_time=5000):
            print("❌ Full capture failed")
            stop_blinking()
            return False
        print("📸 Captured!")
    
    elif preview_running and preview_frame is not None:
        with preview_lock:
            frame = preview_frame.copy()
        
        # Face check for V4L2
        if face_cascade is not None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.1, 5)
            if len(faces) == 0:
                print("⚠️ No face detected")
                stop_blinking()
                return False
            print(f"✅ Face detected ({len(faces)}), get ready!")
        
        # Countdown with delay before capture
        countdown_beep_async(5)
        time.sleep(5)  # Wait for countdown to finish
        
        # Re-capture fresh frame after countdown
        with preview_lock:
            frame = preview_frame.copy()
        
        cv2.imwrite(IMAGE_PATH, frame)
        print("📸 Captured!")
    
    else:
        cap = cv2.VideoCapture(CAMERA_INDEX)
        if not cap.isOpened():
            print("❌ Camera open failed")
            stop_blinking()
            return False
        
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        
        for _ in range(FLUSH_FRAMES):
            cap.read()
            time.sleep(0.05)
        
        # Quick face check first
        ret, frame = cap.read()
        if not ret or frame is None:
            cap.release()
            print("❌ Failed to capture frame")
            stop_blinking()
            return False
        
        # Face check for V4L2
        if face_cascade is not None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.1, 5)
            if len(faces) == 0:
                cap.release()
                print("⚠️ No face detected")
                stop_blinking()
                return False
            print(f"✅ Face detected ({len(faces)}), get ready!")
        
        # Countdown (5 seconds) while keeping camera open
        countdown_beep_async(5)
        time.sleep(5)
        
        # Capture final frame after countdown
        ret, frame = cap.read()
        cap.release()
        
        if not ret or frame is None:
            print("❌ Failed to capture final frame")
            stop_blinking()
            return False
        
        cv2.imwrite(IMAGE_PATH, frame)
        print("📸 Captured!")

    stop_blinking()

    # Send to server and print
    receipt = send_image_to_server(IMAGE_PATH, ws_server)
    if receipt:
        print_image(receipt)
        return True

    # Error indicator
    start_blinking(0.1)
    time.sleep(2)
    stop_blinking()
    return False

# ==============================
# PREVIEW THREAD (OpenCV)
# ==============================
def preview_thread_func(face_cascade_ref):
    global preview_running, preview_frame
    
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print("❌ Preview: Camera open failed")
        return
    
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
    
    # Check if we can show window
    has_window = False
    if DISPLAY_AVAILABLE:
        try:
            cv2.namedWindow("Camera Preview", cv2.WINDOW_NORMAL)
            cv2.resizeWindow("Camera Preview", 640, 480)
            print("📺 Preview started (press 'q' to quit)")
            has_window = True
        except Exception as e:
            print(f"⚠️ Cannot open preview window: {e}")
    
    if not has_window:
        print("⚠️ No display available - running in headless mode")
        print("   Camera is running for capture, but no preview window")
        print("   To see preview: run directly on Pi desktop or use VNC")
    
    preview_running = True
    
    while preview_running:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.01)
            continue
        
        # Store frame for capture
        with preview_lock:
            preview_frame = frame.copy()
        
        # Only show window if display available
        if has_window:
            # Face detection for display
            display_frame = frame.copy()
            if face_cascade_ref is not None:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = face_cascade_ref.detectMultiScale(gray, 1.1, 5)
                
                # Draw bounding boxes (green)
                for (x, y, w, h) in faces:
                    cv2.rectangle(display_frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                
                # Show face count
                cv2.putText(display_frame, f"Faces: {len(faces)}", (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            
            try:
                cv2.imshow("Camera Preview", display_frame)
                # Check for 'q' key
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            except:
                has_window = False
        else:
            # No window, just keep camera running for capture
            time.sleep(0.03)  # ~30fps
    
    preview_running = False
    cap.release()
    if has_window:
        cv2.destroyAllWindows()
    print("📺 Preview stopped")

# ==============================
# HTTP ENDPOINTS
# ==============================
@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "preview": preview_running,
        "gpio": GPIO_ENABLED,
        "face_detection": face_cascade is not None
    })

@app.route('/capture', methods=['GET', 'POST'])
def capture():
    global capture_triggered, last_capture_time

    qr_code = request.args.get('qr', 'manual')
    print(f"\n📱 Capture triggered: {qr_code}")

    if capture_triggered:
        return jsonify({"success": False, "error": "Capture in progress"}), 429

    if time.time() - last_capture_time < CAPTURE_COOLDOWN:
        remaining = int(CAPTURE_COOLDOWN - (time.time() - last_capture_time))
        return jsonify({"success": False, "error": f"Cooldown: {remaining}s"}), 429

    capture_triggered = True
    try:
        ok = do_capture(app.config['WS_SERVER'])
        if ok:
            last_capture_time = time.time()
            return jsonify({"success": True, "message": "Captured and printed!"})
        return jsonify({"success": False, "error": "Capture failed (no face?)"}), 500
    finally:
        capture_triggered = False

# ==============================
# KILL PORT FUNCTION
# ==============================
def kill_port(port):
    """Kill any process using the specified port."""
    try:
        result = subprocess.run(
            ['fuser', '-k', f'{port}/tcp'],
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0:
            print(f"🔪 Killed process on port {port}")
            time.sleep(2)  # Wait for port to be released
            return True
    except:
        pass
    return False

# ==============================
# MAIN
# ==============================
def main():
    global preview_running
    
    parser = argparse.ArgumentParser(description='Raspberry Pi Camera Server')
    parser.add_argument('--server', default=WS_SERVER_DEFAULT, help='WebSocket server URL')
    parser.add_argument('--port', type=int, default=HTTP_PORT, help='HTTP port')
    parser.add_argument('--preview', action='store_true', help='Show live camera preview with face detection')
    parser.add_argument('--no-face', action='store_true', help='Disable face detection requirement')
    args = parser.parse_args()

    if args.no_face:
        global face_cascade
        face_cascade = None
        print("⚠️ Face detection disabled (--no-face)")

    app.config['WS_SERVER'] = args.server

    # Kill any existing process on our port
    print(f"🔍 Checking port {args.port}...")
    kill_port(args.port)

    # Get local IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except:
        ip = "localhost"

    camera_type = "rpicam (Arducam/libcamera)" if USE_RPICAM else "V4L2 (USB webcam)"
    
    print("\n" + "=" * 50)
    print("📷 CAMERA SERVER")
    print("=" * 50)
    print(f"WebSocket: {args.server}")
    print(f"HTTP:      http://{ip}:{args.port}/capture")
    print(f"Camera:    {camera_type}")
    print(f"GPIO:      {'✅ Enabled' if GPIO_ENABLED else '⚠️ Disabled'}")
    print(f"Face Det:  {'✅ Enabled' if face_cascade else '⚠️ Disabled'}")
    print("=" * 50 + "\n")

    preview_t = None
    
    # Start preview thread only for V4L2 cameras (rpicam doesn't support OpenCV preview)
    if args.preview and not USE_RPICAM:
        preview_t = threading.Thread(
            target=preview_thread_func,
            args=(face_cascade,),
            daemon=False
        )
        preview_t.start()
    elif args.preview and USE_RPICAM:
        print("⚠️ Preview not supported with rpicam/Arducam")
        print("   Face detection still works during capture")

    # Run Flask server with retry
    max_retries = 3
    for attempt in range(max_retries):
        try:
            app.run(host='0.0.0.0', port=args.port, debug=False, threaded=True)
            break  # If successful, exit loop
        except KeyboardInterrupt:
            print("\n🛑 Shutting down...")
            break
        except OSError as e:
            if "Address already in use" in str(e):
                print(f"⚠️ Port {args.port} in use, attempt {attempt + 1}/{max_retries}")
                kill_port(args.port)
                time.sleep(3)
                if attempt == max_retries - 1:
                    print(f"❌ Failed to start after {max_retries} attempts")
            else:
                raise
    
    preview_running = False
    if preview_t and preview_t.is_alive():
        preview_t.join(timeout=2)

# ==============================
# START
# ==============================
if __name__ == "__main__":
    main()
