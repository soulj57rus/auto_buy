#!/usr/bin/env bash
set -e

Xvfb :99 -screen 0 1360x768x24 &
export DISPLAY=:99

fluxbox &
x11vnc -display :99 -forever -shared -nopw -localhost &
websockify --web /usr/share/novnc/ 6080 localhost:5900 &

echo "Виртуальный дисплей запущен. Веб-интерфейс доступен на http://localhost:6080/vnc.html"

exec python -u bot.py
