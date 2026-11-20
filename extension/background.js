let serial = Promise.resolve();
let booting = false;

async function config() {
  const response = await fetch(chrome.runtime.getURL('config.json'));
  if (!response.ok) throw new Error('Missing config.json: run setup.sh');
  const data = await response.json();
  if (!Array.isArray(data.urls) || data.urls.length !== 3) throw new Error('Three Glisa URLs required');
  return data.urls;
}

function listId(raw) {
  try {
    const url = new URL(raw);
    if (!['glisa.ru', 'xn--80afpl5a.xn--p1ai'].includes(url.hostname)) return null;
    return decodeURIComponent(url.pathname).match(/^\/личныйкабинет\/adlist\/(\d+)(?:\/|$)/)?.[1] || null;
  } catch (_) { return null; }
}

function offer(raw) {
  try {
    const url = new URL(raw);
    if (!['avito.ru', 'www.avito.ru'].includes(url.hostname) || !['http:', 'https:'].includes(url.protocol)) return null;
    const key = url.pathname.match(/_(\d{5,})\/?$/)?.[1];
    return key ? { key, url: url.href } : null;
  } catch (_) { return null; }
}

async function ensureTabs() {
  if (booting) return;
  booting = true;
  try {
    await chrome.storage.local.set({ lastScans: {} });
    const urls = await config();
    const tabs = await chrome.tabs.query({});
    // Open only the first list until the user completes the Glisa login.
    if (!tabs.some(tab => listId(tab.url) === listId(urls[0]))) {
      await chrome.tabs.create({ url: urls[0], active: false });
    }
    if (!tabs.some(tab => tab.url?.startsWith('https://www.avito.ru/'))) {
      await chrome.tabs.create({ url: 'https://www.avito.ru/', active: false });
    }
    if (!tabs.some(tab => tab.url?.startsWith(chrome.runtime.getURL('welcome.html')))) {
      await chrome.tabs.create({ url: chrome.runtime.getURL('welcome.html'), active: true });
    }
    // On restart, an opened offer's tab may no longer exist.
    const { pending = {} } = await chrome.storage.local.get('pending');
    for (const item of Object.values(pending)) {
      if (item.state === 'opened' && !tabs.some(tab => tab.id === item.tabId)) item.state = 'waiting';
    }
    await chrome.storage.local.set({ pending });
    await pump();
  } catch (error) { console.error('Glisa start:', error); }
  finally { booting = false; }
}

async function pump() {
  const { pending = {}, ready } = await chrome.storage.local.get(['pending', 'ready']);
  if (!ready || Object.values(pending).some(item => item.state === 'opened' || item.state === 'blocked' || item.state === 'missing')) return;
  const entry = Object.entries(pending).find(([, item]) => item.state === 'waiting');
  if (!entry) return;
  const [key, item] = entry;
  item.state = 'opened';
  pending[key] = item;
  await chrome.storage.local.set({ pending });
  try {
    const tab = await chrome.tabs.create({ url: item.url, active: true });
    item.tabId = tab.id;
    await chrome.storage.local.set({ pending });
  } catch (error) {
    item.state = 'waiting';
    await chrome.storage.local.set({ pending });
    throw error;
  }
}

