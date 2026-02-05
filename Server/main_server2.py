"""
Main Server 2 - WebSocket + Web UI with Preview and Capture

Flow:
1. User opens web page with Preview and Capture buttons
2. Click Preview → starts livestream from Raspberry Pi
3. Click Capture → triggers capture on Pi (with countdown)
4. Pi sends image → Server creates receipt → sends back to Pi
5. Pi prints the receipt

Usage:
    python main_server2.py
"""

import asyncio
import websockets
from aiohttp import web
import ssl
import os
import socket
import base64
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
import aiohttp

# Suppress noisy websockets logs
logging.getLogger('websockets').setLevel(logging.ERROR)

# Load environment variables
load_dotenv()

# ==========================================
# CONFIGURATION
# ==========================================

WEBSOCKET_PORT = int(os.getenv('WEBSOCKET_PORT', 8765))
WEB_PORT = int(os.getenv('QR_SERVER_PORT', 5000))
RASPBERRY_PI_PORT = int(os.getenv('RASPBERRY_PI_PORT', 5001))

# Raspberry Pi IP - "auto" means use discovery
_pi_ip_config = os.getenv('RASPBERRY_PI_IP', 'auto').strip()
RASPBERRY_PI_IP = None if _pi_ip_config.lower() == 'auto' else _pi_ip_config

# ==========================================
# GLOBAL STATE
# ==========================================

connected_pi = None  # WebSocket connection to Pi
connected_browsers = set()  # WebSocket connections to browsers
discovered_pi_ip = None
preview_active = False

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


def get_raspberry_pi_ip():
    """Get the Raspberry Pi IP address."""
    if RASPBERRY_PI_IP:
        return RASPBERRY_PI_IP
    if discovered_pi_ip:
        return discovered_pi_ip
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
# RECEIPT GENERATOR (simple version)
# ==========================================

def make_receipt(photo_bytes):
    """Create receipt from photo. For now, just returns the photo."""
    # TODO: Add receipt template, date, etc.
    return photo_bytes


# ==========================================
# WEB UI HTML
# ==========================================

