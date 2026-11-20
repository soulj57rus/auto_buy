const status = document.getElementById('status');
const errorBox = document.getElementById('error');

async function render() {
  try {
    const { ready, seen = {}, pending = {}, lastActivity, lastScans = {} } = await chrome.storage.local.get(
      ['ready', 'seen', 'pending', 'lastActivity', 'lastScans']);
    const active = Object.values(lastScans).filter(at => Date.now() - at < 90000).length;
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
    document.getElementById('lists').textContent = `Списков в истории: ${Object.keys(seen).length} из 3. Объявлений в очереди: ${Object.keys(pending).length}.`;
    document.getElementById('activity').textContent = lastActivity || '';
  } catch (error) {
    errorBox.textContent = `Не удалось прочитать статус: ${error.message}. Перезапустите Chromium через значок «Глиса — Avito».`;
  }
}

async function setMonitoring(ready) {
  errorBox.textContent = '';
  try {
    await chrome.storage.local.set({
      ready,
      lastScans: {},
      lastActivity: ready ? 'Мониторинг запущен' : 'Мониторинг остановлен вручную'
    });
    await render();
  } catch (error) {
    errorBox.textContent = `Не удалось переключить мониторинг: ${error.message}. Закройте Chromium и запустите его снова.`;
  }
}

document.getElementById('start').addEventListener('click', () => setMonitoring(true));
document.getElementById('stop').addEventListener('click', () => setMonitoring(false));
chrome.storage.onChanged.addListener(render);
setInterval(render, 10000);
render();