async function handle(message, sender) {
  if ((message.type === 'activate' || message.type === 'pause') &&
      sender.url?.startsWith(chrome.runtime.getURL('welcome.html'))) {
    if (message.type === 'pause') {
      await chrome.storage.local.set({ ready: false, lastScans: {},
        lastActivity: 'Мониторинг остановлен вручную' });
      return { ok: true };
    }
    await chrome.storage.local.set({ ready: true });
    const { pending = {} } = await chrome.storage.local.get('pending');
    for (const item of Object.values(pending)) {
      if (item.state !== 'opened' || !item.tabId) continue;
      try {
        await chrome.tabs.reload(item.tabId);
      } catch (_) {
        item.state = 'waiting';
      }
    }
    await chrome.storage.local.set({ pending, lastActivity: 'Мониторинг запущен' });
    await pump();
    return { ok: true };
  }
  if (message.type === 'list' || message.type === 'live') {
    const urls = await config();
    if (!urls.some(url => listId(url) === message.listId) || listId(sender.tab?.url) !== message.listId) return;
    const offers = (message.links || []).map(offer).filter(Boolean);
    if (message.type === 'list' && message.listId === listId(urls[0])) {
      const tabs = await chrome.tabs.query({});
      for (const url of urls.slice(1)) {
        if (!tabs.some(tab => listId(tab.url) === listId(url))) {
          await chrome.tabs.create({ url, active: false });
        }
      }
    }
    const { seen = {}, pending = {}, ready, lastScans = {} } = await chrome.storage.local.get(
      ['seen', 'pending', 'ready', 'lastScans']);
    if (message.type === 'list' && ready && Date.now() - (lastScans[message.listId] || 0) > 10000) {
      lastScans[message.listId] = Date.now();
      await chrome.storage.local.set({ lastScans });
    }
    if (message.type === 'list' && !Object.hasOwn(seen, message.listId)) {
      seen[message.listId] = offers.map(item => item.key);
      await chrome.storage.local.set({ seen, lastActivity: `Список ${message.listId} подключён: старые объявления пропущены` });
      console.log('Glisa list', message.listId, 'connected; old ads skipped:', offers.length);
      return;
    }
    if (!ready || !Object.hasOwn(seen, message.listId)) return;
    const allKeys = new Set(Object.values(seen).flat());
    let discovered = 0;
    for (const item of (message.type === 'list' ? offers.reverse() : offers)) {
      if (seen[message.listId].includes(item.key)) continue;
      seen[message.listId].push(item.key);
      discovered++;
      if (!allKeys.has(item.key) && !pending[item.key]) {
        pending[item.key] = { url: item.url, state: 'waiting' };
        console.log('New Glisa offer:', message.listId, item.url);
      }
      allKeys.add(item.key);
    }
    if (!discovered) return;
    await chrome.storage.local.set({ seen, pending,
      lastActivity: `Новые объявления в списке ${message.listId}: ${discovered}` });
    await pump();
    return;
  }
  if (message.type?.startsWith('offer_')) {
    const { pending = {}, ready } = await chrome.storage.local.get(['pending', 'ready']);
    const item = pending[message.key];
    if (message.type === 'offer_status') {
      return { pending: !!ready && !!item && offer(sender.tab?.url)?.key === message.key };
    }
    if (!item) return;
    if (item.tabId !== sender.tab?.id && offer(sender.tab?.url)?.key !== message.key) return;
    if (message.type === 'offer_clicked') {
      delete pending[message.key];
      console.log('Delivery button click attempted:', item.url);
      await chrome.storage.local.set({ lastActivity: `Попытка нажать «Купить с доставкой»: ${item.url}` });
    } else if (message.type === 'offer_blocked') {
      item.state = 'blocked';
      console.warn('Avito blocked. Offer saved:', item.url);
      await chrome.storage.local.set({ lastActivity: 'Avito ограничил доступ; объявление осталось в очереди' });
    } else if (message.type === 'offer_missing') {
      item.state = 'missing';
      console.warn('Delivery button not found. Offer saved:', item.url);
      await chrome.storage.local.set({ lastActivity: 'Кнопка доставки не найдена; проверьте вкладку Avito вручную' });
    }
    await chrome.storage.local.set({ pending });
    await pump();
  }
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  serial = serial.then(() => handle(message, sender)).then(value => respond(value || {}))
    .catch(error => { console.error(error); respond({ error: String(error) }); });
  return true;
});

chrome.runtime.onInstalled.addListener(ensureTabs);
chrome.runtime.onStartup.addListener(ensureTabs);
chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (!change.url || !new URL(change.url).hash.includes('block')) return;
  serial = serial.then(async () => {
    const { pending = {} } = await chrome.storage.local.get('pending');
    const item = Object.values(pending).find(entry => entry.tabId === tabId);
    if (!item) return;
    item.state = 'blocked';
    await chrome.storage.local.set({ pending, lastActivity: 'Avito показал #block; объявление осталось в очереди' });
  }).catch(console.error);
});
