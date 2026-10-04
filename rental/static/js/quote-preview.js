// Live price preview.
//
// The browser does no pricing arithmetic. Pricing -- the hourly cap, the
// per-day extras, the fee table -- lives in rental/domain/pricing.py and is
// reached through /api/quote, so there is exactly one implementation to keep
// right. `total` and each line's `amount` arrive as JSON strings and are
// formatted here to match the server's own `₱{:,.2f}` display formatting
// (see rental/templates/partials/_quote_lines.html) -- this is display
// formatting of a value the server already computed and finalised, not a
// price calculation, and it never feeds back into a request. Each line's
// `detail` string is rendered verbatim: the server already formatted it,
// peso sign included, so reformatting it here would double it up.
//
// The page is fully usable without this file: whenever the URL carries dates,
// the same figures are already server-rendered.
(function () {
  var form = document.querySelector('[data-quote-form][data-vehicle]');
  var panel = document.querySelector('[data-quote-panel]');
  if (!form || !panel) return;

  var timer = null;
  var latest = 0;

  function peso(value) {
    return '₱' + Number(value).toLocaleString('en-PH', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }

  function render(data) {
    if (!data.available) {
      panel.innerHTML = '<div class="alert alert-warning"><span></span></div>';
      panel.querySelector('span').textContent = data.message || 'Not available for those dates.';
      return;
    }
    var rows = data.lines.map(function (line) {
      var tr = document.createElement('tr');
      tr.className = 'border-b border-line last:border-0';
      var left = document.createElement('td');
      left.className = 'py-2';
      var label = document.createElement('span');
      label.className = 'font-medium text-ink';
      label.textContent = line[0];
      var detail = document.createElement('span');
      detail.className = 'block text-xs text-muted';
      detail.textContent = line[1];
      left.appendChild(label);
      left.appendChild(detail);
      var right = document.createElement('td');
      right.className = 'py-2 text-right font-semibold text-ink';
      right.textContent = peso(line[2]);
      tr.appendChild(left);
      tr.appendChild(right);
      return tr;
    });

    panel.innerHTML =
      '<div class="border-t border-line pt-4"><table class="w-full text-sm"><tbody>' +
      '</tbody></table></div>';
    var body = panel.querySelector('tbody');
    rows.forEach(function (row) { body.appendChild(row); });

    var totalRow = document.createElement('tr');
    totalRow.innerHTML =
      '<td class="pt-3 text-sm font-semibold text-ink">Total</td>' +
      '<td class="pt-3 text-right"><span class="rate" data-quote-total></span></td>';
    body.appendChild(totalRow);
    totalRow.querySelector('[data-quote-total]').textContent = peso(data.total);
  }

  function refresh() {
    var pickup = form.querySelector('[name="pickup"]').value;
    var returnAt = form.querySelector('[name="return"]').value;
    if (!pickup || !returnAt) return;

    var params = new URLSearchParams({
      vehicle: form.dataset.vehicle,
      pickup: pickup,
      'return': returnAt
    });
    if (form.querySelector('[name="driver"]').checked) params.set('driver', '1');
    if (form.querySelector('[name="insurance"]').checked) params.set('insurance', '1');

    // The previous figure stays on screen while this is in flight; a stale
    // response that arrives late is discarded rather than overwriting a newer
    // one.
    var ticket = ++latest;
    fetch('/api/quote?' + params.toString())
      .then(function (response) { return response.json(); })
      .then(function (data) { if (ticket === latest) render(data); })
      .catch(function () { /* leave the server-rendered figure in place */ });
  }

  function debounced() {
    window.clearTimeout(timer);
    timer = window.setTimeout(refresh, 300);
  }

  form.addEventListener('change', debounced);
  form.addEventListener('input', debounced);
})();
