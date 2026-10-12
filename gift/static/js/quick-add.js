/* Quick add: drop a gift idea on any list from anywhere.
 *
 * Opened by any [data-quick-add] element (the nav button, the tab bar's +),
 * the A key, or a URL carrying ?quick_add=1 (the home-screen shortcuts and the
 * Android share target, which can also pass name=, url= and for=me|others).
 *
 * The server decides whether an item is a surprise; nothing here can change
 * that. What this file adds on top is convenience: the list you're looking at
 * is pre-picked, recent lists come first, a pasted link fills in the name, and
 * what's already on the list is checked as you type so the same thing doesn't
 * get added twice.
 */
(function () {
  'use strict';

  var modal = document.getElementById('wl-quick-add-modal');
  if (!modal || !window.jQuery) {
    return;
  }

  var $modal = window.jQuery(modal);
  var form = document.getElementById('wl-qa-form');
  var listInput = document.getElementById('wl-qa-list');
  var results = document.getElementById('wl-qa-results');
  var selected = document.getElementById('wl-qa-selected');
  var selectedLabel = document.getElementById('wl-qa-selected-label');
  var changeButton = document.getElementById('wl-qa-change');
  var surprise = document.getElementById('wl-qa-surprise');
  var surprisePerson = document.getElementById('wl-qa-surprise-person');
  var nameInput = document.getElementById('wl-qa-name');
  var urlInput = document.getElementById('wl-qa-url');
  var errorBox = document.getElementById('wl-qa-error');
  var submitButton = document.getElementById('wl-qa-submit');
  var moreLink = document.getElementById('wl-qa-more');
  var dupes = document.getElementById('wl-qa-dupes');
  var dupesTitle = document.getElementById('wl-qa-dupes-title');
  var dupesList = document.getElementById('wl-qa-dupes-list');
  var glance = document.getElementById('wl-qa-glance');
  var sneaky = document.getElementById('wl-qa-sneaky');
  var sneakyList = document.getElementById('wl-qa-sneaky-list');
  var existing = document.getElementById('wl-qa-existing');
  var existingSummary = document.getElementById('wl-qa-existing-summary');
  var existingList = document.getElementById('wl-qa-existing-list');
  var target = document.getElementById('wl-qa-target');
  var targetButtons = target ? target.querySelectorAll('[data-target]') : [];
  var noList = document.getElementById('wl-qa-no-list');

  var RECENT_KEY = 'wikileet:quick-add:recent';
  var RECENT_MAX = 4;

  var options = null;      // cached picker payload; fetched on first open
  var loading = false;
  var chosen = null;
  var highlighted = -1;
  var pendingListId = null;  // pick this list once options arrive
  var mode = null;           // 'mine' | 'others' | null (everyone)
  var pendingMode = null;    // apply this mode once options arrive
  var glanceItems = null;    // what's on the chosen list, once fetched
  var nameWasDerived = false;

  // ---- Small helpers -----------------------------------------------------

  function csrfToken() {
    var field = form.querySelector('[name=csrfmiddlewaretoken]');
    return field ? field.value : '';
  }

  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = !message;
  }

  function label(option) {
    return option.title + ' · ' + option.person;
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined) { node.textContent = text; }
    return node;
  }

  function readRecent() {
    try {
      var ids = JSON.parse(window.localStorage.getItem(RECENT_KEY) || '[]');
      return Array.isArray(ids) ? ids : [];
    } catch (e) {
      return [];
    }
  }

  function rememberRecent(id) {
    var ids = readRecent().filter(function (other) { return other !== id; });
    ids.unshift(id);
    try {
      window.localStorage.setItem(RECENT_KEY, JSON.stringify(ids.slice(0, RECENT_MAX)));
    } catch (e) { /* private mode: recents just don't stick */ }
  }

  function findOption(id) {
    id = Number(id);
    return (options || []).filter(function (option) { return option.id === id; })[0] || null;
  }

  // ---- Matching: is this already on the list? -----------------------------
  // Deliberately simple and forgiving. Names are reduced to words, minus
  // filler and plurals; an existing item matches when most of the shorter
  // name's words appear in the other. The last word being typed also matches
  // as a prefix, so suggestions appear before you've finished typing.

  var STOP_WORDS = ['the', 'a', 'an', 'and', 'or', 'of', 'for', 'with', 'in', 'on', 'to',
    'my', 'new', 'set', 'pack', 'kit', 'size', 'some', 'any'];

  function stem(word) {
    return word.length > 3 && /s$/.test(word) && !/ss$/.test(word) ? word.slice(0, -1) : word;
  }

  function words(text) {
    var seen = {};
    return (text || '').toLowerCase()
      .normalize('NFKD').replace(/[̀-ͯ]/g, '')
      .replace(/[^a-z0-9]+/g, ' ')
      .split(' ')
      .filter(function (word) { return word.length > 1 && STOP_WORDS.indexOf(word) === -1; })
      .map(stem)
      .filter(function (word) {
        if (seen[word]) { return false; }
        seen[word] = true;
        return true;
      });
  }

  function similarity(typed, candidate, typingLastWord) {
    if (typed.length === 0 || candidate.length === 0) { return 0; }
    var shared = 0;
    typed.forEach(function (word, index) {
      var isLast = index === typed.length - 1;
      var hit = candidate.some(function (other) {
        if (other === word) { return true; }
        return typingLastWord && isLast && word.length >= 3 && other.indexOf(word) === 0;
      });
      if (hit) { shared++; }
    });
    return shared / Math.min(typed.length, candidate.length);
  }

  // Same product, different URL decoration: drop the scheme, www/m., query
  // and fragment, and boil Amazon links down to the product ID.
  function normalizeUrl(value) {
    try {
      var url = new URL(value);
      var asin = url.pathname.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})/i);
      if (asin) { return 'amazon:' + asin[1].toUpperCase(); }
      var host = url.hostname.replace(/^(www|m)\./, '');
      return host + url.pathname.replace(/\/+$/, '').toLowerCase();
    } catch (e) {
      return '';
    }
  }

  function findDuplicates() {
    if (!glanceItems || glanceItems.length === 0) { return []; }
    var typed = words(nameInput.value);
    var typedUrl = normalizeUrl(urlInput.value.trim());
    // While the name still has focus, its last word is probably half-typed.
    var typingLastWord = document.activeElement === nameInput && !/\s$/.test(nameInput.value);

    var scored = [];
    glanceItems.forEach(function (item) {
      var sameLink = typedUrl && item.url && normalizeUrl(item.url) === typedUrl;
      var score = sameLink ? 2 : similarity(typed, words(item.name), typingLastWord);
      if (score >= 0.6) {
        scored.push({item: item, score: score, sameLink: sameLink});
      }
    });
    scored.sort(function (a, b) { return b.score - a.score; });
    return scored.slice(0, 3);
  }

  // inSneakySection: the heading already says these are surprises.
  function itemTags(item, inSneakySection) {
    var tags = [];
    if (item.is_sneaky) {
      var prefix = inSneakySection ? '' : '🤫 ';
      tags.push(item.added_by ? prefix + 'from ' + item.added_by : prefix + 'sneaky');
    }
    if (item.purchased) {
      tags.push('✓ bought');
    }
    return tags;
  }

  function renderItem(item, className, inSneakySection) {
    var li = el('li', className);
    li.appendChild(el('span', 'wl-qa-chip-name', item.name));
    itemTags(item, inSneakySection).forEach(function (tag) {
      li.appendChild(el('span', 'wl-qa-chip-tag', tag));
    });
    return li;
  }

  function updateDuplicates() {
    var matches = findDuplicates();
    dupesList.innerHTML = '';
    dupes.hidden = matches.length === 0;
    submitButton.textContent = matches.length ? 'Add anyway' : 'Add';
    if (matches.length === 0) { return; }

    dupesTitle.textContent = matches.some(function (match) { return match.sameLink; })
      ? '👀 That link is already on the list'
      : '👀 Might already be on the list';
    matches.forEach(function (match) {
      dupesList.appendChild(renderItem(match.item, 'wl-qa-dupe'));
    });
  }

  // ---- What's already on the chosen list ----------------------------------

  function renderGlance() {
    sneakyList.innerHTML = '';
    existingList.innerHTML = '';
    if (!glanceItems) {
      glance.hidden = true;
      return;
    }

    var surprises = glanceItems.filter(function (item) { return item.is_sneaky; });
    var wished = glanceItems.filter(function (item) { return !item.is_sneaky; });

    // Only givers ever receive surprise items, so this never shows to the
    // recipient — the server withholds them, not this check.
    sneaky.hidden = surprises.length === 0;
    surprises.forEach(function (item) {
      sneakyList.appendChild(renderItem(item, 'wl-qa-chip', true));
    });

    if (wished.length === 0) {
      existingSummary.textContent = surprises.length
        ? 'Nothing else on the list yet.'
        : 'Nothing on this list yet — yours will be the first!';
      existing.classList.add('is-empty');
    } else {
      existingSummary.textContent = 'See the ' + wished.length + ' thing' +
        (wished.length === 1 ? '' : 's') + ' already on the list';
      existing.classList.remove('is-empty');
      wished.forEach(function (item) {
        existingList.appendChild(renderItem(item, 'wl-qa-chip'));
      });
    }
    existing.open = false;
    glance.hidden = false;
  }

  function loadGlance(option) {
    glanceItems = null;
    renderGlance();
    updateDuplicates();
    fetch(option.glance_url, {
      headers: {'X-Requested-With': 'XMLHttpRequest'},
      credentials: 'same-origin'
    })
      .then(function (response) {
        if (!response.ok) { throw new Error('glance request failed'); }
        return response.json();
      })
      .then(function (data) {
        if (chosen !== option) { return; }  // they picked another list meanwhile
        glanceItems = data.items || [];
        renderGlance();
        updateDuplicates();
      })
      .catch(function () {
        // Only a nicety; adding still works without it.
      });
  }

  // ---- The list picker ----------------------------------------------------

  function resultOption(option, index) {
    var li = el('li', 'wl-qa-result');
    li.setAttribute('role', 'option');
    li.setAttribute('id', 'wl-qa-result-' + index);
    li.setAttribute('aria-selected', 'false');
    li.appendChild(el('span', 'wl-qa-result-person', option.person));
    li.appendChild(el('span', 'wl-qa-result-title', option.title));
    if (!option.can_add_openly) {
      li.appendChild(el('span', 'wl-qa-result-tag', '🤫'));
    }
    li.addEventListener('mousedown', function (event) {
      event.preventDefault();  // keep focus off the list so blur doesn't close it first
      choose(option);
    });
    return li;
  }

  function groupHeading(text) {
    var li = el('li', 'wl-qa-result-group', text);
    li.setAttribute('role', 'presentation');
    return li;
  }

  function inMode(option) {
    if (mode === 'mine') { return option.is_mine; }
    if (mode === 'others') { return !option.is_mine; }
    return true;
  }

  function renderResults(query) {
    var terms = query.toLowerCase().split(/\s+/).filter(Boolean);
    var pool = (options || []).filter(inMode);
    results.innerHTML = '';
    highlighted = -1;

    if (options === null || (options.length === 0 && loading)) {
      results.appendChild(el('li', 'wl-qa-result-empty', 'Loading lists…'));
    } else if (terms.length === 0) {
      // Nothing typed: lists you've added to lately first, then everyone.
      var recentIds = readRecent();
      var recent = recentIds.map(findOption).filter(function (option) {
        return option && inMode(option);
      });
      var rest = pool.filter(function (option) { return recent.indexOf(option) === -1; });
      var index = 0;
      if (recent.length) {
        results.appendChild(groupHeading('Recent'));
        recent.forEach(function (option) { results.appendChild(resultOption(option, index++)); });
        results.appendChild(groupHeading('Everyone'));
      }
      rest.forEach(function (option) { results.appendChild(resultOption(option, index++)); });
    } else {
      var matched = pool.filter(function (option) {
        var haystack = (option.title + ' ' + option.person).toLowerCase();
        return terms.every(function (term) { return haystack.indexOf(term) !== -1; });
      }).slice(0, 8);
      if (matched.length === 0) {
        results.appendChild(el('li', 'wl-qa-result-empty', 'No lists match'));
      }
      matched.forEach(function (option, i) { results.appendChild(resultOption(option, i)); });
    }
    if (!results.firstChild) {
      results.appendChild(el('li', 'wl-qa-result-empty', 'No lists here yet'));
    }

    results.hidden = false;
    listInput.setAttribute('aria-expanded', 'true');
  }

  function closeResults() {
    results.hidden = true;
    listInput.setAttribute('aria-expanded', 'false');
    listInput.removeAttribute('aria-activedescendant');
    highlighted = -1;
  }

  function moveHighlight(delta) {
    var items = results.querySelectorAll('.wl-qa-result');
    if (items.length === 0) {
      return;
    }
    if (highlighted >= 0 && items[highlighted]) {
      items[highlighted].classList.remove('is-highlighted');
      items[highlighted].setAttribute('aria-selected', 'false');
    }
    highlighted = (highlighted + delta + items.length) % items.length;
    items[highlighted].classList.add('is-highlighted');
    items[highlighted].setAttribute('aria-selected', 'true');
    items[highlighted].scrollIntoView({block: 'nearest'});
    listInput.setAttribute('aria-activedescendant', items[highlighted].id);
  }

  function choose(option, keepFocus) {
    chosen = option;
    pendingListId = null;
    pendingMode = null;
    if (target) { target.hidden = true; }
    noList.hidden = true;
    selectedLabel.textContent = label(option);
    selected.hidden = false;
    listInput.hidden = true;
    closeResults();

    // The server decides this for real on submit; this only sets expectations
    // before the user types, so nobody is surprised by a surprise.
    surprise.hidden = option.can_add_openly;
    surprisePerson.textContent = option.person;

    showError('');
    loadGlance(option);
    if (!keepFocus) {
      nameInput.focus();
    }
  }

  function unchoose() {
    chosen = null;
    glanceItems = null;
    renderGlance();
    updateDuplicates();
    selected.hidden = true;
    selectedLabel.textContent = '';
    surprise.hidden = true;
    if (target) { target.hidden = false; }
    listInput.hidden = false;
    listInput.value = '';
    listInput.focus();
  }

  // ---- Mine / Someone else -----------------------------------------------

  function showMode() {
    Array.prototype.forEach.call(targetButtons, function (button) {
      button.setAttribute('aria-checked', String(button.getAttribute('data-target') === mode));
    });
    listInput.placeholder = mode === 'others' ? 'Search everyone else…'
      : mode === 'mine' ? 'Which of your lists?' : 'Type a name…';
  }

  function setMode(next) {
    mode = next;
    showMode();
    noList.hidden = true;
    if (options === null) {
      pendingMode = next;  // decided once the lists arrive
      return;
    }
    if (mode === 'mine') {
      var mine = options.filter(function (option) { return option.is_mine; });
      // Several lists of your own: the one pinned on My Lists is the one you mean
      var pinned = mine.filter(function (option) { return option.is_pinned; });
      if (mine.length === 1 || pinned.length === 1) {
        choose(pinned[0] || mine[0]);
        return;
      }
      if (mine.length === 0) {
        noList.hidden = false;
        closeResults();
        return;
      }
    }
    listInput.focus();
    renderResults(listInput.value);
  }

  Array.prototype.forEach.call(targetButtons, function (button) {
    button.addEventListener('click', function () {
      var next = button.getAttribute('data-target');
      setMode(mode === next ? null : next);
    });
  });

  // Refreshed on every open, not just the first: a list created since the last
  // open should be pickable without a reload. Cached options stay on screen
  // while the refresh is in flight, so reopening never shows a loading state.
  function loadOptions() {
    if (loading) {
      return;
    }
    loading = true;
    fetch(modal.getAttribute('data-picker-url'), {
      headers: {'X-Requested-With': 'XMLHttpRequest'},
      credentials: 'same-origin'
    })
      .then(function (response) {
        if (!response.ok) { throw new Error('picker request failed'); }
        return response.json();
      })
      .then(function (data) {
        options = data.wishlists || [];
        loading = false;
        if (pendingListId && !chosen) {
          var option = findOption(pendingListId);
          if (option) {
            choose(option, document.activeElement === nameInput);
            return;
          }
        }
        if (pendingMode && !chosen) {
          setMode(pendingMode);
          return;
        }
        if (!results.hidden || document.activeElement === listInput) {
          renderResults(listInput.value);
        }
      })
      .catch(function () {
        loading = false;
        showError('Could not load your lists. Please try again.');
      });
  }

  // ---- Links -------------------------------------------------------------

  // A best guess at a product name from its URL: most shops put a slug like
  // /lego-botanicals-orchid/ in the path. Only used to fill an empty name.
  function nameFromUrl(value) {
    var url;
    try { url = new URL(value); } catch (e) { return ''; }
    var best = '';
    url.pathname.split('/').forEach(function (segment) {
      try { segment = decodeURIComponent(segment); } catch (e) { return; }
      segment = segment.replace(/\.(html?|php|aspx?)$/i, '');
      if (/[a-z]/i.test(segment) && /[-_+]/.test(segment) && segment.length > best.length) {
        best = segment;
      }
    });
    best = best.replace(/[-_+]+/g, ' ').replace(/(\s\d{4,})+$/, '').replace(/\s+/g, ' ').trim();
    if (best.length < 4) { return ''; }
    return (best.charAt(0).toUpperCase() + best.slice(1)).slice(0, 120);
  }

  function fillNameFromUrl() {
    if (nameInput.value.trim() && !nameWasDerived) { return; }
    var guess = nameFromUrl(urlInput.value.trim());
    if (guess) {
      nameInput.value = guess;
      nameWasDerived = true;
    }
  }

  // ---- Open / reset ------------------------------------------------------

  function reset() {
    form.reset();
    chosen = null;
    glanceItems = null;
    pendingListId = null;
    pendingMode = null;
    mode = null;
    showMode();
    if (target) { target.hidden = false; }
    noList.hidden = true;
    nameWasDerived = false;
    renderGlance();
    updateDuplicates();
    selected.hidden = true;
    selectedLabel.textContent = '';
    surprise.hidden = true;
    listInput.hidden = false;
    listInput.value = '';
    closeResults();
    showError('');
    submitButton.disabled = false;
    submitButton.textContent = 'Add';
  }

  // open({listId, target, name, url}) — every field optional. target is
  // 'mine' or 'others'.
  function open(prefill) {
    prefill = prefill || {};
    if (prefill.name) { nameInput.value = prefill.name; }
    if (prefill.url) {
      urlInput.value = prefill.url;
      fillNameFromUrl();
    }
    var listId = prefill.listId || document.body.getAttribute('data-quick-add-list');
    if (listId && !chosen) {
      var option = findOption(listId);
      if (option) {
        choose(option, true);
      } else {
        pendingListId = listId;
      }
    } else if (prefill.target && !chosen) {
      setMode(prefill.target);
    }
    loadOptions();
    $modal.modal('show');
  }

  window.wlQuickAdd = {open: open};

  // ---- Wiring ------------------------------------------------------------

  document.addEventListener('click', function (event) {
    var trigger = event.target.closest('[data-quick-add]');
    if (trigger) {
      event.preventDefault();
      // A trigger can name its own list (each card on My Lists does);
      // otherwise open() falls back to the list the page is about.
      open({listId: trigger.getAttribute('data-quick-add-list') || null});
    }
  });

  // A (or +) opens quick add from anywhere, unless you're typing somewhere.
  document.addEventListener('keydown', function (event) {
    if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) { return; }
    if (event.key !== 'a' && event.key !== 'A' && event.key !== '+') { return; }
    var target = event.target;
    if (target.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"]')) { return; }
    if (document.querySelector('.modal.show')) { return; }
    event.preventDefault();
    open();
  });

  $modal.on('shown.bs.modal', function () {
    if (chosen || pendingListId) {
      nameInput.focus();
    } else {
      listInput.focus();
    }
  });
  $modal.on('hidden.bs.modal', reset);

  listInput.addEventListener('focus', function () { renderResults(listInput.value); });
  listInput.addEventListener('input', function () { renderResults(listInput.value); });
  listInput.addEventListener('blur', function () {
    window.setTimeout(closeResults, 120);  // let a click on a result land first
  });

  listInput.addEventListener('keydown', function (event) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (results.hidden) { renderResults(listInput.value); }
      moveHighlight(1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      moveHighlight(-1);
    } else if (event.key === 'Enter') {
      // Enter picks a list rather than submitting a form with no list chosen.
      event.preventDefault();
      var items = results.querySelectorAll('.wl-qa-result');
      var index = highlighted >= 0 ? highlighted : 0;
      if (items[index]) {
        items[index].dispatchEvent(new MouseEvent('mousedown'));
      }
    } else if (event.key === 'Escape' && !results.hidden) {
      event.stopPropagation();  // close the dropdown before the modal
      closeResults();
    }
  });

  changeButton.addEventListener('click', unchoose);

  nameInput.addEventListener('input', function () {
    nameWasDerived = false;
    // A link pasted into the name box belongs in the link box.
    var value = nameInput.value.trim();
    if (/^https?:\/\/\S+$/i.test(value)) {
      if (!urlInput.value.trim()) {
        urlInput.value = value;
      }
      nameInput.value = '';
      fillNameFromUrl();
    }
    updateDuplicates();
  });
  nameInput.addEventListener('blur', updateDuplicates);

  urlInput.addEventListener('input', function () {
    fillNameFromUrl();
    updateDuplicates();
  });

  moreLink.addEventListener('click', function (event) {
    event.preventDefault();
    if (!chosen) {
      showError('Pick a list first.');
      listInput.focus();
      return;
    }
    var params = [];
    if (nameInput.value.trim()) {
      params.push('name=' + encodeURIComponent(nameInput.value.trim()));
    }
    if (urlInput.value.trim()) {
      params.push('url=' + encodeURIComponent(urlInput.value.trim()));
    }
    // The server already resolved which form this list needs.
    window.location.href = chosen.more_options_url + (params.length ? '?' + params.join('&') : '');
  });

  form.addEventListener('submit', function (event) {
    event.preventDefault();

    if (!chosen) {
      showError('Pick a list first.');
      listInput.focus();
      return;
    }
    if (!nameInput.value.trim()) {
      showError('Give the item a name.');
      nameInput.focus();
      return;
    }

    var option = chosen;
    var restoreLabel = submitButton.textContent;
    showError('');
    submitButton.disabled = true;
    submitButton.textContent = 'Adding…';

    function failed(message) {
      showError(message);
      submitButton.disabled = false;
      submitButton.textContent = restoreLabel;
    }

    fetch(modal.getAttribute('data-submit-url'), {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken()
      },
      body: JSON.stringify({
        wishlist_id: option.id,
        name: nameInput.value.trim(),
        url: urlInput.value.trim()
      })
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return {ok: response.ok, data: data};
        });
      })
      .then(function (result) {
        if (!result.ok) {
          failed(result.data.message || 'Could not add that item.');
          return;
        }
        rememberRecent(option.id);
        $modal.modal('hide');
        if (!window.wlToast) {
          return;
        }
        var tone = result.data.is_sneaky ? 'sneaky' : 'success';
        // Added to the list on screen: reload so the new item shows up, and
        // carry the confirmation across.
        if (String(option.id) === document.body.getAttribute('data-quick-add-list')) {
          window.wlToast.afterReload(result.data.message, {tone: tone});
          window.location.reload();
          return;
        }
        window.wlToast(result.data.message, {
          tone: tone,
          actions: [
            {label: 'View list', href: result.data.wishlist.url},
            {label: 'Add another', onClick: function () { open({listId: option.id}); }}
          ]
        });
      })
      .catch(function () {
        failed(navigator.onLine === false
          ? "You're offline — try again when you're back online."
          : 'Could not add that item. Please try again.');
      });
  });

  // ---- Deep links --------------------------------------------------------
  // ?quick_add=1[&for=me|others][&name=…][&url=…] from a home-screen shortcut or the share
  // sheet. Strip the params afterwards so a reload doesn't reopen it.
  var params = new URLSearchParams(window.location.search);
  if (params.get('quick_add') === '1') {
    var prefill = {
      name: params.get('name') || '',
      url: params.get('url') || '',
      target: {me: 'mine', others: 'others'}[params.get('for')] || null
    };
    ['quick_add', 'name', 'url', 'for'].forEach(function (key) { params.delete(key); });
    var rest = params.toString();
    window.history.replaceState(null, '', window.location.pathname + (rest ? '?' + rest : ''));
    open(prefill);
  }
})();
