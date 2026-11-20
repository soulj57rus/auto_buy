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

umask 077
touch .env
echo 'Нужны три разные страницы списков объявлений личного кабинета Глисы.'
list_ids=()
for i in 1 2 3; do
    glisa_url="$(sed -n "s/^GLISA_ADLIST_URL_${i}=//p" .env | tail -n 1)"
    if [[ "$i" == 1 && -z "$glisa_url" ]]; then
        # Keep the URL from the previous one-list version without asking again.
        glisa_url="$(sed -n 's/^GLISA_ADLIST_URL=//p' .env | tail -n 1)"
    fi
    if [[ -z "$glisa_url" ]]; then
        read -r -p "Адрес страницы Глисы №${i}: " glisa_url
        new_url=1
    else
        new_url=0
    fi
    if [[ ! "$glisa_url" =~ ^https?://[^[:space:]]+/adlist/[0-9]+/?.*$ ]]; then
        echo "Адрес №${i} неверен: нужен полный URL страницы /личныйкабинет/adlist/номер/." >&2
        exit 1
    fi
    if [[ "$glisa_url" =~ /adlist/([0-9]+) ]]; then
        list_id="${BASH_REMATCH[1]}"
    fi
    for previous_id in "${list_ids[@]}"; do
        if [[ "$previous_id" == "$list_id" ]]; then
            echo 'Адреса должны вести на три РАЗНЫХ списка объявлений.' >&2
            exit 1
        fi
    done
    list_ids+=("$list_id")
    if [[ "$new_url" == 1 ]]; then
        printf 'GLISA_ADLIST_URL_%s=%s\n' "$i" "$glisa_url" >> .env
    fi
done

mkdir -p avito_profile data
echo 'Собираю приложение (при первом запуске потребуется скачать браузер)...'
sudo docker compose build
sudo docker compose up -d
echo
echo 'Готово. Откройте http://localhost:6080/vnc.html'
echo 'Во вкладке Глисы войдите в личный кабинет. Во вкладке Avito войдите в аккаунт.'
echo 'Три вкладки Глисы оставьте открытыми: программа обновляет все списки.'
echo 'Логи: sudo docker compose logs -f avito-bot'
