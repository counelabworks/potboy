import asyncio
import websockets
from receipt_generator import make_receipt
import os
from datetime import datetime
import requests
import base64
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ==========================================
# CONFIGURATION (from .env)
# ==========================================

WEBSOCKET_PORT = int(os.getenv('WEBSOCKET_PORT', 8765))
RASPBERRY_PI_IP = os.getenv('RASPBERRY_PI_IP', '192.168.0.183')
RASPBERRY_PI_PORT = int(os.getenv('RASPBERRY_PI_PORT', 5001))

# ==========================================


def send_to_raspberry_pi(receipt_bytes, filename):
    """Send receipt to Raspberry Pi's output folder."""
    try:
        url = f"http://{RASPBERRY_PI_IP}:{RASPBERRY_PI_PORT}/save"
        
        # Encode image as base64
        image_data = base64.b64encode(receipt_bytes).decode('utf-8')
        
        response = requests.post(
            url,
            json={
                'image_data': image_data,
                'filename': filename,
                'folder': 'output'
            },
            timeout=30
        )
        
        result = response.json()
        
        if result.get('success'):
            print(f"✅ Receipt sent to Raspberry Pi: {filename}")
            return True
        else:
            print(f"❌ Failed to send receipt: {result.get('error')}")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to Raspberry Pi at {RASPBERRY_PI_IP}:{RASPBERRY_PI_PORT}")
        return False
    except Exception as e:
        print(f"❌ Error sending to Raspberry Pi: {e}")
        return False


def is_valid_image(data):
    """Check if the data is a valid image by checking magic bytes."""
    if len(data) < 8:
        return False
    # JPEG: FF D8 FF
    # PNG: 89 50 4E 47 0D 0A 1A 0A
    # GIF: 47 49 46 38
    if data[:3] == b'\xff\xd8\xff':  # JPEG
        return True
    if data[:8] == b'\x89PNG\r\n\x1a\n':  # PNG
        return True
    if data[:4] == b'GIF8':  # GIF
        return True
    return False


def decode_image_data(data):
    """
    Decode incoming data - handles both raw bytes and base64 encoded.
    Returns raw image bytes.
    """
    # If it's a string, it might be base64
    if isinstance(data, str):
        try:
            decoded = base64.b64decode(data)
            if is_valid_image(decoded):
                return decoded
        except:
            pass
        return None
    
    # If it's bytes, check if it's raw image or base64 encoded bytes
    if isinstance(data, bytes):
        # First check if it's already a valid image
        if is_valid_image(data):
            return data
        
        # Try decoding as base64
        try:
            decoded = base64.b64decode(data)
            if is_valid_image(decoded):
                return decoded
        except:
            pass
    
    return None


async def handler(ws):
    print("📡 Client connected (Raspberry Pi)")

    try:
        while True:
            # 1. Receive data
            data = await ws.recv()
            print(f"📥 Data received ({len(data)} bytes)")
            
            # Decode the image (handles base64)
            photo_bytes = decode_image_data(data)
            
            if photo_bytes is None:
                print(f"❌ Could not decode image data")
                print(f"   First 50 chars: {data[:50] if isinstance(data, str) else data[:50]}")
                continue
            
            print(f"✅ Image decoded ({len(photo_bytes)} bytes)")

            # Save received image
            os.makedirs("received_images", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            photo_name = f"{timestamp}.jpg"
            with open(f"received_images/{photo_name}", "wb") as f:
                f.write(photo_bytes)
            print(f"💾 Photo saved: received_images/{photo_name}")

            # 2. Generate receipt
            try:
                receipt_bytes = make_receipt(photo_bytes)
                print("🧾 Receipt generated")
            except Exception as e:
                print(f"❌ Error generating receipt: {e}")
                continue

            # 3. Save receipt locally
            os.makedirs("output", exist_ok=True)
            receipt_name = f"receipt_{timestamp}.jpg"
            with open(f"output/{receipt_name}", "wb") as f:
                f.write(receipt_bytes)
            print(f"💾 Receipt saved: output/{receipt_name}")

            # 4. Send receipt back to Raspberry Pi via WebSocket (base64 encoded)
            receipt_base64 = base64.b64encode(receipt_bytes)
            await ws.send(receipt_base64)
            print("📤 Receipt sent back to Raspberry Pi")
            print("✅ Done processing photo\n")

    except websockets.exceptions.ConnectionClosed:
        print("🔌 Client disconnected")
    except Exception as e:
        print(f"❌ Handler error: {e}")


async def main():
    print("=" * 60)
    print("🚀 WEBSOCKET SERVER")
    print("=" * 60)
    print(f"WebSocket listening on port {WEBSOCKET_PORT}")
    print(f"Raspberry Pi: {RASPBERRY_PI_IP}:{RASPBERRY_PI_PORT}")
    print("=" * 60)
    print("Waiting for connections...\n")
    
    async with websockets.serve(
        handler,
        "0.0.0.0",
        WEBSOCKET_PORT,
        max_size=15 * 1024 * 1024
    ):
        await asyncio.Future()


asyncio.run(main())
