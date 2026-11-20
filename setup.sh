#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v pacman >/dev/null 2>&1; then
    echo 'Этот установщик предназначен для Arch Linux (или производного с pacman).' >&2
    exit 1
fi

echo 'Для установки Docker и запуска службы могут потребоваться права sudo.'
sudo -v
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    sudo pacman -S --needed docker docker-compose
fi
sudo systemctl enable --now docker.service

if [[ ! -f .env ]] || ! grep -q '^TARGET_CHAT=' .env; then
    read -r -p 'Имя бота-источника в Telegram [glisa_bot]: ' target_chat
    target_chat="${target_chat:-glisa_bot}"
    target_chat="${target_chat#@}"
    if [[ ! "$target_chat" =~ ^[a-zA-Z][a-zA-Z0-9_]{4,31}$ ]]; then
        echo 'Неверное имя бота-источника.' >&2
        exit 1
    fi
    umask 077
    printf 'TARGET_CHAT=%s\n' "$target_chat" >> .env
fi

mkdir -p avito_profile
echo 'Собираю приложение (при первом запуске потребуется скачать браузер)...'
sudo docker compose build
sudo docker compose up -d
echo
echo 'Готово. Откройте http://localhost:6080/vnc.html'
echo 'Во вкладке Telegram Web войдите в аккаунт и откройте чат с ботом-источником.'
echo 'Во вкладке Avito войдите в аккаунт. Вкладку Telegram не закрывайте и чат не переключайте.'
echo 'Логи: sudo docker compose logs -f avito-bot'
