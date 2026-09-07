/* MoneyTrack — Rocket Money style prototype.
   Frontend: static site. Backend: Azure Functions + Table Storage + Plaid (sandbox).
   Local/manual data (budgets, recurring, manual txns, accounts) stays in localStorage.
   Bank transactions live server-side per signed-in user. */

const API = "https://moneytrack-api-nitin.azurewebsites.net/api";

const CATEGORIES = {
  "Groceries":     { icon: "🛒", color: "#7c5cff" },
  "Dining":        { icon: "🍔", color: "#00d4a6" },
  "Transport":     { icon: "🚗", color: "#ffc555" },
  "Shopping":      { icon: "🛍️", color: "#ff5c7a" },
  "Entertainment": { icon: "🎬", color: "#4fc3f7" },
  "Utilities":     { icon: "💡", color: "#ff9d5c" },
  "Housing":       { icon: "🏠", color: "#b98cff" },
  "Health":        { icon: "🩺", color: "#5cffb8" },
  "Subscriptions": { icon: "🔁", color: "#f76dd8" },
  "Income":        { icon: "💵", color: "#2fd67b" },
  "Other":         { icon: "📦", color: "#8b8fa8" },
};

const STORE_KEY = "moneyTrack.v1";
const SESSION_KEY = "moneyTrack.session";
let state = null;          // local data (manual txns, budgets, recurring, accounts)
let session = null;        // { token, email, userId }
let me = null;             // server profile: banks, invited, sharedWithMe
let bankTxns = [];         // bank transactions (mine, or the person I'm viewing)
let viewingAs = null;      // null = my data; { ownerId, ownerEmail } = someone who invited me
let charts = {};

/* ================= API ================= */

async function api(path, body) {
  const headers = { "Content-Type": "application/json" };
  if (session) headers["Authorization"] = "Bearer " + session.token;
  const res = await fetch(`${API}/${path}`, {
    method: "POST", headers, body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && session) { logout(false); }
    throw new Error(data.error || `Request failed (${res.status})`);
  }
  return data;
}

async function refreshServer() {
  if (!session) { me = null; bankTxns = []; return; }
  try {
    me = await api("me");
    const ownerId = viewingAs ? viewingAs.ownerId : undefined;
    const data = await api("get_transactions", ownerId ? { owner_id: ownerId } : {});
    bankTxns = data.transactions.map(t => ({ ...t, source: "bank" }));
  } catch (e) {
    if (session) toast(e.message);
  }
}

function logout(redraw = true) {
  session = null; me = null; bankTxns = []; viewingAs = null;
  try { localStorage.removeItem(SESSION_KEY); } catch (e) {}
  if (redraw) render();
}

/* ================= Local data ================= */

function id() { return Math.random().toString(36).slice(2, 10); }

function todayISO(offsetDays = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}
function monthISO(offsetMonths = 0) {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth() + offsetMonths, 15).toISOString().slice(0, 7);
}
function firstOfNextMonth() {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth() + 1, 1).toISOString().slice(0, 10);
}

function seedData() {
  const mk = (name, category, amount, type, date) => ({ id: id(), name, category, amount, type, date });
  const txns = [
    mk("Paycheck — Acme Corp", "Income", 3450.00, "income", todayISO(-4)),
    mk("Whole Foods", "Groceries", 128.43, "expense", todayISO(-1)),
    mk("Shell Gas", "Transport", 46.20, "expense", todayISO(-2)),
    mk("Chipotle", "Dining", 18.75, "expense", todayISO(-2)),
    mk("Amazon", "Shopping", 74.99, "expense", todayISO(-3)),
    mk("Netflix", "Subscriptions", 15.49, "expense", todayISO(-5)),
    mk("Electric bill", "Utilities", 132.00, "expense", todayISO(-6)),
    mk("Rent", "Housing", 1850.00, "expense", todayISO(-6)),
    mk("Costco", "Groceries", 214.10, "expense", todayISO(-8)),
    mk("AMC Theatres", "Entertainment", 32.00, "expense", todayISO(-9)),
    mk("CVS Pharmacy", "Health", 24.60, "expense", todayISO(-11)),
    mk("Uber", "Transport", 22.35, "expense", todayISO(-12)),
    mk("Trader Joe's", "Groceries", 87.20, "expense", todayISO(-15)),
    mk("Spotify", "Subscriptions", 11.99, "expense", todayISO(-16)),
    mk("Paycheck — Acme Corp", "Income", 3450.00, "income", todayISO(-18)),
  ];
  for (let m = 1; m <= 5; m++) {
    const base = new Date();
    const mkD = (day) => new Date(base.getFullYear(), base.getMonth() - m, day).toISOString().slice(0, 10);
    const jitter = (v) => Math.round(v * (0.85 + Math.random() * 0.3) * 100) / 100;
    txns.push(
      mk("Paycheck — Acme Corp", "Income", 3450.00, "income", mkD(1)),
      mk("Paycheck — Acme Corp", "Income", 3450.00, "income", mkD(15)),
      mk("Rent", "Housing", 1850.00, "expense", mkD(2)),
      mk("Groceries", "Groceries", jitter(430), "expense", mkD(9)),
      mk("Dining out", "Dining", jitter(160), "expense", mkD(12)),
      mk("Gas & rides", "Transport", jitter(120), "expense", mkD(14)),
      mk("Shopping", "Shopping", jitter(180), "expense", mkD(18)),
      mk("Utilities", "Utilities", jitter(210), "expense", mkD(20)),
      mk("Subscriptions", "Subscriptions", 27.48, "expense", mkD(21)),
      mk("Fun", "Entertainment", jitter(70), "expense", mkD(23)),
    );
  }
  return {
    transactions: txns,
    recurring: [
      { id: id(), name: "Rent", amount: 1850.00, cadence: "monthly", nextDue: firstOfNextMonth() },
      { id: id(), name: "Netflix", amount: 15.49, cadence: "monthly", nextDue: todayISO(25) },
      { id: id(), name: "Spotify", amount: 11.99, cadence: "monthly", nextDue: todayISO(14) },
      { id: id(), name: "Electric bill", amount: 132.00, cadence: "monthly", nextDue: todayISO(24) },
      { id: id(), name: "Car insurance", amount: 148.00, cadence: "monthly", nextDue: todayISO(9) },
      { id: id(), name: "iCloud storage", amount: 2.99, cadence: "monthly", nextDue: todayISO(3) },
      { id: id(), name: "Gym membership", amount: 39.99, cadence: "monthly", nextDue: todayISO(1) },
      { id: id(), name: "Internet", amount: 79.99, cadence: "monthly", nextDue: todayISO(19) },
    ],
    budgets: [
      { id: id(), category: "Groceries", limit: 500 },
      { id: id(), category: "Dining", limit: 200 },
      { id: id(), category: "Transport", limit: 150 },
      { id: id(), category: "Shopping", limit: 250 },
      { id: id(), category: "Entertainment", limit: 100 },
    ],
    accounts: [
      { id: id(), name: "Checking — Chase", balance: 4820.55, kind: "asset" },
      { id: id(), name: "Savings — Ally", balance: 12300.00, kind: "asset" },
      { id: id(), name: "Brokerage — Robinhood", balance: 28450.00, kind: "asset" },
      { id: id(), name: "401(k)", balance: 46200.00, kind: "asset" },
      { id: id(), name: "Credit card — Amex", balance: 1240.33, kind: "debt" },
      { id: id(), name: "Car loan", balance: 8900.00, kind: "debt" },
    ],
  };
}

