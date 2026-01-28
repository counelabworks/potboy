"""
QR Print Server - HTTP server for phone-based QR scanning

This server:
1. Serves a mobile-friendly QR scanner web page
2. Receives scanned QR data from phones
3. Triggers print_image.py to print the image

Usage:
    python qr_print_server.py

Then open http://192.168.0.116:5000 on your phone's browser.
Make sure phone and server are on the same WiFi network.
"""

from flask import Flask, request, jsonify, send_from_directory, render_template_string
import subprocess
import sys
import os
import socket
import ssl
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def generate_self_signed_cert():
    """Generate a self-signed SSL certificate for HTTPS."""
    from OpenSSL import crypto
    
    cert_file = "server.crt"
    key_file = "server.key"
    
    # Check if cert already exists
    if os.path.exists(cert_file) and os.path.exists(key_file):
        return cert_file, key_file
    
    print("Generating SSL certificate...")
    
    # Create key pair
    k = crypto.PKey()
    k.generate_key(crypto.TYPE_RSA, 2048)
    
    # Create self-signed cert
    cert = crypto.X509()
    cert.get_subject().C = "US"
    cert.get_subject().ST = "State"
    cert.get_subject().L = "City"
    cert.get_subject().O = "QR Print Server"
    cert.get_subject().OU = "QR Print"
    cert.get_subject().CN = socket.gethostname()
    cert.set_serial_number(1000)
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(365 * 24 * 60 * 60)  # Valid for 1 year
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(k)
    cert.sign(k, 'sha256')
    
    # Save certificate
    with open(cert_file, "wb") as f:
        f.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
    
    # Save private key
    with open(key_file, "wb") as f:
        f.write(crypto.dump_privatekey(crypto.FILETYPE_PEM, k))
    
    print(f"Certificate generated: {cert_file}, {key_file}")
    return cert_file, key_file

# ==========================================
# CONFIGURATION (from .env)
# ==========================================

HOST = '0.0.0.0'  # Listen on all interfaces
PORT = int(os.getenv('QR_SERVER_PORT', 5000))

RASPBERRY_PI_IP = os.getenv('RASPBERRY_PI_IP', '192.168.0.183')
RASPBERRY_PI_PORT = int(os.getenv('RASPBERRY_PI_PORT', 5001))

IMAGE_FOLDER = "received_images"

# ==========================================
app = Flask(__name__)

