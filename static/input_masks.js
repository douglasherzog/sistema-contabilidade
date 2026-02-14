(function () {
  function onlyDigits(s) {
    return (s || "").replace(/\D+/g, "");
  }

  function formatDateDigits(d) {
    // ddmmyyyy -> dd/mm/yyyy
    var dd = d.slice(0, 2);
    var mm = d.slice(2, 4);
    var yyyy = d.slice(4, 8);

    var out = "";
    if (dd.length) out += dd;
    if (mm.length) out += "/" + mm;
    if (yyyy.length) out += "/" + yyyy;
    return out;
  }

  function caretFromDigitsCount(formatted, digitsCount) {
    // Returns the caret position in the formatted string after 'digitsCount' digits.
    if (digitsCount <= 0) return 0;
    var count = 0;
    for (var i = 0; i < formatted.length; i++) {
      if (/\d/.test(formatted[i])) count++;
      if (count >= digitsCount) return i + 1;
    }
    return formatted.length;
  }

  function applyDateMask(el) {
    var raw = el.value;
    var start = el.selectionStart || 0;

    var digitsBeforeCaret = onlyDigits(raw.slice(0, start)).length;
    var digits = onlyDigits(raw).slice(0, 8);
    var formatted = formatDateDigits(digits);

    el.value = formatted;

    // Restore caret close to where the user was typing.
    var newPos = caretFromDigitsCount(formatted, digitsBeforeCaret);
    try {
      el.setSelectionRange(newPos, newPos);
    } catch (e) {
      // ignore
    }
  }

  function normalizeDateOnBlur(el) {
    // If user typed dd/mm/yyyy partially, keep it.
    // If user pasted ISO yyyy-mm-dd, convert to dd/mm/yyyy.
    var v = (el.value || "").trim();
    if (!v) return;

    var mIso = v.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (mIso) {
      el.value = mIso[3] + "/" + mIso[2] + "/" + mIso[1];
      return;
    }

    // If it's just digits, format.
    var d = onlyDigits(v);
    if (d.length >= 4) {
      el.value = formatDateDigits(d.slice(0, 8));
    }
  }

  function mark(el) {
    // Avoid re-binding.
    if (el.dataset.maskBound === "1") return;
    el.dataset.maskBound = "1";

    el.setAttribute("inputmode", "numeric");
    el.setAttribute("autocomplete", "off");

    el.addEventListener("input", function () {
      applyDateMask(el);
    });

    el.addEventListener("blur", function () {
      normalizeDateOnBlur(el);
    });

    // Initial normalization (for server-rendered values).
    normalizeDateOnBlur(el);
  }

  function bindAll() {
    var els = document.querySelectorAll("input.js-date");
    for (var i = 0; i < els.length; i++) mark(els[i]);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindAll);
  } else {
    bindAll();
  }
})();
