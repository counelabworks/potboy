#!/bin/bash
# Setup script for Raspberry Pi
# Run this after copying files to the Pi

set -e

echo "========================================"
echo "🍓 Potboy Client Setup"
echo "========================================"

# Navigate to directory
cd /home/pi/thermalPrinterRaspy

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install/upgrade requirements
echo "Installing requirements..."
pip install --upgrade pip
pip install -r requirements.txt

# Install avahi for mDNS (auto-discovery)
echo "Installing avahi (for auto-discovery)..."
sudo apt-get update
sudo apt-get install -y avahi-daemon avahi-utils

# Make sure avahi is running
sudo systemctl enable avahi-daemon
sudo systemctl start avahi-daemon

# Copy .env.example to .env if .env doesn't exist
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "Created .env from .env.example"
        echo "Edit .env if you want to override default settings"
    fi
fi

# Copy service file
echo "Installing systemd service..."
sudo cp camera-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable camera-server.service

echo ""
echo "========================================"
echo "✅ Setup complete!"
echo "========================================"
echo ""
echo "To start the service:"
echo "  sudo systemctl start camera-server.service"
echo ""
echo "To check status:"
echo "  sudo systemctl status camera-server.service"
echo ""
echo "To view logs:"
echo "  sudo journalctl -u camera-server.service -f"
echo ""
echo "Auto-discovery is ENABLED by default."
echo "The Pi will automatically find the server on the network."
echo ""
echo "To manually set server IP, edit .env:"
echo "  nano .env"
echo "  # Change WS_SERVER=auto to WS_SERVER=ws://YOUR_IP:8765"
echo ""
