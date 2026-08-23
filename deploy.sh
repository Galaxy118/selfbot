#!/bin/bash

# Création de l'environnement virtuel s'il n'existe pas
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    # Sur Ubuntu, python3-venv est nécessaire
    python3 -m venv venv
fi

# Activation de l'environnement virtuel
source venv/bin/activate

echo "Installing dependencies..."
pip3 install -r requirements.txt

echo "Checking environment variables..."
if [ ! -f .env ]; then
    echo "Creating .env file with generated secrets..."
    python3 -c "from cryptography.fernet import Fernet; import secrets; open('.env', 'w').write(f'''CLIENT_ID=YOUR_CLIENT_ID
CLIENT_SECRET=YOUR_CLIENT_SECRET
REDIRECT_URI=http://localhost:8000/auth/callback
ENCRYPTION_KEY={Fernet.generate_key().decode()}
SESSION_SECRET={secrets.token_hex(32)}
ADMIN_IDS=YOUR_DISCORD_ID
''')"
    echo "Please edit the .env file with your Discord OAuth2 credentials, then run this script again."
    exit 0
fi

echo "Starting Web Panel and Discord Manager..."
python3 main.py &
PID=$!
echo "Server started with PID $PID."

echo "------------------------------------------------------"
echo "To make this panel public via Cloudflare Tunnels, run:"
echo "cloudflared tunnel --url http://localhost:8000"
echo "------------------------------------------------------"
echo "Press Ctrl+C to stop the local server."
wait $PID
