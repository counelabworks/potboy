# Potboy - QR Code Triggered Photo Booth

A photo booth system where scanning a QR code triggers a Raspberry Pi camera (Arducam) to capture a photo, sends it to a server for processing, and prints the result on a thermal printer.

## Architecture

```
📱 Phone                    💻 Laptop (Server)              🍓 Raspberry Pi (Client)
┌─────────────┐            ┌─────────────────────┐         ┌─────────────────────────┐
│             │            │                     │         │                         │
│ Scan QR     │───────────▶│   main_server.py    │────────▶│ 007_arducam_qr_system.py│
│ (CAPTURE)   │  HTTPS     │   (port 5000)       │  HTTP   │      (port 5001)        │
│             │            │                     │         │                         │
└─────────────┘            │  Triggers capture   │         │  1. Face detection      │
                           └─────────────────────┘         │  2. Countdown + Focus   │
                                                           │  3. Capture photo       │
                           ┌─────────────────────┐         │  4. Send to server      │
                           │                     │         └───────────┬─────────────┘
                           │   main_server.py    │◀────────────────────┘
                           │  WebSocket (8765)   │         WebSocket (image)
                           │                     │
                           │  1. Receive image   │─────────────────────┐
                           │  2. Process/save    │                     │
                           │  3. Send back       │                     ▼
                           └─────────────────────┘         ┌─────────────────────────┐
                                                           │     Raspberry Pi        │
                                                           │                         │
                                                           │  5. Receive processed   │
                                                           │  6. Print on thermal    │
                                                           │     printer             │
                                                           └─────────────────────────┘
```

## Features

- **QR Code Trigger**: Scan a QR code with your phone to trigger photo capture
- **Face Detection Trigger**: Only captures when a face is detected (face detection as trigger, no bounding boxes on final photo)
- **Countdown with Beeps**: 5-second countdown with LED/buzzer feedback while camera focuses
- **Arducam Support**: Uses `rpicam-still` for Arducam/libcamera on Raspberry Pi 5
- **High Resolution**: Captures at 16MP (4624x3472) for quality prints
- **Thermal Printing**: Automatically resizes and prints on thermal printer
- **Auto-Start Service**: Systemd service for boot-time startup
- **Auto-Reconnect**: WebSocket connection auto-reconnects on failure

## Project Structure

```
potboy/
├── Server/                          # Runs on Laptop/PC
│   ├── main_server.py               # ⬅️ Main server (WebSocket + QR scanner)
│   ├── receipt_generator.py         # Image processing
│   ├── generate_capture_qr.py       # Generates the CAPTURE QR code
│   ├── capture_qr.png               # ⬅️ THE QR CODE - scan this to trigger
│   ├── requirements.txt
│   ├── received_images/             # Captured photos from Raspberry Pi
│   └── output/                      # Processed images
│
├── Client/                          # Runs on Raspberry Pi
│   ├── 007_arducam_qr_system.py     # ⬅️ Main script - Arducam camera server
│   ├── camera-server.service        # Systemd service file for auto-start
│   ├── requirements.txt
│   ├── print_image.py               # Printer test utility
│   └── list_printers.py             # List available printers
│
├── .env.example                     # Server configuration template
└── README.md
```

## Setup

### 1. Server Setup (Laptop/PC)

```bash
cd Server

# Install dependencies
pip install -r requirements.txt

# Generate the QR code (if not exists)
python generate_capture_qr.py
# Creates: capture_qr.png
```

**Configure `.env`** in the Server folder:
```env
# Server Configuration
WEBSOCKET_PORT=8765
QR_SERVER_PORT=5000

# Raspberry Pi Configuration
RASPBERRY_PI_IP=192.168.0.xxx    # ⬅️ Change to your Pi's IP
RASPBERRY_PI_PORT=5001
```

**Run the server:**

```bash
cd Server
python main_server.py
```

### 2. Raspberry Pi Setup

```bash
# Create working directory
mkdir -p ~/thermalPrinterRaspy
cd ~/thermalPrinterRaspy

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install flask opencv-python websockets python-escpos pillow gpiozero

# Copy files from Client/ folder
# - 007_arducam_qr_system.py
# - camera-server.service
```

**Test the camera server manually:**

```bash
source venv/bin/activate
python 007_arducam_qr_system.py --server ws://YOUR_SERVER_IP:8765
```

**Set up auto-start service:**

