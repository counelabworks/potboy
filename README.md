# Potboy - QR Code Triggered Photo Booth

A photo booth system where scanning a QR code triggers a Raspberry Pi camera to capture a photo, sends it to a server for receipt generation, and prints the receipt on a thermal printer.

## Architecture

```
📱 Phone                    💻 Laptop (Server)              🍓 Raspberry Pi (Client)
┌─────────────┐            ┌─────────────────────┐         ┌─────────────────────┐
│             │            │                     │         │                     │
│ Scan QR     │───────────▶│  qr_print_server.py │────────▶│  004_qr_printt.py   │
│ (CAPTURE)   │  HTTPS     │  (port 5000)        │  HTTP   │  (port 5001)        │
│             │            │                     │         │                     │
└─────────────┘            │  Triggers capture   │         │  1. Detect face     │
                           └─────────────────────┘         │  2. Capture photo   │
                                                           │  3. Send to server  │
                           ┌─────────────────────┐         │                     │
                           │                     │         └──────────┬──────────┘
                           │     server.py       │◀────────────────────┘
                           │   (port 8765)       │         WebSocket (image)
                           │                     │
                           │  1. Receive image   │─────────────────────┐
                           │  2. Generate receipt│                     │
                           │  3. Send back       │                     ▼
                           └─────────────────────┘         ┌─────────────────────┐
                                                           │  Raspberry Pi       │
                                                           │                     │
                                                           │  4. Receive receipt │
                                                           │  5. Print on thermal│
                                                           │     printer         │
                                                           └─────────────────────┘
```

## Features

- **QR Code Trigger**: Scan a QR code with your phone to trigger photo capture
- **Face Detection**: Only captures when a face is detected (with bounding boxes)
- **Receipt Generation**: Creates a formatted receipt with photo, name, ID, and date
- **Thermal Printing**: Prints the receipt on a thermal printer
- **Auto-Reconnect**: WebSocket connection auto-reconnects on failure
- **Cooldown**: Prevents spam captures (5 second cooldown)

## Project Structure

```
potboy/
├── Server/                      # Runs on Laptop/PC
│   ├── server.py                # WebSocket server - receives images, generates receipts
│   ├── qr_print_server.py       # HTTPS server - receives QR scans from phone
│   ├── receipt_generator.py     # Generates receipt images
│   ├── generate_capture_qr.py   # Generates the CAPTURE QR code
│   ├── capture_qr.png           # ⬅️ THE QR CODE - scan this to trigger capture
│   ├── requirements.txt
│   ├── received_images/         # Captured photos from Raspberry Pi
│   └── output/                  # Generated receipts
│
├── Client/                      # Runs on Raspberry Pi
│   ├── 004_qr_printt.py         # ⬅️ Main script - camera server with face detection
│   ├── haarcascade_frontalface_default.xml  # Face detection model (required)
│   ├── requirements.txt
│   └── output/                  # Received receipts
│
├── .env                         # Configuration (IP addresses, ports)
├── .env.example                 # Template for .env
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

**Configure `.env`** in the root folder:
```env
# Server Configuration
WEBSOCKET_PORT=8765
QR_SERVER_PORT=5000
HTTP_TRIGGER_PORT=8080

# Raspberry Pi Configuration
RASPBERRY_PI_IP=192.168.0.xxx    # ⬅️ Change to your Pi's IP
RASPBERRY_PI_PORT=5001
```

**Run the server** (single command):

```bash
cd Server
python main_server.py
```

This runs both the WebSocket server and QR scanner server together.

*Alternative: Run separately in two terminals:*
```bash
# Terminal 1
python server.py

# Terminal 2
python qr_print_server.py
```

### 2. Raspberry Pi Setup

```bash
cd Client

# Install dependencies
pip install flask opencv-python websockets python-escpos pillow

# Download face detection model (if not exists)
wget https://raw.githubusercontent.com/opencv/opencv/master/data/haarcascades/haarcascade_frontalface_default.xml
```

**Run the camera server:**

```bash
python 004_qr_printt.py --server ws://YOUR_SERVER_IP:8765
```

Example:
```bash
python 004_qr_printt.py --server ws://192.168.0.116:8765
```

### 3. Using the System

1. **Print or display `Server/capture_qr.png`** - this is the QR code
2. **Open your phone browser** and go to `https://YOUR_SERVER_IP:5000`
3. **Accept the security warning** (self-signed certificate)
4. **Allow camera access**
5. **Scan the QR code** with your phone
6. The Raspberry Pi will:
   - Detect faces
   - Capture the photo
   - Send it to the server
   - Receive the generated receipt
   - Print it on the thermal printer

## Configuration

### Server (.env)

| Variable | Default | Description |
|----------|---------|-------------|
| `WEBSOCKET_PORT` | 8765 | WebSocket server port |
| `QR_SERVER_PORT` | 5000 | HTTPS server for phone scanning |
| `HTTP_TRIGGER_PORT` | 8080 | HTTP API port |
| `RASPBERRY_PI_IP` | - | Raspberry Pi's IP address |
| `RASPBERRY_PI_PORT` | 5001 | Raspberry Pi's HTTP port |

### Raspberry Pi (004_qr_printt.py)

| Variable | Default | Description |
|----------|---------|-------------|
| `PRINTER_DEVICE` | `/dev/usb/lp0` | Thermal printer device path |
| `CAMERA_INDEX` | 0 | Camera device index |
| `CAPTURE_COOLDOWN` | 5 | Seconds between captures |
| `HTTP_PORT` | 5001 | HTTP server port |

## QR Code

The QR code (`Server/capture_qr.png`) contains the text `CAPTURE`.

To regenerate:
```bash
cd Server
python generate_capture_qr.py
```

## Troubleshooting

### Camera not working
```bash
# Check if camera is detected
ls /dev/video*

# Test camera
python -c "import cv2; print(cv2.VideoCapture(0).isOpened())"
```

### Printer not working
```bash
# Check if printer is detected
ls /dev/usb/lp*

# Add user to lp group
sudo usermod -a -G lp $USER
sudo reboot
```

### Phone can't access camera (browser)
- Make sure you're using `https://` not `http://`
- Accept the security warning for the self-signed certificate
- Check that the server and phone are on the same WiFi network

### WebSocket connection fails
- Check that `server.py` is running on the laptop
- Verify the IP address in the `--server` argument
- Check firewall settings

## Requirements

### Server
- Python 3.8+
- websockets
- pillow
- flask
- pyOpenSSL
- requests
- python-dotenv
- aiohttp
- qrcode

### Raspberry Pi
- Python 3.8+
- opencv-python
- websockets
- flask
- python-escpos
- pillow
