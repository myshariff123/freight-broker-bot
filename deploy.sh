#!/bin/bash
# Deploy freight-broker-bot to EC2
# Run from Windows: bash deploy.sh

EC2_IP="35.183.103.197"
KEY="$HOME/Downloads/ECOM Keypair.pem"
REMOTE_DIR="/opt/freight-broker-bot"

echo "==> Copying files to EC2..."
scp -i "$KEY" -r . "ubuntu@$EC2_IP:$REMOTE_DIR"

echo "==> Setting up on EC2..."
ssh -i "$KEY" "ubuntu@$EC2_IP" << 'EOF'
  cd /opt/freight-broker-bot

  # Create .env if it doesn't exist
  if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "*** ACTION REQUIRED ***"
    echo "Edit /opt/freight-broker-bot/.env and fill in:"
    echo "  LOADLINK_EMAIL, LOADLINK_PASSWORD"
    echo "  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID"
    echo "  POSTGRES_PASSWORD"
    echo "Then run: cd /opt/freight-broker-bot && docker-compose up -d --build"
    echo ""
  fi

  # Open port 8080 for dashboard
  sudo iptables -I INPUT -p tcp --dport 8080 -j ACCEPT 2>/dev/null || true

  echo "Deploy complete."
  echo "Next: Edit .env then run 'docker-compose up -d --build'"
EOF
