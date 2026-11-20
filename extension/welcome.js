async function render() {
  const { ready, seen = {}, pending = {}, lastActivity, lastScans = {} } = await chrome.storage.local.get(
    ['ready', 'seen', 'pending', 'lastActivity', 'lastScans']);
  const active = Object.values(lastScans).filter(at => Date.now() - at < 90000).length;
  const status = document.getElementById('status');
  if (!ready) {
    status.className = 'stopped';
    status.textContent = '● СТОП — мониторинг остановлен';
  } else if (active < 3) {
    status.className = 'starting';
    status.textContent = `● СТАРТ — подключение страниц Глисы (${active} из 3)`;
  } else {
    status.className = 'running';
    status.textContent = '● СТАРТ — мониторинг идёт';
  }
  document.getElementById('start').disabled = !!ready;
  document.getElementById('stop').disabled = !ready;
  document.getElementById('lists').textContent = `Списков в истории: ${Object.keys(seen).length} из 3. Объявлений в очереди: ${Object.keys(pending).length}.`;
  document.getElementById('activity').textContent = lastActivity || '';
}

render();
setInterval(render, 10000);
chrome.storage.onChanged.addListener(render);
document.getElementById('start').addEventListener('click', async () => {
  await chrome.runtime.sendMessage({ type: 'activate' });
  await render();
});
document.getElementById('stop').addEventListener('click', async () => {
  await chrome.runtime.sendMessage({ type: 'pause' });
  await render();
});
