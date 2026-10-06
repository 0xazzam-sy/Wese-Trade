// Bundled shell page: startup progress, startup errors and crash recovery.
// It can only call the lifecycle commands granted in capabilities/local-shell.json.
(function () {
  'use strict';
  var invoke = window.__TAURI__.core.invoke;
  var REASONS = {
    migration_failed: 'فشل تحديث قاعدة البيانات. أُعيدت النسخة الأصلية دون أي فقدان للبيانات.',
    config_error: 'خطأ في إعدادات التشغيل المحلية.',
    port_in_use: 'تعذر حجز منفذ محلي للخدمة.',
    health_timeout: 'استغرقت الخدمة وقتاً أطول من المتوقع للبدء.',
    backend_exited: 'توقفت الخدمة أثناء البدء.',
  };

  function show(id) {
    ['starting', 'failed', 'crashed'].forEach(function (s) {
      document.getElementById(s).hidden = s !== id;
    });
    document.getElementById('actions').hidden = id === 'starting';
  }

  function render(status) {
    if (status.state === 'failed') {
      var reason = REASONS[status.reason] || 'حدث خطأ غير متوقع أثناء التشغيل.';
      document.getElementById('failed-reason').textContent = reason;
      show('failed');
    } else if (status.state === 'crashed') {
      show('crashed');
    } else {
      show('starting');
    }
  }

  // One request at a time, and the page navigates only from a completed response: a
  // navigation while an IPC request is in flight can abort the app on macOS.
  function poll() {
    invoke('startup_status').then(function (status) {
      if (status.state === 'ready') {
        invoke('app_location').then(function (url) {
          if (url) window.location.replace(url);
          else setTimeout(poll, 400);
        }, function () {
          setTimeout(poll, 1000);
        });
        return;
      }
      render(status);
      if (status.state === 'crashed') {
        setTimeout(poll, 1000); // follows a service restart
      } else if (status.state !== 'failed') {
        setTimeout(poll, 400);
      }
    }, function () {
      setTimeout(poll, 1000);
    });
  }

  document.getElementById('restart-service').addEventListener('click', function () {
    show('starting');
    invoke('restart_backend').then(poll, poll);
  });
  document.getElementById('open-logs').addEventListener('click', function () {
    invoke('open_logs_dir');
  });
  document.getElementById('restart-app').addEventListener('click', function () {
    invoke('restart_app');
  });
  poll();
})();
