/* Photo framer: drag and zoom a chosen photo inside a fixed frame before it's
 * uploaded. Used for profile photos (square, shown under a circle) and list
 * covers (3:1). Wired up from js/app.js.
 *
 * The browser never re-encodes the picture. The original file is uploaded
 * along with four hidden inputs — crop_x, crop_y, crop_w, crop_h — holding the
 * visible box as fractions (0–1) of the photo as the browser shows it
 * (upright). The server does the cropping. Empty inputs mean "not framed":
 * the server then behaves as if this file didn't exist, which is also what
 * happens when the browser can't preview the format.
 *
 * Markup, all inside one <form> that has the four crop inputs:
 *   <div data-framer data-framer-aspect="3" hidden>      width / height
 *     <div data-framer-view tabindex="0"><img data-framer-img></div>
 *     <input type="range" data-framer-zoom min="1" max="4" step="0.01">
 *   </div>
 *
 * The position is kept as fractions of the photo, never in pixels, and drawn
 * with percentages — so it doesn't matter how big the frame is on screen, or
 * whether it was inside a closed modal when the page loaded.
 */
(function () {
  'use strict';

  // The partial that loads this can appear more than once on a page.
  if (window.wlPhotoFramer) { return; }

  var MAX_ZOOM = 4;
  var FIELDS = ['crop_x', 'crop_y', 'crop_w', 'crop_h'];

  function clamp(value, low, high) {
    return Math.min(Math.max(value, low), high);
  }

  function create(root, form) {
    var view = root.querySelector('[data-framer-view]');
    var img = root.querySelector('[data-framer-img]');
    var slider = root.querySelector('[data-framer-zoom]');
    var aspect = parseFloat(root.getAttribute('data-framer-aspect')) || 1;
    var inputs = FIELDS.map(function (name) {
      return form.querySelector('input[name="' + name + '"]');
    });
    if (!view || !img || inputs.indexOf(null) !== -1) { return null; }

    var maxZoom = (slider && parseFloat(slider.max)) || MAX_ZOOM;
    var objectUrl = null;
    var ready = false;
    // Centre of the visible box (fractions of the photo) and zoom (1 = the
    // photo just covers the frame).
    var cx = 0.5, cy = 0.5, zoom = 1;
    // The box at zoom 1, as fractions of the photo.
    var baseW = 1, baseH = 1;

    function box() {
      var w = baseW / zoom, h = baseH / zoom;
      cx = clamp(cx, w / 2, 1 - w / 2);
      cy = clamp(cy, h / 2, 1 - h / 2);
      return {x: cx - w / 2, y: cy - h / 2, w: w, h: h};
    }

    function clearInputs() {
      inputs.forEach(function (input) { input.value = ''; });
    }

    function render() {
      if (!ready) { return; }
      var b = box();
      img.style.width = (100 / b.w) + '%';
      img.style.height = (100 / b.h) + '%';
      img.style.left = (-100 * b.x / b.w) + '%';
      img.style.top = (-100 * b.y / b.h) + '%';
      if (slider) { slider.value = zoom; }

      // Round the size down and keep the box inside the photo, so rounding
      // can never push x + w past 1.
      var w = Math.floor(b.w * 1e5) / 1e5;
      var h = Math.floor(b.h * 1e5) / 1e5;
      var values = [clamp(b.x, 0, 1 - w), clamp(b.y, 0, 1 - h), w, h];
      inputs.forEach(function (input, i) { input.value = values[i].toFixed(5); });
    }

    function setZoom(next) {
      zoom = clamp(next, 1, maxZoom);
      render();
    }

    // Move the photo by a number of screen pixels.
    function moveBy(dx, dy) {
      var b = box();
      var width = view.clientWidth || 1, height = view.clientHeight || 1;
      cx -= dx / width * b.w;
      cy -= dy / height * b.h;
      render();
    }

    function release() {
      if (objectUrl) { URL.revokeObjectURL(objectUrl); }
      objectUrl = null;
    }

    function close() {
      ready = false;
      root.hidden = true;
      img.removeAttribute('src');
      release();
      clearInputs();
    }

    // Show `file` in the frame. callbacks.onReady runs once it's on screen;
    // callbacks.onError if the browser can't show it (the inputs stay empty).
    function open(file, callbacks) {
      callbacks = callbacks || {};
      close();
      var url = URL.createObjectURL(file);
      objectUrl = url;
      img.onload = function () {
        if (objectUrl !== url) { return; }
        var nw = img.naturalWidth, nh = img.naturalHeight;
        if (!nw || !nh) { img.onerror(); return; }
        if (nw / nh > aspect) {
          baseW = nh * aspect / nw; baseH = 1;
        } else {
          baseW = 1; baseH = nw / aspect / nh;
        }
        cx = 0.5; cy = 0.5; zoom = 1;
        ready = true;
        root.hidden = false;
        render();
        if (callbacks.onReady) { callbacks.onReady(); }
      };
      img.onerror = function () {
        if (objectUrl !== url) { return; }
        close();
        if (callbacks.onError) { callbacks.onError(); }
      };
      img.src = url;
    }

    // ---- Drag to move, pinch to zoom ---------------------------------------
    var pointers = {};
    var pinchDistance = 0;

    function pointerList() {
      return Object.keys(pointers).map(function (id) { return pointers[id]; });
    }
    function distance(list) {
      return Math.hypot(list[0].x - list[1].x, list[0].y - list[1].y);
    }

    view.addEventListener('pointerdown', function (event) {
      if (!ready || (event.pointerType === 'mouse' && event.button !== 0)) { return; }
      pointers[event.pointerId] = {x: event.clientX, y: event.clientY};
      try { view.setPointerCapture(event.pointerId); } catch (e) { /* already gone */ }
      var list = pointerList();
      pinchDistance = list.length === 2 ? distance(list) : 0;
      view.classList.add('is-dragging');
    });

    view.addEventListener('pointermove', function (event) {
      var last = pointers[event.pointerId];
      if (!last || !ready) { return; }
      var dx = event.clientX - last.x, dy = event.clientY - last.y;
      last.x = event.clientX; last.y = event.clientY;
      var list = pointerList();
      if (list.length === 1) {
        moveBy(dx, dy);
      } else if (list.length === 2) {
        var now = distance(list);
        if (pinchDistance > 0 && now > 0) { setZoom(zoom * now / pinchDistance); }
        pinchDistance = now;
        moveBy(dx / 2, dy / 2);  // two fingers sliding together still move it
      }
    });

    function pointerEnd(event) {
      delete pointers[event.pointerId];
      pinchDistance = 0;
      if (!pointerList().length) { view.classList.remove('is-dragging'); }
    }
    view.addEventListener('pointerup', pointerEnd);
    view.addEventListener('pointercancel', pointerEnd);

    // Trackpad pinch arrives as ctrl + wheel. A plain wheel is left alone so
    // scrolling the page past the frame still works.
    view.addEventListener('wheel', function (event) {
      if (!ready || !event.ctrlKey) { return; }
      event.preventDefault();
      setZoom(zoom * Math.exp(-event.deltaY * 0.01));
    }, {passive: false});

    // ---- Keyboard ----------------------------------------------------------
    view.addEventListener('keydown', function (event) {
      if (!ready) { return; }
      var step = event.shiftKey ? 40 : 10;
      switch (event.key) {
        case 'ArrowLeft': moveBy(-step, 0); break;
        case 'ArrowRight': moveBy(step, 0); break;
        case 'ArrowUp': moveBy(0, -step); break;
        case 'ArrowDown': moveBy(0, step); break;
        case '+': case '=': setZoom(zoom * 1.1); break;
        case '-': case '_': setZoom(zoom / 1.1); break;
        default: return;
      }
      event.preventDefault();
    });

    if (slider) {
      slider.addEventListener('input', function () {
        if (ready) { setZoom(parseFloat(slider.value) || 1); }
      });
    }

    return {
      open: open,
      close: close,
      isOpen: function () { return ready; },
      focus: function () { try { view.focus({preventScroll: true}); } catch (e) { view.focus(); } }
    };
  }

  window.wlPhotoFramer = {create: create};
})();
