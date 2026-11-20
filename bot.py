"""Watch the Glisa account's listing page and open new Avito offers."""

import asyncio
import html
import json
import logging
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from playwright.async_api import async_playwright


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PROFILE_DIR = Path("/app/avito_profile")
DATA_DIR = Path("/app/data")
GLISA_URLS = tuple(
    os.environ.get(f"GLISA_ADLIST_URL_{i}") or (os.environ.get("GLISA_ADLIST_URL") if i == 1 else None)
    for i in range(1, 4)
)
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
DELIVERY_BUTTON_TEXT = re.compile(r"^Купить с доставкой(?:\s|$)", re.IGNORECASE)
LINK_PATH = re.compile(r"^/личныйкабинет/adlist/(\d+)(?:/|$)")
AD_ID = re.compile(r"_(\d{5,})$")

# Only offer links in the saved-ad table. The search URL above that table is
# also an Avito URL, but it is NOT an individual offer.
READ_LIST = """() => ({
  ready: document.body.innerText.includes('Сохраненные объявления для ссылки'),
  links: [...document.querySelectorAll('a.adlisthref[href]')].map(a => a.href)
})"""


def list_id(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").encode("idna").decode("ascii")
        match = LINK_PATH.match(unquote(parsed.path))
        if parsed.scheme in ("http", "https") and host in ("glisa.ru", "xn--80afpl5a.xn--p1ai") and match:
            return match.group(1)
    except (ValueError, UnicodeError):
        pass
    return None


def valid_avito_url(value: str) -> str | None:
    url = value.rstrip('.,;:!?)]}\u00bb\u201d\'"')
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() in ("http", "https") and parsed.hostname in ("avito.ru", "www.avito.ru"):
            return url
    except ValueError:
        pass
    return None


def offer_key(url: str) -> str:
    path = urlsplit(url).path
    match = AD_ID.search(path)
    return match.group(1) if match else path


def extract_notification_url(message: str) -> str | None:
    # Live Glisa events carry HTML in their `message` field. HTML entities may
    # encode query strings, so decode before looking for links.
    for match in URL_PATTERN.finditer(html.unescape(message)):
        url = valid_avito_url(match.group())
        if url and AD_ID.search(urlsplit(url).path):
            return url
    return None


class SeenOffers:
    def __init__(self, link_id: str):
        self.link_id = link_id
        self.state_file = DATA_DIR / f"seen_ads_{link_id}.json"
        self.ready = False
        self.keys: set[str] = set()
        for path in (self.state_file, DATA_DIR / "seen_ads.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("link_id") == link_id and isinstance(data.get("seen"), list):
                    self.keys = set(map(str, data["seen"]))
                    self.ready = True
                    log.info("Восстановлена история списка %s (%d объявлений).", link_id, len(self.keys))
                    break
            except FileNotFoundError:
                continue
            except (OSError, ValueError, TypeError):
                log.exception("Не удалось прочитать историю из %s", path)

    def save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self.state_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps({"link_id": self.link_id, "seen": sorted(self.keys)}), encoding="utf-8")
        temp_file.replace(self.state_file)

    def add(self, url: str, queue: asyncio.Queue[str], global_keys: set[str]) -> None:
        key = offer_key(url)
        if key in self.keys:
            return
        self.keys.add(key)
        # Record before clicking: a failed/partial click must not be retried
        # indefinitely on every refresh of the listing page.
        self.save()
        if key in global_keys:
            return
        global_keys.add(key)
        log.info("Новое объявление в списке %s: %s", self.link_id, url)
        queue.put_nowait(url)


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


async def watch_glisa(page, glisa_url: str, queue: asyncio.Queue[str],
                      seen: SeenOffers, global_keys: set[str],
                      primary_page=None, primary_id: str | None = None,
                      login_ready: asyncio.Event | None = None) -> None:
    expected_id = list_id(glisa_url)
    if primary_page is not None:
        # Open secondary lists only after the user logs in on the first tab.
        await login_ready.wait()

    refresh_soon = asyncio.Event()

    async def on_response(response):
        try:
            parsed = urlsplit(response.url)
            if "/stream-sub/" not in parsed.path or ".b20" in parsed.path or response.status != 200:
                return
            data = await response.json()
            if not isinstance(data, dict) or str(data.get("linkId")) != expected_id:
                return
            if not seen.ready:
                return
            url = extract_notification_url(str(data.get("message", "")))
            if url:
                seen.add(url, queue, global_keys)
            else:
                # Some notifications do not include a direct URL; reread table.
                refresh_soon.set()
        except Exception:
            log.exception("Не удалось обработать уведомление Глисы; будет проверена таблица")
            refresh_soon.set()

    page.on("response", on_response)
    log.info("Ожидаю список Глисы %s: %s", expected_id, glisa_url)
    waiting_for_login = False
    while True:
        try:
            if list_id(page.url) != expected_id:
                if "войти" in unquote(urlsplit(page.url).path):
                    if not waiting_for_login:
                        log.warning("Список %s: войдите в Глису через http://localhost:6080/vnc.html", expected_id)
                        waiting_for_login = True
                    if primary_page is not None and list_id(primary_page.url) == primary_id:
                        await page.goto(glisa_url, wait_until="domcontentloaded", timeout=60000)
                        continue
                    await asyncio.sleep(5)
                    continue
                await page.goto(glisa_url, wait_until="domcontentloaded", timeout=60000)
            snapshot = await page.evaluate(READ_LIST)
            if not snapshot["ready"]:
                log.warning("Список %s: таблица объявлений пока не видна; проверю снова", expected_id)
                await asyncio.sleep(10)
                await page.reload(wait_until="domcontentloaded", timeout=60000)
                continue

            waiting_for_login = False
            if login_ready is not None and primary_page is None:
                login_ready.set()
            urls = [url for value in snapshot["links"] if (url := valid_avito_url(value))]
            if not seen.ready:
                seen.keys.update(offer_key(url) for url in urls)
                seen.save()
                global_keys.update(seen.keys)
                seen.ready = True
                log.info("Список %s подключён. %d прежних объявлений пропущено.", expected_id, len(urls))
            else:
                for url in reversed(urls):
                    seen.add(url, queue, global_keys)

            try:
                await asyncio.wait_for(refresh_soon.wait(), timeout=30)
                refresh_soon.clear()
                await asyncio.sleep(2)
            except asyncio.TimeoutError:
                pass
            await page.reload(wait_until="domcontentloaded", timeout=60000)
        except Exception:
            log.exception("Ошибка чтения списка %s; повторю через 10 секунд", expected_id)
            await asyncio.sleep(10)


async def process_links(context, queue: asyncio.Queue[str]) -> None:
    while True:
        url = await queue.get()
        try:
            await click_delivery_button(context, url)
        finally:
            queue.task_done()


async def main() -> None:
    ids = [list_id(url) if url else None for url in GLISA_URLS]
    if None in ids or len(set(ids)) != 3:
        raise ValueError("Укажите три РАЗНЫХ адреса списков Глисы в GLISA_ADLIST_URL_1/2/3")
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), headless=False, args=["--no-sandbox"],
        )
        try:
            glisa_pages = [await context.new_page() for _ in GLISA_URLS]
            avito = await context.new_page()
            for page, address in ((glisa_pages[0], GLISA_URLS[0]), (avito, "https://www.avito.ru/")):
                try:
                    await page.goto(address, wait_until="domcontentloaded", timeout=60000)
                except Exception as exc:
                    log.warning("Не удалось открыть %s: %s", address, exc)
            await glisa_pages[0].bring_to_front()
            log.info("Окно браузера: http://localhost:6080/vnc.html")
            queue: asyncio.Queue[str] = asyncio.Queue()
            login_ready = asyncio.Event()
            histories = [SeenOffers(link_id) for link_id in ids]
            global_keys = set().union(*(history.keys for history in histories))
            watchers = [
                watch_glisa(page, url, queue, histories[i], global_keys,
                            primary_page=glisa_pages[0] if i else None,
                            primary_id=ids[0], login_ready=login_ready)
                for i, (page, url) in enumerate(zip(glisa_pages, GLISA_URLS))
            ]
            await asyncio.gather(*watchers, process_links(context, queue))
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(main())
