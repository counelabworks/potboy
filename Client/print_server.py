"""
Print Server - Runs on Raspberry Pi to receive print commands

This server listens for HTTP requests from the main server
and triggers the thermal printer.

Usage:
    python print_server.py

The server will listen on port 5001 for print commands.
"""

from flask import Flask, request, jsonify
import subprocess
import sys
import os
import socket

# ==========================================
# CONFIGURATION
# ==========================================

HOST = '0.0.0.0'  # Listen on all interfaces
PORT = 5001

# Path to print_image.py (in same folder)
PRINT_SCRIPT = "print_image.py"

# Folder where images are stored (synced from server or local)
IMAGE_FOLDER = "images"

# ==========================================

app = Flask(__name__)


def get_local_ip():
    """Get the local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "localhost"


def print_image(image_path):
    """Execute print_image.py with the given image path."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    print_script = os.path.join(script_dir, PRINT_SCRIPT)
    
    print(f"🖨️ Printing: {image_path}")
    
    try:
        result = subprocess.run(
            [sys.executable, print_script, image_path],
            capture_output=True,
            text=True,
            cwd=script_dir
        )
        print(result.stdout)
        if result.stderr:
            print(f"Stderr: {result.stderr}")
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        print(f"Error: {e}")
        return False, str(e)


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({'status': 'ok', 'printer': 'ready'})


@app.route('/print', methods=['POST'])
def api_print():
    """
    Receive print command from server.
    
    Expects JSON body with either:
    - image_path: Full path to image file
    - image_name: Filename to look in IMAGE_FOLDER
    - image_data: Base64 encoded image data
    """
    try:
        data = request.get_json()
        
        # Option 1: Direct image path
        if 'image_path' in data:
            image_path = data['image_path']
            if not os.path.exists(image_path):
                return jsonify({'success': False, 'error': f'File not found: {image_path}'}), 404
        
        # Option 2: Image name (look in IMAGE_FOLDER)
        elif 'image_name' in data:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            image_folder = os.path.join(script_dir, IMAGE_FOLDER)
            image_path = os.path.join(image_folder, data['image_name'])
            
            if not os.path.exists(image_path):
                return jsonify({'success': False, 'error': f'File not found: {data["image_name"]}'}), 404
        
        # Option 3: Base64 image data
        elif 'image_data' in data:
            import base64
            import tempfile
            
            image_data = base64.b64decode(data['image_data'])
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
            temp_file.write(image_data)
            temp_file.close()
            image_path = temp_file.name
        
        else:
            return jsonify({'success': False, 'error': 'No image specified'}), 400
        
        # Print the image
        success, output = print_image(image_path)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Printed: {os.path.basename(image_path)}'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Print failed: {output}'
            }), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/print/url', methods=['POST'])
def api_print_url():
    """
    Download image from URL and print it.
    
    Expects JSON body with:
    - url: URL of the image to download and print
    """
    try:
        import urllib.request
        import tempfile
        
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'success': False, 'error': 'No URL provided'}), 400
        
        print(f"📥 Downloading: {url}")
        
        # Download image
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
        urllib.request.urlretrieve(url, temp_file.name)
        
        # Print it
        success, output = print_image(temp_file.name)
        
        # Clean up temp file
        try:
            os.unlink(temp_file.name)
        except:
            pass
        
        if success:
            return jsonify({'success': True, 'message': 'Printed from URL'})
        else:
            return jsonify({'success': False, 'error': f'Print failed: {output}'}), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/save', methods=['POST'])
def api_save():
    """
    Save an image file to a specified folder.
    
    Expects JSON body with:
    - image_data: Base64 encoded image data
    - filename: Name for the file
    - folder: Folder to save to (default: 'output')
    """
    try:
        import base64
        
        data = request.get_json()
        
        image_data = data.get('image_data')
        filename = data.get('filename', 'image.jpg')
        folder = data.get('folder', 'output')
        
        if not image_data:
            return jsonify({'success': False, 'error': 'No image data provided'}), 400
        
        # Create folder if needed
        script_dir = os.path.dirname(os.path.abspath(__file__))
        save_folder = os.path.join(script_dir, folder)
        os.makedirs(save_folder, exist_ok=True)
        
        # Decode and save image
        image_bytes = base64.b64decode(image_data)
        save_path = os.path.join(save_folder, filename)
        
        with open(save_path, 'wb') as f:
            f.write(image_bytes)
        
        print(f"💾 Saved: {save_path}")
        
        return jsonify({
            'success': True,
            'message': f'Saved to {folder}/{filename}',
            'path': save_path
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/save/print', methods=['POST'])
def api_save_and_print():
    """
    Save an image and immediately print it.
    
    Expects JSON body with:
    - image_data: Base64 encoded image data
    - filename: Name for the file
    - folder: Folder to save to (default: 'output')
    """
    try:
        import base64
        
        data = request.get_json()
        
        image_data = data.get('image_data')
        filename = data.get('filename', 'image.jpg')
        folder = data.get('folder', 'output')
        
        if not image_data:
            return jsonify({'success': False, 'error': 'No image data provided'}), 400
        
        # Create folder if needed
        script_dir = os.path.dirname(os.path.abspath(__file__))
        save_folder = os.path.join(script_dir, folder)
        os.makedirs(save_folder, exist_ok=True)
        
        # Decode and save image
        image_bytes = base64.b64decode(image_data)
        save_path = os.path.join(save_folder, filename)
        
        with open(save_path, 'wb') as f:
            f.write(image_bytes)
        
        print(f"💾 Saved: {save_path}")
        
        # Print the saved image
        success, output = print_image(save_path)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Saved and printed: {filename}',
                'path': save_path
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Saved but print failed: {output}',
                'path': save_path
            }), 500
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    local_ip = get_local_ip()
    
    print("=" * 60)
    print("🖨️ RASPBERRY PI PRINT SERVER")
    print("=" * 60)
    print(f"\n📡 Listening on: http://{local_ip}:{PORT}")
    print(f"\nEndpoints:")
    print(f"  GET  /health      - Health check")
    print(f"  POST /print       - Print image")
    print(f"  POST /print/url   - Print from URL")
    print(f"  POST /save        - Save image to folder")
    print(f"  POST /save/print  - Save and print image")
    print("\n" + "=" * 60)
    print("Waiting for commands...\n")
    
    app.run(host=HOST, port=PORT, debug=False)
