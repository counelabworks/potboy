"""
Camera Client v2 - Raspberry Pi with Preview Stream + Capture

Features:
1. MJPEG livestream for web preview
2. HTTP endpoints for preview start/stop and capture
3. 5-second countdown with LED/Buzzer blinking
4. Capture with Arducam (rpicam-still)
5. Send image to server via WebSocket
6. Receive receipt and print with thermal printer

Flow:
1. Server requests /preview/start → starts MJPEG stream
2. Server requests /capture → starts 5s countdown with LED/buzzer
3. After countdown, capture image
4. Send image to server via WebSocket
5. Receive processed receipt
6. Print receipt on thermal printer

Usage:
    python 008_main_client.py
    python 008_main_client.py --server ws://192.168.0.100:8765

Requirements:
    pip install flask websockets python-escpos pillow opencv-python gpiozero python-dotenv
"""

import os
import subprocess
import time
import asyncio
import websockets
import base64
import json
import threading
from datetime import datetime
from flask import Flask, Response, jsonify, request
import socket
import argparse

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ==============================
# CONFIG
# ==============================
PRINTER_DEVICE = os.getenv('PRINTER_DEVICE', '/dev/usb/lp0')
HTTP_PORT = int(os.getenv('HTTP_PORT', 5001))
RPICAM_INDEX = int(os.getenv('RPICAM_INDEX', 1))
CAMERA_INDEX = int(os.getenv('CAMERA_INDEX', 0))

# WebSocket server
_ws_config = os.getenv('WS_SERVER', 'auto').strip()
WS_SERVER_DEFAULT = None if _ws_config.lower() == 'auto' else _ws_config

WS_TIMEOUT = 10
COUNTDOWN_SECONDS = 5

LED_PIN = int(os.getenv('LED_PIN', 24))
BUZZER_PIN = int(os.getenv('BUZZER_PIN', 23))

# Paths
IMAGE_PATH = "/tmp/capture.jpg"
OUTPUT_FOLDER = "output"

# Printer settings
PRINTER_PAPER_WIDTH = 576
PRINTER_IMAGE_WIDTH = 500

# ==============================
# GLOBAL STATE
# ==============================
app = Flask(__name__)
preview_active = False
capture_in_progress = False
stream_thread = None
stream_frame = None
stream_lock = threading.Lock()
stream_process = None  # Track rpicam-vid process
ws_server_url = None

# ==============================
# GPIO SETUP
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
# CAMERA DETECTION
# ==============================
USE_RPICAM = False

def check_rpicam():
    """Check if rpicam-still is available."""
    try:
        result = subprocess.run(['rpicam-still', '--version'], 
                              capture_output=True, text=True, timeout=5)
        return result.returncode == 0 or 'rpicam-still' in result.stderr
    except:
        return False

def check_opencv_camera():
    """Check if OpenCV camera is available."""
    try:
        import cv2
        cap = cv2.VideoCapture(CAMERA_INDEX)
        if cap.isOpened():
            ret, _ = cap.read()
            cap.release()
            return ret
    except:
        pass
    return False

# Detect camera type
if check_rpicam():
    USE_RPICAM = True
    print("✅ Camera: rpicam (Arducam/libcamera)")
elif check_opencv_camera():
    USE_RPICAM = False
    print("✅ Camera: OpenCV (USB webcam)")
else:
    print("⚠️ No camera detected!")

# ==============================
# LED/BUZZER CONTROL
# ==============================
def blink_countdown(seconds, ws_callback=None):
    """Blink LED and buzzer for countdown."""
    print(f"⏱️ Countdown: {seconds} seconds...")
    
    for i in range(seconds, 0, -1):
        print(f"   {i}...")
        
        # Send countdown to server
        if ws_callback:
            try:
                ws_callback({'type': 'countdown', 'value': i})
            except:
                pass
        
        # Blink
        if GPIO_ENABLED:
            led.on()
            buzzer.on()
            time.sleep(0.1)
            led.off()
            buzzer.off()
        time.sleep(0.9)
    
    # Final beep
    print("   📸 CAPTURE!")
    if GPIO_ENABLED:
        led.on()
        buzzer.on()
        time.sleep(0.3)
        led.off()
        buzzer.off()

