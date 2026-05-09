// StockSight UI Preview — mirrors the Streamlit app aesthetic
import { useState, useEffect } from "react";

const MOCK_DATA = [
  { rank: 1, ticker: "RELIANCE", price: 2847.35, pe: 12.4, volRatio: 3.82, rsi: 67.2, score: 78.4 },
  { rank: 2, ticker: "HDFCBANK", price: 1623.70, pe: 14.1, volRatio: 2.95, rsi: 61.8, score: 64.1 },
  { rank: 3, ticker: "INFY",     price: 1489.20, pe: 16.8, volRatio: 2.41, rsi: 57.4, score: 51.7 },
  { rank: 4, ticker: "TCS",      price: 3912.50, pe: 18.2, volRatio: 2.11, rsi: 53.9, score: 43.2 },
  { rank: 5, ticker: "WIPRO",    price: 472.80,  pe: 19.7, volRatio: 2.04, rsi: 51.1, score: 37.8 },
  { rank: 6, ticker: "HCLTECH",  price: 1354.60, pe: 17.5, volRatio: 2.08, rsi: 50.6, score: 36.9 },
];

const scoreColor = (s) => s >= 60 ? "#00e5a0" : s >= 35 ? "#f0b429" : "#e05252";
const scoreBar = (s) => {
  const filled = Math.round(s / 10);
  return "█".repeat(filled) + "░".repeat(10 - filled);
};

