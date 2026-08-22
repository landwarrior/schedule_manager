(() => {
  const inputs = document.querySelectorAll(".effort-input");
  let activeRow = null;

  function setActiveRow(input) {
    if (activeRow) {
      activeRow.classList.remove("row-editing");
    }
    activeRow = input.closest("tr");
    if (activeRow) {
      activeRow.classList.add("row-editing");
    }
  }

  function clearActiveRow() {
    if (activeRow) {
      activeRow.classList.remove("row-editing");
      activeRow = null;
    }
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
        diffEl.classList.toggle("warn", data.phase.diff !== 0);
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
    input.addEventListener("focus", () => setActiveRow(input));
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
})();