# ==============================
# MJPEG STREAM (for preview)
# ==============================
def stop_stream_process():
    """Stop the rpicam-vid process if running."""
    global stream_process
    if stream_process:
        try:
            stream_process.terminate()
            stream_process.wait(timeout=2)
        except:
            try:
                stream_process.kill()
            except:
                pass
        stream_process = None
        time.sleep(0.5)  # Give camera time to release


def generate_mjpeg_stream():
    """Generate MJPEG stream from camera."""
    global stream_frame, stream_process
    
    print(f"🎬 generate_mjpeg_stream called, preview_active={preview_active}, USE_RPICAM={USE_RPICAM}")
    
    if USE_RPICAM:
        # Use rpicam-vid for streaming (--nopreview disables X11 window)
        cmd = [
            'rpicam-vid',
            '-t', '0',  # Run indefinitely
            '--nopreview',  # Don't try to open X11 preview window
            '--camera', str(RPICAM_INDEX),
            '--width', '640',
            '--height', '480',
            '--framerate', '15',
            '--codec', 'mjpeg',
            '-o', '-'  # Output to stdout
        ]
        
        try:
            print(f"🎬 Starting rpicam-vid: {' '.join(cmd)}")
            stream_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Read MJPEG frames
            buffer = b''
            frame_count = 0
            while preview_active and not capture_in_progress:
                chunk = stream_process.stdout.read(4096)
                if not chunk:
                    # Check for errors
                    stderr_data = stream_process.stderr.read()
                    if stderr_data:
                        print(f"❌ rpicam-vid stderr: {stderr_data.decode()}")
                    print("🎬 No more data from rpicam-vid")
                    break
                buffer += chunk
                
                # Find JPEG markers
                start = buffer.find(b'\xff\xd8')
                end = buffer.find(b'\xff\xd9')
                
                if start != -1 and end != -1 and end > start:
                    frame = buffer[start:end+2]
                    buffer = buffer[end+2:]
                    frame_count += 1
                    
                    if frame_count == 1:
                        print(f"🎬 First frame captured ({len(frame)} bytes)")
                    elif frame_count % 100 == 0:
                        print(f"🎬 Streamed {frame_count} frames...")
                    
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            
            print(f"🎬 Stream loop ended, preview_active={preview_active}, capture_in_progress={capture_in_progress}")
            stop_stream_process()
        except Exception as e:
            print(f"❌ Stream error: {e}")
            import traceback
            traceback.print_exc()
            stop_stream_process()
    else:
        # Use OpenCV
        import cv2
        cap = cv2.VideoCapture(CAMERA_INDEX)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        while preview_active:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue
            
            with stream_lock:
                stream_frame = frame.copy()
            
            _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
            
            time.sleep(0.066)  # ~15 fps
        
        cap.release()