# Mobile-friendly QR Scanner HTML page
QR_SCANNER_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>QR Print Scanner</title>
    <script src="https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js"></script>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            color: white;
            padding: 20px;
        }
        
        .container {
            max-width: 500px;
            margin: 0 auto;
        }
        
        h1 {
            text-align: center;
            font-size: 24px;
            margin-bottom: 20px;
            color: #00d9ff;
        }
        
        #reader {
            width: 100%;
            border-radius: 12px;
            overflow: hidden;
            background: #000;
        }
        
        #reader video {
            border-radius: 12px;
        }
        
        .status {
            margin-top: 20px;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
            font-size: 16px;
        }
        
        .status.ready {
            background: rgba(0, 217, 255, 0.2);
            border: 1px solid #00d9ff;
        }
        
        .status.success {
            background: rgba(0, 255, 136, 0.2);
            border: 1px solid #00ff88;
            color: #00ff88;
        }
        
        .status.error {
            background: rgba(255, 68, 68, 0.2);
            border: 1px solid #ff4444;
            color: #ff4444;
        }
        
        .status.printing {
            background: rgba(255, 193, 7, 0.2);
            border: 1px solid #ffc107;
            color: #ffc107;
        }
        
        .last-scan {
            margin-top: 15px;
            padding: 15px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 8px;
            font-size: 14px;
        }
        
        .last-scan h3 {
            font-size: 14px;
            color: #888;
            margin-bottom: 8px;
        }
        
        .last-scan code {
            word-break: break-all;
            color: #00d9ff;
        }
        
        .history {
            margin-top: 20px;
        }
        
        .history h3 {
            font-size: 16px;
            color: #888;
            margin-bottom: 10px;
        }
        
        .history-item {
            padding: 10px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 6px;
            margin-bottom: 8px;
            font-size: 13px;
        }
        
        .history-item.success {
            border-left: 3px solid #00ff88;
        }
        
        .history-item.error {
            border-left: 3px solid #ff4444;
        }
        
        .manual-input {
            margin-top: 20px;
            padding: 15px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 8px;
        }
        
        .manual-input h3 {
            font-size: 14px;
            color: #888;
            margin-bottom: 10px;
        }
        
        .manual-input input {
            width: 100%;
            padding: 12px;
            border: 1px solid #444;
            border-radius: 6px;
            background: #1a1a2e;
            color: white;
            font-size: 16px;
            margin-bottom: 10px;
        }
        
        .manual-input button {
            width: 100%;
            padding: 12px;
            border: none;
            border-radius: 6px;
            background: #00d9ff;
            color: #1a1a2e;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
        }
        
        .manual-input button:active {
            background: #00b8d9;
        }
        
        /* Fix for html5-qrcode UI */
        #reader__scan_region {
            background: transparent !important;
        }
        
        #reader__dashboard_section {
            padding: 10px !important;
        }
        
        #reader__dashboard_section_csr button {
            background: #00d9ff !important;
            color: #1a1a2e !important;
            border: none !important;
            padding: 10px 20px !important;
            border-radius: 6px !important;
            font-weight: bold !important;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📷 QR Print Scanner</h1>
        
        <div id="reader"></div>
        
        <div id="status" class="status ready">
            📱 Point camera at QR code to scan
        </div>
        
        <div id="lastScan" class="last-scan" style="display: none;">
            <h3>Last Scanned:</h3>
            <code id="lastScanText"></code>
        </div>
        
        <div class="manual-input">
            <h3>Or enter image name manually:</h3>
            <input type="text" id="manualInput" placeholder="e.g., 20260127_142917.jpg">
            <button onclick="manualPrint()">🖨️ Print</button>
        </div>
        
        <div class="history">
            <h3>Recent Prints:</h3>
            <div id="historyList"></div>
        </div>
    </div>

    <script>
        const SERVER_URL = window.location.origin;
        let lastScanTime = 0;
        const SCAN_COOLDOWN = 3000; // 3 seconds between scans
        
        // Initialize QR Scanner
        const html5QrCode = new Html5Qrcode("reader");
        
        const config = {
            fps: 10,
            qrbox: { width: 250, height: 250 },
            aspectRatio: 1.0
        };
        
        function onScanSuccess(decodedText, decodedResult) {
            // Prevent duplicate scans
            const now = Date.now();
            if (now - lastScanTime < SCAN_COOLDOWN) {
                return;
            }
            lastScanTime = now;
            
            console.log("Scanned:", decodedText);
            triggerPrint(decodedText);
        }
        
        function onScanFailure(error) {
            // Ignore scan failures (no QR in frame)
        }
        
        // Start scanning
        html5QrCode.start(
            { facingMode: "environment" }, // Use back camera
            config,
            onScanSuccess,
            onScanFailure
        ).catch(err => {
            console.error("Camera error:", err);
            document.getElementById('status').className = 'status error';
            document.getElementById('status').textContent = '❌ Camera access denied. Please allow camera permission.';
        });
        
        function triggerPrint(qrContent) {
            const statusEl = document.getElementById('status');
            const lastScanEl = document.getElementById('lastScan');
            const lastScanText = document.getElementById('lastScanText');
            
            // Show what was scanned
            lastScanEl.style.display = 'block';
            lastScanText.textContent = qrContent;
            
            // Update status
            statusEl.className = 'status printing';
            statusEl.textContent = '🖨️ Sending to printer...';
            
            // Send to server
            fetch(`${SERVER_URL}/api/print`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ qr_content: qrContent })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    statusEl.className = 'status success';
                    statusEl.textContent = '✅ Print job sent!';
                    addToHistory(qrContent, true);
                } else {
                    statusEl.className = 'status error';
                    statusEl.textContent = '❌ ' + (data.error || 'Print failed');
                    addToHistory(qrContent, false, data.error);
                }
                
                // Reset status after 3 seconds
                setTimeout(() => {
                    statusEl.className = 'status ready';
                    statusEl.textContent = '📱 Point camera at QR code to scan';
                }, 3000);
            })
            .catch(error => {
                statusEl.className = 'status error';
                statusEl.textContent = '❌ Connection error: ' + error.message;
                addToHistory(qrContent, false, error.message);
            });
        }
        
        function manualPrint() {
            const input = document.getElementById('manualInput');
            const value = input.value.trim();
            if (value) {
                triggerPrint(value);
                input.value = '';
            }
        }
        
        function addToHistory(content, success, error = null) {
            const historyList = document.getElementById('historyList');
            const item = document.createElement('div');
            item.className = 'history-item ' + (success ? 'success' : 'error');
            
            const time = new Date().toLocaleTimeString();
            item.innerHTML = `
                <strong>${time}</strong> - 
                <code>${content}</code>
                ${success ? ' ✅' : ' ❌ ' + (error || '')}
            `;
            
            historyList.insertBefore(item, historyList.firstChild);
            
            // Keep only last 10 items
            while (historyList.children.length > 10) {
                historyList.removeChild(historyList.lastChild);
            }
        }
        
        // Handle Enter key in manual input
        document.getElementById('manualInput').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                manualPrint();
            }
        });
    </script>
