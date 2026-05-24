(function () {
  const presetEl = document.getElementById("preset");
  const explainFallEl = document.getElementById("explainFall");
  const autoRefreshEl = document.getElementById("autoRefresh");
  const scanBtn = document.getElementById("scanBtn");
  const progressWrap = document.getElementById("progressWrap");
  const progressFill = document.getElementById("progressFill");
  const progressLabel = document.getElementById("progressLabel");
  const resultsBody = document.getElementById("resultsBody");

  const statusText = document.getElementById("statusText");
  const universeText = document.getElementById("universeText");
  const scannedText = document.getElementById("scannedText");
  const matchText = document.getElementById("matchText");
  const lastRunText = document.getElementById("lastRunText");
  const regimeText = document.getElementById("regimeText");

  let autoTimer = null;
  let eventSource = null;

  function fmtNum(v, d) {
    if (v == null || Number.isNaN(v)) return "—";
    return Number(v).toFixed(d);
  }

  function renderChecks(criteria) {
    if (!criteria) return "";
    const labels = {
      roe: "ROE",
      debt: "D/E",
      pe: "PE",
      drawdown: "↓52w",
      rsi: "RSI",
      ma200: "200MA",
    };
    return Object.entries(labels)
      .map(([k, lbl]) => {
        const ok = criteria[k];
        return `<span class="badge ${ok ? "ok" : "miss"}">${lbl}</span>`;
      })
      .join("");
  }

  function renderRows(rows) {
    if (!rows || !rows.length) {
      resultsBody.innerHTML =
        '<tr class="empty-row"><td colspan="11">No stocks met <strong>all</strong> filters this run. Try the Nifty 50 preset or loosen criteria in Streamlit Healthy Dip.</td></tr>';
      return;
    }
    resultsBody.innerHTML = rows
      .map((r) => {
        const cur = r.currency || "₹";
        const passCls = r.all_conditions_met ? "pass-row" : "";
        const links = [];
        if (r.yahoo) links.push(`<a href="${r.yahoo}" target="_blank" rel="noopener">Yahoo</a>`);
        if (r.research) links.push(`<a href="${r.research}" target="_blank" rel="noopener">Research</a>`);
        if (r.chart) links.push(`<a href="${r.chart}" target="_blank" rel="noopener">Chart</a>`);
        return `<tr class="${passCls}">
          <td class="ticker">${r.ticker}</td>
          <td>${cur}${fmtNum(r.price, 2)}</td>
          <td>${fmtNum(r.roe_pct, 0)}%</td>
          <td>${fmtNum(r.debt_equity, 2)}</td>
          <td>${fmtNum(r.pe, 1)}</td>
          <td>${fmtNum(r.drawdown_52w_pct, 0)}%</td>
          <td>${fmtNum(r.rsi, 0)}</td>
          <td>${r.pct_vs_ma200 != null ? fmtNum(r.pct_vs_ma200, 1) + "%" : "—"}</td>
          <td><div class="checks">${renderChecks(r.criteria)}</div></td>
          <td class="fall-cell">${r.fall_context ? escapeHtml(r.fall_context) : "—"}</td>
          <td class="links">${links.join("")}</td>
        </tr>`;
      })
      .join("");
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function formatRegime(reg) {
    if (!reg || reg.error) return reg?.error || "Unavailable";
    const flag = reg.above_ma ? "above" : "below";
    const pct = reg.pct_vs_ma != null ? `${reg.pct_vs_ma > 0 ? "+" : ""}${reg.pct_vs_ma}%` : "";
    return `${reg.price} vs MA ${reg.ma} (${flag} 200-DMA ${pct})`;
  }

  function applySummary(summary, rows) {
    statusText.textContent = summary.running ? "Scanning…" : "Idle";
    statusText.classList.toggle("pulse", summary.running);
    universeText.textContent = summary.universe || "—";
    scannedText.textContent = summary.total_scanned ? String(summary.total_scanned) : "—";
    matchText.textContent = String(summary.match_count ?? rows?.length ?? 0);
    lastRunText.textContent = summary.finished_at
      ? summary.finished_at.replace("T", " ").slice(0, 19)
      : "—";
    regimeText.textContent = formatRegime(summary.index_regime);
    if (rows) renderRows(rows);
  }

  async function pollStatus() {
    try {
      const res = await fetch("/api/status");
      const data = await res.json();
      applySummary(data, data.rows);
      if (data.running) {
        progressWrap.hidden = false;
        progressFill.style.width = `${data.progress_pct || 0}%`;
        progressLabel.textContent = data.progress_label || "";
      }
    } catch (e) {
      console.warn(e);
    }
  }

  function startScan() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    const preset = presetEl.value;
    const explain = explainFallEl.checked ? "1" : "0";
    const p = window.SCREENER_PRESETS[preset] || {};
    universeText.textContent = p.universe || "—";

    scanBtn.disabled = true;
    statusText.textContent = "Scanning…";
    progressWrap.hidden = false;
    progressFill.style.width = "0%";
    progressLabel.textContent = "Connecting…";

    const qs = new URLSearchParams({ preset, explain_fall: explain });
    eventSource = new EventSource(`/api/scan/stream?${qs}`);

    eventSource.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === "progress") {
        progressFill.style.width = `${msg.pct || 0}%`;
        progressLabel.textContent = `${msg.symbol} (${msg.i}/${msg.total})`;
        pollStatus();
      } else if (msg.type === "start") {
        scannedText.textContent = String(msg.total || "—");
        universeText.textContent = msg.universe || universeText.textContent;
      } else if (msg.type === "warn") {
        progressLabel.textContent = msg.message;
      } else if (msg.type === "done") {
        progressFill.style.width = "100%";
        progressLabel.textContent = `Done — ${msg.matches} match(es)`;
        applySummary(
          {
            running: false,
            match_count: msg.matches,
            finished_at: new Date().toISOString(),
            universe: universeText.textContent,
            total_scanned: scannedText.textContent,
          },
          msg.rows
        );
        finishScan();
      } else if (msg.type === "error") {
        statusText.textContent = "Error";
        progressLabel.textContent = msg.message || "Scan failed";
        finishScan();
      }
    };

    eventSource.onerror = () => {
      finishScan();
      pollStatus();
    };
  }

  function finishScan() {
    scanBtn.disabled = false;
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    setTimeout(() => {
      progressWrap.hidden = true;
    }, 1500);
    scheduleAuto();
  }

  function scheduleAuto() {
    if (autoTimer) clearInterval(autoTimer);
    if (!autoRefreshEl.checked) return;
    autoTimer = setInterval(() => {
      if (!scanBtn.disabled) startScan();
    }, 5 * 60 * 1000);
  }

  scanBtn.addEventListener("click", startScan);
  autoRefreshEl.addEventListener("change", scheduleAuto);
  presetEl.addEventListener("change", () => {
    const p = window.SCREENER_PRESETS[presetEl.value];
    if (p) universeText.textContent = p.universe;
  });

  pollStatus();
  const p0 = window.SCREENER_PRESETS[presetEl.value];
  if (p0) universeText.textContent = p0.universe;
})();