# ==============================
# CAPTURE FUNCTION
# ==============================
def capture_image():
    """Capture image with camera."""
    if USE_RPICAM:
        cmd = [
            'rpicam-still',
            '-o', IMAGE_PATH,
            '-t', '1000',  # 1 second for autofocus
            '-n',  # No preview
            '--camera', str(RPICAM_INDEX),
            '--autofocus-mode', 'auto',
            '--width', '4624',
            '--height', '3472',
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0 and os.path.exists(IMAGE_PATH):
                print(f"📸 Captured: {IMAGE_PATH}")
                return True
            print(f"❌ rpicam-still error: {result.stderr}")
            return False
        except Exception as e:
            print(f"❌ Capture error: {e}")
            return False
    else:
        # Use OpenCV / stream frame
        import cv2
        
        with stream_lock:
            if stream_frame is not None:
                cv2.imwrite(IMAGE_PATH, stream_frame)
                print(f"📸 Captured from stream: {IMAGE_PATH}")
                return True
        
        # Fallback: open camera
        cap = cv2.VideoCapture(CAMERA_INDEX)
        if cap.isOpened():
            ret, frame = cap.read()
            cap.release()
            if ret:
                cv2.imwrite(IMAGE_PATH, frame)
                print(f"📸 Captured: {IMAGE_PATH}")
                return True
        
        print("❌ Capture failed")
        return False

# ==============================
# WEBSOCKET COMMUNICATION
# ==============================
async def send_image_and_receive_receipt(image_path, ws_server):
    """Send image to server and receive receipt."""
    try:
        print(f"🌐 Connecting to {ws_server}...")
        
        # Create SSL context that doesn't verify self-signed certificates
        ssl_context = None
        if ws_server.startswith('wss://'):
            import ssl
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        
        async with websockets.connect(
            ws_server,
            max_size=15_000_000,
            open_timeout=WS_TIMEOUT,
            close_timeout=WS_TIMEOUT,
            ssl=ssl_context
        ) as ws:
            # Read and send image
            with open(image_path, "rb") as f:
                image_data = f.read()
            
            await ws.send(base64.b64encode(image_data))
            print("📤 Image sent to server")
            
            # Receive receipt
            response = await ws.recv()
            receipt_bytes = base64.b64decode(response)
            
            # Save receipt
            os.makedirs(OUTPUT_FOLDER, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            receipt_path = f"{OUTPUT_FOLDER}/receipt_{ts}.png"
            
            with open(receipt_path, "wb") as f:
                f.write(receipt_bytes)
            
            print(f"📥 Receipt received: {receipt_path}")
            return receipt_path
            
    except Exception as e:
        print(f"❌ WebSocket error: {e}")
        return None

def send_to_server_sync(image_path, ws_server):
    """Synchronous wrapper for WebSocket communication."""
    return asyncio.run(send_image_and_receive_receipt(image_path, ws_server))

# ==============================
# PRINT FUNCTION
# ==============================
def print_receipt(image_path):
    """Print receipt on thermal printer."""
    try:
        from escpos.printer import File
        from PIL import Image
        
        if not os.path.exists(image_path):
            print(f"❌ Receipt not found: {image_path}")
            return False
        
        # Load and resize image
        img = Image.open(image_path).convert('L')
        
        if img.width > PRINTER_IMAGE_WIDTH:
            ratio = PRINTER_IMAGE_WIDTH / img.width
            new_height = int(img.height * ratio)
            img = img.resize((PRINTER_IMAGE_WIDTH, new_height), Image.LANCZOS)
        
        # Center image
        padding_left = (PRINTER_PAPER_WIDTH - img.width) // 2
        centered_img = Image.new('L', (PRINTER_PAPER_WIDTH, img.height), 255)
        centered_img.paste(img, (padding_left, 0))
        
        # Save temp file
        temp_path = "/tmp/print_receipt.bmp"
        centered_img.save(temp_path)
        
        # Print
        print(f"🖨️ Printing receipt...")
        p = File(PRINTER_DEVICE)
        p._raw(b'\x1B\x40')  # Reset
        p.image(temp_path, impl="bitImageRaster",
                high_density_vertical=True, high_density_horizontal=True)
        p.text("\n\n\n")
        p.cut()
        p.close()
        
        print("🖨️ Print complete!")
        return True
        
    except Exception as e:
        print(f"❌ Print error: {e}")
        return False

# ==============================
# FULL CAPTURE FLOW
# ==============================
def do_capture_flow(ws_server):
    """Complete capture flow: stop stream → countdown → capture → send → print."""
    global capture_in_progress, preview_active
    
    if capture_in_progress:
        return False, "Capture already in progress"
    
    capture_in_progress = True
    was_preview_active = preview_active
    
    try:
        # 1. Stop stream if using rpicam (camera can only be used by one process)
        if USE_RPICAM and stream_process:
            print("⏸️ Pausing preview for capture...")
            stop_stream_process()
            time.sleep(0.5)  # Extra time for camera to release
        
        # 2. Countdown with LED/buzzer
        blink_countdown(COUNTDOWN_SECONDS)
        
        # 3. Capture image
        if not capture_image():
            return False, "Capture failed"
        
        # 4. Send to server and get receipt
        receipt_path = send_to_server_sync(IMAGE_PATH, ws_server)
        if not receipt_path:
            return False, "Failed to get receipt from server"
        
        # 5. Print receipt
        if not print_receipt(receipt_path):
            return False, "Print failed"
        
        return True, "Captured and printed!"
        
    finally:
        capture_in_progress = False
        # Note: Preview will need to be restarted by user clicking preview again

# ==============================
# HTTP ENDPOINTS
# ==============================
@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "preview": preview_active,
        "gpio": GPIO_ENABLED,
        "camera": "rpicam" if USE_RPICAM else "opencv"
    })

