#!/bin/bash

# Ensure we are in the right directory
APP_DIR=$(pwd)
USER_NAME=$(whoami)

echo "Creating systemd service file..."

cat <<EOF | sudo tee /etc/systemd/system/selfbot-panel.service
[Unit]
Description=Selfbot Web Panel
After=network.target

[Service]
User=$USER_NAME
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "Reloading systemd and enabling service..."
sudo systemctl daemon-reload
sudo systemctl enable selfbot-panel.service
sudo systemctl start selfbot-panel.service

echo "------------------------------------------------------"
echo "Service installed successfully!"
echo "To check the logs: sudo journalctl -u selfbot-panel -f"
echo "To stop the server: sudo systemctl stop selfbot-panel"
echo "To restart the server: sudo systemctl restart selfbot-panel"
echo "------------------------------------------------------"