WEB_UI_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Potboy Photo Booth</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: #0a0a0a;
            color: #fafafa;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 24px;
        }
        
        .container {
            max-width: 720px;
            width: 100%;
        }
        
        .header {
            text-align: center;
            margin-bottom: 32px;
        }
        
        .header h1 {
            font-size: 28px;
            font-weight: 700;
            color: #fff;
            letter-spacing: -0.5px;
            margin-bottom: 8px;
        }
        
        .header p {
            color: #666;
            font-size: 14px;
        }
        
        .video-wrapper {
            position: relative;
            width: 100%;
            margin-bottom: 24px;
        }
        
        .video-container {
            background: #111;
            border-radius: 16px;
            overflow: hidden;
            aspect-ratio: 4/3;
            display: flex;
            align-items: center;
            justify-content: center;
            border: 1px solid #222;
        }
        
        .video-container img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
        
        .placeholder {
            color: #444;
            font-size: 15px;
            text-align: center;
            padding: 20px;
        }
        
        .placeholder-icon {
            font-size: 48px;
            margin-bottom: 12px;
            opacity: 0.5;
        }
        
        .buttons {
            display: flex;
            gap: 12px;
            justify-content: center;
        }
        
        button {
            padding: 14px 32px;
            font-size: 15px;
            font-weight: 600;
            font-family: inherit;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }
        
        button:disabled {
            opacity: 0.4;
            cursor: not-allowed;
        }
        
        button:active:not(:disabled) {
            transform: scale(0.97);
        }
        
        .btn-preview {
            background: #fff;
            color: #0a0a0a;
        }
        
        .btn-preview:hover:not(:disabled) {
            background: #e5e5e5;
        }
        
        .btn-capture {
            background: #dc2626;
            color: white;
            display: none;
        }
        
        .btn-capture.visible {
            display: inline-flex;
        }
        
        .btn-capture:hover:not(:disabled) {
            background: #b91c1c;
        }
        
        .btn-stop {
            background: #333;
            color: #fff;
        }
        
        .btn-stop:hover:not(:disabled) {
            background: #444;
        }
        
        .status {
            margin-top: 24px;
            padding: 16px 20px;
            border-radius: 12px;
            text-align: center;
            font-size: 14px;
            background: #111;
            border: 1px solid #222;
            color: #888;
        }
        
        .status.error {
            background: #1a0a0a;
            border-color: #3d1515;
            color: #f87171;
        }
        
        .status.success {
            background: #0a1a0a;
            border-color: #153d15;
            color: #4ade80;
        }
        
        .countdown {
            font-size: 120px;
            font-weight: 700;
            color: #fff;
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            z-index: 10;
            display: none;
            opacity: 0.9;
        }
        
        .countdown.visible {
            display: block;
            animation: countPulse 1s ease-out infinite;
        }
        
        @keyframes countPulse {
            0% { transform: translate(-50%, -50%) scale(0.8); opacity: 0; }
            20% { transform: translate(-50%, -50%) scale(1); opacity: 1; }
            100% { transform: translate(-50%, -50%) scale(1); opacity: 0.9; }
        }
        
        .overlay {
            position: absolute;
            inset: 0;
            background: rgba(0,0,0,0.6);
            border-radius: 16px;
            display: none;
        }
        
        .overlay.visible {
            display: block;
        }
        
        .footer {
            margin-top: 40px;
            text-align: center;
            color: #333;
            font-size: 12px;
        }
        
        @media (max-width: 480px) {
            body { padding: 16px; }
            .header h1 { font-size: 22px; }
            button { padding: 12px 24px; font-size: 14px; }
            .countdown { font-size: 80px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Potboy Photo Booth</h1>
            <p>Capture moments, print memories</p>
        </div>
        
        <div class="video-wrapper">
            <div class="video-container" id="videoContainer">
                <div class="placeholder">
                    <div class="placeholder-icon">📷</div>
                    <div>Press Start Preview to connect</div>
                </div>
            </div>
            <canvas id="frozenFrame" style="display:none; width:100%; height:100%; object-fit:cover;"></canvas>
            <div class="overlay" id="overlay"></div>
            <div class="countdown" id="countdown"></div>
        </div>
        
        <div class="buttons">
            <button class="btn-preview" id="btnPreview" onclick="togglePreview()">
                <span>▶</span> Start Preview
            </button>
            <button class="btn-capture" id="btnCapture" onclick="capture()">
                <span>●</span> Capture
            </button>
        </div>
        
        <div class="status" id="status">
            Ready to connect
        </div>
        
        <div class="footer">
            Potboy v2
        </div>
    </div>
    
    <script>
        const PI_IP = '{{PI_IP}}';
        const PI_PORT = '{{PI_PORT}}';
        const WS_PORT = '{{WS_PORT}}';
        
        let previewActive = false;
        let ws = null;
        
        function setStatus(msg, type = '') {
            const el = document.getElementById('status');
            el.textContent = msg;
            el.className = 'status ' + type;
        }
        
        function connectWebSocket() {
            // Always use wss:// since WebSocket server has SSL enabled
            ws = new WebSocket(`wss://${window.location.hostname}:${WS_PORT}`);
            
            ws.onopen = () => console.log('WebSocket connected');
            ws.onclose = () => {
                console.log('WebSocket disconnected');
                setTimeout(connectWebSocket, 3000);
            };
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                handleMessage(data);
            };
        }
        
        function freezeFrame() {
            const container = document.getElementById('videoContainer');
            const img = container.querySelector('img');
            const canvas = document.getElementById('frozenFrame');
            
            if (img && img.complete) {
                // Freeze current frame
                canvas.width = img.naturalWidth || 640;
                canvas.height = img.naturalHeight || 480;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0);
                
                // Hide video, show frozen frame
                container.style.display = 'none';
                canvas.style.display = 'block';
            }
        }
        
        function unfreezeFrame() {
            const container = document.getElementById('videoContainer');
            const canvas = document.getElementById('frozenFrame');
            
            container.style.display = 'block';
            canvas.style.display = 'none';
        }
        
        function handleMessage(data) {
            switch(data.type) {
                case 'countdown':
                    showCountdown(data.value);
                    break;
                case 'capture_start':
                    freezeFrame();  // Freeze the preview
                    setStatus('Get ready!', '');
                    break;
                case 'capture_done':
                    setStatus('Photo captured! Printing...', 'success');
                    hideCountdown();
                    break;
                case 'print_done':
                    setStatus('Receipt printed! Click Preview to continue', 'success');
                    unfreezeFrame();
                    // Reset preview state
                    previewActive = false;
                    const btn = document.getElementById('btnPreview');
                    btn.innerHTML = '<span>▶</span> Start Preview';
                    btn.classList.remove('btn-stop');
                    btn.classList.add('btn-preview');
                    document.getElementById('btnCapture').classList.remove('visible');
                    break;
                case 'error':
                    setStatus(data.message, 'error');
                    hideCountdown();
                    break;
            }
        }
        
        function showCountdown(value) {
            document.getElementById('overlay').classList.add('visible');
            const el = document.getElementById('countdown');
            el.textContent = value;
            el.classList.add('visible');
        }
        
        function hideCountdown() {
            document.getElementById('countdown').classList.remove('visible');
            document.getElementById('overlay').classList.remove('visible');
        }
        
        async function togglePreview() {
            const btn = document.getElementById('btnPreview');
            const captureBtn = document.getElementById('btnCapture');
            const container = document.getElementById('videoContainer');
            
            if (!previewActive) {
                // Start preview
                btn.disabled = true;
                setStatus('Connecting to camera...', '');
                
                try {
                    const response = await fetch('/api/preview/start', { method: 'POST' });
                    const result = await response.json();
                    
                    if (result.success) {
                        // Show MJPEG stream (add timestamp to prevent caching)
                        const streamUrl = result.stream_url + '?t=' + Date.now();
                        container.innerHTML = `<img src="${streamUrl}" alt="Camera Preview" onerror="console.error('Stream failed to load')" onload="console.log('Stream loaded')">`;
                        previewActive = true;
                        btn.innerHTML = '<span>■</span> Stop';
                        btn.classList.remove('btn-preview');
                        btn.classList.add('btn-stop');
                        captureBtn.classList.add('visible');
                        setStatus('Preview active — ready to capture', 'success');
                    } else {
                        setStatus(result.error, 'error');
                    }
                } catch (e) {
                    setStatus('Failed to start preview: ' + e.message, 'error');
                }
                btn.disabled = false;
            } else {
                // Stop preview
                btn.disabled = true;
                
                try {
                    await fetch('/api/preview/stop', { method: 'POST' });
                } catch (e) {}
                
                container.innerHTML = '<div class="placeholder"><div class="placeholder-icon">📷</div><div>Press Start Preview to connect</div></div>';
                previewActive = false;
                btn.innerHTML = '<span>▶</span> Start Preview';
                btn.classList.remove('btn-stop');
                btn.classList.add('btn-preview');
                captureBtn.classList.remove('visible');
                setStatus('Preview stopped', '');
                btn.disabled = false;
            }
        }
        
        async function capture() {
            const btn = document.getElementById('btnCapture');
            btn.disabled = true;
            setStatus('Starting capture...', '');
            
            try {
                const response = await fetch('/api/capture', { method: 'POST' });
                const result = await response.json();
                
                if (!result.success) {
                    setStatus(result.error, 'error');
                }
            } catch (e) {
                setStatus('Capture failed: ' + e.message, 'error');
            }
            
            setTimeout(() => { btn.disabled = false; }, 2000);
        }
        
        // Connect WebSocket on load
        connectWebSocket();
    </script>