@app.route('/stream')
def stream():
    """MJPEG stream endpoint."""
    if not preview_active:
        return jsonify({"error": "Preview not active"}), 400
    
    return Response(
        generate_mjpeg_stream(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@app.route('/preview/start', methods=['POST'])
def preview_start():
    """Start preview stream."""
    global preview_active
    
    if preview_active:
        return jsonify({"success": True, "message": "Preview already active"})
    
    preview_active = True
    print("🎥 Preview started")
    return jsonify({"success": True})

@app.route('/preview/stop', methods=['POST'])
def preview_stop():
    """Stop preview stream."""
    global preview_active
    
    preview_active = False
    print("🎥 Preview stopped")
    return jsonify({"success": True})

@app.route('/capture', methods=['POST', 'GET'])
def capture():
    """Trigger capture with countdown."""
    if capture_in_progress:
        return jsonify({"success": False, "error": "Capture in progress"}), 429
    
    # Run capture in background thread
    def capture_thread():
        success, message = do_capture_flow(app.config['WS_SERVER'])
        if success:
            print(f"✅ {message}")
        else:
            print(f"❌ {message}")
    
    thread = threading.Thread(target=capture_thread, daemon=True)
    thread.start()
    
    return jsonify({"success": True, "message": "Capture started"})

# ==============================
# MAIN
# ==============================
def main():
    global ws_server_url
    
    parser = argparse.ArgumentParser(description='Raspberry Pi Camera Client v2')
    parser.add_argument('--server', default=WS_SERVER_DEFAULT, help='WebSocket server URL')
    parser.add_argument('--port', type=int, default=HTTP_PORT, help='HTTP port')
    args = parser.parse_args()
    
    ws_server_url = args.server
    if not ws_server_url:
        print("⚠️ No WebSocket server specified. Use --server ws://IP:8765")
        ws_server_url = "ws://localhost:8765"
    
    app.config['WS_SERVER'] = ws_server_url
    
    # Get local IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except:
        ip = "localhost"
    
    camera_type = "rpicam (Arducam)" if USE_RPICAM else "OpenCV"
    
    print("\n" + "=" * 50)
    print("📷 CAMERA CLIENT v2")
    print("=" * 50)
    print(f"HTTP:       http://{ip}:{args.port}")
    print(f"Stream:     http://{ip}:{args.port}/stream")
    print(f"WebSocket:  {ws_server_url}")
    print(f"Camera:     {camera_type}")
    print(f"GPIO:       {'✅ Enabled' if GPIO_ENABLED else '⚠️ Disabled'}")
    print(f"Printer:    {PRINTER_DEVICE}")
    print("=" * 50 + "\n")
    
    print("Endpoints:")
    print(f"  POST /preview/start  - Start camera preview")
    print(f"  POST /preview/stop   - Stop camera preview")
    print(f"  GET  /stream         - MJPEG video stream")
    print(f"  POST /capture        - Capture with countdown")
    print()
    
    app.run(host='0.0.0.0', port=args.port, debug=False, threaded=True)

if __name__ == "__main__":
    main()
