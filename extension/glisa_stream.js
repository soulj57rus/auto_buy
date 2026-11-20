// Observe the site's existing live notification request (not its old .b20 replay).
// This code runs in the page's MAIN world; the isolated glisa.js relays events.
(() => {
  const open = XMLHttpRequest.prototype.open;
  const send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__glisaLive = String(url).includes('/stream-sub/') && !String(url).includes('.b20');
    return open.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function (...args) {
    if (this.__glisaLive) {
      this.addEventListener('load', () => {
        if (this.status !== 200) return;
        try {
          const data = JSON.parse(this.responseText);
          if (data && typeof data === 'object' && data.linkId && data.message) {
            window.postMessage({ source: 'glisa-local-monitor', kind: 'live',
              linkId: String(data.linkId), message: String(data.message) }, location.origin);
          }
        } catch (_) { /* Ignore empty heartbeat responses. */ }
      });
    }
    return send.apply(this, args);
  };
})();