export default function StockSight() {
  const [universe, setUniverse] = useState("Nifty 50 (NSE)");
  const [peMax, setPeMax] = useState(20);
  const [volMult, setVolMult] = useState(2.0);
  const [rsiMin, setRsiMin] = useState(50);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState([]);
  const [hasRun, setHasRun] = useState(false);
  const [lastRun, setLastRun] = useState(null);
  const [progress, setProgress] = useState(0);
  const [countdown, setCountdown] = useState(60);

  useEffect(() => {
    let timer;
    if (autoRefresh && hasRun) {
      timer = setInterval(() => setCountdown(c => {
        if (c <= 1) { handleRun(); return 60; }
        return c - 1;
      }), 1000);
    }
    return () => clearInterval(timer);
  }, [autoRefresh, hasRun]);

  const handleRun = () => {
    setRunning(true);
    setProgress(0);
    setResults([]);
    let p = 0;
    const iv = setInterval(() => {
      p += Math.random() * 12;
      if (p >= 100) {
        clearInterval(iv);
        setProgress(100);
        setTimeout(() => {
          const filtered = MOCK_DATA.filter(
            d => d.pe <= peMax && d.volRatio >= volMult && d.rsi >= rsiMin
          );
          setResults(filtered);
          setRunning(false);
          setHasRun(true);
          setLastRun(new Date().toLocaleTimeString());
          setCountdown(60);
        }, 400);
      } else {
        setProgress(Math.min(Math.round(p), 99));
      }
    }, 120);
  };

  const styles = {
    root: {
      background: "#0a0e17",
      minHeight: "100vh",
      color: "#c8d8e8",
      fontFamily: "'IBM Plex Sans', sans-serif",
      display: "flex",
    },
    sidebar: {
      width: 260,
      background: "#080d16",
      borderRight: "1px solid #1c2e44",
      padding: "28px 20px",
      flexShrink: 0,
    },
    main: { flex: 1, padding: "28px 32px" },
    label: { fontSize: 11, color: "#4a7a9b", textTransform: "uppercase", letterSpacing: 1.5, marginBottom: 6, display: "block" },
    select: {
      width: "100%", background: "#0f1724", border: "1px solid #1c3550",
      color: "#c8d8e8", padding: "8px 10px", borderRadius: 6, fontSize: 13,
      fontFamily: "'IBM Plex Sans', sans-serif", outline: "none", marginBottom: 16,
    },
    sliderWrap: { marginBottom: 20 },
    slider: { width: "100%", accentColor: "#00e5a0" },
    sliderVal: { fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, color: "#00e5a0", float: "right" },
    runBtn: {
      width: "100%", background: "linear-gradient(135deg,#00c87e,#009e62)",
      color: "#000", border: "none", borderRadius: 6, padding: "11px 0",
      fontFamily: "'IBM Plex Mono', monospace", fontWeight: 700, fontSize: 12,
      letterSpacing: 2, textTransform: "uppercase", cursor: "pointer", marginTop: 8,
    },
    divider: { borderColor: "#1c2e44", margin: "16px 0" },
    title: { fontFamily: "'IBM Plex Mono', monospace", fontSize: 30, fontWeight: 700, color: "#00e5a0", letterSpacing: -0.5 },
    subtitle: { fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: "#4a7a9b", letterSpacing: 2.5, textTransform: "uppercase", marginTop: 2 },
    metricCard: {
      background: "#0f1724", border: "1px solid #1c2e44", borderRadius: 8,
      padding: "16px 20px", textAlign: "center", flex: 1, margin: "0 6px",
    },
    metricVal: { fontFamily: "'IBM Plex Mono', monospace", fontSize: 28, fontWeight: 700, color: "#00e5a0" },
    metricLbl: { fontSize: 10, color: "#4a7a9b", textTransform: "uppercase", letterSpacing: 1.5, marginTop: 4 },
    table: { width: "100%", borderCollapse: "collapse", fontFamily: "'IBM Plex Mono', monospace", fontSize: 12 },
    th: {
      background: "#0a1525", color: "#4a9fb5", borderBottom: "1px solid #1c3550",
      padding: "10px 14px", textAlign: "left", fontSize: 10, textTransform: "uppercase", letterSpacing: 1.5,
    },
    td: { padding: "10px 14px", borderBottom: "1px solid #131d2e", color: "#c8d8e8" },
    emptyState: {
      background: "#0f1724", border: "1px dashed #1c3550", borderRadius: 12,
      padding: "60px 40px", textAlign: "center", marginTop: 40,
    },
    topCard: (color) => ({
      background: "#0f1724", border: "1px solid #1c3550",
      borderTop: `3px solid ${color}`, borderRadius: 8, padding: "16px 14px",
    }),
    progressBar: {
      height: 3, background: "#0f1724", borderRadius: 2, margin: "12px 0", overflow: "hidden",
    },
    toggle: {
      display: "flex", alignItems: "center", gap: 10, marginTop: 8,
    },
  };

  const passed = results.length;
  const avgScore = passed > 0 ? (results.reduce((a, b) => a + b.score, 0) / passed).toFixed(1) : "—";
  const topPick = passed > 0 ? results[0].ticker : "—";

  return (
    <div style={styles.root}>
      {/* ── Sidebar ── */}
      <aside style={styles.sidebar}>
        <div style={{ fontFamily: "'IBM Plex Mono',monospace", fontSize: 13, color: "#00e5a0", fontWeight: 700, marginBottom: 20 }}>
          ⚙ SCREENER SETTINGS
        </div>

        <label style={styles.label}>Stock Universe</label>
        <select style={styles.select} value={universe} onChange={e => setUniverse(e.target.value)}>
          {["Nifty 50 (NSE)", "Nifty 500 (NSE)", "S&P 500 Sample (NYSE)"].map(u => (
            <option key={u}>{u}</option>
          ))}
        </select>

        <hr style={styles.divider} />
        <div style={{ ...styles.label, marginBottom: 14, color: "#7fa8c4" }}>FILTERS</div>

        {[
          { lbl: "Max PE Ratio", val: peMax, set: setPeMax, min: 5, max: 50, step: 0.5, suffix: "×" },
          { lbl: "Min Volume Spike", val: volMult, set: setVolMult, min: 1, max: 10, step: 0.1, suffix: "× avg" },
          { lbl: "Min RSI (14)", val: rsiMin, set: setRsiMin, min: 30, max: 80, step: 1, suffix: "" },
        ].map(({ lbl, val, set, min, max, step, suffix }) => (
          <div key={lbl} style={styles.sliderWrap}>
            <label style={styles.label}>
              {lbl}
              <span style={styles.sliderVal}>{val}{suffix}</span>
            </label>
            <input type="range" min={min} max={max} step={step} value={val}
              style={styles.slider} onChange={e => set(parseFloat(e.target.value))} />
          </div>
        ))}

        <hr style={styles.divider} />

        <div style={styles.toggle}>
          <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)} id="ar" />
          <label htmlFor="ar" style={{ fontSize: 12, color: "#7fa8c4", cursor: "pointer" }}>
            Auto-refresh (60s)
          </label>
        </div>
        {autoRefresh && hasRun && (
          <div style={{ fontFamily: "'IBM Plex Mono',monospace", fontSize: 10, color: "#2e5070", marginTop: 6 }}>
            ⏱ Refreshing in {countdown}s
          </div>
        )}

        <button style={styles.runBtn} onClick={handleRun} disabled={running}>
          {running ? "SCANNING…" : "▶  SCAN NOW"}
        </button>

        <hr style={styles.divider} />
        <div style={{ fontSize: 10, color: "#2e4060", lineHeight: 1.9 }}>
          <b style={{ color: "#4a7a9b" }}>Data source</b><br />
          Yahoo Finance via yfinance<br /><br />
          <b style={{ color: "#4a7a9b" }}>Scoring</b><br />
          PE (40pts) + Vol (30pts) + RSI (30pts)<br /><br />
          <b style={{ color: "#4a7a9b" }}>Indicators</b><br />
          RSI-14 · 20-day avg vol · Trailing PE
        </div>
      </aside>

      {/* ── Main ── */}
      <main style={styles.main}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
          <div>
            <div style={styles.title}>📈 StockSight</div>
            <div style={styles.subtitle}>Real-time Fundamental + Momentum Screener</div>
          </div>
          {lastRun && (
            <div style={{ fontFamily: "'IBM Plex Mono',monospace", fontSize: 10, color: "#2e5070", marginTop: 4 }}>
              <span style={{ display:"inline-block", width:7, height:7, borderRadius:"50%", background:"#00e5a0", marginRight:5, verticalAlign:"middle" }} />
              Last run: {lastRun}
            </div>
          )}
        </div>
        <hr style={styles.divider} />

        {/* Progress */}
        {running && (
          <div style={styles.progressBar}>
            <div style={{ height: "100%", width: `${progress}%`, background: "#00e5a0", transition: "width 0.2s", borderRadius: 2 }} />
          </div>
        )}

        {/* Empty state */}
        {!hasRun && !running && (
          <div style={styles.emptyState}>
            <div style={{ fontSize: 48, marginBottom: 16 }}>🔍</div>
            <div style={{ fontFamily: "'IBM Plex Mono',monospace", color: "#3a6080", fontSize: 16 }}>
              Configure your filters and click <span style={{ color: "#00c87e" }}>SCAN NOW</span>
            </div>
            <div style={{ color: "#2e4060", fontSize: 11, marginTop: 10 }}>
              Scanning {universe} against PE · Volume · RSI criteria
            </div>
          </div>
        )}

        {/* Results */}
        {hasRun && !running && (
          <>
            {/* Metrics row */}
            <div style={{ display: "flex", margin: "0 -6px 24px" }}>
              {[
                { v: "50", l: "Stocks Scanned" },
                { v: String(passed), l: "Passed Filters" },
                { v: String(avgScore), l: "Avg Score" },
                { v: topPick, l: "Top Pick" },
              ].map(({ v, l }) => (
                <div key={l} style={styles.metricCard}>
                  <div style={styles.metricVal}>{v}</div>
                  <div style={styles.metricLbl}>{l}</div>
                </div>
              ))}
            </div>

            {passed === 0 ? (
              <div style={{ background: "#1a1000", border: "1px solid #3a2800", borderRadius: 8, padding: "16px 20px", color: "#f0b429", fontSize: 13 }}>
                ⚠ No stocks passed the current filters. Try relaxing the thresholds.
              </div>
            ) : (
              <>
                {/* Table */}
                <div style={{ marginBottom: 8, fontFamily: "'IBM Plex Mono',monospace", fontSize: 13, color: "#7fa8c4" }}>Results</div>
                <div style={{ background: "#0f1724", borderRadius: 8, overflow: "hidden", border: "1px solid #1c2e44" }}>
                  <table style={styles.table}>
                    <thead>
                      <tr>
                        {["Rank", "Ticker", "Price (₹)", "PE Ratio", "Volume Ratio", "RSI", "Score"].map(h => (
                          <th key={h} style={styles.th}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {results.map(row => (
                        <tr key={row.ticker} style={{ transition: "background 0.1s" }}
                          onMouseEnter={e => e.currentTarget.style.background = "#121e30"}
                          onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                          <td style={{ ...styles.td, color: "#4a7a9b" }}>#{row.rank}</td>
                          <td style={{ ...styles.td, fontWeight: 700, color: "#fff" }}>{row.ticker}</td>
                          <td style={styles.td}>{row.price.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
                          <td style={styles.td}>{row.pe.toFixed(1)}×</td>
                          <td style={{ ...styles.td, color: row.volRatio >= 3 ? "#00e5a0" : "#c8d8e8" }}>{row.volRatio.toFixed(2)}×</td>
                          <td style={{ ...styles.td, color: row.rsi >= 65 ? "#00e5a0" : "#c8d8e8" }}>{row.rsi.toFixed(1)}</td>
                          <td style={{ ...styles.td, color: scoreColor(row.score), fontWeight: 700 }}>
                            <span style={{ fontSize: 9, letterSpacing: -1 }}>{scoreBar(row.score)}</span>
                            {" "}{row.score.toFixed(1)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Top cards */}
                <div style={{ marginTop: 28, marginBottom: 10, fontFamily: "'IBM Plex Mono',monospace", fontSize: 13, color: "#7fa8c4" }}>
                  🏆 Top Picks — Detailed View
                </div>
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                  {results.slice(0, 5).map(row => {
                    const c = scoreColor(row.score);
                    return (
                      <div key={row.ticker} style={{ ...styles.topCard(c), minWidth: 140, flex: 1 }}>
                        <div style={{ fontFamily: "'IBM Plex Mono',monospace", fontWeight: 700, color: "#fff", fontSize: 15 }}>
                          #{row.rank} {row.ticker}
                        </div>
                        <div style={{ color: "#4a7a9b", fontSize: 11, margin: "6px 0 12px" }}>
                          ₹{row.price.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                        </div>
                        <div style={{ fontSize: 11, lineHeight: 2.1, color: "#8aa8c4" }}>
                          <span style={{ color: "#4a7a9b" }}>PE   </span>{row.pe.toFixed(1)}×<br />
                          <span style={{ color: "#4a7a9b" }}>VOL  </span>{row.volRatio.toFixed(2)}× avg<br />
                          <span style={{ color: "#4a7a9b" }}>RSI  </span>{row.rsi.toFixed(1)}
                        </div>
                        <div style={{ marginTop: 10 }}>
                          <div style={{ fontSize: 9, color: "#2e5070", marginBottom: 2 }}>SCORE</div>
                          <div style={{ fontFamily: "'IBM Plex Mono',monospace", color: c, fontSize: 10 }}>
                            {scoreBar(row.score)} {row.score.toFixed(1)}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </>
        )}

        {/* Footer */}
        <div style={{ marginTop: 40, paddingTop: 16, borderTop: "1px solid #1c2e44", fontSize: 10, color: "#2e4060", textAlign: "center" }}>
          StockSight · Data via Yahoo Finance (yfinance) · For educational purposes only. Not financial advice.
        </div>
      </main>
    </div>
  );
}
