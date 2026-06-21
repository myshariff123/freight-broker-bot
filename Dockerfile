FROM python:3.12-slim

# Install Chromium system dependencies manually
# (playwright --with-deps fails on Debian Trixie due to renamed font packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl gnupg ca-certificates \
    libnss3 libnspr4 libdbus-1-3 \
    libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 \
    libcups2 libdrm2 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 \
    libpango-1.0-0 libcairo2 \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium browser only (no --with-deps, we installed them above)
RUN playwright install chromium

COPY . .

RUN mkdir -p /app/logs /app/screenshots

CMD ["python", "main.py"]
