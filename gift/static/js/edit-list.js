/* Edit List: add item cards, toggle removal, create categories inline.
 *
 * The item cards are an ordinary Django formset rendered on the server, so
 * the page works without this file. This only adds conveniences on top:
 * cloning the blank card from <template id="wl-empty-item">, fading a card
 * marked for removal, and the "+ New" category modal.
 */
(function () {
  'use strict';

  var script = document.currentScript;
  var form = document.getElementById('wishlist-form');
  var list = document.getElementById('wl-edit-items');
  var template = document.getElementById('wl-empty-item');
  var totalForms = form && form.querySelector('[name$="-TOTAL_FORMS"]');
  var count = document.getElementById('wl-item-count');
  if (!form || !list || !template || !totalForms) {
    return;
  }

  function liveCards() {
    return list.querySelectorAll('.wl-edit-item:not(.is-removed)').length;
  }

  function updateCount() {
    if (count) { count.textContent = liveCards(); }
  }

  // ---- Add -------------------------------------------------------------

  function addItem() {
    var index = parseInt(totalForms.value, 10) || 0;
    var html = template.innerHTML.replace(/__prefix__/g, String(index));
    var holder = document.createElement('div');
    holder.innerHTML = html.trim();
    var card = holder.firstElementChild;
    card.classList.add('is-new');

    var empty = list.querySelector('[data-empty-items]');
    if (empty) { empty.remove(); }

    list.appendChild(card);
    totalForms.value = index + 1;
    updateCount();

    var name = card.querySelector('.wl-edit-item-name');
    card.scrollIntoView({behavior: 'smooth', block: 'center'});
    if (name) { name.focus({preventScroll: true}); }
  }

  Array.prototype.forEach.call(document.querySelectorAll('[data-add-item]'), function (button) {
    button.addEventListener('click', addItem);
  });

  // ---- Remove / undo -----------------------------------------------------

  list.addEventListener('change', function (event) {
    var box = event.target;
    if (!box.matches('[name$="-DELETE"]')) { return; }
    var card = box.closest('.wl-edit-item');
    card.classList.toggle('is-removed', box.checked);
    updateCount();
  });

  // ---- New category ------------------------------------------------------

  var modal = window.jQuery && window.jQuery('#newCategoryModal');
  var saveBtn = document.getElementById('saveNewCategoryBtn');
  var nameInput = document.getElementById('newCategoryName');
  var errorBox = document.getElementById('newCategoryError');
  var url = script && script.getAttribute('data-create-category-url');
  var pendingSelect = null;

  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = !message;
  }

  list.addEventListener('click', function (event) {
    var button = event.target.closest('[data-new-category]');
    if (!button || !modal) { return; }
    pendingSelect = button.closest('.wl-edit-item').querySelector('[data-category-select]');
    nameInput.value = '';
    showError('');
    modal.modal('show');
  });

  if (modal) {
    modal.on('shown.bs.modal', function () { nameInput.focus(); });
  }

  function addOption(select, id, label) {
    var option = document.createElement('option');
    option.value = id;
    option.textContent = label;
    select.appendChild(option);
    return option;
  }

  if (saveBtn && url) {
    saveBtn.addEventListener('click', function () {
      var name = nameInput.value.trim();
      if (!name) {
        showError('Give the category a name.');
        return;
      }
      saveBtn.disabled = true;
      showError('');

      fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': form.querySelector('[name=csrfmiddlewaretoken]').value
        },
        body: JSON.stringify({name: name})
      })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          saveBtn.disabled = false;
          if (data.status !== 'success') {
            showError(data.message || 'Could not create that category.');
            return;
          }
          // Every card (and the blank template) can use the new category.
          Array.prototype.forEach.call(list.querySelectorAll('[data-category-select]'), function (select) {
            addOption(select, data.category_id, data.category_name);
          });
          var blank = template.content.querySelector('[data-category-select]');
          if (blank) { addOption(blank, data.category_id, data.category_name); }
          if (pendingSelect) { pendingSelect.value = String(data.category_id); }
          modal.modal('hide');
        })
        .catch(function () {
          saveBtn.disabled = false;
          showError('Something went wrong. Please try again.');
        });
    });
  }

  // ---- New family --------------------------------------------------------

  var familySelect = document.getElementById('id_family_name');
  var newFamily = document.getElementById('new_family_name_wrapper');
  if (familySelect && newFamily) {
    var syncFamily = function () { newFamily.hidden = familySelect.value !== '__CREATE_NEW__'; };
    familySelect.addEventListener('change', syncFamily);
    syncFamily();
  }
})();