function emptyData() {
  return { transactions: [], recurring: [], budgets: [], accounts: [] };
}

function load() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (raw) { state = JSON.parse(raw); }
  } catch (e) {}
  if (!state) { state = seedData(); save(); }
  try {
    const s = localStorage.getItem(SESSION_KEY);
    if (s) session = JSON.parse(s);
  } catch (e) {}
}

function save() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (e) {}
}
function saveSession() {
  try { localStorage.setItem(SESSION_KEY, JSON.stringify(session)); } catch (e) {}
}

/* ================= Helpers ================= */

const fmt  = (n) => n.toLocaleString("en-US", { style: "currency", currency: "USD" });
const fmt0 = (n) => n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const catInfo = (c) => CATEGORIES[c] || CATEGORIES["Other"];
const monthOf = (d) => String(d).slice(0, 7);
const thisMonth = () => monthISO(0);

// All transactions in view: someone else's = bank only; mine = manual + bank.
function getTxns() {
  if (viewingAs) return bankTxns;
  return [...state.transactions, ...bankTxns];
}

function niceDate(dateStr) {
  return new Date(dateStr + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
function monthLabel(ym) {
  const [y, m] = ym.split("-").map(Number);
  return new Date(y, m - 1, 15).toLocaleDateString("en-US", { month: "short" });
}
function daysUntil(dateStr) {
  return Math.round((new Date(dateStr + "T12:00:00") - new Date(todayISO() + "T12:00:00")) / 86400000);
}

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstChild;
}
function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
}

function toast(msg) {
  const root = document.getElementById("toast");
  root.innerHTML = "";
  const m = el(`<div class="toast-msg">${esc(msg)}</div>`);
  root.appendChild(m);
  setTimeout(() => { if (m.parentNode) m.remove(); }, 3000);
}

function sumTxns(type, month) {
  return getTxns()
    .filter(t => t.type === type && (!month || monthOf(t.date) === month))
    .reduce((s, t) => s + t.amount, 0);
}

function spentByCategory(month) {
  const out = {};
  for (const t of getTxns()) {
    if (t.type !== "expense" || monthOf(t.date) !== month) continue;
    out[t.category] = (out[t.category] || 0) + t.amount;
  }
  return out;
}

function destroyCharts() {
  for (const k of Object.keys(charts)) { try { charts[k].destroy(); } catch (e) {} }
  charts = {};
}

if (window.Chart) {
  Chart.defaults.color = "#8b8fa8";
  Chart.defaults.borderColor = "#2a2c45";
  Chart.defaults.font.family = '"Segoe UI", system-ui, sans-serif';
}

/* ================= Router ================= */

const ROUTES = {
  dashboard: renderDashboard,
  transactions: renderTransactions,
  recurring: renderRecurring,
  spending: renderSpending,
  budgets: renderBudgets,
  accounts: renderAccounts,
  networth: renderNetWorth,
  settings: renderSettings,
};

function currentRoute() {
  const h = location.hash.replace("#", "");
  return ROUTES[h] ? h : "dashboard";
}

function render() {
  destroyCharts();
  const main = document.getElementById("main");
  main.innerHTML = "";

  if (!session) { renderAuth(main); syncSidebar(); return; }

  const route = currentRoute();
  document.querySelectorAll("nav a").forEach(a => {
    a.classList.toggle("active", a.getAttribute("href") === "#" + route);
  });
  if (viewingAs) {
    main.appendChild(el(`
      <div class="card" style="border-color:#7c5cff;display:flex;align-items:center;gap:12px;justify-content:space-between">
        <span>👀 Viewing <b>${esc(viewingAs.ownerEmail)}</b>'s bank transactions (read-only)</span>
        <button class="btn ghost" id="btnStopViewing">Back to my data</button>
      </div>`));
    main.querySelector("#btnStopViewing").onclick = async () => {
      viewingAs = null; await refreshServer(); render();
    };
  }
  ROUTES[route](main);
  syncSidebar();
}

function syncSidebar() {
  let footer = document.querySelector(".sidebar-footer");
  let userBox = document.getElementById("userBox");
  if (!userBox) {
    userBox = el(`<div id="userBox" class="tiny muted" style="margin-top:8px"></div>`);
    footer.appendChild(userBox);
  }
  userBox.innerHTML = session
    ? `Signed in as <b>${esc(session.email)}</b> · <a href="#" id="lnkLogout" style="color:inherit">log out</a>`
    : `Not signed in`;
  const lnk = document.getElementById("lnkLogout");
  if (lnk) lnk.onclick = (e) => { e.preventDefault(); logout(); toast("Logged out"); };
}

window.addEventListener("hashchange", render);

/* ================= Auth view ================= */

