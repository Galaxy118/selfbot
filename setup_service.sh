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

echo "Setting up secure storage..."
SECURE_DIR="/var/lib/selfbot"
sudo mkdir -p $SECURE_DIR/db $SECURE_DIR/config
sudo chown -R $USER_NAME $SECURE_DIR
sudo chmod 700 $SECURE_DIR

if [ -f "$APP_DIR/data.db" ]; then
    echo "Moving data.db to secure storage..."
    sudo mv "$APP_DIR/data.db" "$SECURE_DIR/db/data.db"
    sudo chown $USER_NAME "$SECURE_DIR/db/data.db"
    sudo chmod 600 "$SECURE_DIR/db/data.db"
fi

if [ -f "$APP_DIR/.env" ]; then
    echo "Moving .env to secure storage..."
    sudo mv "$APP_DIR/.env" "$SECURE_DIR/config/.env"
    sudo chown $USER_NAME "$SECURE_DIR/config/.env"
    sudo chmod 600 "$SECURE_DIR/config/.env"
fi

echo "Creating systemd service file..."

cat <<EOF | sudo tee /etc/systemd/system/selfbot-panel.service
[Unit]
Description=Selfbot Web Panel
After=network.target

[Service]
User=$USER_NAME
WorkingDirectory=$APP_DIR
Environment="DB_PATH=$SECURE_DIR/db/data.db"
Environment="ENV_PATH=$SECURE_DIR/config/.env"
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
echo "Data storage: $SECURE_DIR"
echo "To check the logs: sudo journalctl -u selfbot-panel -f"
echo "To restart the server: sudo systemctl restart selfbot-panel"
echo "------------------------------------------------------"
