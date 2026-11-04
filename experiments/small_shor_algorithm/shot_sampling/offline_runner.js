/* Self-contained worker adapter. No HTTP calls or runtime downloads. */
(function () {
  'use strict';
  const plans = JSON.parse(document.getElementById('offline-plans').textContent);
  const defaults = JSON.parse(document.getElementById('offline-defaults').textContent);
  const source = JSON.parse(document.getElementById('offline-worker').textContent);
  window.ShorOffline = {
    defaults,
    run(request, signal) {
      return new Promise((resolve, reject) => {
        if (signal.aborted) { reject(new DOMException('Cancelled', 'AbortError')); return; }
        const url = URL.createObjectURL(new Blob([source], {type: 'text/javascript'}));
        let worker;
        const cleanup = () => {
          if (worker) worker.terminate();
          URL.revokeObjectURL(url);
          signal.removeEventListener('abort', cancel);
        };
        const cancel = () => { cleanup(); reject(new DOMException('Cancelled', 'AbortError')); };
        try {
          worker = new Worker(url);
          signal.addEventListener('abort', cancel, {once: true});
          worker.onmessage = event => {
            cleanup();
            if (event.data.error) reject(new Error(event.data.error));
            else resolve(event.data.result);
          };
          worker.onerror = event => { cleanup(); reject(new Error(event.message || '浏览器采样失败。')); };
          worker.postMessage({plan: plans[String(request.n)], request});
        } catch (error) { cleanup(); reject(error); }
      });
    }
  };
})();
