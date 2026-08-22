/**
 * Lightweight date / month pickers with direct text input.
 * - data-datepicker="date"  -> YYYY-MM-DD (YYYY/MM/DD also accepted)
 * - data-datepicker="month" -> YYYY-MM    (YYYY/MM also accepted)
 */
(() => {
  const WEEKDAYS = ["日", "月", "火", "水", "木", "金", "土"];

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function normalizeDate(raw) {
    const s = String(raw || "").trim().replace(/\//g, "-");
    const m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(s);
    if (!m) return null;
    const y = Number(m[1]);
    const mo = Number(m[2]);
    const d = Number(m[3]);
    const dt = new Date(y, mo - 1, d);
    if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== d) {
      return null;
    }
    return `${y}-${pad(mo)}-${pad(d)}`;
  }

  function normalizeMonth(raw) {
    const s = String(raw || "").trim().replace(/\//g, "-");
    const m = /^(\d{4})-(\d{1,2})$/.exec(s);
    if (!m) return null;
    const y = Number(m[1]);
    const mo = Number(m[2]);
    if (mo < 1 || mo > 12) return null;
    return `${y}-${pad(mo)}`;
  }

  function parseDate(raw) {
    const n = normalizeDate(raw);
    if (!n) return null;
    const [y, mo, d] = n.split("-").map(Number);
    return new Date(y, mo - 1, d);
  }

  function parseMonth(raw) {
    const n = normalizeMonth(raw);
    if (!n) return null;
    const [y, mo] = n.split("-").map(Number);
    return { year: y, month: mo };
  }

  let openPopup = null;

  function closePopup() {
    if (openPopup) {
      openPopup.remove();
      openPopup = null;
    }
  }

  function positionPopup(popup, anchor) {
    const rect = anchor.getBoundingClientRect();
    const top = rect.bottom + window.scrollY + 4;
    let left = rect.left + window.scrollX;
    popup.style.top = `${top}px`;
    popup.style.left = `${left}px`;
    document.body.appendChild(popup);
    const pw = popup.offsetWidth;
    const maxLeft = window.scrollX + document.documentElement.clientWidth - pw - 8;
    if (left > maxLeft) {
      popup.style.left = `${Math.max(8, maxLeft)}px`;
    }
  }

  function buildMonthPopup(input) {
    closePopup();
    const current = parseMonth(input.value) || {
      year: new Date().getFullYear(),
      month: new Date().getMonth() + 1,
    };
    let viewYear = current.year;

    const popup = document.createElement("div");
    popup.className = "dp-popup";
    popup.tabIndex = -1;

    function render() {
      popup.innerHTML = "";
      const head = document.createElement("div");
      head.className = "dp-head";
      const prev = document.createElement("button");
      prev.type = "button";
      prev.className = "dp-nav";
      prev.textContent = "‹";
      prev.addEventListener("click", (e) => {
        e.stopPropagation();
        viewYear -= 1;
        render();
      });
      const title = document.createElement("div");
      title.className = "dp-title";
      title.textContent = `${viewYear}年`;
      const next = document.createElement("button");
      next.type = "button";
      next.className = "dp-nav";
      next.textContent = "›";
      next.addEventListener("click", (e) => {
        e.stopPropagation();
        viewYear += 1;
        render();
      });
      head.append(prev, title, next);
      popup.appendChild(head);

      const grid = document.createElement("div");
      grid.className = "dp-month-grid";
      for (let mo = 1; mo <= 12; mo += 1) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "dp-month-btn";
        if (viewYear === current.year && mo === current.month) {
          btn.classList.add("selected");
        }
        btn.textContent = `${mo}月`;
        btn.addEventListener("click", () => {
          input.value = `${viewYear}-${pad(mo)}`;
          input.dispatchEvent(new Event("change", { bubbles: true }));
          closePopup();
        });
        grid.appendChild(btn);
      }
      popup.appendChild(grid);
    }

    render();
    positionPopup(popup, input);
    openPopup = popup;
  }

  function buildDatePopup(input) {
    closePopup();
    const selected = parseDate(input.value);
    const base = selected || new Date();
    let viewYear = base.getFullYear();
    let viewMonth = base.getMonth(); // 0-based

    const popup = document.createElement("div");
    popup.className = "dp-popup";
    popup.tabIndex = -1;

    function render() {
      popup.innerHTML = "";
      const head = document.createElement("div");
      head.className = "dp-head";
      const prev = document.createElement("button");
      prev.type = "button";
      prev.className = "dp-nav";
      prev.textContent = "‹";
      prev.addEventListener("click", (e) => {
        e.stopPropagation();
        viewMonth -= 1;
        if (viewMonth < 0) {
          viewMonth = 11;
          viewYear -= 1;
        }
        render();
      });
      const title = document.createElement("div");
      title.className = "dp-title";
      title.textContent = `${viewYear}年${viewMonth + 1}月`;
      const next = document.createElement("button");
      next.type = "button";
      next.className = "dp-nav";
      next.textContent = "›";
      next.addEventListener("click", (e) => {
        e.stopPropagation();
        viewMonth += 1;
        if (viewMonth > 11) {
          viewMonth = 0;
          viewYear += 1;
        }
        render();
      });
      head.append(prev, title, next);
      popup.appendChild(head);

      const week = document.createElement("div");
      week.className = "dp-weekdays";
      WEEKDAYS.forEach((w) => {
        const el = document.createElement("div");
        el.textContent = w;
        week.appendChild(el);
      });
      popup.appendChild(week);

      const grid = document.createElement("div");
      grid.className = "dp-day-grid";
      const first = new Date(viewYear, viewMonth, 1);
      const startPad = first.getDay();
      const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
      for (let i = 0; i < startPad; i += 1) {
        const empty = document.createElement("div");
        empty.className = "dp-day empty";
        grid.appendChild(empty);
      }
      for (let d = 1; d <= daysInMonth; d += 1) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "dp-day";
        const dow = new Date(viewYear, viewMonth, d).getDay();
        if (dow === 0) btn.classList.add("sun");
        if (dow === 6) btn.classList.add("sat");
        if (
          selected &&
          selected.getFullYear() === viewYear &&
          selected.getMonth() === viewMonth &&
          selected.getDate() === d
        ) {
          btn.classList.add("selected");
        }
        btn.textContent = String(d);
        btn.addEventListener("click", () => {
          input.value = `${viewYear}-${pad(viewMonth + 1)}-${pad(d)}`;
          input.dispatchEvent(new Event("change", { bubbles: true }));
          closePopup();
        });
        grid.appendChild(btn);
      }
      const totalCells = startPad + daysInMonth;
      for (let i = totalCells; i < 42; i += 1) {
        const empty = document.createElement("div");
        empty.className = "dp-day empty";
        grid.appendChild(empty);
      }
      popup.appendChild(grid);
    }

    render();
    positionPopup(popup, input);
    openPopup = popup;
  }

  function wrapInput(input) {
    if (input.dataset.dpReady) return;
    input.dataset.dpReady = "1";
    const mode = input.dataset.datepicker;
    input.type = "text";
    input.autocomplete = "off";
    input.spellcheck = false;
    if (mode === "date") {
      input.placeholder = input.placeholder || "YYYY-MM-DD";
      input.title = "YYYY-MM-DD または YYYY/MM/DD。カレンダーアイコンでも選択できます";
    } else {
      input.placeholder = input.placeholder || "YYYY-MM";
      input.title = "YYYY-MM または YYYY/MM。カレンダーアイコンでも選択できます";
    }

    const wrap = document.createElement("div");
    wrap.className = "dp-field";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "dp-toggle";
    btn.setAttribute("aria-label", "カレンダーを開く");
    btn.textContent = "▼";
    wrap.appendChild(btn);

    function open() {
      if (mode === "date") buildDatePopup(input);
      else buildMonthPopup(input);
    }

    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (openPopup) closePopup();
      else open();
    });

    input.addEventListener("blur", () => {
      const raw = input.value.trim();
      if (!raw) return;
      const normalized = mode === "date" ? normalizeDate(raw) : normalizeMonth(raw);
      if (normalized) {
        input.value = normalized;
        input.classList.remove("dp-invalid");
      } else {
        input.classList.add("dp-invalid");
      }
    });

    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closePopup();
      if (e.key === "ArrowDown" && (e.altKey || e.metaKey)) {
        e.preventDefault();
        open();
      }
    });
  }

  document.addEventListener("click", (e) => {
    if (!openPopup) return;
    if (openPopup.contains(e.target)) return;
    if (e.target.closest && e.target.closest(".dp-field")) return;
    closePopup();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closePopup();
  });

  function init(root = document) {
    root.querySelectorAll("[data-datepicker]").forEach(wrapInput);
  }

  // Normalize values before form submit so slash input is accepted
  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    form.querySelectorAll("[data-datepicker]").forEach((input) => {
      const mode = input.dataset.datepicker;
      const raw = input.value.trim();
      if (!raw) return;
      const normalized = mode === "date" ? normalizeDate(raw) : normalizeMonth(raw);
      if (normalized) {
        input.value = normalized;
        input.classList.remove("dp-invalid");
      } else {
        e.preventDefault();
        input.classList.add("dp-invalid");
        input.focus();
        alert(
          mode === "date"
            ? "日付は YYYY-MM-DD 形式で入力してください"
            : "月は YYYY-MM 形式で入力してください"
        );
      }
    });
  }, true);

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => init());
  } else {
    init();
  }
})();
