(() => {
  const inputs = document.querySelectorAll(".effort-input");

  function syncEffortStyle(input, effort) {
    const cell = input.closest(".effort-cell");
    if (cell) {
      cell.classList.toggle("has-effort", Number(effort) > 0);
    }
  }

  async function saveInput(input) {
    const raw = input.value.trim();
    const effort = raw === "" ? 0 : Number(raw);
    if (Number.isNaN(effort) || effort < 0) {
      input.classList.add("error");
      return;
    }
    // 0.1 increment check
    if (Math.abs(effort * 10 - Math.round(effort * 10)) > 1e-9) {
      input.classList.add("error");
      alert("工数は 0.1 刻みで入力してください");
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
          phase: input.dataset.phase,
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
      syncEffortStyle(input, data.effort);

      const key = `${input.dataset.projectId}-${input.dataset.phase}`;
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
    syncEffortStyle(input, input.value.trim() === "" ? 0 : Number(input.value));
    input.addEventListener("change", () => saveInput(input));
    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => saveInput(input), 500);
    });
  });
})();
