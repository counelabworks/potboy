import asyncio
import websockets
from receipt_generator import make_receipt
import os
from datetime import datetime

async def handler(ws):
    print("📡 Client connected")

    try:
        while True:
            # 1. Receive photo
            photo_bytes = await ws.recv()
            print(f"📥 Photo received ({len(photo_bytes)} bytes)")

            # Save received image
            os.makedirs("received_images", exist_ok=True)
            name = datetime.now().strftime("%Y%m%d_%H%M%S.jpg")
            with open(f"received_images/{name}", "wb") as f:
                f.write(photo_bytes)

            # 2. Generate receipt
            receipt_bytes = make_receipt(photo_bytes)
            print("🧾 Receipt generated")

            # 3. Send receipt back
            await ws.send(receipt_bytes)
            print("📤 Receipt sent back")

    except websockets.exceptions.ConnectionClosed:
        print("🔌 Client disconnected")

async def main():
    async with websockets.serve(
        handler,
        "0.0.0.0",
        8765,
        max_size=15 * 1024 * 1024
    ):
        print("🚀 Server running on port 8765")
        await asyncio.Future()

asyncio.run(main())