function renderAuth(main) {
  main.appendChild(el(`
    <div style="max-width:400px;margin:8vh auto 0">
      <header class="view-header" style="text-align:center">
        <h1>💸 MoneyTrack</h1>
        <p class="sub">Sign in to track your money</p>
      </header>
      <div class="card">
        <div class="card-title" id="authTitle">Sign in</div>
        <form id="authForm">
          <div class="form-field"><label>Email</label><input name="email" type="email" required placeholder="you@example.com"></div>
          <div class="form-field"><label>Password</label><input name="password" type="password" required minlength="8" placeholder="min 8 characters"></div>
          <div class="form-field" id="tfaField" style="display:none"><label>2FA code</label><input name="code" inputmode="numeric" pattern="[0-9]{6}" placeholder="6-digit code from your authenticator app"></div>
          <button type="submit" class="btn primary block" id="authSubmit">Sign in</button>
        </form>
        <p class="tiny muted" style="margin-top:14px;text-align:center">
          <span id="authToggleText">No account?</span>
          <a href="#" id="authToggle" style="color:#7c5cff">Create one</a>
        </p>
        <p class="tiny muted" id="authError" style="color:#ff5c7a;margin-top:10px;text-align:center"></p>
      </div>
    </div>`));

  let mode = "login";
  const toggle = document.getElementById("authToggle");
  toggle.onclick = (e) => {
    e.preventDefault();
    mode = mode === "login" ? "signup" : "login";
    document.getElementById("authTitle").textContent = mode === "login" ? "Sign in" : "Create account";
    document.getElementById("authSubmit").textContent = mode === "login" ? "Sign in" : "Sign up";
    document.getElementById("authToggleText").textContent = mode === "login" ? "No account?" : "Already registered?";
    toggle.textContent = mode === "login" ? "Create one" : "Sign in";
  };
  document.getElementById("authForm").onsubmit = async (e) => {
    e.preventDefault();
    const d = new FormData(e.target);
    const btn = document.getElementById("authSubmit");
    btn.disabled = true; btn.textContent = "…";
    try {
      const payload = { email: d.get("email"), password: d.get("password") };
      const code = d.get("code");
      if (code) payload.code = code;
      const data = await api(mode, payload);
      if (data.requires_2fa) {
        document.getElementById("tfaField").style.display = "";
        document.getElementById("authError").textContent = "Enter the 6-digit code from your authenticator app";
        btn.disabled = false; btn.textContent = "Sign in";
        e.target.querySelector('[name="code"]').focus();
        return;
      }
      session = { token: data.token, email: data.email, userId: data.userId };
      saveSession();
      await refreshServer();
      toast(mode === "signup" ? "Account created — welcome!" : "Welcome back!");
      render();
    } catch (err) {
      document.getElementById("authError").textContent = err.message;
      btn.disabled = false;
      btn.textContent = mode === "login" ? "Sign in" : "Sign up";
    }
  };
}

/* ================= Shared row builders ================= */

function txnRow(t, withActions = true) {
  const info = catInfo(t.category);
  const isIncome = t.type === "income";
  const isBank = t.source === "bank";
  const row = el(`
    <div class="list-row">
      <div class="row-icon">${info.icon}</div>
      <div class="row-main">
        <div class="row-title">${esc(t.name)}${t.pending ? ' <span class="pill">pending</span>' : ""}</div>
        <div class="row-sub">${esc(t.category)} · ${niceDate(t.date)}${isBank ? " · 🏦 bank" : ""}</div>
      </div>
      <div class="row-amount ${isIncome ? "green" : ""}">${isIncome ? "+" : "−"}${fmt(t.amount)}</div>
      ${withActions && !isBank ? `<div class="row-actions"><button class="icon-btn" title="Delete">🗑</button></div>` : ""}
    </div>`);
  if (withActions && !isBank) {
    row.querySelector(".icon-btn").onclick = () => {
      state.transactions = state.transactions.filter(x => x.id !== t.id);
      save(); render(); toast("Transaction deleted");
    };
  }
  return row;
}

function dueBadge(dateStr) {
  const days = daysUntil(dateStr);
  const cls = days <= 0 ? "today" : days <= 5 ? "soon" : "";
  const txt = days <= 0 ? "Due today" : days === 1 ? "Tomorrow" : `In ${days} days`;
  return `<span class="due-badge ${cls}">${txt}</span>`;
}

/* ================= Views ================= */

