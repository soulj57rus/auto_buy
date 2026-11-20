#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v pacman >/dev/null 2>&1; then
    echo 'Этот установщик предназначен для Arch Linux.' >&2
    exit 1
fi

sudo -v
sudo pacman -S --needed chromium jq

umask 077
touch .env
echo 'Нужны три разные страницы списков объявлений личного кабинета Глисы.'
urls=()
ids=()
for i in 1 2 3; do
    url="$(sed -n "s/^GLISA_ADLIST_URL_${i}=//p" .env | tail -n 1)"
    if [[ "$i" == 1 && -z "$url" ]]; then
        url="$(sed -n 's/^GLISA_ADLIST_URL=//p' .env | tail -n 1)"
    fi
    if [[ -z "$url" ]]; then
        read -r -p "Адрес списка Глисы №${i}: " url
        new_url=1
    else
        new_url=0
    fi
    if [[ ! "$url" =~ ^https?://(glisa\.ru|xn--80afpl5a\.xn--p1ai|глиса\.рф)/[^[:space:]]*/adlist/[0-9]+/?.*$ ]]; then
        echo "Адрес №${i} неверен: нужен полный URL сайта Глисы /личныйкабинет/adlist/номер/." >&2
        exit 1
    fi
    [[ "$url" =~ /adlist/([0-9]+) ]]
    id="${BASH_REMATCH[1]}"
    for previous in "${ids[@]}"; do
        if [[ "$previous" == "$id" ]]; then
            echo 'Адреса должны вести на три РАЗНЫХ списка объявлений.' >&2
            exit 1
        fi
    done
    ids+=("$id")
    urls+=("$url")
    if [[ "$new_url" == 1 ]]; then
        printf 'GLISA_ADLIST_URL_%s=%s\n' "$i" "$url" >> .env
    fi
done

jq -n --arg a "${urls[0]}" --arg b "${urls[1]}" --arg c "${urls[2]}" \
    '{urls: [$a, $b, $c]}' > extension/config.json

# If an old installation is still running, stop only our legacy container.
if command -v docker >/dev/null 2>&1; then
    if sudo docker ps --format '{{.Names}}' 2>/dev/null | grep -Fxq avito_watcher_bot; then
        echo 'Останавливаю старую версию Docker/VNC...'
        sudo docker stop avito_watcher_bot >/dev/null
    fi
fi

mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
printf '#!/usr/bin/env bash\nexec bash %q\n' "$PWD/start.sh" > "$HOME/.local/bin/glisa-avito"
chmod +x "$HOME/.local/bin/glisa-avito"
printf '[Desktop Entry]\nType=Application\nName=Глиса — Avito\nComment=Мониторинг объявлений\nExec="%s/.local/bin/glisa-avito"\nIcon=chromium\nTerminal=false\nCategories=Utility;\n' \
    "$HOME" > "$HOME/.local/share/applications/glisa-avito.desktop"

bash start.sh
echo 'Готово. Далее запускайте через значок «Глиса — Avito» в меню приложений.'
echo 'В обычном Chromium войдите в Avito и Глису, затем нажмите «Я вошёл в Avito — начать».'
