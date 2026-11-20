"""Watch an open Telegram Web chat; click Avito's delivery button, without checkout."""

import asyncio
import logging
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TARGET_CHAT = os.environ.get("TARGET_CHAT", "glisa_bot").lstrip("@")
PROFILE_DIR = Path("/app/avito_profile")
URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
DELIVERY_BUTTON_TEXT = re.compile(r"^Купить с доставкой(?:\s|$)", re.IGNORECASE)
WEB_URL = "https://web.telegram.org/k/"

# Telegram Web K currently uses .bubbles-inner and .bubble[data-mid]. Its HTML
# is not a public API and can change; fail visibly instead of reading other chats.
READ_MESSAGES = """() => {
  const bubbles = [...document.querySelectorAll(
    '.bubbles-inner:not(.bubbles-remover) .bubble[data-mid][data-peer-id]'
  )].filter(el => el.getClientRects().length > 0);
  return {
    hash: location.hash,
    messages: bubbles.map(el => ({
      id: el.dataset.mid,
      peer: el.dataset.peerId,
      outgoing: el.classList.contains('is-outgoing') || el.classList.contains('is-out'),
      text: el.querySelector('.message')?.innerText || '',
      urls: [...el.querySelectorAll('a[href]')].map(a => a.href)
    }))
  };
}"""


def valid_avito_url(value: str) -> str | None:
    url = value.rstrip('.,;:!?)]}\u00bb\u201d\'"')
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() in ("http", "https") and parsed.hostname in ("avito.ru", "www.avito.ru"):
            return url
    except ValueError:
        pass
    return None


def extract_avito_url(message: dict) -> str | None:
    for value in message["urls"]:
        url = valid_avito_url(value)
        if url:
            return url
    for match in URL_PATTERN.finditer(message["text"]):
        url = valid_avito_url(match.group())
        if url:
            return url
    return None


async def click_delivery_button(context, url: str) -> None:
    page = await context.new_page()
    keep_open = False
    try:
        log.info("Открываю предложение: %s", url)
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        if not valid_avito_url(page.url):
            log.warning("Страница перенаправила на другой сайт: %s; ничего не нажимаю", page.url)
            return
        for role in ("button", "link"):
            button = page.get_by_role(role, name=DELIVERY_BUTTON_TEXT).first
            try:
                await button.click(timeout=8000)
                keep_open = True
                log.info("Нажата «Купить с доставкой»: %s. Дальнейшее оформление — вручную.", url)
                await page.wait_for_timeout(3000)
                return
            except Exception as exc:
                log.info("Кнопка «Купить с доставкой» (%s) не сработала: %s", role, exc)
        log.warning("Кнопка «Купить с доставкой» не найдена: %s", url)
    except Exception:
        log.exception("Ошибка при обработке предложения: %s", url)
    finally:
        if not keep_open:
            await page.close()


async def watch_telegram(page, queue: asyncio.Queue[str]) -> None:
    peer = None
    chat_hash = None
    seen: set[str] = set()
    last_warning = None
    log.info("Войдите в Telegram Web и откройте чат с @%s в его вкладке.", TARGET_CHAT)
    while True:
        try:
            if not page.url.startswith(WEB_URL):
                raise ValueError("вкладка Telegram Web закрыта или адрес изменён")
            snapshot = await page.evaluate(READ_MESSAGES)
            messages = snapshot["messages"]
            current_hash = snapshot["hash"]
            peers = {m["peer"] for m in messages}
            if peer is None:
                if len(peers) == 1 and current_hash:
                    peer = peers.pop()
                    chat_hash = current_hash
                    seen.update(m["id"] for m in messages)
                    log.info("Начато наблюдение за открытым чатом (%s). Старые сообщения пропущены.", chat_hash)
                elif messages and len(peers) != 1 and last_warning != "ambiguous":
                    log.warning("Не удалось определить один открытый чат; проверьте вкладку Telegram Web.")
                    last_warning = "ambiguous"
            elif current_hash not in {chat_hash, f"#@{TARGET_CHAT}", f"#{peer}", f"#/im?p={peer}"} or (peers and peers != {peer}):
                if last_warning != "switched":
                    log.warning("Открыт другой чат. Вернитесь к исходному чату @%s; обработка приостановлена.", TARGET_CHAT)
                    last_warning = "switched"
            else:
                last_warning = None
                for message in messages:
                    mid = message["id"]
                    if mid in seen:
                        continue
                    seen.add(mid)
                    if not message["outgoing"]:
                        url = extract_avito_url(message)
                        if url:
                            log.info("Новая ссылка Avito в Telegram Web")
                            queue.put_nowait(url)
        except Exception:
            log.exception("Ошибка чтения Telegram Web; повторю попытку")
        await asyncio.sleep(2)


async def process_links(context, queue: asyncio.Queue[str]) -> None:
    while True:
        url = await queue.get()
        try:
            await click_delivery_button(context, url)
        finally:
            queue.task_done()


async def main() -> None:
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), headless=False, args=["--no-sandbox"],
        )
        try:
            # Use dedicated tabs so opening Avito links cannot navigate the watched chat.
            telegram = await context.new_page()
            avito = await context.new_page()
            for page, address in ((telegram, f"{WEB_URL}#@{TARGET_CHAT}"), (avito, "https://www.avito.ru/")):
                try:
                    await page.goto(address, wait_until="domcontentloaded", timeout=60000)
                except Exception as exc:
                    log.warning("Не удалось открыть %s: %s", address, exc)
            await telegram.bring_to_front()
            log.info("Окно браузера: http://localhost:6080/vnc.html")
            queue: asyncio.Queue[str] = asyncio.Queue()
            await asyncio.gather(watch_telegram(telegram, queue), process_links(context, queue))
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(main())
