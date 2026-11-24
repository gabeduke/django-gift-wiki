// Gift exchange reveal: unwrap the box, flick through everyone's names, land
// on yours. Without JS (or with reduced motion) the <details> just opens.
(function () {
  var section = document.querySelector('[data-exchange-reveal]');
  if (!section) return;
  var box = section.querySelector('details');
  var nameEl = section.querySelector('[data-reveal-name]');
  var decoysEl = document.getElementById('wl-reveal-decoys');
  var decoys = decoysEl ? JSON.parse(decoysEl.textContent) : [];
  var realName = nameEl.textContent;
  var calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function shuffleTo(done) {
    var ticks = 0;
    var total = Math.min(14, Math.max(6, decoys.length * 2));
    function tick() {
      if (ticks >= total || !decoys.length) {
        nameEl.textContent = realName;
        done();
        return;
      }
      nameEl.textContent = decoys[Math.floor(Math.random() * decoys.length)];
      ticks += 1;
      // Slow down towards the end, like a wheel coming to rest
      setTimeout(tick, 60 + ticks * ticks * 3);
    }
    tick();
  }

  box.querySelector('summary').addEventListener('click', function (event) {
    if (box.open || calm) return;
    event.preventDefault();
    section.classList.add('is-unwrapping');
    setTimeout(function () {
      box.open = true;
      section.classList.remove('is-unwrapping');
      section.classList.add('is-shuffling');
      shuffleTo(function () {
        section.classList.remove('is-shuffling');
        section.classList.add('is-revealed');
      });
    }, 700);
  });

  // Arriving from the home page's "Open it": bring the box into view
  if (!box.open && window.location.hash === '#reveal') {
    section.scrollIntoView({ block: 'center' });
  }
})();
