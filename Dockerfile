FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

WORKDIR /app

RUN apt-get update && apt-get install -y \
    xvfb \
    x11vnc \
    novnc \
    websockify \
    fluxbox \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py entrypoint.sh ./

RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]
