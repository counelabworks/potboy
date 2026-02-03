#!/bin/bash
# Startup script for Camera Server
# Kills port 5001 if in use, then starts the server

set -e

WORKDIR="/home/pi/thermalPrinterRaspy"
SCRIPT="007_arducam_qr_system.py"
WS_SERVER="ws://172.20.10.2:8765"

cd "$WORKDIR" || exit 1

# Kill any process using port 5001
echo "Checking port 5001..."
fuser -k 5001/tcp 2>/dev/null || true
sleep 1

# Activate virtual environment and run
echo "Starting Camera Server..."
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    exec python "$SCRIPT" --server "$WS_SERVER"
else
    echo "Error: venv not found at $WORKDIR/venv"
    exit 1
fi
