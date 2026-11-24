// Exchanges: unwrapping your pick, opening a letter, and writing one.
// Without JS (or with reduced motion) every <details> just opens.
(function () {
  var calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function csrfToken() {
    var input = document.querySelector('input[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  }

  // Flick through everyone's names, slowing down like a wheel coming to rest
  function shuffleTo(nameEl, decoys, done) {
    var realName = nameEl.textContent;
    var ticks = 0;
    var total = Math.min(14, Math.max(6, decoys.length * 2));
    nameEl.setAttribute('aria-live', 'off');
    function tick() {
      if (ticks >= total || !decoys.length) {
        nameEl.textContent = realName;
        nameEl.setAttribute('aria-live', 'polite');
        done();
        return;
      }
      nameEl.textContent = decoys[Math.floor(Math.random() * decoys.length)];
      ticks += 1;
      setTimeout(tick, 60 + ticks * ticks * 3);
    }
    tick();
  }

  function focusInside(box) {
    var target = box.querySelector('[data-reveal-focus]');
    if (target) target.focus({ preventScroll: false });
  }

  // Your pick has been seen: tell the server quietly, and drop the button
  function markSeen(section) {
    var url = section.getAttribute('data-seen-url');
    var button = section.querySelector('[data-reveal-done]');
    if (!url) return;
    fetch(url, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrfToken(), 'X-Requested-With': 'fetch' },
      credentials: 'same-origin'
    }).then(function (response) {
      if (response.ok && button) button.remove();
    });
  }

  document.querySelectorAll('[data-envelope]').forEach(function (section) {
    var box = section.querySelector('details');
    var summary = box && box.querySelector('summary');
    if (!summary) return;
    var isPick = section.hasAttribute('data-exchange-reveal');
    var busy = false;

    summary.addEventListener('click', function (event) {
      if (box.open) return;
      if (calm) {
        // Let it open natively, then do the bookkeeping
        setTimeout(function () {
          focusInside(box);
          if (isPick) markSeen(section);
        }, 0);
        return;
      }
      event.preventDefault();
      if (busy) return;
      busy = true;
      section.classList.add('is-unwrapping');
      setTimeout(function () {
        box.open = true;
        section.classList.remove('is-unwrapping');
        focusInside(box);
        if (!isPick) {
          section.classList.add('is-revealed');
          return;
        }
        var nameEl = section.querySelector('[data-reveal-name]');
        var decoysEl = document.getElementById('wl-reveal-decoys');
        var decoys = decoysEl ? JSON.parse(decoysEl.textContent) : [];
        section.classList.add('is-shuffling');
        shuffleTo(nameEl, decoys, function () {
          section.classList.remove('is-shuffling');
          section.classList.add('is-revealed');
          markSeen(section);
        });
      }, 700);
    });
  });

  // Arriving from the home page: bring the right card into view
  var target = window.location.hash && document.querySelector(window.location.hash);
  if (target && target.querySelector && target.querySelector('details:not([open])')) {
    target.scrollIntoView({ block: 'center' });
  }
})();

// Writing a letter: a live count, the chosen photo's name, and a draft kept
// in this browser so nothing typed is lost if a save is turned away.
(function () {
  var form = document.querySelector('[data-letter-form]');
  if (!form) return;
  var section = form.closest('[data-draft-key]');
  var key = section ? section.getAttribute('data-draft-key') : null;
  var body = form.querySelector('[data-letter-body]');
  var count = form.querySelector('[data-letter-count]');
  var photo = form.querySelector('[data-letter-photo]');
  var photoName = form.querySelector('[data-letter-photo-name]');

  function store(action, value) {
    try {
      if (action === 'get') return window.localStorage.getItem(key);
      if (action === 'set') window.localStorage.setItem(key, value);
      if (action === 'remove') window.localStorage.removeItem(key);
    } catch (e) { /* private mode: no drafts, nothing breaks */ }
    return null;
  }

  function updateCount() {
    if (count) count.textContent = body.value.length.toLocaleString();
  }

  if (key && body) {
    var saved = body.value;
    var draft = store('get');
    if (draft !== null && draft !== saved && draft.trim()) {
      body.value = draft;
      var note = document.createElement('p');
      note.className = 'wl-exchange-meta';
      note.textContent = 'Picked up your unsaved draft — save it when you’re ready.';
      body.insertAdjacentElement('beforebegin', note);
    } else if (draft !== null) {
      // The saved letter caught up with the draft
      store('remove');
    }
    body.addEventListener('input', function () {
      store('set', body.value);
      updateCount();
    });
  }
  if (body) updateCount();

  if (photo && photoName) {
    photo.addEventListener('change', function () {
      photoName.textContent = photo.files.length ? '📎 ' + photo.files[0].name : '';
    });
  }
})();