```bash
# Copy service file
sudo cp camera-server.service /etc/systemd/system/

# Edit the service file to match your paths and server IP
sudo nano /etc/systemd/system/camera-server.service

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable camera-server.service
sudo systemctl start camera-server.service

# Check status
sudo systemctl status camera-server.service
journalctl -u camera-server.service -f
```

### 3. Using the System

1. **Print or display `Server/capture_qr.png`** - this is the QR code
2. **Open your phone browser** and go to `https://YOUR_SERVER_IP:5000`
3. **Accept the security warning** (self-signed certificate)
4. **Allow camera access**
5. **Scan the QR code** with your phone
6. The Raspberry Pi will:
   - Quick face detection check (~2 seconds)
   - If face found: 5-second countdown with beeps + autofocus
   - Capture high-resolution photo
   - Send to server via WebSocket
   - Receive processed image
   - Print on thermal printer

## Configuration

### Server (.env)

| Variable | Default | Description |
|----------|---------|-------------|
| `WEBSOCKET_PORT` | 8765 | WebSocket server port |
| `QR_SERVER_PORT` | 5000 | HTTPS server for phone scanning |
| `RASPBERRY_PI_IP` | - | Raspberry Pi's IP address |
| `RASPBERRY_PI_PORT` | 5001 | Raspberry Pi's HTTP port |

### Raspberry Pi (007_arducam_qr_system.py)

| Variable | Default | Description |
|----------|---------|-------------|
| `--server` | `ws://172.20.10.2:8765` | WebSocket server URL |
| `--port` | 5001 | HTTP server port |
| `PRINTER_DEVICE` | `/dev/usb/lp0` | Thermal printer device path |
| `PRINTER_IMAGE_WIDTH` | 500 | Image width for printing (pixels) |
| `PRINTER_PAPER_WIDTH` | 576 | Paper width for centering (pixels) |

### Systemd Service (camera-server.service)

Edit `/etc/systemd/system/camera-server.service` to configure:
- `WorkingDirectory` - Path to your script folder
- `ExecStart` - Python path and server URL
- `User` - Set to `root` for GPIO access

## QR Code

The QR code (`Server/capture_qr.png`) contains the text `CAPTURE`.

To regenerate:
```bash
cd Server
python generate_capture_qr.py
```

## Troubleshooting

### Camera not working (Arducam/libcamera)

```bash
# Check if rpicam-still is available
rpicam-still --version

# Test capture
rpicam-still -o test.jpg -t 2000

# Check camera detection
libcamera-hello --list-cameras
```

### Camera not working (USB/V4L2)

```bash
# Check if camera is detected
ls /dev/video*

# Test camera with OpenCV
python -c "import cv2; print(cv2.VideoCapture(0).isOpened())"
```

### Printer not working

```bash
# Check if printer is detected
ls /dev/usb/lp*

# Test print
echo "Test" > /dev/usb/lp0

# Add user to lp group (if not running as root)
sudo usermod -a -G lp $USER
sudo reboot
```

### Port 5001 already in use

```bash
# Find what's using the port
sudo lsof -i :5001

# Kill the process
sudo fuser -k 5001/tcp

# Restart the service
sudo systemctl restart camera-server.service
```

### Service not starting

```bash
# Check service status
sudo systemctl status camera-server.service

# View logs
journalctl -u camera-server.service -n 50 --no-pager

# Restart after changes
sudo systemctl daemon-reload
sudo systemctl restart camera-server.service
```

### GPIO busy error

```bash
# Run service as root (edit service file)
User=root

# Or add user to gpio group
sudo usermod -a -G gpio $USER
sudo reboot
```

### Phone can't access camera (browser)

- Make sure you're using `https://` not `http://`
- Accept the security warning for the self-signed certificate
- Check that the server and phone are on the same WiFi network

### WebSocket connection fails

- Check that `main_server.py` is running on the laptop
- Verify the IP address in the `--server` argument
- Check firewall settings

## Requirements

### Server
- Python 3.8+
- websockets
- pillow
- flask
- pyOpenSSL
- python-dotenv
- aiohttp
- qrcode

### Raspberry Pi
- Python 3.8+
- Raspberry Pi OS with libcamera support
- rpicam-still (for Arducam/libcamera cameras)
- opencv-python
- websockets
- flask
- python-escpos
- pillow
- gpiozero (for LED/buzzer feedback)

## Hardware

### Tested Configuration
- **Raspberry Pi 5**
- **Arducam 64MP Camera** (works with libcamera/rpicam-still)
- **58mm USB Thermal Printer** (ESC/POS compatible)
- **Optional**: LED on GPIO 17, Buzzer on GPIO 27