</body>
</html>
"""


def get_local_ip():
    """Get the local IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "localhost"


def find_image(qr_content):
    """Resolves QR code content to an image path."""
    qr_content = qr_content.strip()
    
    # Check if it's an absolute path
    if os.path.isabs(qr_content):
        if os.path.exists(qr_content):
            return qr_content
        return None
    
    # Look in IMAGE_FOLDER
    script_dir = os.path.dirname(os.path.abspath(__file__))
    image_folder = os.path.join(script_dir, IMAGE_FOLDER)
    image_path = os.path.join(image_folder, qr_content)
    
    if os.path.exists(image_path):
        return image_path
    
    # Check current directory
    if os.path.exists(qr_content):
        return os.path.abspath(qr_content)
    
    return None


def trigger_print(image_path):
    """Sends image to Raspberry Pi print server."""
    import requests
    import base64
    
    print(f"🖨️ Sending to Raspberry Pi: {image_path}")
    
    try:
        # Read image and encode as base64
        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')
        
        # Send to Raspberry Pi
        url = f"http://{RASPBERRY_PI_IP}:{RASPBERRY_PI_PORT}/print"
        response = requests.post(
            url,
            json={'image_data': image_data},
            timeout=30
        )
        
        result = response.json()
        
        if result.get('success'):
            print(f"✅ Print command sent successfully")
            return True, result.get('message', 'Success')
        else:
            print(f"❌ Print failed: {result.get('error')}")
            return False, result.get('error', 'Unknown error')
            
    except requests.exceptions.ConnectionError:
        error = f"Cannot connect to Raspberry Pi at {RASPBERRY_PI_IP}:{RASPBERRY_PI_PORT}"
        print(f"❌ {error}")
        return False, error
    except requests.exceptions.Timeout:
        error = "Raspberry Pi connection timed out"
        print(f"❌ {error}")
        return False, error
    except Exception as e:
        print(f"❌ Error: {e}")
        return False, str(e)


@app.route('/')
def index():
    """Serve the QR scanner web page."""
    return render_template_string(QR_SCANNER_HTML)