function renderDashboard(main) {
  const hr = new Date().getHours();
  const greeting = hr < 12 ? "Good morning" : hr < 17 ? "Good afternoon" : "Good evening";
  const tm = thisMonth(), lm = monthISO(-1);
  const spent = sumTxns("expense", tm);
  const spentLast = sumTxns("expense", lm);
  const income = sumTxns("income", tm);
  const recTotal = state.recurring.reduce((s, r) => s + r.amount, 0);
  const assets = state.accounts.filter(a => a.kind === "asset").reduce((s, a) => s + a.balance, 0);
  const debts = state.accounts.filter(a => a.kind === "debt").reduce((s, a) => s + a.balance, 0);

  const diff = spent - spentLast;
  const deltaHtml = spentLast > 0
    ? `<div class="stat-delta ${diff >= 0 ? "up" : "down"}">${diff >= 0 ? "▲" : "▼"} ${fmt0(Math.abs(diff))} vs last month</div>`
    : `<div class="stat-delta muted">no data for last month</div>`;

  main.appendChild(el(`
    <div>
      <header class="view-header">
        <h1>${greeting}</h1>
        <p class="sub">${new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" })}</p>
      </header>
      <div class="grid grid-4">
        <div class="card"><div class="stat-label">Spent this month</div><div class="stat-value">${fmt0(spent)}</div>${deltaHtml}</div>
        <div class="card"><div class="stat-label">Income this month</div><div class="stat-value green">${fmt0(income)}</div><div class="stat-delta muted">paychecks &amp; deposits</div></div>
        <div class="card"><div class="stat-label">Recurring / mo</div><div class="stat-value">${fmt0(recTotal)}</div><div class="stat-delta muted">${state.recurring.length} active charges</div></div>
        <div class="card"><div class="stat-label">Net worth</div><div class="stat-value">${fmt0(assets - debts)}</div><div class="stat-delta muted">${fmt0(assets)} assets − ${fmt0(debts)} debts</div></div>
      </div>
      <div class="grid grid-2">
        <div class="card">
          <div class="card-title">Spending by category <span class="pill">${new Date().toLocaleDateString("en-US", { month: "long" })}</span></div>
          <div class="chart-box"><canvas id="chartDonut"></canvas></div>
        </div>
        <div class="card">
          <div class="card-title">Upcoming bills <span class="pill">next 30 days</span></div>
          <div class="list" id="dashBills"></div>
        </div>
      </div>
      <div class="card">
        <div class="card-title">Recent transactions</div>
        <div class="list" id="dashRecent"></div>
      </div>
    </div>`));

  const byCat = spentByCategory(tm);
  const entries = Object.entries(byCat).sort((a, b) => b[1] - a[1]);
  if (entries.length && window.Chart) {
    charts.donut = new Chart(document.getElementById("chartDonut"), {
      type: "doughnut",
      data: {
        labels: entries.map(e => e[0]),
        datasets: [{ data: entries.map(e => e[1]), backgroundColor: entries.map(e => catInfo(e[0]).color), borderWidth: 0 }],
      },
      options: { maintainAspectRatio: false, cutout: "68%", plugins: { legend: { position: "right", labels: { boxWidth: 12, padding: 10 } } } },
    });
  }

  const bills = document.getElementById("dashBills");
  const upcoming = [...state.recurring].filter(r => daysUntil(r.nextDue) <= 30)
    .sort((a, b) => a.nextDue.localeCompare(b.nextDue)).slice(0, 6);
  if (!upcoming.length) bills.appendChild(el(`<div class="empty">Nothing due in the next 30 days 🎉</div>`));
  for (const r of upcoming) {
    bills.appendChild(el(`
      <div class="list-row">
        <div class="row-icon">🔁</div>
        <div class="row-main"><div class="row-title">${esc(r.name)}</div><div class="row-sub">${niceDate(r.nextDue)}</div></div>
        ${dueBadge(r.nextDue)}
        <div class="row-amount">${fmt(r.amount)}</div>
      </div>`));
  }

  const recent = document.getElementById("dashRecent");
  const txns = [...getTxns()].sort((a, b) => String(b.date).localeCompare(String(a.date))).slice(0, 6);
  if (!txns.length) recent.appendChild(el(`<div class="empty">No transactions yet.</div>`));
  for (const t of txns) recent.appendChild(txnRow(t, false));
}

function renderTransactions(main) {
  main.appendChild(el(`
    <div>
      <header class="view-header row">
        <div><h1>Transactions</h1><p class="sub" id="txnCount"></p></div>
        <div style="display:flex;gap:10px">
          ${!viewingAs ? `<button class="btn ghost" id="btnSyncTxn">↻ Sync banks</button>
          <button class="btn primary" id="btnAddTxn">+ Add transaction</button>` : ""}
        </div>
      </header>
      <div class="toolbar">
        <input type="search" id="txnSearch" placeholder="Search transactions…">
        <select id="txnCatFilter"><option value="">All categories</option>${Object.keys(CATEGORIES).map(c => `<option>${c}</option>`).join("")}</select>
        <select id="txnTypeFilter"><option value="">All types</option><option value="expense">Expenses</option><option value="income">Income</option></select>
        <select id="txnSrcFilter"><option value="">All sources</option><option value="bank">Bank</option><option value="manual">Manual</option></select>
      </div>
      <div class="card"><div class="list" id="txnList"></div></div>
    </div>`));

  const draw = () => {
    const q = document.getElementById("txnSearch").value.trim().toLowerCase();
    const cat = document.getElementById("txnCatFilter").value;
    const type = document.getElementById("txnTypeFilter").value;
    const src = document.getElementById("txnSrcFilter").value;
    let txns = [...getTxns()].sort((a, b) => String(b.date).localeCompare(String(a.date)));
    if (q) txns = txns.filter(t => t.name.toLowerCase().includes(q) || t.category.toLowerCase().includes(q));
    if (cat) txns = txns.filter(t => t.category === cat);
    if (type) txns = txns.filter(t => t.type === type);
    if (src === "bank") txns = txns.filter(t => t.source === "bank");
    if (src === "manual") txns = txns.filter(t => t.source !== "bank");
    document.getElementById("txnCount").textContent = `${txns.length} transaction${txns.length === 1 ? "" : "s"}`;
    const wrap = document.getElementById("txnList");
    wrap.innerHTML = "";
    if (!txns.length) wrap.appendChild(el(`<div class="empty">No transactions match.</div>`));
    for (const t of txns.slice(0, 200)) wrap.appendChild(txnRow(t));
  };
  document.getElementById("txnSearch").oninput = draw;
  document.getElementById("txnCatFilter").onchange = draw;
  document.getElementById("txnTypeFilter").onchange = draw;
  document.getElementById("txnSrcFilter").onchange = draw;
  const addBtn = document.getElementById("btnAddTxn");
  if (addBtn) addBtn.onclick = addTxnForm;
  const syncBtn = document.getElementById("btnSyncTxn");
  if (syncBtn) syncBtn.onclick = () => syncBanks(syncBtn);
  draw();
}

async function syncBanks(btn) {
  if (btn) { btn.disabled = true; btn.textContent = "Syncing…"; }
  try {
    const r = await api("sync_transactions");
    await refreshServer();
    toast(r.items ? `Synced ${r.items} bank(s): +${r.added} transactions` : "No banks linked yet — connect one in Accounts");
    render();
  } catch (e) {
    toast(e.message);
    if (btn) { btn.disabled = false; btn.textContent = "↻ Sync banks"; }
  }
}

