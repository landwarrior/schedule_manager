(() => {
  const table = document.querySelector(".schedule-table");
  const inputs = document.querySelectorAll(".effort-input");
  let activeRow = null;
  let activeColEls = [];

  function syncStickyOffsets() {
    if (!table) {
      return;
    }
    const header = table.querySelector("thead tr:first-child");
    if (!header) {
      return;
    }
    const project = header.querySelector(".col-project");
    const phase = header.querySelector(".col-phase");
    const meta1 = header.querySelector(".col-meta1");
    const meta2 = header.querySelector(".col-meta2");
    if (!project || !phase || !meta1 || !meta2) {
      return;
    }

    const projectWidth = project.getBoundingClientRect().width;
    const phaseWidth = phase.getBoundingClientRect().width;
    const meta1Width = meta1.getBoundingClientRect().width;
    const meta2Width = meta2.getBoundingClientRect().width;

    table.style.setProperty("--sticky-left-phase", `${projectWidth}px`);
    table.style.setProperty("--sticky-left-meta1", `${projectWidth + phaseWidth}px`);
    table.style.setProperty("--sticky-left-meta2", `${projectWidth + phaseWidth + meta1Width}px`);
    table.style.setProperty(
      "--sticky-left-meta3",
      `${projectWidth + phaseWidth + meta1Width + meta2Width}px`
    );
  }

  function effortGrid() {
    return [...document.querySelectorAll(".schedule-table tbody tr")]
      .filter((row) => row.querySelector(".effort-input"))
      .map((row) => [...row.querySelectorAll(".effort-input")]);
  }

  function effortPosition(grid, input) {
    for (let row = 0; row < grid.length; row += 1) {
      const col = grid[row].indexOf(input);
      if (col >= 0) {
        return { row, col };
      }
    }
    return null;
  }

  function stickyColumnsWidth(scrollRoot) {
    const edge = scrollRoot.querySelector(".schedule-table .col-meta3");
    if (!edge) {
      return 0;
    }
    const rootRect = scrollRoot.getBoundingClientRect();
    const edgeRect = edge.getBoundingClientRect();
    return Math.max(0, edgeRect.right - rootRect.left);
  }

  function scrollEffortIntoView(input) {
    const scrollRoot = input.closest(".table-scroll");
    if (!scrollRoot) {
      return;
    }

    const stickyWidth = stickyColumnsWidth(scrollRoot);
    const rootRect = scrollRoot.getBoundingClientRect();
    const inputRect = input.getBoundingClientRect();
    const thead = scrollRoot.querySelector(".schedule-table thead");
    const stickyTop = thead ? thead.getBoundingClientRect().height : 0;

    let nextTop = scrollRoot.scrollTop;
    let nextLeft = scrollRoot.scrollLeft;

    const visibleTop = rootRect.top + stickyTop;
    if (inputRect.top < visibleTop) {
      nextTop -= visibleTop - inputRect.top;
    } else if (inputRect.bottom > rootRect.bottom) {
      nextTop += inputRect.bottom - rootRect.bottom;
    }

    const visibleLeft = rootRect.left + stickyWidth;
    const pad = 4;
    if (inputRect.left < visibleLeft + pad) {
      nextLeft -= visibleLeft + pad - inputRect.left;
    } else if (inputRect.right > rootRect.right - pad) {
      nextLeft += inputRect.right + pad - rootRect.right;
    }

    if (nextTop !== scrollRoot.scrollTop) {
      scrollRoot.scrollTop = nextTop;
    }
    if (nextLeft !== scrollRoot.scrollLeft) {
      scrollRoot.scrollLeft = nextLeft;
    }
  }

  function focusEffortInput(input) {
    input.focus({ preventScroll: true });
    input.select();
    scrollEffortIntoView(input);
  }

  function moveEffortInput(input, rowDelta, colDelta) {
    const grid = effortGrid();
    const pos = effortPosition(grid, input);
    if (!pos) {
      return;
    }
    const nextRow = pos.row + rowDelta;
    const nextCol = pos.col + colDelta;
    if (nextRow < 0 || nextRow >= grid.length) {
      return;
    }
    if (nextCol < 0 || nextCol >= grid[nextRow].length) {
      return;
    }
    focusEffortInput(grid[nextRow][nextCol]);
  }

  function handleEffortKeydown(event) {
    const key = event.key;
    if (key !== "ArrowLeft" && key !== "ArrowRight" && key !== "ArrowUp" && key !== "ArrowDown") {
      return;
    }
    event.preventDefault();
    if (key === "ArrowLeft") {
      moveEffortInput(event.target, 0, -1);
    } else if (key === "ArrowRight") {
      moveEffortInput(event.target, 0, 1);
    } else if (key === "ArrowUp") {
      moveEffortInput(event.target, -1, 0);
    } else if (key === "ArrowDown") {
      moveEffortInput(event.target, 1, 0);
    }
  }

  function clearActiveColumn() {
    activeColEls.forEach((el) => el.classList.remove("col-editing"));
    activeColEls = [];
  }

  function setActiveColumn(input) {
    clearActiveColumn();
    const ym = input.dataset.ym;
    const decade = input.dataset.decade;
    if (!ym || !decade) {
      return;
    }
    const targets = [
      ...document.querySelectorAll(`.month-head[data-ym="${ym}"]`),
      ...document.querySelectorAll(`.decade-head[data-ym="${ym}"][data-decade="${decade}"]`),
    ];
    targets.forEach((el) => {
      el.classList.add("col-editing");
      activeColEls.push(el);
    });
  }

  function setActiveRow(input) {
    if (activeRow) {
      activeRow.classList.remove("row-editing");
    }
    activeRow = input.closest("tr");
    if (activeRow) {
      activeRow.classList.add("row-editing");
    }
    setActiveColumn(input);
  }

  function clearActiveRow() {
    if (activeRow) {
      activeRow.classList.remove("row-editing");
      activeRow = null;
    }
    clearActiveColumn();
  }

  function syncEffortStyle(input, effort) {
    const cell = input.closest(".phase-cell");
    if (cell) {
      cell.classList.toggle("active", Number(effort) > 0);
    }
  }

  async function saveInput(input) {
    const raw = input.value.trim();
    const effort = raw === "" ? 0 : Number(raw);
    if (Number.isNaN(effort) || effort < 0) {
      input.classList.add("error");
      return;
    }
    if (Math.abs(effort * 10 - Math.round(effort * 10)) > 1e-9) {
      input.classList.add("error");
      if (input.dataset.invalidAlertFor !== raw) {
        input.dataset.invalidAlertFor = raw;
        alert("工数は 0.1 刻みで入力してください");
      }
      return;
    }
    delete input.dataset.invalidAlertFor;

    const normalized = raw === "" ? "" : effort.toFixed(1);
    if (input.dataset.lastSaved === normalized) {
      return;
    }

    input.classList.remove("error");
    input.classList.add("saving");

    try {
      const res = await fetch("/api/allocations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: Number(input.dataset.projectId),
          phase_id: Number(input.dataset.phaseId),
          year_month: input.dataset.ym,
          decade: Number(input.dataset.decade),
          effort,
        }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.error || "保存に失敗しました");
      }

      input.value = data.effort ? data.effort.toFixed(1) : "";
      input.dataset.lastSaved = input.value;
      syncEffortStyle(input, data.effort);

      const key = `${input.dataset.projectId}-${input.dataset.phaseId}`;
      const allocatedEl = document.querySelector(`[data-phase-allocated="${key}"]`);
      const diffEl = document.querySelector(`[data-phase-diff="${key}"]`);
      if (allocatedEl) allocatedEl.textContent = data.phase.allocated.toFixed(1);
      if (diffEl) {
        diffEl.textContent = data.phase.diff.toFixed(1);
        diffEl.classList.toggle("warn", data.phase.diff > 0);
        diffEl.classList.toggle("diff-over", data.phase.diff < 0);
      }

      const periodKey = `${data.period.year_month}-${data.period.decade}`;
      const sumEl = document.querySelector(`[data-sum="${periodKey}"]`);
      if (sumEl) {
        sumEl.textContent = data.period.allocated.toFixed(1);
        sumEl.classList.remove("cap-warn", "cap-over");
        if (data.period.status === "over") {
          sumEl.classList.add("cap-over");
        } else if (data.period.status === "warn") {
          sumEl.classList.add("cap-warn");
        }
      }
    } catch (err) {
      input.classList.add("error");
      alert(err.message);
    } finally {
      input.classList.remove("saving");
    }
  }

  inputs.forEach((input) => {
    let timer = null;
    input.dataset.lastSaved = input.value.trim() === "" ? "" : input.value.trim();
    syncEffortStyle(input, input.value.trim() === "" ? 0 : Number(input.value));
    input.addEventListener("focus", () => {
      setActiveRow(input);
      scrollEffortIntoView(input);
    });
    input.addEventListener("keydown", handleEffortKeydown);
    input.addEventListener("blur", () => {
      window.setTimeout(() => {
        if (!document.activeElement?.classList.contains("effort-input")) {
          clearActiveRow();
        }
      }, 0);
    });
    input.addEventListener("change", () => {
      clearTimeout(timer);
      saveInput(input);
    });
    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => saveInput(input), 500);
    });
  });

  syncStickyOffsets();
  window.addEventListener("resize", syncStickyOffsets);
})();
