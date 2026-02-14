(function () {
  function onlyDigits(s) {
    return (s || "").replace(/\D+/g, "");
  }

  function sanitizeMoneyTyping(v) {
    // Keep only digits and a single comma. Do not add thousands separators while typing.
    v = (v || "").replace(/\./g, ",");
    v = v.replace(/[^0-9,]/g, "");
    var firstComma = v.indexOf(",");
    if (firstComma >= 0) {
      var head = v.slice(0, firstComma + 1);
      var tail = v.slice(firstComma + 1).replace(/,/g, "");
      tail = tail.slice(0, 2);
      v = head + tail;
    }
    return v;
  }

  function countMoneyKeptCharsBeforeCaret(raw, caretPos) {
    var s = raw.slice(0, caretPos);
    s = s.replace(/\./g, ",");
    s = s.replace(/[^0-9,]/g, "");
    var idx = s.indexOf(",");
    if (idx >= 0) {
      var head = s.slice(0, idx + 1);
      var tail = s.slice(idx + 1).replace(/,/g, "");
      s = head + tail;
    }
    return s.length;
  }

  function caretFromKeptCharCount(str, keptCount) {
    if (keptCount <= 0) return 0;
    return Math.min(str.length, keptCount);
  }

  function parseMoneyLoose(v) {
    var s = (v || "").trim();
    if (!s) return null;
    s = s.replace(/\s+/g, "");

    // Normalize optional currency prefix.
    s = s.replace(/^R\$/i, "");

    var hasDot = s.indexOf(".") >= 0;
    var hasComma = s.indexOf(",") >= 0;

    if (hasDot && hasComma) {
      // pt-BR full format: 1.234,56
      s = s.replace(/\./g, "");
      s = s.replace(/,/g, ".");
    } else if (hasComma) {
      // 1234,56
      s = s.replace(/,/g, ".");
    } else {
      // 1234.56 (common server-rendered decimal string)
      // keep dot as decimal separator
    }

    var n = Number(s);
    if (!isFinite(n)) return null;
    return n;
  }

  function formatMoneyPtBr(n) {
    try {
      return new Intl.NumberFormat("pt-BR", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(n);
    } catch (e) {
      // Fallback: basic fixed with dot->comma
      return (Math.round(n * 100) / 100).toFixed(2).replace(".", ",");
    }
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

  function applyMoneyMask(el) {
    var raw = el.value;
    var start = el.selectionStart || 0;
    var keptBefore = countMoneyKeptCharsBeforeCaret(raw, start);

    var sanitized = sanitizeMoneyTyping(raw);
    el.value = sanitized;

    var newPos = caretFromKeptCharCount(sanitized, keptBefore);
    try {
      el.setSelectionRange(newPos, newPos);
    } catch (e) {
      // ignore
    }
  }

  function normalizeMoneyOnBlur(el) {
    var v = (el.value || "").trim();
    if (!v) return;

    var n = parseMoneyLoose(v);
    if (n === null) return;
    el.value = formatMoneyPtBr(n);
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

  function markMoney(el) {
    if (el.dataset.maskMoneyBound === "1") return;
    el.dataset.maskMoneyBound = "1";

    el.setAttribute("inputmode", "decimal");
    el.setAttribute("autocomplete", "off");

    el.addEventListener("input", function () {
      applyMoneyMask(el);
    });

    el.addEventListener("blur", function () {
      normalizeMoneyOnBlur(el);
    });

    normalizeMoneyOnBlur(el);
  }

  function bindAll() {
    var els = document.querySelectorAll("input.js-date");
    for (var i = 0; i < els.length; i++) mark(els[i]);

    var mons = document.querySelectorAll("input.js-money");
    for (var j = 0; j < mons.length; j++) markMoney(mons[j]);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindAll);
  } else {
    bindAll();
  }
})();
