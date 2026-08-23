#!/bin/bash

# Ensure we are in the right directory
APP_DIR=$(pwd)

# Security check: Do not run as root
if [ "$SUDO_USER" == "root" ] || { [ -z "$SUDO_USER" ] && [ "$(whoami)" == "root" ]; }; then
    echo "ERREUR : Pour des raisons de sécurité, le service ne doit pas être exécuté en tant que root."
    echo "Veuillez exécuter ce script avec 'sudo ./setup_service.sh' depuis un compte utilisateur standard (ex: ubuntu)."
    exit 1
fi

USER_NAME=$SUDO_USER
if [ -z "$USER_NAME" ]; then
    USER_NAME=$(whoami)
fi

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