function renderRecurring(main) {
  const total = state.recurring.reduce((s, r) => s + r.amount, 0);
  main.appendChild(el(`
    <div>
      <header class="view-header row">
        <div><h1>Recurring</h1><p class="sub">${state.recurring.length} charges · ${fmt(total)}/month (${fmt0(total * 12)}/year)</p></div>
        <button class="btn primary" id="btnAddRecurring">+ Add recurring</button>
      </header>
      <div class="card"><div class="list" id="recurringList"></div></div>
    </div>`));
  document.getElementById("btnAddRecurring").onclick = addRecurringForm;

  const wrap = document.getElementById("recurringList");
  const sorted = [...state.recurring].sort((a, b) => a.nextDue.localeCompare(b.nextDue));
  if (!sorted.length) wrap.appendChild(el(`<div class="empty">No recurring charges yet.</div>`));
  for (const r of sorted) {
    const row = el(`
      <div class="list-row">
        <div class="row-icon">🔁</div>
        <div class="row-main"><div class="row-title">${esc(r.name)}</div><div class="row-sub">${r.cadence} · next ${niceDate(r.nextDue)}</div></div>
        ${dueBadge(r.nextDue)}
        <div class="row-amount">${fmt(r.amount)}</div>
        <div class="row-actions"><button class="icon-btn" title="Delete">🗑</button></div>
      </div>`);
    row.querySelector(".icon-btn").onclick = () => {
      state.recurring = state.recurring.filter(x => x.id !== r.id);
      save(); render(); toast(`Removed ${r.name}`);
    };
    wrap.appendChild(row);
  }
}

function renderSpending(main) {
  main.appendChild(el(`
    <div>
      <header class="view-header"><h1>Spending</h1><p class="sub">Where your money goes</p></header>
      <div class="card">
        <div class="card-title">Monthly spend <span class="pill">last 6 months</span></div>
        <div class="chart-box tall"><canvas id="chartMonthly"></canvas></div>
      </div>
      <div class="grid grid-2">
        <div class="card">
          <div class="card-title">This month by category</div>
          <div class="chart-box"><canvas id="chartCat"></canvas></div>
        </div>
        <div class="card">
          <div class="card-title">Category detail</div>
          <div class="list" id="catList"></div>
        </div>
      </div>
    </div>`));

  const months = [];
  for (let m = 5; m >= 0; m--) months.push(monthISO(-m));

  if (window.Chart) {
    charts.monthly = new Chart(document.getElementById("chartMonthly"), {
      type: "bar",
      data: {
        labels: months.map(monthLabel),
        datasets: [
          { label: "Spent", data: months.map(m => sumTxns("expense", m)), backgroundColor: "#7c5cff", borderRadius: 6 },
          { label: "Income", data: months.map(m => sumTxns("income", m)), backgroundColor: "#2fd67b55", borderRadius: 6 },
        ],
      },
      options: { maintainAspectRatio: false, scales: { y: { grid: { color: "#2a2c45" } }, x: { grid: { display: false } } } },
    });
  }

  const byCat = spentByCategory(thisMonth());
  const entries = Object.entries(byCat).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, e) => s + e[1], 0);
  if (entries.length && window.Chart) {
    charts.cat = new Chart(document.getElementById("chartCat"), {
      type: "doughnut",
      data: { labels: entries.map(e => e[0]), datasets: [{ data: entries.map(e => e[1]), backgroundColor: entries.map(e => catInfo(e[0]).color), borderWidth: 0 }] },
      options: { maintainAspectRatio: false, cutout: "68%", plugins: { legend: { display: false } } },
    });
  }
  const catList = document.getElementById("catList");
  if (!entries.length) catList.appendChild(el(`<div class="empty">No spending this month.</div>`));
  for (const [cat, amt] of entries) {
    const pct = total ? Math.round((amt / total) * 100) : 0;
    catList.appendChild(el(`
      <div class="list-row">
        <div class="row-icon">${catInfo(cat).icon}</div>
        <div class="row-main"><div class="row-title">${esc(cat)}</div><div class="row-sub">${pct}% of spending</div></div>
        <div class="row-amount">${fmt0(amt)}</div>
      </div>`));
  }
}

function renderBudgets(main) {
  const tm = thisMonth();
  const byCat = spentByCategory(tm);
  const totalLimit = state.budgets.reduce((s, b) => s + b.limit, 0);
  const totalSpent = state.budgets.reduce((s, b) => s + (byCat[b.category] || 0), 0);

  main.appendChild(el(`
    <div>
      <header class="view-header row">
        <div><h1>Budgets</h1><p class="sub">${fmt0(totalSpent)} of ${fmt0(totalLimit)} budgeted this month</p></div>
        <button class="btn primary" id="btnAddBudget">+ Add budget</button>
      </header>
      <div class="grid grid-2" id="budgetList"></div>
    </div>`));
  document.getElementById("btnAddBudget").onclick = addBudgetForm;

  const wrap = document.getElementById("budgetList");
  if (!state.budgets.length) wrap.appendChild(el(`<div class="card empty">No budgets yet.</div>`));
  for (const b of state.budgets) {
    const spent = byCat[b.category] || 0;
    const pct = Math.min(100, (spent / b.limit) * 100);
    const cls = spent > b.limit ? "over" : pct > 80 ? "warn" : "";
    const left = b.limit - spent;
    const card = el(`
      <div class="card budget-card">
        <div class="budget-head">
          <div style="display:flex;align-items:center;gap:10px">
            <div class="row-icon">${catInfo(b.category).icon}</div>
            <div class="row-title">${esc(b.category)}</div>
          </div>
          <button class="icon-btn" title="Delete">🗑</button>
        </div>
        <div class="bar"><div class="bar-fill ${cls}" style="width:${pct}%"></div></div>
        <div class="budget-meta">
          <span>${fmt0(spent)} spent</span>
          <span>${left >= 0 ? fmt0(left) + " left" : fmt0(-left) + " over"} of ${fmt0(b.limit)}</span>
        </div>
      </div>`);
    card.querySelector(".icon-btn").onclick = () => {
      state.budgets = state.budgets.filter(x => x.id !== b.id);
      save(); render(); toast(`Removed ${b.category} budget`);
    };
    wrap.appendChild(card);
  }
}