def trigger_capture():
    """Send capture command directly to Raspberry Pi."""
    import requests
    import time
    
    # Generate unique QR code ID to avoid duplicate detection
    qr_id = f"CAPTURE_{int(time.time())}"
    url = f"http://{RASPBERRY_PI_IP}:{RASPBERRY_PI_PORT}/capture?qr={qr_id}"
    
    print(f"📷 Triggering capture on Raspberry Pi (qr={qr_id})...")
    
    try:
        response = requests.post(url, timeout=30)
        result = response.json()
        
        if result.get('success'):
            print(f"✅ Capture triggered: {result.get('message')}")
            return True, result.get('message', 'Captured!')
        else:
            print(f"❌ Capture failed: {result.get('error')}")
            return False, result.get('error', 'Unknown error')
            
    except requests.exceptions.ConnectionError:
        error = f"Cannot connect to Raspberry Pi at {RASPBERRY_PI_IP}:{RASPBERRY_PI_PORT}"
        print(f"❌ {error}")
        return False, error
    except requests.exceptions.Timeout:
        # Timeout might mean it's working (capture + print takes time)
        return True, "Capture command sent (processing...)"
    except Exception as e:
        print(f"❌ Error: {e}")
        return False, str(e)


@app.route('/api/print', methods=['POST'])
def api_print():
    """API endpoint to receive QR scan data and trigger print or capture."""
    try:
        data = request.get_json()
        qr_content = data.get('qr_content', '').strip()
        
        if not qr_content:
            return jsonify({'success': False, 'error': 'No QR content provided'}), 400
        
        print(f"\n📱 Received scan: {qr_content}")
        
        # Check for special CAPTURE command
        if qr_content.upper() == 'CAPTURE':
            success, message = trigger_capture()
            if success:
                return jsonify({'success': True, 'message': message})
            else:
                return jsonify({'success': False, 'error': message}), 503
        
        # Find the image
        image_path = find_image(qr_content)
        
        if not image_path:
            return jsonify({
                'success': False, 
                'error': f'Image not found: {qr_content}'
            }), 404
        
        # Trigger print
        success, output = trigger_print(image_path)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Printing: {os.path.basename(image_path)}',
                'image': image_path
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Print failed: {output}'
            }), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/images', methods=['GET'])
def api_list_images():
    """API endpoint to list available images."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    image_folder = os.path.join(script_dir, IMAGE_FOLDER)
    
    if not os.path.exists(image_folder):
        return jsonify({'images': []})
    
    images = [f for f in os.listdir(image_folder) 
              if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp'))]
    images.sort(reverse=True)  # Most recent first
    
    return jsonify({'images': images})


if __name__ == '__main__':
    local_ip = get_local_ip()
    
    # Generate SSL certificate for HTTPS (required for camera access)
    try:
        cert_file, key_file = generate_self_signed_cert()
        use_https = True
    except ImportError:
        print("⚠️  pyOpenSSL not installed. Running without HTTPS.")
        print("   Camera may not work. Install with: pip install pyOpenSSL")
        use_https = False
    except Exception as e:
        print(f"⚠️  Could not generate SSL cert: {e}")
        print("   Running without HTTPS. Camera may not work.")
        use_https = False
    
    protocol = "https" if use_https else "http"
    
    print("=" * 60)
    print("📱 QR PRINT SERVER")
    print("=" * 60)
    print(f"\n🌐 Open this URL on your phone:\n")
    print(f"   {protocol}://{local_ip}:{PORT}")
    print(f"\n   (Make sure phone is on the same WiFi network)")
    if use_https:
        print(f"\n⚠️  Accept the security warning on your phone")
        print(f"   (The certificate is self-signed)")
    print("\n" + "=" * 60)
    print("Waiting for scans...\n")
    
    if use_https:
        app.run(host=HOST, port=PORT, debug=False, ssl_context=(cert_file, key_file))
    else:
        app.run(host=HOST, port=PORT, debug=False)
