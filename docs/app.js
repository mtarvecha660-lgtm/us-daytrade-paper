(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const istFmt = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
  const etFmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
  const ist = (ts) => ts ? istFmt.format(new Date(ts * 1000)) : "–";
  const usd = (v, d = 2) => (v < 0 ? "−$" : "$") + Math.abs(Number(v)).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const sgn = (v, d = 2) => (v > 0 ? "+" : v < 0 ? "−" : "") + "$" + Math.abs(v).toFixed(d);
  const pct = (v) => v == null ? "–" : (v > 0 ? "+" : "") + (v * 100).toFixed(2) + "%";
  const cls = (v) => (v > 0.00005 ? "up" : v < -0.00005 ? "down" : "flat");
  const num = (v, d = 2) => v == null ? "–" : Number(v).toFixed(d);
  let data = null, chart = null;

  function ago(ts) {
    if (!ts) return "never";
    const m = Math.round((Date.now() / 1000 - ts) / 60);
    if (m < 1) return "just now";
    if (m < 60) return m + " min ago";
    const h = Math.floor(m / 60);
    return h < 48 ? h + " h " + (m % 60) + " min ago" : Math.floor(h / 24) + " days ago";
  }

  function marketOpenNow() {
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false })
      .formatToParts(new Date()).map((x) => [x.type, x.value]));
    const hm = Number(p.hour) * 60 + Number(p.minute);
    return !["Sat", "Sun"].includes(p.weekday) && hm >= 9 * 60 + 35 && hm < 16 * 60 + 5;
  }

  function renderClock() {
    if (!data) return;
    const h = data.health || {};
    const ageMin = (Date.now() / 1000 - data.updated) / 60;
    $("updated").textContent = "Updated " + ago(data.updated) + " · " + ist(data.updated) + " IST";
    const late = marketOpenNow() && ageMin > 20;   // ~5-min ticks during the session
    const bad = h.ok === false;
    $("dot").className = "dot " + (bad ? "bad" : late || h.stale_data ? "stale" : "ok");
    const s = $("stale");
    const msgs = [];
    if (bad) msgs.push("The last run failed: " + (h.errors || []).join("; "));
    if (late) msgs.push(`No update for ${Math.round(ageMin)} min while the US market is open: the bot may be stalled. Numbers may be out of date.`);
    else if (h.stale_data) msgs.push(`Yahoo's data is ${h.yahoo_lag_min ?? "?"} min behind the clock: the bot may be acting on old prices.`);
    s.hidden = !msgs.length;
    s.textContent = msgs.join(" ");
  }

  function cards() {
    const a = data.account, s = data.spy, st = data.stats || {}, c = data.curve || {}, sc = data.spy_curve || {};
    const ddBot = Math.min(c.max_drawdown ?? 0, data.intraday_max_drawdown ?? 0);
    $("cards").innerHTML = `
      <div class="card"><div class="row1"><div class="name"><i class="swatch" style="background:#2f5d8a"></i>Day-trade bot</div>
        <span class="pill ${cls(a.return)}">${pct(a.return)}</span></div>
        <div class="why">Opening-range breakouts, flat every night</div>
        <div class="eq">${usd(a.equity)}<small>of $10,000</small></div>
        <dl class="kv"><dt>Trades</dt><dd>${st.trades || 0}${st.trades ? ` · ${(st.win_rate * 100).toFixed(0)}% won` : ""}</dd>
        <dt>Avg R</dt><dd>${st.avg_r == null ? "–" : (st.avg_r > 0 ? "+" : "") + st.avg_r.toFixed(2) + "R"}</dd>
        <dt>Max drawdown</dt><dd>${pct(ddBot)}</dd></dl></div>
      <div class="card hold"><div class="row1"><div class="name"><i class="swatch" style="background:#9a9a9a"></i>Just hold SPY</div>
        <span class="pill ${cls(s.return ?? 0)}">${pct(s.return)}</span></div>
        <div class="why">Bought with $10,000 at the bot’s first bar, never sold</div>
        <div class="eq">${s.value ? usd(s.value) : "–"}<small>${s.last ? "SPY $" + num(s.last) : "waiting for the first open"}</small></div>
        <dl class="kv"><dt>Bought at</dt><dd>${s.start_price ? "$" + num(s.start_price) : "–"}</dd>
        <dt>Max drawdown</dt><dd>${pct(sc.max_drawdown)}</dd><dt>Bot vs SPY</dt><dd class="${cls((a.return ?? 0) - (s.return ?? 0))}">${s.return == null ? "–" : pct(a.return - s.return)}</dd></dl></div>`;
  }

  function why(w) {
    if (!w) return "";
    const order = [["scanner", "Scanner"], ["exit", "Exit plan"], ["budget", "Budget"], ["risk", "Risk check"], ["approval", "Approval"]];
    return `<details class="why"><summary>full reasoning</summary><ol>${order.filter(([k]) => w[k]).map(([k, n]) => `<li><b>${n}:</b> ${esc(w[k])}</li>`).join("")}</ol></details>`;
  }

  function position() {
    const p = data.position, q = data.pending;
    if (p) {
      $("poshint").textContent = "bought " + p.entry_et + " ET";
      $("position").innerHTML = `<div class="pos"><div><span>Stock</span><b>${esc(p.symbol)}</b> × ${p.qty}</div>
        <div><span>Entry</span>$${num(p.entry)}</div><div><span>Stop</span><b class="down">$${num(p.stop)}</b></div>
        <div><span>Target (1R)</span><b class="up">$${num(p.target)}</b></div></div>${why(p.why)}`;
    } else if (q) {
      $("poshint").textContent = "order waiting for the next bar";
      $("position").innerHTML = `<div class="pos"><div><span>Buying</span><b>${esc(q.symbol)}</b> × ${q.qty}</div>
        <div><span>Signal</span>${esc(q.plan.entry_time)}</div><div><span>Stop</span>$${num(q.plan.stop)}</div><div><span>Target</span>$${num(q.plan.target)}</div></div>${why(q.why)}`;
    } else {
      $("poshint").textContent = "";
      $("position").innerHTML = `<div class="empty">No open position. The bot is in cash.</div>`;
    }
  }

  function stats() {
    const st = data.stats || {}, c = data.curve || {}, sc = data.spy_curve || {};
    const items = [
      ["Win rate", st.trades ? (st.win_rate * 100).toFixed(0) + "%" : "–"],
      ["Avg R / trade", st.avg_r == null ? "–" : (st.avg_r > 0 ? "+" : "") + st.avg_r.toFixed(2) + "R"],
      ["Profit factor", st.profit_factor == null ? "–" : st.profit_factor.toFixed(2)],
      ["Expectancy", st.trades ? sgn(st.expectancy_usd) + "/trade" : "–"],
      ["Max drawdown", pct(Math.min(c.max_drawdown ?? 0, data.intraday_max_drawdown ?? 0))],
      ["Slippage paid", st.trades ? usd(st.costs_usd) : "–"],
      ["Sharpe bot / SPY", `${num(c.sharpe)} / ${num(sc.sharpe)}`],
      ["Sortino bot / SPY", `${num(c.sortino)} / ${num(sc.sortino)}`],
    ];
    $("stats").innerHTML = items.map(([k, v]) => `<div class="stat"><span>${k}</span><b>${v}</b></div>`).join("");
    const n = st.trades || 0;
    $("scorehint").textContent = n >= 100 ? `${n} trades` : `${n} of the 100 trades needed for a verdict`;
  }

  function hits() {
    const t = data.today || {};
    const taken = new Set((data.trades || []).filter((x) => x.date === t.date).map((x) => x.symbol));
    if (data.position) taken.add(data.position.symbol);
    const hs = (t.hits || []).slice().reverse();
    $("hitshint").textContent = t.date ? `${t.n_hits} breakouts · ${t.entries}/${t.max_trades} trades used · ${t.date}` : "";
    const more = hs.length > 24 ? `<span class="hit">+${hs.length - 24} earlier</span>` : "";
    $("hits").innerHTML = hs.length ? hs.slice(0, 24).map((h) => `<span class="hit ${taken.has(h.symbol) ? "taken" : ""}"><b>${esc(h.symbol)}</b> ${esc(h.at)} $${num(h.price)} <span class="up">+${num(h.pct_over)}%</span></span>`).join("") + more
      : `<div class="empty">No breakouts yet today. Hits appear from 9:50 AM ET (8:20 PM IST).</div>`;
  }

  function trades() {
    const ts = data.trades || [];
    $("tradecount").textContent = ts.length ? `${(data.stats || {}).trades} closed` : "";
    $("trades").innerHTML = ts.length ? ts.slice(0, 60).map((t) => `<div class="t"><div class="l1"><span><span class="tag ${t.pnl > 0 ? "BUY" : "SELL"}">${t.r > 0 ? "+" : ""}${num(t.r)}R</span><b>${esc(t.symbol)}</b> × ${t.qty}</span>
      <span class="${cls(t.pnl)}"><b>${sgn(t.pnl)}</b></span></div>
      <div class="when">${esc(t.date)} · in ${esc(t.entry_et)} @ $${num(t.entry_fill)} → out ${esc(t.exit_et)} @ $${num(t.exit_fill)} ET</div>
      <div class="reason">Exit: ${esc(t.exit_reason)}${t.late ? " · decided on a late run" : ""}</div>${why(t.why)}</div>`).join("")
      : `<div class="empty">No trades yet.</div>`;
  }

  function decisions() {
    const ds = data.decisions || [];
    $("decisions").innerHTML = ds.length ? ds.slice(0, 40).map((d) => `<div class="dec"><span class="when">${esc(d.et)} ET</span>${esc(d.text)}</div>`).join("")
      : `<div class="empty">Nothing yet: the first decisions come after 9:50 AM ET.</div>`;
  }

  function ticks() {
    const rs = data.runs || [];
    $("tickhint").textContent = "every ~5 min in market hours";
    $("ticks").innerHTML = rs.length ? rs.slice(0, 25).map((r) => `<div class="k"><span>${ist(r.ts)} IST</span><span>${esc(r.phase || "")}${r.bars ? " · " + r.bars + " bars" : ""}</span>
      <span class="st-${r.status === "ok" ? "ok" : "error"}">${esc(r.status)}${r.errors && r.errors.length ? ": " + esc(r.errors[0]) : ""}</span></div>`).join("")
      : `<div class="empty">No runs yet.</div>`;
  }

  function drawChart() {
    const pts = (data.equity || []).filter((p) => p.equity != null);
    if (!window.Chart) return;
    const lab = pts.map((p) => ist(p.ts));
    const ds = [
      { label: "Bot", data: pts.map((p) => p.equity), borderColor: "#2f5d8a", backgroundColor: "#2f5d8a", borderWidth: 2, pointRadius: 0, tension: 0.1 },
      { label: "Just hold SPY", data: pts.map((p) => p.spy), borderColor: "#9a9a9a", backgroundColor: "#9a9a9a", borderWidth: 1.6, pointRadius: 0, borderDash: [4, 3], tension: 0.1 },
    ];
    if (chart) chart.destroy();
    chart = new Chart($("chart"), { type: "line", data: { labels: lab, datasets: ds },
      options: { responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => c.dataset.label + ": " + usd(c.parsed.y) } } },
        scales: { x: { ticks: { maxTicksLimit: 5, autoSkip: true, maxRotation: 0 }, grid: { display: false } },
                  y: { ticks: { callback: (v) => "$" + Number(v).toLocaleString("en-US") } } } } });
  }

  function render() {
    const ph = { open: "Open", "pre-open": "Pre-open", "after-close": "Closed", closed: "Closed" }[data.phase] || data.phase;
    $("phase").textContent = ph + " · " + (data.updated_et || "");
    $("nextmove").textContent = data.next_move || "–";
    cards(); position(); stats(); hits(); trades(); decisions(); ticks(); drawChart(); renderClock();
  }

  async function load() {
    try {
      const r = await fetch("data/latest.json?t=" + Date.now(), { cache: "no-store" });
      data = await r.json();
      render();
    } catch (e) {
      $("updated").textContent = "couldn't load data";
      $("dot").className = "dot bad";
    }
  }
  load();
  setInterval(load, 120000);
  setInterval(renderClock, 30000);
})();
