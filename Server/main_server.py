"""
Main Server - Combined WebSocket + QR Print Server

Runs both servers in one process:
1. WebSocket server (port 8765) - receives images, generates receipts
2. HTTPS server (port 5000) - receives QR scans from phone

Usage:
    python main_server.py
"""

import asyncio
import websockets
from aiohttp import web
import ssl
import os
import socket
import base64
from datetime import datetime
from dotenv import load_dotenv
from receipt_generator import make_receipt
import aiohttp

# Load environment variables
load_dotenv()

# ==========================================
# CONFIGURATION
# ==========================================

WEBSOCKET_PORT = int(os.getenv('WEBSOCKET_PORT', 8765))
QR_SERVER_PORT = int(os.getenv('QR_SERVER_PORT', 5000))
RASPBERRY_PI_IP = os.getenv('RASPBERRY_PI_IP', '100.102.29.90')
RASPBERRY_PI_PORT = int(os.getenv('RASPBERRY_PI_PORT', 5001))

# ==========================================
# CONNECTED CLIENTS
# ==========================================

connected_clients = set()

# ==========================================
# UTILITY FUNCTIONS
# ==========================================

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "localhost"


def is_valid_image(data):
    if len(data) < 8:
        return False
    if data[:3] == b'\xff\xd8\xff':
        return True
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return True
    if data[:4] == b'GIF8':
        return True
    return False


def decode_image_data(data):
    if isinstance(data, str):
        try:
            decoded = base64.b64decode(data)
            if is_valid_image(decoded):
                return decoded
        except:
            pass
        return None
    
    if isinstance(data, bytes):
        if is_valid_image(data):
            return data
        try:
            decoded = base64.b64decode(data)
            if is_valid_image(decoded):
                return decoded
        except:
            pass
    
    return None


def generate_ssl_context():
    """Generate self-signed SSL certificate for HTTPS."""
    try:
        from OpenSSL import crypto
        
        cert_file = "server.crt"
        key_file = "server.key"
        
        if os.path.exists(cert_file) and os.path.exists(key_file):
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert_file, key_file)
            return ctx
        
        print("Generating SSL certificate...")
        
        k = crypto.PKey()
        k.generate_key(crypto.TYPE_RSA, 2048)
        
        cert = crypto.X509()
        cert.get_subject().CN = socket.gethostname()
        cert.set_serial_number(1000)
        cert.gmtime_adj_notBefore(0)
        cert.gmtime_adj_notAfter(365 * 24 * 60 * 60)
        cert.set_issuer(cert.get_subject())
        cert.set_pubkey(k)
        cert.sign(k, 'sha256')
        
        with open(cert_file, "wb") as f:
            f.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
        with open(key_file, "wb") as f:
            f.write(crypto.dump_privatekey(crypto.FILETYPE_PEM, k))
        
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_file, key_file)
        return ctx
        
    except ImportError:
        print("⚠️ pyOpenSSL not installed. HTTPS disabled.")
        return None


# ==========================================
# WEBSOCKET HANDLER
# ==========================================

