(() => {
  const match = location.pathname.match(/_(\d{5,})\/?$/);
  if (!match) return;
  const key = match[1];

  chrome.runtime.sendMessage({ type: 'offer_status', key }).then(result => {
    if (!result?.pending) return;
    if (location.hash === '#block' || document.body?.innerText.includes('Страница не загрузилась из-за проблем с IP')) {
      chrome.runtime.sendMessage({ type: 'offer_blocked', key }).catch(() => {});
      return;
    }

    let tries = 0;
    const timer = setInterval(async () => {
      tries++;
      const button = [...document.querySelectorAll('button, a, [role="button"]')].find(el => {
        const label = (el.innerText || el.getAttribute('aria-label') || '').trim();
        return /^Купить с доставкой(?:\s|$)/i.test(label) && el.getClientRects().length > 0;
      });
      if (!button) {
        if (tries >= 30) {
          clearInterval(timer);
          chrome.runtime.sendMessage({ type: 'offer_missing', key }).catch(() => {});
        }
        return;
      }
      clearInterval(timer);
      // A Stop click while this tab was loading must prevent further clicks.
      const current = await chrome.runtime.sendMessage({ type: 'offer_status', key }).catch(() => null);
      if (!current?.pending) return;
      button.scrollIntoView({ block: 'center' });
      // This is only the first delivery button. Never click checkout/payment.
      button.click();
      chrome.runtime.sendMessage({ type: 'offer_clicked', key }).catch(() => {});
    }, 1000);
  }).catch(() => {});
})();