</body>
</html>
"""


# ==========================================
# HTTP HANDLERS
# ==========================================

async def handle_index(request):
    pi_ip = get_raspberry_pi_ip() or 'localhost'
    html = WEB_UI_HTML.replace('{{PI_IP}}', pi_ip)
    html = html.replace('{{PI_PORT}}', str(RASPBERRY_PI_PORT))
    html = html.replace('{{WS_PORT}}', str(WEBSOCKET_PORT))
    return web.Response(text=html, content_type='text/html')


async def handle_preview_start(request):
    """Start preview stream on Raspberry Pi."""
    global preview_active
    
    pi_ip = get_raspberry_pi_ip()
    print(f"▶️ Preview start requested, Pi IP: {pi_ip}")
    if not pi_ip:
        return web.json_response({'success': False, 'error': 'Raspberry Pi not found'}, status=503)
    
    try:
        url = f"http://{pi_ip}:{RASPBERRY_PI_PORT}/preview/start"
        print(f"▶️ Calling Pi at: {url}")
        async with aiohttp.ClientSession() as session:
            async with session.post(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                result = await resp.json()
                print(f"▶️ Pi response: {result}")
                
                if result.get('success'):
                    preview_active = True
                    # Return proxied stream URL (goes through this server, so HTTPS works)
                    stream_url = "/api/stream"
                    print(f"▶️ Returning stream_url: {stream_url}")
                    return web.json_response({
                        'success': True,
                        'stream_url': stream_url
                    })
                else:
                    return web.json_response({'success': False, 'error': result.get('error')}, status=500)
                    
    except Exception as e:
        print(f"❌ Preview start error: {e}")
        return web.json_response({'success': False, 'error': str(e)}, status=503)


async def handle_stream_proxy(request):
    """Proxy the MJPEG stream from Raspberry Pi (solves HTTPS mixed content issue)."""
    print(f"📹 Stream proxy request received from {request.remote}")
    
    pi_ip = get_raspberry_pi_ip()
    if not pi_ip:
        print("❌ Stream proxy: Pi not found")
        return web.Response(text="Pi not found", status=503)
    
    stream_url = f"http://{pi_ip}:{RASPBERRY_PI_PORT}/stream"
    print(f"📹 Stream proxy connecting to: {stream_url}")
    
    response = web.StreamResponse(
        status=200,
        headers={
            'Content-Type': 'multipart/x-mixed-replace; boundary=frame',
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0',
            'Connection': 'keep-alive',
        }
    )
    await response.prepare(request)
    
    try:
        timeout = aiohttp.ClientTimeout(total=None, sock_read=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            print(f"📹 Opening connection to Pi stream...")
            async with session.get(stream_url) as resp:
                print(f"📹 Stream proxy connected, status: {resp.status}, content-type: {resp.content_type}")
                chunk_count = 0
                async for chunk in resp.content.iter_any():
                    chunk_count += 1
                    if chunk_count == 1:
                        print(f"📹 First chunk received ({len(chunk)} bytes)")
                    elif chunk_count % 100 == 0:
                        print(f"📹 Streamed {chunk_count} chunks...")
                    await response.write(chunk)
    except asyncio.CancelledError:
        print("📹 Stream proxy: client disconnected")
    except Exception as e:
        print(f"❌ Stream proxy error: {type(e).__name__}: {e}")
    
    return response


async def handle_preview_stop(request):
    """Stop preview stream on Raspberry Pi."""
    global preview_active
    
    pi_ip = get_raspberry_pi_ip()
    if pi_ip:
        try:
            url = f"http://{pi_ip}:{RASPBERRY_PI_PORT}/preview/stop"
            async with aiohttp.ClientSession() as session:
                await session.post(url, timeout=aiohttp.ClientTimeout(total=5))
        except:
            pass
    
    preview_active = False
    return web.json_response({'success': True})


async def handle_notify(request):
    """Receive notifications from Raspberry Pi and broadcast to browsers."""
    try:
        data = await request.json()
        msg_type = data.get('type')
        
        if msg_type in ['capture_start', 'countdown', 'capture_done', 'print_done']:
            print(f"📢 Notification: {msg_type} = {data.get('value', '')}")
            await broadcast_to_browsers(data)
            return web.json_response({'success': True})
        else:
            return web.json_response({'success': False, 'error': 'Unknown type'}, status=400)
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)}, status=500)


async def handle_capture(request):
    """Trigger capture on Raspberry Pi."""
    pi_ip = get_raspberry_pi_ip()
    if not pi_ip:
        return web.json_response({'success': False, 'error': 'Raspberry Pi not found'}, status=503)
    
    try:
        url = f"http://{pi_ip}:{RASPBERRY_PI_PORT}/capture"
        print(f"📷 Triggering capture on {pi_ip}...")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                result = await resp.json()
                
                if result.get('success'):
                    return web.json_response({'success': True, 'message': result.get('message')})
                else:
                    return web.json_response({'success': False, 'error': result.get('error')}, status=500)
                    
    except asyncio.TimeoutError:
        return web.json_response({'success': True, 'message': 'Capture in progress...'})
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)}, status=503)


async def handle_status(request):
    pi_ip = get_raspberry_pi_ip()
    return web.json_response({
        'raspberry_pi': f"{pi_ip or 'not found'}:{RASPBERRY_PI_PORT}",
        'preview_active': preview_active
    })


# ==========================================
# WEBSOCKET HANDLER (Pi connection)
# ==========================================

async def websocket_handler(ws):
    """Handle WebSocket connection from Raspberry Pi."""
    global connected_pi
    
    print("📡 Raspberry Pi connected via WebSocket")
    connected_pi = ws
    
    try:
        async for message in ws:
            # Check if it's JSON command or image data
            if isinstance(message, str):
                try:
                    data = json.loads(message)
                    await handle_pi_message(data)
                    continue
                except json.JSONDecodeError:
                    pass
            
            # Assume it's image data (base64 encoded)
            print(f"📥 Image received ({len(message)} bytes)")
            
            try:
                if isinstance(message, str):
                    photo_bytes = base64.b64decode(message)
                else:
                    photo_bytes = base64.b64decode(message.decode())
                
                # Save image
                os.makedirs("received_images", exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                with open(f"received_images/{timestamp}.jpg", "wb") as f:
                    f.write(photo_bytes)
                print(f"💾 Saved: received_images/{timestamp}.jpg")
                
                # Create receipt (for now just the photo)
                receipt_bytes = make_receipt(photo_bytes)
                
                # Save receipt
                os.makedirs("output", exist_ok=True)
                with open(f"output/receipt_{timestamp}.jpg", "wb") as f:
                    f.write(receipt_bytes)
                print(f"💾 Saved: output/receipt_{timestamp}.jpg")
                
                # Send back to Pi
                await ws.send(base64.b64encode(receipt_bytes))
                print("📤 Receipt sent to Raspberry Pi")
                
                # Notify browsers
                await broadcast_to_browsers({'type': 'capture_done'})
                
            except Exception as e:
                print(f"❌ Error processing image: {e}")
                await broadcast_to_browsers({'type': 'error', 'message': str(e)})
                
    except websockets.exceptions.ConnectionClosed:
        print("🔌 Raspberry Pi disconnected")
    finally:
        connected_pi = None


async def handle_pi_message(data):
    """Handle JSON messages from Pi."""
    msg_type = data.get('type')
    
    if msg_type == 'countdown':
        await broadcast_to_browsers(data)
    elif msg_type == 'capture_start':
        await broadcast_to_browsers(data)
    elif msg_type == 'print_done':
        await broadcast_to_browsers(data)
    elif msg_type == 'error':
        await broadcast_to_browsers(data)


# ==========================================
# WEBSOCKET HANDLER (Browser connection)
# ==========================================

async def browser_websocket_handler(ws):
    """Handle WebSocket connection from browser."""
    print("🌐 Browser connected via WebSocket")
    connected_browsers.add(ws)
    
    try:
        async for message in ws:
            # Handle browser commands if needed
            pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        connected_browsers.discard(ws)
        print("🌐 Browser disconnected")


async def broadcast_to_browsers(data):
    """Send message to all connected browsers."""
    if connected_browsers:
        message = json.dumps(data)
        await asyncio.gather(
            *[ws.send(message) for ws in connected_browsers],
            return_exceptions=True
        )


# ==========================================
# MAIN
# ==========================================

async def main():
    global discovered_pi_ip
    
    local_ip = get_local_ip()
    pi_ip = RASPBERRY_PI_IP or "auto-discovery"
    
    # SSL context (create early so we can show correct URLs)
    ssl_ctx = generate_ssl_context()
    
    ws_protocol = "wss" if ssl_ctx else "ws"
    http_protocol = "https" if ssl_ctx else "http"
    
    print("=" * 60)
    print("🚀 POTBOY SERVER v2 (Preview + Capture)")
    print("=" * 60)
    print(f"\n🌐 Web UI:        {http_protocol}://{local_ip}:{WEB_PORT}")
    print(f"📡 WebSocket:     {ws_protocol}://{local_ip}:{WEBSOCKET_PORT}")
    print(f"🍓 Raspberry Pi:  {pi_ip}:{RASPBERRY_PI_PORT}")
    print("\n" + "=" * 60)
    
    # Setup HTTP server
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_post('/api/preview/start', handle_preview_start)
    app.router.add_post('/api/preview/stop', handle_preview_stop)
    app.router.add_get('/api/stream', handle_stream_proxy)  # Proxy stream for HTTPS
    app.router.add_post('/api/capture', handle_capture)
    app.router.add_post('/api/notify', handle_notify)  # Pi notifications for countdown
    app.router.add_get('/api/status', handle_status)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    if ssl_ctx:
        site = web.TCPSite(runner, '0.0.0.0', WEB_PORT, ssl_context=ssl_ctx)
        print(f"🔒 HTTPS enabled")
    else:
        site = web.TCPSite(runner, '0.0.0.0', WEB_PORT)
    
    await site.start()
    
    # Start WebSocket server (with SSL if available)
    ws_server_pi = await websockets.serve(
        websocket_handler,
        "0.0.0.0",
        WEBSOCKET_PORT,
        max_size=15 * 1024 * 1024,
        ssl=ssl_ctx,  # Enable SSL for WebSocket too
        logger=None,  # Suppress noisy handshake error logs
    )
    
    print(f"\n✅ Server running!")
    print(f"   Open {http_protocol}://{local_ip}:{WEB_PORT} in your browser\n")
    
    await asyncio.Future()  # Run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Server stopped")
