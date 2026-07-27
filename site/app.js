(function () {
  var data = (window.SHANXI_DATA || {}).recipes || [];
  var list = document.getElementById('list');
  var countEl = document.getElementById('count');
  var emptyEl = document.getElementById('empty');
  var q = document.getElementById('q');
  var filters = { book: '', category: '' };

  var params = new URLSearchParams(location.search);
  if (params.get('book')) filters.book = params.get('book');
  if (params.get('category')) filters.category = params.get('category');

  function matches(r) {
    if (filters.book && r.b !== filters.book) return false;
    if (filters.category && r.c !== filters.category) return false;
    var term = q.value.trim();
    if (!term) return true;
    return r.s.indexOf(term) !== -1;
  }

  function render() {
    var frag = document.createDocumentFragment();
    var n = 0;
    for (var i = 0; i < data.length; i++) {
      var r = data[i];
      if (!matches(r)) continue;
      n++;
      var li = document.createElement('li');
      li.className = 'card';
      var a = document.createElement('a');
      a.href = 'recipes/' + encodeURIComponent(r.u) + '.html';
      a.textContent = r.t;
      var sub = document.createElement('div');
      sub.className = 'sub';
      sub.textContent = r.bl + ' · ' + r.p + ' · ' + r.c;
      li.appendChild(a);
      li.appendChild(sub);
      frag.appendChild(li);
    }
    list.textContent = '';
    list.appendChild(frag);
    countEl.textContent = n;
    emptyEl.hidden = n > 0;
  }

  q.addEventListener('input', render);
  document.querySelectorAll('.chip').forEach(function (chip) {
    chip.addEventListener('click', function () {
      var kind = chip.dataset.filter;
      filters[kind] = chip.dataset.value;
      document.querySelectorAll('.chip[data-filter="' + kind + '"]').forEach(function (c) {
        c.classList.toggle('active', c === chip);
      });
      render();
    });
  });

  document.querySelectorAll('.chip').forEach(function (chip) {
    if (chip.dataset.value && chip.dataset.value === filters[chip.dataset.filter]) {
      document.querySelectorAll('.chip[data-filter="' + chip.dataset.filter + '"]').forEach(function (c) {
        c.classList.toggle('active', c === chip);
      });
    }
  });

  render();
})();
