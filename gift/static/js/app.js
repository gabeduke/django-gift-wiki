/* Site-wide behaviour: service worker, the install prompt, toasts.
 * Loaded on every page from the base template. */
(function () {
  'use strict';

  var script = document.currentScript;

  function storageGet(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }
  function storageSet(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* private mode */ }
  }

  // ---- Installed? --------------------------------------------------------
  // iOS reports it through navigator.standalone; everyone else via the media
  // query. The class lets CSS tighten things up when there's no browser chrome.
  var standalone = window.matchMedia('(display-mode: standalone)').matches ||
    window.navigator.standalone === true;
  if (standalone) {
    document.documentElement.classList.add('is-standalone');
  }

  // ---- Service worker ----------------------------------------------------
  var swUrl = script && script.getAttribute('data-sw-url');
  if (swUrl && 'serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register(swUrl).catch(function () {
        // Not fatal: the site works the same, just without the offline page.
      });
    });
  }

  // ---- Toasts ------------------------------------------------------------
  // wlToast('Added!', {actions: [{label: 'View', href: '/x/'}, {label: 'Undo', onClick: fn}]})
  window.wlToast = function (message, options) {
    var region = document.getElementById('wl-toasts');
    if (!region) { return; }
    options = options || {};

    var toast = document.createElement('div');
    toast.className = 'wl-toast' + (options.tone ? ' wl-toast-' + options.tone : '');
    toast.setAttribute('role', 'status');

    var text = document.createElement('span');
    text.className = 'wl-toast-text';
    text.textContent = message;
    toast.appendChild(text);

    function dismiss() {
      toast.classList.add('is-leaving');
      window.setTimeout(function () { toast.remove(); }, 200);
    }

    (options.actions || []).forEach(function (action) {
      var el;
      if (action.href) {
        el = document.createElement('a');
        el.href = action.href;
      } else {
        el = document.createElement('button');
        el.type = 'button';
        el.addEventListener('click', function () {
          dismiss();
          action.onClick();
        });
      }
      el.className = 'wl-toast-action';
      el.textContent = action.label;
      toast.appendChild(el);
    });

    region.appendChild(toast);
    // Long enough to reach for "View list" on a phone.
    window.setTimeout(dismiss, options.duration || 7000);
  };

  // Show a toast on the next page load instead — for when the action that
  // earned it also reloads the page. Only link actions survive the trip.
  var PENDING_KEY = 'wikileet:pending-toast';
  window.wlToast.afterReload = function (message, options) {
    options = options || {};
    var actions = (options.actions || []).filter(function (action) { return action.href; });
    try {
      window.sessionStorage.setItem(PENDING_KEY, JSON.stringify(
        {message: message, tone: options.tone, actions: actions}
      ));
    } catch (e) { /* the toast is a nicety; losing it is fine */ }
  };

  (function showPendingToast() {
    var pending;
    try {
      pending = JSON.parse(window.sessionStorage.getItem(PENDING_KEY) || 'null');
      window.sessionStorage.removeItem(PENDING_KEY);
    } catch (e) {
      return;
    }
    if (pending && pending.message) {
      window.wlToast(pending.message, pending);
    }
  })();

  // ---- Share a link ------------------------------------------------------
  // [data-share-url]: the native share sheet where there is one (phones),
  // otherwise copy the link. Family still has to be signed in to see it.
  document.addEventListener('click', function (event) {
    var button = event.target.closest('[data-share-url]');
    if (!button) { return; }
    event.preventDefault();
    var url = button.getAttribute('data-share-url');
    var title = button.getAttribute('data-share-title') || 'Wikileet';
    if (navigator.share) {
      navigator.share({title: title, url: url}).catch(function () { /* cancelled */ });
      return;
    }
    var copied = navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject();
    copied.then(function () {
      window.wlToast('Link copied — paste it anywhere.', {tone: 'success'});
    }, function () {
      window.prompt('Copy this link:', url);
    });
  });

  // ---- Colour theme --------------------------------------------------------
  // The picker on My Lists switches colour the moment a swatch is tapped,
  // then saves in the background; the theme lives on <html data-theme>.
  var picker = document.querySelector('[data-theme-picker]');
  function applyTheme(key, colour) {
    if (key === 'forest') {
      delete document.documentElement.dataset.theme;
    } else {
      document.documentElement.dataset.theme = key;
    }
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta && colour) { meta.setAttribute('content', colour); }
  }
  if (picker) {
    var saved = picker.querySelector('input[name="theme"]:checked');
    picker.addEventListener('change', function (event) {
      var input = event.target;
      if (input.name !== 'theme') { return; }
      applyTheme(input.value, input.getAttribute('data-colour'));
      fetch(picker.action, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'X-Requested-With': 'XMLHttpRequest'},
        body: new FormData(picker)
      })
        .then(function (response) {
          if (!response.ok) { throw new Error('theme save failed'); }
          saved = input;
        })
        .catch(function () {
          // Put back what's actually saved, so the page doesn't lie.
          if (saved) {
            saved.checked = true;
            applyTheme(saved.value, saved.getAttribute('data-colour'));
          }
          window.wlToast("Couldn't save your colour. Try again?");
        });
    });
  }

  // ---- Install prompt ----------------------------------------------------
  var DISMISS_KEY = 'wikileet:install-dismissed';
  var DISMISS_DAYS = 45;
  var banner = document.getElementById('wl-install-banner');
  var installButtons = document.querySelectorAll('[data-install-app]');
  var deferredPrompt = null;

  function recentlyDismissed() {
    var at = parseInt(storageGet(DISMISS_KEY) || '0', 10);
    return at && (Date.now() - at) < DISMISS_DAYS * 864e5;
  }

  function showBanner(mode) {
    if (!banner || standalone || recentlyDismissed()) { return; }
    banner.querySelector('[data-install-pitch]').hidden = mode === 'ios';
    banner.querySelector('[data-install-ios]').hidden = mode !== 'ios';
    banner.hidden = false;
  }

  function hideBanner() {
    if (banner) { banner.hidden = true; }
  }

  // Chrome, Edge, Samsung Internet: we get to show the real install dialog.
  window.addEventListener('beforeinstallprompt', function (event) {
    event.preventDefault();
    deferredPrompt = event;
    Array.prototype.forEach.call(installButtons, function (button) { button.hidden = false; });
    showBanner('prompt');
  });

  Array.prototype.forEach.call(installButtons, function (button) {
    button.addEventListener('click', function () {
      if (!deferredPrompt) { return; }
      window.jQuery && window.jQuery('#wl-more-sheet').modal('hide');
      deferredPrompt.prompt();
      deferredPrompt.userChoice.finally(function () { deferredPrompt = null; });
    });
  });

  window.addEventListener('appinstalled', function () {
    hideBanner();
    Array.prototype.forEach.call(installButtons, function (button) { button.hidden = true; });
    window.wlToast('Installed — find Wikileet on your home screen. 🎁');
  });

  // iOS can't be prompted; explain the two taps instead. Only Safari (and,
  // since iOS 16.4, other browsers' share sheets) can add to the home screen.
  var ua = window.navigator.userAgent;
  var isIOS = /iPhone|iPad|iPod/.test(ua) ||
    (ua.indexOf('Macintosh') !== -1 && navigator.maxTouchPoints > 1);  // iPadOS
  if (isIOS && !standalone) {
    showBanner('ios');
  }

  if (banner) {
    banner.querySelector('[data-install-dismiss]').addEventListener('click', function () {
      storageSet(DISMISS_KEY, String(Date.now()));
      hideBanner();
    });
  }
})();
