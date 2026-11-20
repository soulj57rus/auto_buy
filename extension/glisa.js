(() => {
  const match = decodeURIComponent(location.pathname).match(/^\/личныйкабинет\/adlist\/(\d+)(?:\/|$)/);
  if (!match) return;
  const listId = match[1];
  const send = (data) => chrome.runtime.sendMessage(data).catch(() => {});

  function scan() {
    if (!document.body?.innerText.includes('Сохраненные объявления для ссылки')) return;
    // The search URL in the page header is NOT an individual offer.
    const links = [...document.querySelectorAll('a.adlisthref[href]')].map(a => a.href);
    send({ type: 'list', listId, links });
  }

  window.addEventListener('message', event => {
    if (event.source !== window || event.origin !== location.origin ||
        event.data?.source !== 'glisa-local-monitor' || event.data.kind !== 'live' ||
        event.data.linkId !== listId) return;
    const links = [...event.data.message.matchAll(/https?:\/\/(?:www\.)?avito\.ru\/[^\s"'<>]+/gi)]
      .map(match => match[0].replaceAll('&amp;', '&'));
    send({ type: 'live', listId, links });
  });

  scan();
  setInterval(scan, 3000);
  // The listing HTML is server-rendered. Refresh to catch offers not included
  // in a live notification; never refresh the login form.
  setInterval(async () => {
    const { ready } = await chrome.storage.local.get('ready');
    if (ready) location.reload();
  }, 30000);
})();
