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