function accountRow(a) {
  const row = el(`
    <div class="list-row">
      <div class="row-icon">${a.kind === "asset" ? "🏦" : "💳"}</div>
      <div class="row-main"><div class="row-title">${esc(a.name)}</div><div class="row-sub">${a.kind}</div></div>
      <div class="row-amount">${fmt(a.balance)}</div>
      <div class="row-actions"><button class="icon-btn" title="Delete">🗑</button></div>
    </div>`);
  row.querySelector(".icon-btn").onclick = () => {
    state.accounts = state.accounts.filter(x => x.id !== a.id);
    save(); render(); toast(`Removed ${a.name}`);
  };
  return row;
}

function renderAccounts(main) {
  const assets = state.accounts.filter(a => a.kind === "asset");
  const debts = state.accounts.filter(a => a.kind === "debt");
  const at = assets.reduce((s, a) => s + a.balance, 0);
  const dt = debts.reduce((s, a) => s + a.balance, 0);
  const banks = (me && me.banks) || [];

  main.appendChild(el(`
    <div>
      <header class="view-header row">
        <div><h1>Accounts</h1><p class="sub">${state.accounts.length} manual accounts · ${banks.length} linked bank(s)</p></div>
        <button class="btn primary" id="btnAddAccount">+ Add account</button>
      </header>
      <div class="card">
        <div class="card-title">🔗 Linked banks <span class="pill">via Plaid ${me && me.plaidEnv ? esc(me.plaidEnv) : "sandbox"}</span></div>
        <div class="list" id="bankList"></div>
        <div style="margin-top:14px;display:flex;gap:10px">
          <button class="btn primary" id="btnLinkBank">+ Connect a bank</button>
          <button class="btn ghost" id="btnSyncBanks">↻ Sync transactions</button>
        </div>
        ${!me || me.plaidEnv !== "production" ? `<p class="tiny muted" style="margin-top:10px">Sandbox test login: username <b>user_good</b>, password <b>pass_good</b> (skip the phone step with “Continue without phone number”)</p>` : ""}
      </div>
      <div class="grid grid-2">
        <div class="card"><div class="card-title green">Assets <span class="pill">${fmt0(at)}</span></div><div class="list" id="assetsList"></div></div>
        <div class="card"><div class="card-title red">Debts <span class="pill">${fmt0(dt)}</span></div><div class="list" id="debtsList"></div></div>
      </div>
    </div>`));
  document.getElementById("btnAddAccount").onclick = addAccountForm;
  document.getElementById("btnLinkBank").onclick = connectBank;
  document.getElementById("btnSyncBanks").onclick = (e) => syncBanks(e.target);

  const bankWrap = document.getElementById("bankList");
  if (!banks.length) bankWrap.appendChild(el(`<div class="empty">No banks linked yet.</div>`));
  for (const b of banks) {
    bankWrap.appendChild(el(`
      <div class="list-row">
        <div class="row-icon">🏛️</div>
        <div class="row-main"><div class="row-title">${esc(b.institution)}</div><div class="row-sub">item ${esc(b.itemId).slice(0, 12)}…</div></div>
        <span class="pill">connected</span>
      </div>`));
  }

  const aWrap = document.getElementById("assetsList");
  const dWrap = document.getElementById("debtsList");
  if (!assets.length) aWrap.appendChild(el(`<div class="empty">None</div>`));
  if (!debts.length) dWrap.appendChild(el(`<div class="empty">None</div>`));
  assets.forEach(a => aWrap.appendChild(accountRow(a)));
  debts.forEach(a => dWrap.appendChild(accountRow(a)));
}

async function connectBank() {
  try {
    const { link_token } = await api("create_link_token");
    const handler = Plaid.create({
      token: link_token,
      onSuccess: async (public_token, metadata) => {
        try {
          const inst = metadata && metadata.institution ? metadata.institution.name : "Bank";
          toast("Linking bank & importing transactions…");
          const r = await api("exchange_public_token", { public_token, institution: inst });
          await refreshServer();
          toast(`${inst} linked — imported ${r.synced} transactions`);
          render();
        } catch (e) { toast(e.message); }
      },
      onExit: (err) => { if (err) toast("Plaid Link closed: " + (err.display_message || err.error_code)); },
    });
    handler.open();
  } catch (e) {
    toast(e.message);
  }
}

function renderNetWorth(main) {
  const assets = state.accounts.filter(a => a.kind === "asset").reduce((s, a) => s + a.balance, 0);
  const debts = state.accounts.filter(a => a.kind === "debt").reduce((s, a) => s + a.balance, 0);
  const nw = assets - debts;

  main.appendChild(el(`
    <div>
      <header class="view-header"><h1>Net Worth</h1><p class="sub">Assets minus debts across all accounts</p></header>
      <div class="grid grid-3">
        <div class="card"><div class="stat-label">Net worth</div><div class="stat-value">${fmt(nw)}</div></div>
        <div class="card"><div class="stat-label">Total assets</div><div class="stat-value green">${fmt(assets)}</div></div>
        <div class="card"><div class="stat-label">Total debts</div><div class="stat-value red">${fmt(debts)}</div></div>
      </div>
      <div class="card">
        <div class="card-title">Trend <span class="pill">simulated history</span></div>
        <div class="chart-box tall"><canvas id="chartNW"></canvas></div>
      </div>
      <div class="card">
        <div class="card-title">Breakdown by account</div>
        <div class="chart-box tall"><canvas id="chartAccounts"></canvas></div>
      </div>
    </div>`));

  if (window.Chart) {
    const labels = [], data = [];
    for (let m = 11; m >= 0; m--) {
      labels.push(monthLabel(monthISO(-m)));
      data.push(Math.round(nw * (1 - m * 0.018 - (m % 3 === 0 ? 0.01 : 0))));
    }
    charts.nw = new Chart(document.getElementById("chartNW"), {
      type: "line",
      data: { labels, datasets: [{ label: "Net worth", data, borderColor: "#7c5cff", backgroundColor: "#7c5cff22", fill: true, tension: 0.35, pointRadius: 0, borderWidth: 2.5 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { grid: { color: "#2a2c45" } }, x: { grid: { display: false } } } },
    });

    const accs = [...state.accounts].sort((a, b) => b.balance - a.balance);
    charts.accounts = new Chart(document.getElementById("chartAccounts"), {
      type: "bar",
      data: {
        labels: accs.map(a => a.name),
        datasets: [{ data: accs.map(a => a.kind === "debt" ? -a.balance : a.balance), backgroundColor: accs.map(a => a.kind === "debt" ? "#ff5c7a" : "#00d4a6"), borderRadius: 6 }],
      },
      options: { indexAxis: "y", maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { color: "#2a2c45" } }, y: { grid: { display: false } } } },
    });
  }
}

