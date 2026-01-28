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


async def handler(ws):
    print("📡 Client connected")

    try:
        while True:
            # 1. Receive photo
            photo_bytes = await ws.recv()
            print(f"📥 Photo received ({len(photo_bytes)} bytes)")

            # Save received image
            os.makedirs("received_images", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            photo_name = f"{timestamp}.jpg"
            with open(f"received_images/{photo_name}", "wb") as f:
                f.write(photo_bytes)
            print(f"💾 Photo saved: received_images/{photo_name}")

            # 2. Generate receipt
            receipt_bytes = make_receipt(photo_bytes)
            print("🧾 Receipt generated")

            # 3. Save receipt locally
            os.makedirs("output", exist_ok=True)
            receipt_name = f"receipt_{timestamp}.jpg"
            with open(f"output/{receipt_name}", "wb") as f:
                f.write(receipt_bytes)
            print(f"💾 Receipt saved: output/{receipt_name}")

            # 4. Send receipt to Raspberry Pi only
            send_to_raspberry_pi(receipt_bytes, receipt_name)
            print("✅ Done processing photo\n")

    except websockets.exceptions.ConnectionClosed:
        print("🔌 Client disconnected")


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
