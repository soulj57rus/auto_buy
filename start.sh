#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
umask 077
if [[ ! -f extension/config.json ]]; then
    echo 'Сначала выполните bash setup.sh.' >&2
    exit 1
fi
mkdir -p browser_profile
nohup chromium --user-data-dir="$PWD/browser_profile" \
    --load-extension="$PWD/extension" --no-first-run --no-default-browser-check \
    > browser.log 2>&1 < /dev/null &
echo 'Открываю обычный Chromium на компьютере (без Docker/VNC).'