function renderSettings(main) {
  const invited = (me && me.invited) || [];
  const shared = (me && me.sharedWithMe) || [];

  main.appendChild(el(`
    <div>
      <header class="view-header"><h1>Settings</h1><p class="sub">Signed in as ${esc(session.email)}</p></header>

      <div class="card">
        <div class="card-title">👥 Share my transactions</div>
        <p class="tiny muted" style="margin-bottom:12px">Invite someone by email. Once they sign up / log in with that email, they can view your bank transactions (read-only).</p>
        <form id="inviteForm" style="display:flex;gap:10px">
          <input name="email" type="email" required placeholder="person@example.com" style="flex:1">
          <button type="submit" class="btn primary">Invite</button>
        </form>
        <div class="list" id="inviteList" style="margin-top:10px"></div>
      </div>

      <div class="card">
        <div class="card-title">🔓 Shared with me</div>
        <div class="list" id="sharedList"></div>
      </div>

      <div class="card">
        <div class="card-title">🔐 Two-factor authentication <span class="pill">${me && me.twoFA ? "enabled" : "off"}</span></div>
        <div id="tfaBox"></div>
      </div>

      <div class="card">
        <div class="card-title">Data</div>
        <div style="display:flex;gap:10px;flex-wrap:wrap">
          <button class="btn ghost" id="btnExport">⬇ Export local data</button>
          <button class="btn ghost" id="btnClearSample">Clear sample data</button>
          <button class="btn danger" id="btnReset">Reset to sample data</button>
        </div>
        <p class="tiny muted" style="margin-top:10px">Manual transactions, budgets, recurring and accounts are stored in this browser. Bank transactions are stored server-side (Azure Table Storage) under your login.</p>
      </div>
    </div>`));

  const invWrap = document.getElementById("inviteList");
  if (!invited.length) invWrap.appendChild(el(`<div class="empty">Nobody invited yet.</div>`));
  for (const email of invited) {
    const row = el(`
      <div class="list-row">
        <div class="row-icon">✉️</div>
        <div class="row-main"><div class="row-title">${esc(email)}</div><div class="row-sub">can view your transactions</div></div>
        <div class="row-actions"><button class="icon-btn" title="Revoke">✕</button></div>
      </div>`);
    row.querySelector(".icon-btn").onclick = async () => {
      try {
        await api("invite", { email, revoke: true });
        await refreshServer(); render(); toast(`Revoked ${email}`);
      } catch (e) { toast(e.message); }
    };
    invWrap.appendChild(row);
  }

  const shWrap = document.getElementById("sharedList");
  if (!shared.length) shWrap.appendChild(el(`<div class="empty">Nobody has shared their data with you.</div>`));
  for (const s of shared) {
    const row = el(`
      <div class="list-row">
        <div class="row-icon">👀</div>
        <div class="row-main"><div class="row-title">${esc(s.ownerEmail)}</div><div class="row-sub">invited you to view their transactions</div></div>
        <button class="btn ghost">View</button>
      </div>`);
    row.querySelector("button").onclick = async () => {
      viewingAs = { ownerId: s.ownerId, ownerEmail: s.ownerEmail };
      await refreshServer();
      location.hash = "#transactions";
      render();
    };
    shWrap.appendChild(row);
  }

  renderTfaBox();

  document.getElementById("inviteForm").onsubmit = async (e) => {
    e.preventDefault();
    const email = new FormData(e.target).get("email");
    try {
      await api("invite", { email });
      await refreshServer(); render(); toast(`Invited ${email}`);
    } catch (err) { toast(err.message); }
  };

  document.getElementById("btnExport").onclick = () => {
    const blob = new Blob([JSON.stringify({ local: state, bank: bankTxns }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "moneytrack-export.json";
    a.click();
    URL.revokeObjectURL(a.href);
  };
  document.getElementById("btnClearSample").onclick = () => {
    if (confirm("Remove all local sample/manual data (keeps bank transactions)?")) {
      state = emptyData(); save(); render(); toast("Local data cleared");
    }
  };
  document.getElementById("btnReset").onclick = () => {
    if (confirm("Reset local data back to the sample data?")) {
      state = seedData(); save(); render(); toast("Sample data restored");
    }
  };
}

function renderTfaBox() {
  const box = document.getElementById("tfaBox");
  if (!box) return;
  box.innerHTML = "";
  if (me && me.twoFA) {
    box.appendChild(el(`
      <div>
        <p class="tiny muted" style="margin-bottom:10px">Logins require a code from your authenticator app.</p>
        <form style="display:flex;gap:10px">
          <input name="code" inputmode="numeric" required placeholder="6-digit code" style="width:160px">
          <button type="submit" class="btn danger">Disable 2FA</button>
        </form>
      </div>`));
    box.querySelector("form").onsubmit = async (e) => {
      e.preventDefault();
      try {
        await api("disable_2fa", { code: new FormData(e.target).get("code") });
        await refreshServer(); render(); toast("2FA disabled");
      } catch (err) { toast(err.message); }
    };
  } else {
    box.appendChild(el(`
      <div>
        <p class="tiny muted" style="margin-bottom:10px">Protect your account with an authenticator app (Google Authenticator, Authy, 1Password…).</p>
        <button class="btn primary" id="btnEnableTfa">Enable 2FA</button>
        <div id="tfaSetup" style="margin-top:14px"></div>
      </div>`));
    box.querySelector("#btnEnableTfa").onclick = async () => {
      try {
        const r = await api("enable_2fa");
        const setup = document.getElementById("tfaSetup");
        setup.innerHTML = "";
        setup.appendChild(el(`
          <div>
            <p class="tiny" style="margin-bottom:10px">1. Scan this QR code with your authenticator app (or enter the key manually):</p>
            <div id="tfaQr" style="background:#fff;padding:12px;border-radius:10px;width:fit-content"></div>
            <p class="tiny muted" style="margin:10px 0">Manual key: <b style="user-select:all">${esc(r.secret)}</b></p>
            <p class="tiny" style="margin-bottom:8px">2. Enter the 6-digit code it shows:</p>
            <form style="display:flex;gap:10px">
              <input name="code" inputmode="numeric" required placeholder="123456" style="width:160px">
              <button type="submit" class="btn primary">Confirm &amp; enable</button>
            </form>
          </div>`));
        if (window.QRCode) new QRCode(document.getElementById("tfaQr"), { text: r.otpauth, width: 168, height: 168 });
        setup.querySelector("form").onsubmit = async (e) => {
          e.preventDefault();
          try {
            await api("confirm_2fa", { code: new FormData(e.target).get("code") });
            await refreshServer(); render(); toast("2FA enabled 🎉");
          } catch (err) { toast(err.message); }
        };
      } catch (err) { toast(err.message); }
    };
  }
}

/* ================= Modal forms ================= */

function openModal(title, formEl) {
  const root = document.getElementById("modal-root");
  root.innerHTML = "";
  const backdrop = el(`
    <div class="modal-backdrop">
      <div class="modal">
        <div class="modal-head"><h2>${esc(title)}</h2><button class="close-btn">✕</button></div>
      </div>
    </div>`);
  backdrop.querySelector(".modal").appendChild(formEl);
  backdrop.querySelector(".close-btn").onclick = closeModal;
  backdrop.onclick = (e) => { if (e.target === backdrop) closeModal(); };
  root.appendChild(backdrop);
  const first = formEl.querySelector("input, select");
  if (first) first.focus();
}
function closeModal() { document.getElementById("modal-root").innerHTML = ""; }

const field = (label, inner) => `<div class="form-field"><label>${label}</label>${inner}</div>`;
const catOptions = (sel) => Object.keys(CATEGORIES).map(c => `<option ${c === sel ? "selected" : ""}>${c}</option>`).join("");
const formActions = `<div class="form-actions"><button type="button" class="btn ghost" data-cancel>Cancel</button><button type="submit" class="btn primary">Add</button></div>`;

function wireForm(f, onSubmit) {
  f.onsubmit = (e) => { e.preventDefault(); onSubmit(new FormData(f)); };
  f.querySelector("[data-cancel]").onclick = closeModal;
}

function addTxnForm() {
  const f = el(`<form>
    ${field("Name", `<input name="name" required placeholder="e.g. Target">`)}
    ${field("Amount ($)", `<input name="amount" type="number" step="0.01" min="0.01" required placeholder="0.00">`)}
    ${field("Type", `<select name="type"><option value="expense">Expense</option><option value="income">Income</option></select>`)}
    ${field("Category", `<select name="category">${catOptions("Groceries")}</select>`)}
    ${field("Date", `<input name="date" type="date" value="${todayISO()}" required>`)}
    ${formActions}</form>`);
  wireForm(f, (d) => {
    state.transactions.push({
      id: id(), name: d.get("name"), amount: parseFloat(d.get("amount")),
      type: d.get("type"), category: d.get("type") === "income" ? "Income" : d.get("category"),
      date: d.get("date"),
    });
    save(); closeModal(); location.hash = "#transactions"; render(); toast("Transaction added");
  });
  openModal("Add transaction", f);
}

function addRecurringForm() {
  const f = el(`<form>
    ${field("Name", `<input name="name" required placeholder="e.g. Hulu">`)}
    ${field("Amount ($)", `<input name="amount" type="number" step="0.01" min="0.01" required placeholder="0.00">`)}
    ${field("Cadence", `<select name="cadence"><option>monthly</option><option>yearly</option><option>weekly</option></select>`)}
    ${field("Next due", `<input name="nextDue" type="date" value="${todayISO(7)}" required>`)}
    ${formActions}</form>`);
  wireForm(f, (d) => {
    state.recurring.push({
      id: id(), name: d.get("name"), amount: parseFloat(d.get("amount")),
      cadence: d.get("cadence"), nextDue: d.get("nextDue"),
    });
    save(); closeModal(); render(); toast("Recurring charge added");
  });
  openModal("Add recurring charge", f);
}

function addBudgetForm() {
  const used = new Set(state.budgets.map(b => b.category));
  const avail = Object.keys(CATEGORIES).filter(c => c !== "Income" && !used.has(c));
  const f = el(`<form>
    ${field("Category", `<select name="category">${avail.map(c => `<option>${c}</option>`).join("")}</select>`)}
    ${field("Monthly limit ($)", `<input name="limit" type="number" step="1" min="1" required placeholder="e.g. 300">`)}
    ${formActions}</form>`);
  wireForm(f, (d) => {
    state.budgets.push({ id: id(), category: d.get("category"), limit: parseFloat(d.get("limit")) });
    save(); closeModal(); render(); toast("Budget added");
  });
  openModal("Add budget", f);
}

function addAccountForm() {
  const f = el(`<form>
    ${field("Name", `<input name="name" required placeholder="e.g. HSA — Fidelity">`)}
    ${field("Balance ($)", `<input name="balance" type="number" step="0.01" required placeholder="0.00">`)}
    ${field("Type", `<select name="kind"><option value="asset">Asset</option><option value="debt">Debt</option></select>`)}
    ${formActions}</form>`);
  wireForm(f, (d) => {
    state.accounts.push({ id: id(), name: d.get("name"), balance: parseFloat(d.get("balance")), kind: d.get("kind") });
    save(); closeModal(); render(); toast("Account added");
  });
  openModal("Add account", f);
}

/* ================= Init ================= */

document.querySelector('[data-action="add-tx"]').onclick = () => {
  if (!session) { toast("Sign in first"); return; }
  if (viewingAs) { toast("Read-only while viewing someone else's data"); return; }
  addTxnForm();
};

load();
render();
if (session) refreshServer().then(render);