async def websocket_handler(ws):
    print("📡 Raspberry Pi connected")
    connected_clients.add(ws)
    
    try:
        while True:
            data = await ws.recv()
            
            # Skip small messages (commands/pings)
            if isinstance(data, (str, bytes)) and len(data) < 100:
                continue
            
            print(f"📥 Image received ({len(data)} bytes)")
            
            photo_bytes = decode_image_data(data)
            if photo_bytes is None:
                print("❌ Invalid image data")
                continue
            
            # Save image
            os.makedirs("received_images", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            photo_name = f"{timestamp}.jpg"
            with open(f"received_images/{photo_name}", "wb") as f:
                f.write(photo_bytes)
            print(f"💾 Saved: received_images/{photo_name}")
            
            # Generate receipt
            try:
                receipt_bytes = make_receipt(photo_bytes)
                print("🧾 Receipt generated")
            except Exception as e:
                print(f"❌ Receipt error: {e}")
                continue
            
            # Save receipt
            os.makedirs("output", exist_ok=True)
            receipt_name = f"receipt_{timestamp}.jpg"
            with open(f"output/{receipt_name}", "wb") as f:
                f.write(receipt_bytes)
            print(f"💾 Saved: output/{receipt_name}")
            
            # Send back to Raspberry Pi
            await ws.send(base64.b64encode(receipt_bytes))
            print("📤 Receipt sent to Raspberry Pi\n")
            
    except websockets.exceptions.ConnectionClosed:
        print("🔌 Raspberry Pi disconnected")
    finally:
        connected_clients.discard(ws)


# ==========================================
# HTTP HANDLERS (QR Scanner)
# ==========================================

# QR Scanner HTML page
QR_SCANNER_HTML = """
<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>QR Scanner</title>
<script src="https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js"></script>
<style>
body { font-family: Arial; background: #1a1a2e; color: white; padding: 20px; margin: 0; }
.container { max-width: 500px; margin: 0 auto; }
h1 { text-align: center; color: #00d9ff; }
#reader { border-radius: 12px; overflow: hidden; }
.status { margin-top: 20px; padding: 15px; border-radius: 8px; text-align: center; background: rgba(0,217,255,0.2); border: 1px solid #00d9ff; }
.success { background: rgba(0,255,136,0.2); border-color: #00ff88; color: #00ff88; }
.error { background: rgba(255,68,68,0.2); border-color: #ff4444; color: #ff4444; }
button { width: 100%; padding: 15px; margin-top: 15px; border: none; border-radius: 8px; background: #00d9ff; color: #1a1a2e; font-size: 18px; font-weight: bold; cursor: pointer; }
</style>
</head><body>
<div class="container">
<h1>📷 QR Scanner</h1>
<div id="reader"></div>
<div id="status" class="status">Point camera at QR code</div>
<button onclick="capture()">📸 Manual Capture</button>
</div>
<script>
const html5QrCode = new Html5Qrcode("reader");
let lastScan = 0;

html5QrCode.start({ facingMode: "environment" }, { fps: 10, qrbox: { width: 250, height: 250 } },
    (text) => {
        if (Date.now() - lastScan < 3000) return;
        lastScan = Date.now();
        if (text.toUpperCase() === 'CAPTURE') capture();
    },
    () => {}
).catch(err => {
    document.getElementById('status').innerHTML = '❌ Camera error: ' + err;
    document.getElementById('status').className = 'status error';
});

async function capture() {
    document.getElementById('status').innerHTML = '⏳ Capturing...';
    try {
        const res = await fetch('/api/capture', { method: 'POST' });
        const data = await res.json();
        document.getElementById('status').innerHTML = data.success ? '✅ ' + data.message : '❌ ' + data.error;
        document.getElementById('status').className = 'status ' + (data.success ? 'success' : 'error');
    } catch (e) {
        document.getElementById('status').innerHTML = '❌ ' + e.message;
        document.getElementById('status').className = 'status error';
    }
    setTimeout(() => {
        document.getElementById('status').innerHTML = 'Point camera at QR code';
        document.getElementById('status').className = 'status';
    }, 3000);
}
</script>
</body></html>
"""


async def handle_index(request):
    return web.Response(text=QR_SCANNER_HTML, content_type='text/html')


async def handle_capture(request):
    """Trigger capture on Raspberry Pi."""
    import time
    qr_id = f"CAPTURE_{int(time.time())}"
    url = f"http://{RASPBERRY_PI_IP}:{RASPBERRY_PI_PORT}/capture?qr={qr_id}"
    
    print(f"📷 Triggering capture on Raspberry Pi...")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                result = await resp.json()
                
                if result.get('success'):
                    print(f"✅ Capture successful")
                    return web.json_response({'success': True, 'message': result.get('message', 'Captured!')})
                else:
                    print(f"❌ Capture failed: {result.get('error')}")
                    return web.json_response({'success': False, 'error': result.get('error')}, status=500)
                    
    except aiohttp.ClientError as e:
        error = f"Cannot connect to Raspberry Pi at {RASPBERRY_PI_IP}:{RASPBERRY_PI_PORT}"
        print(f"❌ {error}")
        return web.json_response({'success': False, 'error': error}, status=503)
    except asyncio.TimeoutError:
        return web.json_response({'success': True, 'message': 'Capture in progress...'})


async def handle_status(request):
    return web.json_response({
        'websocket_clients': len(connected_clients),
        'raspberry_pi': f"{RASPBERRY_PI_IP}:{RASPBERRY_PI_PORT}"
    })


# ==========================================
# MAIN
# ==========================================

async def main():
    local_ip = get_local_ip()
    
    print("=" * 60)
    print("🚀 POTBOY SERVER")
    print("=" * 60)
    print(f"\n📡 WebSocket server: ws://{local_ip}:{WEBSOCKET_PORT}")
    print(f"📱 QR Scanner:       https://{local_ip}:{QR_SERVER_PORT}")
    print(f"🍓 Raspberry Pi:     {RASPBERRY_PI_IP}:{RASPBERRY_PI_PORT}")
    print("\n" + "=" * 60)
    print("Waiting for connections...\n")
    
    # Setup HTTP server
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_post('/api/capture', handle_capture)
    app.router.add_get('/api/capture', handle_capture)
    app.router.add_get('/api/status', handle_status)
    
    # SSL context for HTTPS
    ssl_ctx = generate_ssl_context()
    
    # Start HTTP server
    runner = web.AppRunner(app)
    await runner.setup()
    
    if ssl_ctx:
        site = web.TCPSite(runner, '0.0.0.0', QR_SERVER_PORT, ssl_context=ssl_ctx)
        print(f"🔒 HTTPS enabled (accept security warning on phone)")
    else:
        site = web.TCPSite(runner, '0.0.0.0', QR_SERVER_PORT)
        print(f"⚠️ Running without HTTPS (camera may not work on phone)")
    
    await site.start()
    
    # Start WebSocket server
    async with websockets.serve(
        websocket_handler,
        "0.0.0.0",
        WEBSOCKET_PORT,
        max_size=15 * 1024 * 1024
    ):
        print(f"\n✅ Both servers running!")
        print(f"   Open https://{local_ip}:{QR_SERVER_PORT} on your phone\n")
        await asyncio.Future()  # Run forever


if __name__ == "__main__":
    asyncio.run(main())
