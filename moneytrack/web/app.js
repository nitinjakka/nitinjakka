/* MoneyTrack — Rocket Money style prototype (v7).
   Frontend: static site. Backend: Azure Functions + Table Storage + Plaid.
   Local data (manual txns, budgets, recurring, manual accounts, categories, rules) stays in localStorage.
   Bank accounts + transactions live server-side per signed-in user; edits to bank transactions
   (category / name / notes / delete) are persisted server-side too. */

const API = "https://moneytrack-api-nitin.azurewebsites.net/api";

/* ================= Categories ================= */

const DEFAULT_CATEGORIES = [
  { name: "Groceries",     icon: "🛒", color: "#7c5cff" },
  { name: "Dining",        icon: "🍔", color: "#00d4a6" },
  { name: "Transport",     icon: "🚗", color: "#ffc555" },
  { name: "Travel",        icon: "✈️", color: "#4fa3ff" },
  { name: "Shopping",      icon: "🛍️", color: "#ff5c7a" },
  { name: "Entertainment", icon: "🎬", color: "#4fc3f7" },
  { name: "Subscriptions", icon: "🔁", color: "#f76dd8", bill: true },
  { name: "Utilities",     icon: "💡", color: "#ff9d5c", bill: true },
  { name: "Housing",       icon: "🏠", color: "#b98cff", bill: true },
  { name: "Loan Payment",  icon: "🏦", color: "#d4a94f", bill: true },
  { name: "Health",        icon: "🩺", color: "#5cffb8" },
  { name: "Services",      icon: "🧰", color: "#9ad0ff" },
  { name: "Fees",          icon: "🏷️", color: "#ff8a5c" },
  { name: "Income",        icon: "💵", color: "#2fd67b", kind: "income" },
  { name: "Transfer",      icon: "↔️", color: "#6b7089", kind: "transfer" },
  { name: "Other",         icon: "📦", color: "#8b8fa8" },
];

// Keyword rules: applied to a transaction's name when Plaid/the user has not set a category.
const DEFAULT_RULES = [
  ["netflix", "Subscriptions"], ["spotify", "Subscriptions"], ["hulu", "Subscriptions"], ["disney", "Subscriptions"],
  ["apple.com", "Subscriptions"], ["icloud", "Subscriptions"], ["youtube", "Subscriptions"], ["prime video", "Subscriptions"],
  ["chatgpt", "Subscriptions"], ["openai", "Subscriptions"], ["anthropic", "Subscriptions"], ["claude.ai", "Subscriptions"],
  ["audible", "Subscriptions"], ["peacock", "Subscriptions"], ["paramount", "Subscriptions"], ["max.com", "Subscriptions"],
  ["planet fitness", "Health"], ["gym", "Health"], ["cvs", "Health"], ["walgreens", "Health"],
  ["costco", "Groceries"], ["h-e-b", "Groceries"], ["heb ", "Groceries"], ["kroger", "Groceries"], ["trader joe", "Groceries"],
  ["whole foods", "Groceries"], ["aldi", "Groceries"], ["safeway", "Groceries"], ["walmart", "Groceries"],
  ["amazon", "Shopping"], ["amzn", "Shopping"], ["target", "Shopping"], ["best buy", "Shopping"],
  ["uber eats", "Dining"], ["doordash", "Dining"], ["grubhub", "Dining"], ["starbucks", "Dining"], ["chipotle", "Dining"],
  ["uber", "Transport"], ["lyft", "Transport"], ["shell", "Transport"], ["chevron", "Transport"], ["exxon", "Transport"],
  ["verizon", "Utilities"], ["t-mobile", "Utilities"], ["at&t", "Utilities"], ["xfinity", "Utilities"], ["comcast", "Utilities"],
  ["electric", "Utilities"], ["energy", "Utilities"], ["water", "Utilities"], ["internet", "Utilities"],
  ["rent", "Housing"], ["mortgage", "Housing"],
  ["payroll", "Income"], ["direct dep", "Income"], ["salary", "Income"], ["paycheck", "Income"],
  ["zelle", "Transfer"], ["venmo", "Transfer"], ["transfer", "Transfer"], ["payment thank you", "Transfer"], ["autopay", "Transfer"],
].map(([keyword, category]) => ({ keyword, category }));

/* ================= Account groups ================= */

const GROUPS = {
  checking:    { label: "Checking",     icon: "🏦", debt: false, order: 1 },
  credit:      { label: "Card Balance", icon: "💳", debt: true,  order: 2 },
  savings:     { label: "Savings",      icon: "🐖", debt: false, order: 3 },
  investment:  { label: "Investments",  icon: "📈", debt: false, order: 4 },
  loan:        { label: "Loans",        icon: "🏠", debt: true,  order: 5 },
  other_asset: { label: "Other assets", icon: "💼", debt: false, order: 6 },
  other_debt:  { label: "Other debts",  icon: "📉", debt: true,  order: 7 },
};

// Plaid type/subtype → group
function groupOf(type, subtype) {
  type = String(type || "").toLowerCase(); subtype = String(subtype || "").toLowerCase();
  if (type === "depository") {
    if (["savings", "money market", "cd", "hsa", "gic"].includes(subtype)) return "savings";
    return "checking";
  }
  if (type === "credit") return "credit";
  if (type === "investment" || type === "brokerage") return "investment";
  if (type === "loan") return "loan";
  return "other_asset";
}

/* ================= State ================= */

const STORE_KEY = "moneyTrack.v2";
const SESSION_KEY = "moneyTrack.session";
const LASTSYNC_KEY = "moneyTrack.lastSync";
const AUTO_SYNC_MS = 10 * 60 * 1000;

let state = null;          // local data
let session = null;        // { token, email, userId }
let me = null;             // server profile: banks, accounts, invited, sharedWithMe
let bankTxns = [];         // bank transactions (mine, or the person I'm viewing)
let viewingAs = null;      // null = my data; { ownerId, ownerEmail } = someone who invited me
let charts = {};
let syncing = false;

let viewMonth = "";        // month shown on Dashboard / Spending / Budgets (YYYY-MM)
let barsEnd = "";          // last month shown on the income-vs-spending bars
let txFilters = { q: "", cat: "", type: "", src: "", accounts: [], month: "" };
let includeBills = true;

/* ================= API ================= */

async function api(path, body) {
  const headers = { "Content-Type": "application/json" };
  if (session) headers["Authorization"] = "Bearer " + session.token;
  const res = await fetch(`${API}/${path}`, { method: "POST", headers, body: JSON.stringify(body || {}) });
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
    const ownerArg = viewingAs ? { owner_id: viewingAs.ownerId } : {};
    const [profile, data] = await Promise.all([api("me", ownerArg), api("get_transactions", ownerArg)]);
    me = profile;
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
const pad = (n) => String(n).padStart(2, "0");
function isoOf(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
function todayISO(offsetDays = 0) { const d = new Date(); d.setDate(d.getDate() + offsetDays); return isoOf(d); }
function monthISO(offsetMonths = 0) { const d = new Date(); return isoOf(new Date(d.getFullYear(), d.getMonth() + offsetMonths, 15)).slice(0, 7); }
function shiftMonth(ym, n) { const [y, m] = ym.split("-").map(Number); return isoOf(new Date(y, m - 1 + n, 15)).slice(0, 7); }
function daysInMonth(ym) { const [y, m] = ym.split("-").map(Number); return new Date(y, m, 0).getDate(); }
function firstOfNextMonth() { const d = new Date(); return isoOf(new Date(d.getFullYear(), d.getMonth() + 1, 1)); }
const thisMonth = () => monthISO(0);

function emptyData() {
  return {
    transactions: [], recurring: [], budgets: [], accounts: [],
    categories: DEFAULT_CATEGORIES.map(c => ({ ...c })),
    rules: DEFAULT_RULES.map(r => ({ ...r })),
    aliases: {},   // { "Old category name": "New name" } — keeps renamed categories in sync with server data
  };
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
  for (let m = 1; m <= 8; m++) {
    const base = new Date();
    const mkD = (day) => isoOf(new Date(base.getFullYear(), base.getMonth() - m, day));
    const jitter = (v) => Math.round(v * (0.85 + Math.random() * 0.3) * 100) / 100;
    txns.push(
      mk("Paycheck — Acme Corp", "Income", 3450.00, "income", mkD(1)),
      mk("Paycheck — Acme Corp", "Income", 3450.00, "income", mkD(15)),
      mk("Rent", "Housing", 1850.00, "expense", mkD(2)),
      mk("H-E-B", "Groceries", jitter(180), "expense", mkD(6)),
      mk("Costco", "Groceries", jitter(240), "expense", mkD(19)),
      mk("Chipotle", "Dining", jitter(60), "expense", mkD(9)),
      mk("DoorDash", "Dining", jitter(95), "expense", mkD(22)),
      mk("Shell Gas", "Transport", jitter(120), "expense", mkD(14)),
      mk("Amazon", "Shopping", jitter(180), "expense", mkD(18)),
      mk("Electric bill", "Utilities", jitter(140), "expense", mkD(20)),
      mk("Internet", "Utilities", 79.99, "expense", mkD(8)),
      mk("Netflix", "Subscriptions", 15.49, "expense", mkD(12)),
      mk("Spotify", "Subscriptions", 11.99, "expense", mkD(5)),
      mk("AMC Theatres", "Entertainment", jitter(70), "expense", mkD(23)),
      mk("Credit card payment", "Transfer", jitter(900), "expense", mkD(25)),
    );
  }
  return {
    ...emptyData(),
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
      { id: id(), name: "Checking — Chase", balance: 4820.55, type: "checking" },
      { id: id(), name: "Savings — Ally", balance: 12300.00, type: "savings" },
      { id: id(), name: "Brokerage — Robinhood", balance: 28450.00, type: "investment" },
      { id: id(), name: "401(k)", balance: 46200.00, type: "investment" },
      { id: id(), name: "Credit card — Amex", balance: 1240.33, type: "credit" },
      { id: id(), name: "Car loan", balance: 8900.00, type: "loan" },
    ],
  };
}

function load() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (raw) { state = JSON.parse(raw); }
  } catch (e) {}
  if (!state) { state = emptyData(); }
  // migrate older local data
  const base = emptyData();
  for (const k of Object.keys(base)) if (state[k] === undefined) state[k] = base[k];
  for (const a of state.accounts) if (!a.type) a.type = a.kind === "debt" ? "other_debt" : "other_asset";
  save();
  try { localStorage.removeItem("moneyTrack.v1"); } catch (e) {}
  try { const s = localStorage.getItem(SESSION_KEY); if (s) session = JSON.parse(s); } catch (e) {}
  viewMonth = thisMonth(); barsEnd = thisMonth();
}

function save() { try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (e) {} }
function saveSession() { try { localStorage.setItem(SESSION_KEY, JSON.stringify(session)); } catch (e) {} }

/* ================= Helpers ================= */

const fmt  = (n) => (n || 0).toLocaleString("en-US", { style: "currency", currency: "USD" });
const fmt0 = (n) => (n || 0).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const monthOf = (d) => String(d).slice(0, 7);
const cats = () => state.categories;
const catByName = (n) => cats().find(c => c.name === n);
const catInfo = (n) => catByName(n) || catByName("Other") || { name: n, icon: "📦", color: "#8b8fa8" };
const catKind = (n) => (catByName(n) || {}).kind || "expense";
const catNames = (kind) => cats().filter(c => !kind || (c.kind || "expense") === kind).map(c => c.name);

function ruleMatch(name) {
  const n = String(name || "").toLowerCase();
  const rules = [...state.rules].sort((a, b) => b.keyword.length - a.keyword.length);
  for (const r of rules) if (r.keyword && n.includes(r.keyword.toLowerCase())) return r.category;
  return null;
}

// Effective category for a transaction: user choice > alias-mapped auto category > keyword rules > Other
function resolveCat(t) {
  let c = t.category;
  if (state.aliases[c]) c = state.aliases[c];
  if (!t.userSet && (!c || c === "Other" || !catByName(c))) {
    const r = ruleMatch(t.name) || ruleMatch(t.originalName);
    if (r && catByName(r)) c = r;
  }
  if (!catByName(c)) c = "Other";
  return c;
}

// All transactions in view, with resolved category `cat`.
function getTxns() {
  const list = viewingAs ? bankTxns : [...state.transactions, ...bankTxns];
  return list.map(t => ({ ...t, cat: resolveCat(t) }));
}
const isSpend  = (t) => t.type === "expense" && catKind(t.cat) === "expense";
const isIncome = (t) => t.type === "income" && catKind(t.cat) !== "transfer";
const isBill   = (t) => !!(catByName(t.cat) || {}).bill;

function niceDate(dateStr) {
  return new Date(dateStr + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
function longDate(dateStr) {
  return new Date(dateStr + "T12:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
}
function monthLabel(ym, long = false) {
  const [y, m] = ym.split("-").map(Number);
  return new Date(y, m - 1, 15).toLocaleDateString("en-US", long ? { month: "long", year: "numeric" } : { month: "short" });
}
function daysUntil(dateStr) {
  return Math.round((new Date(dateStr + "T12:00:00") - new Date(todayISO() + "T12:00:00")) / 86400000);
}
function timeAgo(iso) {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso)) / 1000;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

function el(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstChild; }
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c])); }
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

function toast(msg) {
  const root = document.getElementById("toast");
  root.innerHTML = "";
  const m = el(`<div class="toast-msg">${esc(msg)}</div>`);
  root.appendChild(m);
  setTimeout(() => { if (m.parentNode) m.remove(); }, 3500);
}

function spendIn(month, txns = getTxns()) { return txns.filter(t => isSpend(t) && monthOf(t.date) === month).reduce((s, t) => s + t.amount, 0); }
function incomeIn(month, txns = getTxns()) { return txns.filter(t => isIncome(t) && monthOf(t.date) === month).reduce((s, t) => s + t.amount, 0); }
function spentByCategory(month, txns = getTxns(), withBills = true) {
  const out = {};
  for (const t of txns) {
    if (!isSpend(t) || monthOf(t.date) !== month) continue;
    if (!withBills && isBill(t)) continue;
    out[t.cat] = (out[t.cat] || 0) + t.amount;
  }
  return out;
}

/* ---------- accounts (bank + manual) ---------- */

function allAccounts() {
  const bank = ((me && me.accounts) || []).map(a => ({
    id: a.accountId, name: a.name, mask: a.mask, institution: a.institution, subtype: a.subtype,
    group: groupOf(a.type, a.subtype), balance: a.current || 0, available: a.available, limit: a.limit,
    source: "bank", itemId: a.itemId, updatedAt: a.updatedAt,
  }));
  if (viewingAs) return bank;
  const manual = state.accounts.map(a => ({
    id: a.id, name: a.name, institution: "Manual", group: a.type || "other_asset", balance: a.balance, source: "manual", raw: a,
  }));
  return [...bank, ...manual];
}
function groupTotal(group, accts = allAccounts()) { return accts.filter(a => a.group === group).reduce((s, a) => s + a.balance, 0); }
function netWorth(accts = allAccounts()) {
  let assets = 0, debts = 0;
  for (const a of accts) { if (GROUPS[a.group] && GROUPS[a.group].debt) debts += a.balance; else assets += a.balance; }
  return { assets, debts, net: assets - debts };
}
function accountName(accountId) {
  if (!accountId) return "Manual";
  const a = allAccounts().find(x => x.id === accountId);
  return a ? `${a.name}${a.mask ? " ••" + a.mask : ""}` : "Bank";
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

/* ================= Sync ================= */

async function syncBanks(btn, { silent = false } = {}) {
  if (syncing || viewingAs) return null;
  syncing = true;
  const label = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "Syncing…"; }
  try {
    const r = await api("sync_transactions");
    try { localStorage.setItem(LASTSYNC_KEY, String(Date.now())); } catch (e) {}
    await refreshServer();
    if (!silent) {
      if (!r.items) toast("No banks linked yet — connect one in Accounts");
      else if (r.errors && r.errors.length) toast(`Synced, but ${r.errors[0].institution || "a bank"} needs attention: ${r.errors[0].error}`);
      else toast(`Synced ${r.items} bank(s): ${r.accounts} accounts, +${r.added} transactions`);
    }
    render();
    return r;
  } catch (e) {
    if (!silent) toast(e.message);
    return null;
  } finally {
    syncing = false;
    if (btn && btn.isConnected) { btn.disabled = false; btn.textContent = label; }
  }
}

// Called on every app load: refresh balances/transactions automatically if the last sync is stale.
async function autoSync() {
  if (!session || viewingAs || !me || !me.banks || !me.banks.length) return;
  let last = 0;
  try { last = Number(localStorage.getItem(LASTSYNC_KEY) || 0); } catch (e) {}
  if (Date.now() - last < AUTO_SYNC_MS) return;
  await syncBanks(null, { silent: true });
}

// After linking a bank, Plaid's first pull can take a while — keep polling until transactions arrive.
async function waitForInitialTransactions(before) {
  for (let i = 0; i < 20; i++) {
    await sleep(5000);
    const r = await syncBanks(null, { silent: true });
    if (!r) break;
    if (bankTxns.length > before && !r.notReady) { toast(`Imported ${bankTxns.length - before} transactions`); return; }
  }
  toast("Still waiting for the bank's first transaction batch — it will appear automatically.");
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
  document.body.classList.toggle("auth-only", !session);

  if (!session) { renderAuth(main); syncSidebar(); return; }

  const route = currentRoute();
  document.querySelectorAll("nav a").forEach(a => a.classList.toggle("active", a.getAttribute("href") === "#" + route));
  if (viewingAs) {
    main.appendChild(el(`
      <div class="card" style="border-color:#7c5cff;display:flex;align-items:center;gap:12px;justify-content:space-between">
        <span>👀 Viewing <b>${esc(viewingAs.ownerEmail)}</b>'s bank data (read-only)</span>
        <button class="btn ghost" id="btnStopViewing">Back to my data</button>
      </div>`));
    main.querySelector("#btnStopViewing").onclick = async () => { viewingAs = null; await refreshServer(); render(); };
  }
  ROUTES[route](main);
  syncSidebar();
}

function syncSidebar() {
  const footer = document.querySelector(".sidebar-footer");
  let userBox = document.getElementById("userBox");
  if (!userBox) { userBox = el(`<div id="userBox" class="tiny muted" style="margin-top:8px"></div>`); footer.appendChild(userBox); }
  userBox.innerHTML = session
    ? `Signed in as <b>${esc(session.email)}</b> · <a href="#" id="lnkLogout" style="color:inherit">log out</a>`
    : `Not signed in`;
  const lnk = document.getElementById("lnkLogout");
  if (lnk) lnk.onclick = (e) => { e.preventDefault(); logout(); toast("Logged out"); };
}

window.addEventListener("hashchange", render);

/* ================= Shared UI bits ================= */

function monthNav(value, onChange, { allowAll = false } = {}) {
  const node = el(`
    <div class="month-nav">
      <button type="button" title="Previous month">‹</button>
      <span>${value ? monthLabel(value, true) : "All time"}</span>
      <button type="button" title="Next month">›</button>
      ${value !== thisMonth() ? `<button type="button" class="btn ghost btn-today">This month</button>` : ""}
      ${allowAll && value ? `<button type="button" class="btn ghost btn-today">All</button>` : ""}
    </div>`);
  const btns = node.querySelectorAll("button");
  btns[0].onclick = () => onChange(shiftMonth(value || thisMonth(), -1));
  btns[1].onclick = () => onChange(shiftMonth(value || thisMonth(), 1));
  let i = 2;
  if (value !== thisMonth()) btns[i++].onclick = () => onChange(thisMonth());
  if (allowAll && value) btns[i].onclick = () => onChange("");
  return node;
}

function txnRow(t, { actions = true, showAccount = true } = {}) {
  const info = catInfo(t.cat);
  const income = t.type === "income";
  const editable = actions && !viewingAs;
  const sub = [showAccount ? accountName(t.accountId) : null, niceDate(t.date), t.source === "bank" ? "🏦" : "✍️", t.notes ? `“${t.notes}”` : null]
    .filter(Boolean).map(esc).join(" · ");
  const row = el(`
    <div class="list-row ${editable ? "clickable" : ""}">
      <div class="row-icon" style="background:${info.color}22">${info.icon}</div>
      <div class="row-main">
        <div class="row-title">${esc(t.name)}${t.pending ? ' <span class="pill">pending</span>' : ""}</div>
        <div class="row-sub">${sub}</div>
      </div>
      ${editable
        ? `<select class="inline-cat" title="Change category">${catOptions(t.cat)}</select>`
        : `<span class="pill">${esc(t.cat)}</span>`}
      <div class="row-amount ${income ? "green" : ""}">${income ? "+" : "−"}${fmt(t.amount)}</div>
      ${editable ? `<div class="row-actions"><button class="icon-btn" title="Edit">✎</button><button class="icon-btn" title="Delete">🗑</button></div>` : ""}
    </div>`);
  if (editable) {
    const sel = row.querySelector(".inline-cat");
    sel.onclick = (e) => e.stopPropagation();
    sel.onchange = (e) => { e.stopPropagation(); setCategory([t], sel.value).then(() => { toast(`${t.name} → ${sel.value}`); render(); }); };
    const [editBtn, delBtn] = row.querySelectorAll(".icon-btn");
    editBtn.onclick = (e) => { e.stopPropagation(); editTxnForm(t); };
    delBtn.onclick = (e) => { e.stopPropagation(); deleteTxn(t); };
    row.onclick = () => editTxnForm(t);
  }
  return row;
}

function dueBadge(dateStr) {
  const days = daysUntil(dateStr);
  const cls = days <= 0 ? "today" : days <= 5 ? "soon" : "";
  const txt = days <= 0 ? "Due today" : days === 1 ? "Tomorrow" : `In ${days} days`;
  return `<span class="due-badge ${cls}">${txt}</span>`;
}

/* ---------- transaction mutations (manual = local, bank = server) ---------- */

async function setCategory(txns, category, { addRule = false, ruleKeyword = "" } = {}) {
  const bankUpdates = [];
  for (const t of txns) {
    if (t.source === "bank") { bankUpdates.push({ id: t.id, category }); t.category = category; t.userSet = true; }
    else { const m = state.transactions.find(x => x.id === t.id); if (m) { m.category = category; m.userSet = true; } }
  }
  for (const b of bankTxns) { const u = bankUpdates.find(x => x.id === b.id); if (u) { b.category = category; b.userSet = true; } }
  if (addRule && ruleKeyword) {
    state.rules = state.rules.filter(r => r.keyword.toLowerCase() !== ruleKeyword.toLowerCase());
    state.rules.unshift({ keyword: ruleKeyword, category });
  }
  save();
  if (bankUpdates.length) {
    try { for (let i = 0; i < bankUpdates.length; i += 200) await api("update_transaction", { updates: bankUpdates.slice(i, i + 200) }); }
    catch (e) { toast("Saved locally, but server update failed: " + e.message); }
  }
}

async function deleteTxn(t) {
  if (!confirm(`Delete "${t.name}" (${fmt(t.amount)})?`)) return;
  if (t.source === "bank") {
    try { await api("update_transaction", { id: t.id, hidden: true }); bankTxns = bankTxns.filter(x => x.id !== t.id); }
    catch (e) { toast(e.message); return; }
  } else {
    state.transactions = state.transactions.filter(x => x.id !== t.id); save();
  }
  render(); toast("Transaction deleted");
}

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
          <div class="form-field" id="phoneField" style="display:none"><label>Phone (optional — lets others share with you by phone)</label><input name="phone" type="tel" placeholder="(512) 555-1234"></div>
          <div class="form-field" id="tfaField" style="display:none"><label>2FA code</label><input name="code" inputmode="numeric" pattern="[0-9]{6}" placeholder="6-digit code from your authenticator app"></div>
          <button type="submit" class="btn primary block" id="authSubmit">Sign in</button>
        </form>
        <p class="tiny muted" style="margin-top:14px;text-align:center">
          <span id="authToggleText">No account?</span>
          <a href="#" id="authToggle" style="color:#7c5cff">Create one</a>
        </p>
        <p class="tiny muted" id="authError" style="color:#ff5c7a;margin-top:10px;text-align:center"></p>
        <p class="tiny muted" style="margin-top:12px;text-align:center">By signing up or logging in you agree to the <a href="privacy.html" target="_blank" style="color:#7c5cff">Privacy Policy</a></p>
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
    document.getElementById("phoneField").style.display = mode === "signup" ? "" : "none";
    toggle.textContent = mode === "login" ? "Create one" : "Sign in";
  };
  document.getElementById("authForm").onsubmit = async (e) => {
    e.preventDefault();
    const d = new FormData(e.target);
    const btn = document.getElementById("authSubmit");
    btn.disabled = true; btn.textContent = "…";
    try {
      const payload = { email: d.get("email"), password: d.get("password") };
      const code = d.get("code"); if (code) payload.code = code;
      const phone = d.get("phone"); if (mode === "signup" && phone) payload.phone = phone;
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
      autoSync();
    } catch (err) {
      document.getElementById("authError").textContent = err.message;
      btn.disabled = false;
      btn.textContent = mode === "login" ? "Sign in" : "Sign up";
    }
  };
}

/* ================= Dashboard ================= */

function renderDashboard(main) {
  const hr = new Date().getHours();
  const greeting = hr < 12 ? "Good morning" : hr < 17 ? "Good afternoon" : "Good evening";
  const txns = getTxns();
  const m = viewMonth, lm = shiftMonth(m, -1);
  const isCurrent = m === thisMonth();
  const spent = spendIn(m, txns), spentLast = spendIn(lm, txns);
  const income = incomeIn(m, txns), incomeLast = incomeIn(lm, txns);

  // cumulative spend by day — this month vs last month
  const dim = daysInMonth(m), dimLast = daysInMonth(lm);
  const cumul = (month, days) => {
    const perDay = new Array(days).fill(0);
    for (const t of txns) if (isSpend(t) && monthOf(t.date) === month) perDay[Math.min(days, Number(t.date.slice(8, 10))) - 1] += t.amount;
    let run = 0; return perDay.map(v => (run += v));
  };
  const curCum = cumul(m, dim), lastCum = cumul(lm, dimLast);
  const todayDay = isCurrent ? new Date().getDate() : dim;
  const lastAtSameDay = lastCum[Math.min(todayDay, dimLast) - 1] || 0;
  const spentToDate = curCum[todayDay - 1] || 0;
  const diff = spentToDate - lastAtSameDay;

  main.appendChild(el(`
    <div>
      <header class="view-header row">
        <div><h1>${greeting}</h1><p class="sub">${new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" })}</p></div>
        <div id="dashMonthNav"></div>
      </header>
      <div class="grid grid-2">
        <div class="card">
          <div class="card-head">
            <div class="card-title">Current spend <span class="pill">${monthLabel(m, true)}</span></div>
            <div class="delta-note">${spentLast > 0
              ? `<span style="font-size:16px">${diff >= 0 ? "🔺" : "🔻"}</span><span>You've spent <b class="${diff >= 0 ? "up" : "down"}">${fmt0(Math.abs(diff))} ${diff >= 0 ? "more" : "less"}</b> than ${isCurrent ? "this time " : ""}last month</span>`
              : `<span>No spending data for ${monthLabel(lm)}</span>`}</div>
          </div>
          <div class="big-number">${fmt(spent)}</div>
          <div class="chart-box"><canvas id="chartSpendCurve"></canvas></div>
          <div class="legend"><span><i style="background:#7c5cff"></i>${monthLabel(m)}</span><span><i style="background:#7c5cff55"></i>${monthLabel(lm)}</span></div>
        </div>
        <div class="card acct-summary">
          <div class="card-head">
            <div class="card-title">Accounts</div>
            <div class="tiny muted" id="dashSyncBox"></div>
          </div>
          <div id="dashAccounts"></div>
        </div>
      </div>
      <div class="grid grid-3">
        <div class="card"><div class="stat-label">Income in ${monthLabel(m)}</div><div class="stat-value green">${fmt0(income)}</div>
          <div class="stat-delta ${incomeLast ? (income >= incomeLast ? "down" : "up") : "muted"}">${incomeLast ? `${income >= incomeLast ? "▲" : "▼"} ${fmt0(Math.abs(income - incomeLast))} vs ${monthLabel(lm)}` : "no data for last month"}</div></div>
        <div class="card"><div class="stat-label">Spent in ${monthLabel(m)}</div><div class="stat-value">${fmt0(spent)}</div>
          <div class="stat-delta ${spentLast ? (spent - spentLast >= 0 ? "up" : "down") : "muted"}">${spentLast ? `${spent - spentLast >= 0 ? "▲" : "▼"} ${fmt0(Math.abs(spent - spentLast))} vs ${monthLabel(lm)}` : "no data for last month"}</div></div>
        <div class="card"><div class="stat-label">Left over</div><div class="stat-value ${income - spent >= 0 ? "green" : "red"}">${fmt0(income - spent)}</div><div class="stat-delta muted">income − spending</div></div>
      </div>
      <div class="grid grid-2">
        <div class="card">
          <div class="card-head"><div class="card-title">Upcoming <span class="pill">next 7 days</span></div></div>
          <div class="upcoming-total" id="upcomingTotal"></div>
          <div class="list" id="dashBills"></div>
        </div>
        <div class="card">
          <div class="card-title">Recent transactions</div>
          <div class="list" id="dashRecent"></div>
        </div>
      </div>
      <div class="card" id="dashBreakdown"></div>
    </div>`));

  document.getElementById("dashMonthNav").appendChild(monthNav(viewMonth, (v) => { viewMonth = v; render(); }));

  if (window.Chart) {
    const labels = Array.from({ length: dim }, (_, i) => i + 1);
    charts.curve = new Chart(document.getElementById("chartSpendCurve"), {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: monthLabel(lm), data: lastCum.slice(0, dim), borderColor: "#7c5cff55", backgroundColor: "#7c5cff14", fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 },
          { label: monthLabel(m), data: curCum.map((v, i) => (i < todayDay ? v : null)), borderColor: "#7c5cff", backgroundColor: "#7c5cff00", tension: 0.3, pointRadius: (c) => (c.dataIndex === todayDay - 1 ? 5 : 0), pointBackgroundColor: "#fff", borderWidth: 3 },
        ],
      },
      options: {
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: false }, tooltip: { callbacks: { title: (it) => `Day ${it[0].label}`, label: (c) => ` ${c.dataset.label}: ${fmt0(c.raw || 0)}` } } },
        scales: { y: { grid: { color: "#2a2c45" }, ticks: { callback: (v) => fmt0(v) } }, x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } } },
      },
    });
  }

  renderAccountSummary(document.getElementById("dashAccounts"));
  const syncBox = document.getElementById("dashSyncBox");
  if (!viewingAs && me && me.banks && me.banks.length) {
    const last = me.banks.map(b => b.lastSync).filter(Boolean).sort().pop();
    syncBox.innerHTML = `↻ ${timeAgo(last)} · <a href="#" id="dashSyncNow" style="color:#7c5cff">Sync now</a>`;
    syncBox.querySelector("#dashSyncNow").onclick = (e) => { e.preventDefault(); syncBanks(e.target); };
  }

  const bills = document.getElementById("dashBills");
  const upcoming = [...state.recurring].filter(r => daysUntil(r.nextDue) <= 7 && daysUntil(r.nextDue) >= -1)
    .sort((a, b) => a.nextDue.localeCompare(b.nextDue));
  document.getElementById("upcomingTotal").textContent = upcoming.length
    ? `${upcoming.length} recurring charge${upcoming.length === 1 ? "" : "s"} due within the next 7 days for ${fmt(upcoming.reduce((s, r) => s + r.amount, 0))}`
    : "";
  if (!upcoming.length) bills.appendChild(el(`<div class="empty">Nothing due in the next 7 days 🎉</div>`));
  for (const r of upcoming.slice(0, 7)) {
    bills.appendChild(el(`
      <div class="list-row">
        <div class="row-icon">🔁</div>
        <div class="row-main"><div class="row-title">${esc(r.name)}</div><div class="row-sub">${niceDate(r.nextDue)}</div></div>
        ${dueBadge(r.nextDue)}
        <div class="row-amount">${fmt(r.amount)}</div>
      </div>`));
  }

  const recent = document.getElementById("dashRecent");
  const rec = txns.filter(t => monthOf(t.date) === m).sort((a, b) => String(b.date).localeCompare(String(a.date))).slice(0, 7);
  if (!rec.length) recent.appendChild(el(`<div class="empty">No transactions in ${monthLabel(m, true)}.</div>`));
  for (const t of rec) recent.appendChild(txnRow(t, { actions: false }));

  renderBreakdown(document.getElementById("dashBreakdown"), m, txns);
}

function renderAccountSummary(wrap) {
  const accts = allAccounts();
  wrap.innerHTML = "";
  if (!accts.length) {
    wrap.appendChild(el(`<div class="empty">No accounts yet. <a href="#accounts" style="color:#7c5cff">Connect a bank</a> or add one manually.</div>`));
    return;
  }
  const order = ["checking", "credit", "__netcash", "savings", "investment", "loan", "other_asset", "other_debt"];
  for (const g of order) {
    if (g === "__netcash") {
      const net = groupTotal("checking", accts) + groupTotal("savings", accts) - groupTotal("credit", accts);
      wrap.appendChild(el(`
        <div class="list-row net-cash" title="Checking + Savings − Card balances">
          <div class="row-icon">💰</div>
          <div class="row-main"><div class="row-title">Net Cash</div></div>
          <div class="row-amount ${net < 0 ? "red" : ""}" style="${net < 0 ? "color:var(--red)" : ""}">${net < 0 ? "−" : ""}${fmt(Math.abs(net))}</div>
        </div>`));
      continue;
    }
    const list = accts.filter(a => a.group === g);
    if (!list.length && !["checking", "credit", "savings", "investment"].includes(g)) continue;
    const info = GROUPS[g];
    const total = list.reduce((s, a) => s + a.balance, 0);
    const row = el(`
      <div>
        <div class="list-row">
          <div class="row-icon">${info.icon}</div>
          <div class="row-main"><div class="row-title">${info.label}</div><div class="row-sub">${list.length ? `${list.length} account${list.length === 1 ? "" : "s"}` : "none"}</div></div>
          <div class="row-amount">${list.length ? fmt(total) : `<a href="#accounts" class="tiny" style="color:#7c5cff">Add ⊕</a>`}</div>
          ${list.length ? `<button class="toggle" title="Show accounts">▾</button>` : ""}
        </div>
        <div class="sub-rows">${list.map(a => `<div class="sub-row"><span><b>${esc(a.name)}</b>${a.mask ? " ••" + esc(a.mask) : ""} <span class="muted">· ${esc(a.institution)}</span></span><span>${fmt(a.balance)}</span></div>`).join("")}</div>
      </div>`);
    const tg = row.querySelector(".toggle");
    if (tg) tg.onclick = () => { const s = row.querySelector(".sub-rows"); s.classList.toggle("open"); tg.textContent = s.classList.contains("open") ? "▴" : "▾"; };
    wrap.appendChild(row);
  }
}

/* ---------- Spending breakdown (donut + table), shared by Dashboard & Spending ---------- */

function renderBreakdown(card, month, txns) {
  const lm = shiftMonth(month, -1);
  const byCat = spentByCategory(month, txns, includeBills);
  const byCatLast = spentByCategory(lm, txns, includeBills);
  const entries = Object.entries(byCat).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, e) => s + e[1], 0);
  const totalLast = Object.values(byCatLast).reduce((s, v) => s + v, 0);
  const chg = totalLast > 0 ? ((total - totalLast) / totalLast) * 100 : null;
  card.innerHTML = "";
  card.appendChild(el(`
    <div>
      <div class="card-head">
        <div class="card-title">Spending breakdown <span class="pill">${monthLabel(month, true)}</span></div>
        <label class="switch"><input type="checkbox" id="bdBills" ${includeBills ? "checked" : ""}><i></i> Include bills</label>
      </div>
      <div class="donut-wrap"><canvas id="chartBreakdown"></canvas></div>
      <table class="bd-table">
        <thead><tr><th>Category</th><th>% Spend</th><th>Change <span title="vs ${monthLabel(lm, true)}">ⓘ</span></th><th class="r">Amount</th></tr></thead>
        <tbody id="bdBody"></tbody>
      </table>
    </div>`));
  card.querySelector("#bdBills").onchange = (e) => { includeBills = e.target.checked; render(); };

  const canvas = card.querySelector("#chartBreakdown");
  if (window.Chart) {
    const centerText = {
      id: "centerText",
      afterDraw(chart) {
        const { ctx, chartArea: a } = chart;
        if (!a) return;
        const cx = (a.left + a.right) / 2, cy = (a.top + a.bottom) / 2;
        ctx.save(); ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillStyle = "#8b8fa8"; ctx.font = "600 11px 'Segoe UI', system-ui"; ctx.fillText("TOTAL SPEND", cx, cy - 26);
        ctx.fillStyle = "#eef0ff"; ctx.font = "700 26px 'Segoe UI', system-ui"; ctx.fillText(fmt(total), cx, cy);
        if (chg !== null) { ctx.fillStyle = chg <= 0 ? "#2fd67b" : "#ff5c7a"; ctx.font = "500 13px 'Segoe UI', system-ui"; ctx.fillText(`${chg <= 0 ? "↓" : "↑"} ${Math.abs(Math.round(chg))}% from ${monthLabel(lm)}`, cx, cy + 26); }
        ctx.restore();
      },
    };
    charts.breakdown = new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: entries.length ? entries.map(e => e[0]) : ["No spending"],
        datasets: [{ data: entries.length ? entries.map(e => e[1]) : [1], backgroundColor: entries.length ? entries.map(e => catInfo(e[0]).color) : ["#2a2c45"], borderWidth: 2, borderColor: "#171827", hoverOffset: 6 }],
      },
      options: { maintainAspectRatio: false, cutout: "70%", plugins: { legend: { display: false }, tooltip: { enabled: entries.length > 0, callbacks: { label: (c) => ` ${c.label}: ${fmt(c.raw)} (${total ? Math.round(c.raw / total * 100) : 0}%)` } } } },
      plugins: [centerText],
    });
  }

  const body = card.querySelector("#bdBody");
  if (!entries.length) body.appendChild(el(`<tr><td colspan="4" class="empty">No spending in ${monthLabel(month, true)}.</td></tr>`));
  for (const [cat, amt] of entries) {
    const info = catInfo(cat);
    const prev = byCatLast[cat] || 0;
    const pct = total ? Math.round((amt / total) * 100) : 0;
    let chgHtml;
    if (prev > 0) { const p = ((amt - prev) / prev) * 100; chgHtml = `<span class="chg ${p <= 0 ? "down" : "up"}">${p <= 0 ? "↓" : "↑"} ${Math.abs(Math.round(p))}%</span>`; }
    else chgHtml = `<span class="chg new">new</span>`;
    const tr = el(`
      <tr class="clickable" title="Show these transactions">
        <td><div class="cat"><div class="row-icon" style="width:32px;height:32px;font-size:15px;background:${info.color}22">${info.icon}</div>${esc(cat)}${info.bill ? ' <span class="pill">bill</span>' : ""}</div></td>
        <td style="min-width:120px">${pct}% of spend<div class="mini-bar"><i style="width:${pct}%;background:${info.color}"></i></div></td>
        <td>${chgHtml}<div class="tiny muted">${prev ? fmt0(prev) + " in " + monthLabel(lm) : ""}</div></td>
        <td class="r"><b>${fmt(amt)}</b></td>
      </tr>`);
    tr.onclick = () => gotoTransactions({ cat, month });
    body.appendChild(tr);
  }
}

function gotoTransactions(f) {
  txFilters = { q: "", cat: "", type: "", src: "", accounts: [], month: "", ...f };
  if (location.hash === "#transactions") render(); else location.hash = "#transactions";
}

/* ================= Transactions ================= */

function renderTransactions(main) {
  const accts = allAccounts();
  const f = txFilters;
  main.appendChild(el(`
    <div>
      <header class="view-header row">
        <div><h1>Transactions</h1><p class="sub" id="txnCount"></p></div>
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
          <div id="txnMonthNav"></div>
          ${!viewingAs ? `<button class="btn ghost" id="btnSyncTxn">↻ Sync banks</button><button class="btn primary" id="btnAddTxn">+ Add</button>` : ""}
        </div>
      </header>
      <div class="toolbar">
        <input type="search" id="txnSearch" placeholder="Search name, notes, amount, account…" value="${esc(f.q)}">
        <details class="dd" id="acctDD">
          <summary id="acctSummary">All accounts ▾</summary>
          <div class="dd-menu" id="acctMenu"></div>
        </details>
        <select id="txnCatFilter"><option value="">All categories</option>${catNames().map(c => `<option ${c === f.cat ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>
        <select id="txnTypeFilter"><option value="">All types</option><option value="expense" ${f.type === "expense" ? "selected" : ""}>Expenses</option><option value="income" ${f.type === "income" ? "selected" : ""}>Income</option></select>
        <select id="txnSrcFilter"><option value="">All sources</option><option value="bank" ${f.src === "bank" ? "selected" : ""}>Bank</option><option value="manual" ${f.src === "manual" ? "selected" : ""}>Manual</option></select>
      </div>
      <div class="chips" id="txnChips"></div>
      <div class="card"><div class="list" id="txnList"></div></div>
    </div>`));

  document.getElementById("txnMonthNav").appendChild(monthNav(f.month, (v) => { txFilters.month = v; render(); }, { allowAll: true }));

  // accounts multi-select
  const menu = document.getElementById("acctMenu");
  const groups = {};
  for (const a of accts) (groups[a.institution] ||= []).push(a);
  if (!viewingAs) groups["Manual entries"] = [{ id: "__manual", name: "Manual transactions" }];
  const boxes = [];
  for (const [inst, list] of Object.entries(groups)) {
    menu.appendChild(el(`<div class="dd-group">${esc(inst)}</div>`));
    for (const a of list) {
      const lab = el(`<label><input type="checkbox" value="${esc(a.id)}" ${f.accounts.includes(a.id) ? "checked" : ""}> <span>${esc(a.name)}${a.mask ? " ••" + esc(a.mask) : ""}</span></label>`);
      boxes.push(lab.querySelector("input"));
      menu.appendChild(lab);
    }
  }
  const act = el(`<div class="dd-actions"><button type="button" class="btn ghost">Clear</button><button type="button" class="btn primary">Apply</button></div>`);
  menu.appendChild(act);
  act.children[0].onclick = () => { boxes.forEach(b => (b.checked = false)); txFilters.accounts = []; document.getElementById("acctDD").open = false; draw(); };
  act.children[1].onclick = () => { txFilters.accounts = boxes.filter(b => b.checked).map(b => b.value); document.getElementById("acctDD").open = false; draw(); };
  document.addEventListener("click", function closeDD(e) {
    const dd = document.getElementById("acctDD");
    if (!dd) { document.removeEventListener("click", closeDD); return; }
    if (!dd.contains(e.target)) dd.open = false;
  });

  const draw = () => {
    const f = txFilters;
    f.q = document.getElementById("txnSearch").value.trim();
    f.cat = document.getElementById("txnCatFilter").value;
    f.type = document.getElementById("txnTypeFilter").value;
    f.src = document.getElementById("txnSrcFilter").value;
    const q = f.q.toLowerCase();
    document.getElementById("acctSummary").textContent = f.accounts.length ? `${f.accounts.length} account${f.accounts.length === 1 ? "" : "s"} ▾` : "All accounts ▾";

    let txns = getTxns().sort((a, b) => String(b.date).localeCompare(String(a.date)));
    if (f.month) txns = txns.filter(t => monthOf(t.date) === f.month);
    if (q) txns = txns.filter(t =>
      String(t.name).toLowerCase().includes(q) || String(t.originalName || "").toLowerCase().includes(q) ||
      String(t.notes || "").toLowerCase().includes(q) || t.cat.toLowerCase().includes(q) ||
      accountName(t.accountId).toLowerCase().includes(q) || String(t.amount.toFixed(2)).includes(q) || String(t.date).includes(q));
    if (f.cat) txns = txns.filter(t => t.cat === f.cat);
    if (f.type) txns = txns.filter(t => t.type === f.type);
    if (f.src === "bank") txns = txns.filter(t => t.source === "bank");
    if (f.src === "manual") txns = txns.filter(t => t.source !== "bank");
    if (f.accounts.length) txns = txns.filter(t => f.accounts.includes(t.source === "bank" ? (t.accountId || "") : "__manual"));

    const spend = txns.filter(isSpend).reduce((s, t) => s + t.amount, 0);
    const inc = txns.filter(isIncome).reduce((s, t) => s + t.amount, 0);
    document.getElementById("txnCount").textContent = `${txns.length} transaction${txns.length === 1 ? "" : "s"} · ${fmt(spend)} spent · ${fmt(inc)} income`;

    const chips = document.getElementById("txnChips");
    chips.innerHTML = "";
    const chip = (label, onX) => { const c = el(`<span class="chip">${esc(label)} <span class="x">✕</span></span>`); c.querySelector(".x").onclick = onX; chips.appendChild(c); };
    if (f.cat) chip(`Category: ${f.cat}`, () => { txFilters.cat = ""; render(); });
    if (f.accounts.length) chip(`${f.accounts.length} account(s)`, () => { txFilters.accounts = []; render(); });
    if (f.month) chip(monthLabel(f.month, true), () => { txFilters.month = ""; render(); });

    const wrap = document.getElementById("txnList");
    wrap.innerHTML = "";
    if (!txns.length) wrap.appendChild(el(`<div class="empty">No transactions match.</div>`));
    let lastDate = "";
    for (const t of txns.slice(0, 400)) {
      if (t.date !== lastDate) { wrap.appendChild(el(`<div class="txn-date-head">${longDate(t.date)}</div>`)); lastDate = t.date; }
      wrap.appendChild(txnRow(t));
    }
    if (txns.length > 400) wrap.appendChild(el(`<div class="empty">Showing first 400 of ${txns.length} — narrow the filters or pick a month.</div>`));
  };
  document.getElementById("txnSearch").oninput = draw;
  document.getElementById("txnCatFilter").onchange = draw;
  document.getElementById("txnTypeFilter").onchange = draw;
  document.getElementById("txnSrcFilter").onchange = draw;
  const addBtn = document.getElementById("btnAddTxn"); if (addBtn) addBtn.onclick = addTxnForm;
  const syncBtn = document.getElementById("btnSyncTxn"); if (syncBtn) syncBtn.onclick = () => syncBanks(syncBtn);
  draw();
}

/* ================= Recurring ================= */

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
    row.querySelector(".icon-btn").onclick = () => { state.recurring = state.recurring.filter(x => x.id !== r.id); save(); render(); toast(`Removed ${r.name}`); };
    wrap.appendChild(row);
  }
}

/* ================= Spending ================= */

function renderSpending(main) {
  const txns = getTxns();
  main.appendChild(el(`
    <div>
      <header class="view-header row">
        <div><h1>Spending</h1><p class="sub">Income vs spending, month by month</p></div>
        <div id="spMonthNav"></div>
      </header>
      <div class="card">
        <div class="card-head">
          <div class="card-title">Income vs spending <span class="pill">6 months</span></div>
          <div class="bars-nav"><button id="barsPrev" title="Earlier">‹</button><button id="barsNext" title="Later">›</button></div>
        </div>
        <div class="chart-box tall"><canvas id="chartMonthly"></canvas></div>
        <div class="legend"><span><i style="background:#4b5bd6"></i>Income</span><span><i style="background:#8ea2ff"></i>Spending</span><span><i style="background:#0e0f1a;border:1px solid #555"></i>Bills &amp; utilities</span></div>
        <p class="tiny muted" style="margin-top:6px">Click a bar to open that month.</p>
      </div>
      <div class="card" id="spBreakdown"></div>
    </div>`));
  document.getElementById("spMonthNav").appendChild(monthNav(viewMonth, (v) => { viewMonth = v; barsEnd = v; render(); }));

  const months = [];
  for (let m = 5; m >= 0; m--) months.push(shiftMonth(barsEnd, -m));
  document.getElementById("barsPrev").onclick = () => { barsEnd = shiftMonth(barsEnd, -1); render(); };
  const next = document.getElementById("barsNext");
  next.disabled = barsEnd >= shiftMonth(thisMonth(), 1);
  next.onclick = () => { barsEnd = shiftMonth(barsEnd, 1); render(); };

  if (window.Chart) {
    const income = months.map(m => incomeIn(m, txns));
    const bills = months.map(m => txns.filter(t => isSpend(t) && isBill(t) && monthOf(t.date) === m).reduce((s, t) => s + t.amount, 0));
    const other = months.map((m, i) => spendIn(m, txns) - bills[i]);
    charts.monthly = new Chart(document.getElementById("chartMonthly"), {
      type: "bar",
      data: {
        labels: months.map(m => monthLabel(m) + (m === viewMonth ? " ●" : "")),
        datasets: [
          { label: "Income", data: income, backgroundColor: "#4b5bd6", borderRadius: 6, stack: "in", barPercentage: 0.5 },
          { label: "Spending", data: other, backgroundColor: "#8ea2ff", borderRadius: { topLeft: 0, topRight: 0, bottomLeft: 6, bottomRight: 6 }, stack: "out", barPercentage: 0.5 },
          { label: "Bills & Utilities", data: bills, backgroundColor: "#1a1d33", borderColor: "#3a3f66", borderWidth: 1, borderRadius: { topLeft: 6, topRight: 6 }, stack: "out", barPercentage: 0.5 },
        ],
      },
      options: {
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        onClick: (evt, els) => { if (els.length) { viewMonth = months[els[0].index]; render(); } },
        plugins: { legend: { display: false }, tooltip: { callbacks: { title: (it) => monthLabel(months[it[0].dataIndex], true), label: (c) => ` ${c.dataset.label}: ${fmt(c.raw)}` } } },
        scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, grid: { color: "#2a2c45" }, ticks: { callback: (v) => fmt0(v) } } },
      },
    });
  }
  renderBreakdown(document.getElementById("spBreakdown"), viewMonth, txns);
}

/* ================= Budgets ================= */

function renderBudgets(main) {
  const m = viewMonth;
  const byCat = spentByCategory(m);
  const totalLimit = state.budgets.reduce((s, b) => s + b.limit, 0);
  const totalSpent = state.budgets.reduce((s, b) => s + (byCat[b.category] || 0), 0);

  main.appendChild(el(`
    <div>
      <header class="view-header row">
        <div><h1>Budgets</h1><p class="sub">${fmt0(totalSpent)} of ${fmt0(totalLimit)} budgeted in ${monthLabel(m, true)}</p></div>
        <div style="display:flex;gap:10px;align-items:center"><div id="bdMonthNav"></div><button class="btn primary" id="btnAddBudget">+ Add budget</button></div>
      </header>
      <div class="grid grid-2" id="budgetList"></div>
    </div>`));
  document.getElementById("bdMonthNav").appendChild(monthNav(viewMonth, (v) => { viewMonth = v; render(); }));
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
          <div style="display:flex;align-items:center;gap:10px"><div class="row-icon">${catInfo(b.category).icon}</div><div class="row-title">${esc(b.category)}</div></div>
          <div><button class="icon-btn" title="Edit">✎</button><button class="icon-btn" title="Delete">🗑</button></div>
        </div>
        <div class="bar"><div class="bar-fill ${cls}" style="width:${pct}%"></div></div>
        <div class="budget-meta"><span>${fmt0(spent)} spent</span><span>${left >= 0 ? fmt0(left) + " left" : fmt0(-left) + " over"} of ${fmt0(b.limit)}</span></div>
      </div>`);
    const [editBtn, delBtn] = card.querySelectorAll(".icon-btn");
    editBtn.onclick = () => addBudgetForm(b);
    delBtn.onclick = () => { state.budgets = state.budgets.filter(x => x.id !== b.id); save(); render(); toast(`Removed ${b.category} budget`); };
    wrap.appendChild(card);
  }
}

/* ================= Accounts ================= */

function renderAccounts(main) {
  const accts = allAccounts();
  const nw = netWorth(accts);
  const banks = (me && me.banks) || [];
  const bankAccts = accts.filter(a => a.source === "bank");
  const manual = accts.filter(a => a.source === "manual");

  main.appendChild(el(`
    <div>
      <header class="view-header row">
        <div><h1>Accounts</h1><p class="sub">${bankAccts.length} linked account${bankAccts.length === 1 ? "" : "s"} across ${banks.length} bank${banks.length === 1 ? "" : "s"} · ${manual.length} manual</p></div>
        ${!viewingAs ? `<button class="btn primary" id="btnAddAccount">+ Add manual account</button>` : ""}
      </header>
      <div class="grid grid-3">
        <div class="card"><div class="stat-label">Net worth</div><div class="stat-value small">${fmt(nw.net)}</div></div>
        <div class="card"><div class="stat-label">Assets</div><div class="stat-value small green">${fmt(nw.assets)}</div></div>
        <div class="card"><div class="stat-label">Debts</div><div class="stat-value small red">${fmt(nw.debts)}</div></div>
      </div>
      <div class="card">
        <div class="card-head">
          <div class="card-title">🔗 Linked banks <span class="pill">via Plaid ${me && me.plaidEnv ? esc(me.plaidEnv) : "sandbox"}</span></div>
          ${!viewingAs ? `<div style="display:flex;gap:10px"><button class="btn primary" id="btnLinkBank">+ Connect a bank</button><button class="btn ghost" id="btnSyncBanks">↻ Sync now</button></div>` : ""}
        </div>
        <div id="bankList"></div>
        ${!me || me.plaidEnv !== "production" ? `<p class="tiny muted" style="margin-top:10px">Sandbox test login: username <b>user_good</b>, password <b>pass_good</b></p>` : ""}
      </div>
      ${!viewingAs ? `<div class="card"><div class="card-title">✍️ Manual accounts</div><div class="list" id="manualList"></div></div>` : ""}
      <div class="card acct-summary"><div class="card-title">Summary</div><div id="acctSummaryBox"></div></div>
    </div>`));
  const addBtn = document.getElementById("btnAddAccount"); if (addBtn) addBtn.onclick = () => addAccountForm();
  const linkBtn = document.getElementById("btnLinkBank"); if (linkBtn) linkBtn.onclick = connectBank;
  const syncBtn = document.getElementById("btnSyncBanks"); if (syncBtn) syncBtn.onclick = (e) => syncBanks(e.target);

  const bankWrap = document.getElementById("bankList");
  if (!banks.length) bankWrap.appendChild(el(`<div class="empty">No banks linked yet.</div>`));
  for (const b of banks) {
    const list = bankAccts.filter(a => a.itemId === b.itemId);
    const g = el(`
      <div class="bank-group">
        <div class="bg-head">
          <div><div class="row-title">🏛️ ${esc(b.institution)}</div>
            <div class="row-sub">${list.length} account${list.length === 1 ? "" : "s"} · synced ${timeAgo(b.lastSync)}${b.error ? ` · <span class="err">⚠ ${esc(b.error)}</span>` : ""}${b.syncStatus === "TRANSACTIONS_UPDATE_STATUS_NOT_READY" ? " · first import in progress…" : ""}</div></div>
          ${!viewingAs ? `<button class="btn ghost" title="Unlink this bank and delete its transactions">Remove</button>` : ""}
        </div>
        <div class="list"></div>
      </div>`);
    const lst = g.querySelector(".list");
    if (!list.length) lst.appendChild(el(`<div class="empty">Accounts not loaded yet — press “Sync now”.</div>`));
    for (const a of list) {
      lst.appendChild(el(`
        <div class="list-row">
          <div class="row-icon">${GROUPS[a.group].icon}</div>
          <div class="row-main"><div class="row-title">${esc(a.name)}${a.mask ? ` <span class="muted">••${esc(a.mask)}</span>` : ""}</div>
            <div class="row-sub">${esc(a.subtype || a.group)} · ${GROUPS[a.group].label}${a.available != null && a.group !== "credit" ? ` · ${fmt(a.available)} available` : ""}${a.limit ? ` · limit ${fmt0(a.limit)}` : ""}</div></div>
          <div class="row-amount ${GROUPS[a.group].debt ? "" : "green"}">${GROUPS[a.group].debt ? "−" : ""}${fmt(a.balance)}</div>
        </div>`));
    }
    const rm = g.querySelector(".bg-head .btn");
    if (rm) rm.onclick = async () => {
      if (!confirm(`Remove ${b.institution}? Its accounts and transactions are deleted from MoneyTrack (you can re-link it later — a fresh link imports up to 2 years of history).`)) return;
      try { const r = await api("remove_bank", { item_id: b.itemId }); await refreshServer(); render(); toast(`Removed ${b.institution} (${r.removed.transactions} transactions)`); }
      catch (e) { toast(e.message); }
    };
    bankWrap.appendChild(g);
  }

  const mWrap = document.getElementById("manualList");
  if (mWrap) {
    if (!manual.length) mWrap.appendChild(el(`<div class="empty">No manual accounts. Use these for cash, 401(k), property, loans not at a linked bank…</div>`));
    for (const a of manual) {
      const row = el(`
        <div class="list-row clickable">
          <div class="row-icon">${GROUPS[a.group].icon}</div>
          <div class="row-main"><div class="row-title">${esc(a.name)}</div><div class="row-sub">${GROUPS[a.group].label}</div></div>
          <div class="row-amount ${GROUPS[a.group].debt ? "" : "green"}">${GROUPS[a.group].debt ? "−" : ""}${fmt(a.balance)}</div>
          <div class="row-actions"><button class="icon-btn" title="Edit">✎</button><button class="icon-btn" title="Delete">🗑</button></div>
        </div>`);
      const [e, d] = row.querySelectorAll(".icon-btn");
      e.onclick = (ev) => { ev.stopPropagation(); addAccountForm(a.raw); };
      d.onclick = (ev) => { ev.stopPropagation(); state.accounts = state.accounts.filter(x => x.id !== a.id); save(); render(); toast(`Removed ${a.name}`); };
      row.onclick = () => addAccountForm(a.raw);
      mWrap.appendChild(row);
    }
  }
  renderAccountSummary(document.getElementById("acctSummaryBox"));
}

async function connectBank() {
  try {
    const { link_token } = await api("create_link_token");
    const handler = Plaid.create({
      token: link_token,
      onSuccess: async (public_token, metadata) => {
        try {
          const inst = metadata && metadata.institution ? metadata.institution.name : "Bank";
          const instId = metadata && metadata.institution ? metadata.institution.institution_id : "";
          toast(`Linking ${inst} & importing…`);
          const before = bankTxns.length;
          const r = await api("exchange_public_token", { public_token, institution: inst, institution_id: instId });
          try { localStorage.setItem(LASTSYNC_KEY, String(Date.now())); } catch (e) {}
          await refreshServer();
          render();
          toast(`${inst} linked — ${r.accounts} accounts, ${r.synced} transactions so far`);
          if (r.pending || r.synced === 0) waitForInitialTransactions(before);
        } catch (e) { toast(e.message); }
      },
      onExit: (err) => { if (err) toast("Plaid Link closed: " + (err.display_message || err.error_code)); },
    });
    handler.open();
  } catch (e) {
    toast(e.message);
  }
}

/* ================= Net worth ================= */

function renderNetWorth(main) {
  const accts = allAccounts();
  const nw = netWorth(accts);
  main.appendChild(el(`
    <div>
      <header class="view-header"><h1>Net Worth</h1><p class="sub">Assets minus debts across linked + manual accounts</p></header>
      <div class="grid grid-3">
        <div class="card"><div class="stat-label">Net worth</div><div class="stat-value">${fmt(nw.net)}</div></div>
        <div class="card"><div class="stat-label">Total assets</div><div class="stat-value green">${fmt(nw.assets)}</div></div>
        <div class="card"><div class="stat-label">Total debts</div><div class="stat-value red">${fmt(nw.debts)}</div></div>
      </div>
      <div class="card"><div class="card-title">Trend <span class="pill">simulated history</span></div><div class="chart-box tall"><canvas id="chartNW"></canvas></div></div>
      <div class="card"><div class="card-title">Breakdown by account</div><div class="chart-box tall"><canvas id="chartAccounts"></canvas></div></div>
    </div>`));

  if (window.Chart) {
    const labels = [], data = [];
    for (let m = 11; m >= 0; m--) { labels.push(monthLabel(monthISO(-m))); data.push(Math.round(nw.net * (1 - m * 0.018 - (m % 3 === 0 ? 0.01 : 0)))); }
    charts.nw = new Chart(document.getElementById("chartNW"), {
      type: "line",
      data: { labels, datasets: [{ label: "Net worth", data, borderColor: "#7c5cff", backgroundColor: "#7c5cff22", fill: true, tension: 0.35, pointRadius: 0, borderWidth: 2.5 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { grid: { color: "#2a2c45" }, ticks: { callback: (v) => fmt0(v) } }, x: { grid: { display: false } } } },
    });
    const sorted = [...accts].sort((a, b) => b.balance - a.balance);
    charts.accounts = new Chart(document.getElementById("chartAccounts"), {
      type: "bar",
      data: {
        labels: sorted.map(a => `${a.name}${a.mask ? " ••" + a.mask : ""}`),
        datasets: [{ data: sorted.map(a => (GROUPS[a.group].debt ? -a.balance : a.balance)), backgroundColor: sorted.map(a => (GROUPS[a.group].debt ? "#ff5c7a" : "#00d4a6")), borderRadius: 6 }],
      },
      options: { indexAxis: "y", maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { color: "#2a2c45" }, ticks: { callback: (v) => fmt0(v) } }, y: { grid: { display: false } } } },
    });
  }
}

/* ================= Settings ================= */

function renderSettings(main) {
  const invited = (me && me.invited) || [];
  const shared = (me && me.sharedWithMe) || [];

  main.appendChild(el(`
    <div>
      <header class="view-header"><h1>Settings</h1><p class="sub">Signed in as ${esc(session.email)}</p></header>

      <div class="card">
        <div class="card-head"><div class="card-title">🏷️ Categories</div><button class="btn primary" id="btnAddCat">+ Add category</button></div>
        <p class="tiny muted" style="margin-bottom:12px">Click a category to rename it, change its icon/colour, or mark it as a bill. Deleting one moves its transactions to “Other”.</p>
        <div class="cat-grid" id="catGrid"></div>
      </div>

      <div class="card">
        <div class="card-title">🤖 Auto-categorize rules</div>
        <p class="tiny muted" style="margin-bottom:12px">Bank transactions are categorized by Plaid first. These keyword rules fill in anything left as “Other” and apply to manual entries. Longest keyword wins.</p>
        <form id="ruleForm" style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px">
          <input name="keyword" required placeholder="keyword, e.g. netflix" style="flex:1;min-width:160px">
          <select name="category">${catOptions("Subscriptions")}</select>
          <button type="submit" class="btn primary">Add rule</button>
          <button type="button" class="btn ghost" id="btnApplyRules" title="Re-apply rules to manual transactions still marked Other">Re-run on manual</button>
        </form>
        <div id="ruleList"></div>
      </div>

      <div class="card">
        <div class="card-title">👥 Share my transactions</div>
        <p class="tiny muted" style="margin-bottom:12px">Invite someone by <b>email or phone number</b>. Once they sign up / log in with that email (or add that phone in their Settings), they can view your bank accounts and transactions (read-only).</p>
        <form id="inviteForm" style="display:flex;gap:10px">
          <input name="contact" required placeholder="person@example.com or (512) 555-1234" style="flex:1">
          <button type="submit" class="btn primary">Invite</button>
        </form>
        <div class="list" id="inviteList" style="margin-top:10px"></div>
      </div>

      <div class="card">
        <div class="card-title">📱 My phone number <span class="pill">${me && me.phone ? esc(me.phone) : "not set"}</span></div>
        <p class="tiny muted" style="margin-bottom:12px">If someone shares their data with your phone number, add it here so it shows up under “Shared with me”.</p>
        <form id="phoneForm" style="display:flex;gap:10px">
          <input name="phone" type="tel" placeholder="(512) 555-1234" value="${esc((me && me.phone) || "")}" style="flex:1">
          <button type="submit" class="btn primary">Save</button>
        </form>
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
          <button class="btn ghost" id="btnExport">⬇ Export data (JSON)</button>
          <button class="btn ghost" id="btnReset">Load demo data</button>
          <button class="btn ghost" id="btnResetCats">Reset categories &amp; rules</button>
          <button class="btn danger" id="btnClearSample">Clear local data</button>
        </div>
        <p class="tiny muted" style="margin-top:10px">Manual transactions, budgets, recurring, manual accounts, categories and rules are stored in this browser. Bank accounts/transactions (and your edits to them) are stored server-side under your login. <a href="privacy.html" target="_blank" style="color:#7c5cff">Privacy Policy</a></p>
      </div>
    </div>`));

  // categories
  const grid = document.getElementById("catGrid");
  const counts = {};
  for (const t of getTxns()) counts[t.cat] = (counts[t.cat] || 0) + 1;
  for (const c of cats()) {
    const tile = el(`
      <div class="cat-tile" style="cursor:pointer" title="Edit">
        <span class="row-icon" style="width:32px;height:32px;font-size:16px;background:${c.color}22">${c.icon}</span>
        <span class="sw" style="background:${c.color}"></span>
        <span class="nm">${esc(c.name)}<div class="tag">${counts[c.name] || 0} txns${c.bill ? " · bill" : ""}${c.kind && c.kind !== "expense" ? " · " + c.kind : ""}</div></span>
        ${c.name !== "Other" ? `<button class="icon-btn" title="Delete">🗑</button>` : ""}
      </div>`);
    tile.onclick = () => categoryForm(c);
    const del = tile.querySelector(".icon-btn");
    if (del) del.onclick = (e) => { e.stopPropagation(); deleteCategory(c); };
    grid.appendChild(tile);
  }
  document.getElementById("btnAddCat").onclick = () => categoryForm(null);

  // rules
  const rl = document.getElementById("ruleList");
  if (!state.rules.length) rl.appendChild(el(`<div class="empty">No rules.</div>`));
  for (const r of state.rules) {
    const row = el(`<div class="rule-row"><code>${esc(r.keyword)}</code><span class="arrow">→</span><span>${catInfo(r.category).icon} ${esc(r.category)}</span><span style="flex:1"></span><button class="icon-btn" title="Delete">🗑</button></div>`);
    row.querySelector(".icon-btn").onclick = () => { state.rules = state.rules.filter(x => x !== r); save(); render(); };
    rl.appendChild(row);
  }
  document.getElementById("ruleForm").onsubmit = (e) => {
    e.preventDefault();
    const d = new FormData(e.target);
    const kw = String(d.get("keyword")).trim().toLowerCase();
    if (!kw) return;
    state.rules = state.rules.filter(r => r.keyword.toLowerCase() !== kw);
    state.rules.unshift({ keyword: kw, category: d.get("category") });
    save(); render(); toast(`Rule added: “${kw}” → ${d.get("category")}`);
  };
  document.getElementById("btnApplyRules").onclick = () => {
    let n = 0;
    for (const t of state.transactions) { if (t.userSet || (t.category && t.category !== "Other")) continue; const c = ruleMatch(t.name); if (c) { t.category = c; n++; } }
    save(); render(); toast(`Re-categorized ${n} manual transaction(s)`);
  };

  // sharing
  const invWrap = document.getElementById("inviteList");
  if (!invited.length) invWrap.appendChild(el(`<div class="empty">Nobody invited yet.</div>`));
  for (const contact of invited) {
    const row = el(`
      <div class="list-row">
        <div class="row-icon">${contact.includes("@") ? "✉️" : "📱"}</div>
        <div class="row-main"><div class="row-title">${esc(contact)}</div><div class="row-sub">can view your accounts &amp; transactions</div></div>
        <div class="row-actions"><button class="icon-btn" title="Revoke">✕</button></div>
      </div>`);
    row.querySelector(".icon-btn").onclick = async () => {
      try { await api("invite", { contact, revoke: true }); await refreshServer(); render(); toast(`Revoked ${contact}`); }
      catch (e) { toast(e.message); }
    };
    invWrap.appendChild(row);
  }
  document.getElementById("inviteForm").onsubmit = async (e) => {
    e.preventDefault();
    const contact = new FormData(e.target).get("contact");
    try { const r = await api("invite", { contact }); await refreshServer(); render(); toast(`Invited ${r.invited}`); }
    catch (err) { toast(err.message); }
  };
  document.getElementById("phoneForm").onsubmit = async (e) => {
    e.preventDefault();
    try { const r = await api("update_profile", { phone: new FormData(e.target).get("phone") }); await refreshServer(); render(); toast(r.phone ? `Phone saved: ${r.phone}` : "Phone cleared"); }
    catch (err) { toast(err.message); }
  };

  const shWrap = document.getElementById("sharedList");
  if (!shared.length) shWrap.appendChild(el(`<div class="empty">Nobody has shared their data with you.</div>`));
  for (const s of shared) {
    const row = el(`
      <div class="list-row">
        <div class="row-icon">👀</div>
        <div class="row-main"><div class="row-title">${esc(s.ownerEmail)}</div><div class="row-sub">invited you to view their data</div></div>
        <button class="btn ghost">View</button>
      </div>`);
    row.querySelector("button").onclick = async () => {
      viewingAs = { ownerId: s.ownerId, ownerEmail: s.ownerEmail };
      await refreshServer();
      location.hash = "#dashboard"; render();
    };
    shWrap.appendChild(row);
  }

  renderTfaBox();

  document.getElementById("btnExport").onclick = () => {
    const blob = new Blob([JSON.stringify({ local: state, bank: bankTxns, accounts: (me && me.accounts) || [] }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = "moneytrack-export.json"; a.click();
    URL.revokeObjectURL(a.href);
  };
  document.getElementById("btnClearSample").onclick = () => {
    if (confirm("Remove all local data — manual transactions, budgets, recurring, manual accounts, custom categories & rules? (Bank data is kept.)")) {
      state = emptyData(); save(); render(); toast("Local data cleared");
    }
  };
  document.getElementById("btnResetCats").onclick = () => {
    if (confirm("Reset categories and rules to the defaults? Custom categories are removed (their transactions become Other).")) {
      state.categories = DEFAULT_CATEGORIES.map(c => ({ ...c })); state.rules = DEFAULT_RULES.map(r => ({ ...r })); state.aliases = {};
      save(); render(); toast("Categories & rules reset");
    }
  };
  document.getElementById("btnReset").onclick = () => {
    if (confirm("Load demo/sample data? This replaces your current local data.")) {
      state = seedData(); save(); render(); toast("Demo data loaded");
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
        <form style="display:flex;gap:10px"><input name="code" inputmode="numeric" required placeholder="6-digit code" style="width:160px"><button type="submit" class="btn danger">Disable 2FA</button></form>
      </div>`));
    box.querySelector("form").onsubmit = async (e) => {
      e.preventDefault();
      try { await api("disable_2fa", { code: new FormData(e.target).get("code") }); await refreshServer(); render(); toast("2FA disabled"); }
      catch (err) { toast(err.message); }
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
            <form style="display:flex;gap:10px"><input name="code" inputmode="numeric" required placeholder="123456" style="width:160px"><button type="submit" class="btn primary">Confirm &amp; enable</button></form>
          </div>`));
        if (window.QRCode) new QRCode(document.getElementById("tfaQr"), { text: r.otpauth, width: 168, height: 168 });
        setup.querySelector("form").onsubmit = async (e) => {
          e.preventDefault();
          try { await api("confirm_2fa", { code: new FormData(e.target).get("code") }); await refreshServer(); render(); toast("2FA enabled 🎉"); }
          catch (err) { toast(err.message); }
        };
      } catch (err) { toast(err.message); }
    };
  }
}

/* ================= Category management ================= */

function categoryForm(c) {
  const isNew = !c;
  const f = el(`<form>
    <div class="form-row">
      ${field("Icon (emoji)", `<input name="icon" value="${esc(c ? c.icon : "🏷️")}" maxlength="4" style="width:80px">`)}
      ${field("Name", `<input name="name" required value="${esc(c ? c.name : "")}" placeholder="e.g. Kids">`)}
    </div>
    <div class="form-row">
      ${field("Colour", `<input name="color" type="color" value="${esc(c ? c.color : "#7c5cff")}">`)}
      ${field("Type", `<select name="kind"><option value="expense" ${!c || !c.kind || c.kind === "expense" ? "selected" : ""}>Expense</option><option value="income" ${c && c.kind === "income" ? "selected" : ""}>Income</option><option value="transfer" ${c && c.kind === "transfer" ? "selected" : ""}>Transfer (ignored in totals)</option></select>`)}
    </div>
    <label class="switch" style="margin-bottom:14px"><input type="checkbox" name="bill" ${c && c.bill ? "checked" : ""}><i></i> This is a bill / fixed cost</label>
    ${formActions(isNew ? "Add" : "Save")}</form>`);
  wireForm(f, async (d) => {
    const name = String(d.get("name")).trim();
    if (!name) return;
    const clash = catByName(name);
    if (clash && (isNew || clash !== c)) { toast("A category with that name already exists"); return; }
    const data = { name, icon: String(d.get("icon")).trim() || "🏷️", color: d.get("color"), bill: d.get("bill") === "on" };
    const kind = d.get("kind"); if (kind !== "expense") data.kind = kind;
    if (isNew) { state.categories.push(data); save(); closeModal(); render(); toast(`Added ${name}`); return; }
    const old = c.name;
    Object.assign(c, data); if (kind === "expense") delete c.kind;
    if (old !== name) {
      for (const t of state.transactions) if (t.category === old) t.category = name;
      for (const b of state.budgets) if (b.category === old) b.category = name;
      for (const r of state.rules) if (r.category === old) r.category = name;
      for (const [k, v] of Object.entries(state.aliases)) if (v === old) state.aliases[k] = name;
      state.aliases[old] = name; delete state.aliases[name];
      const bank = bankTxns.filter(t => t.userSet && t.category === old);
      for (const t of bank) t.category = name;
      if (bank.length) {
        try { await api("update_transaction", { updates: bank.slice(0, 500).map(t => ({ id: t.id, category: name })) }); } catch (e) { toast("Rename saved locally; server update failed: " + e.message); }
      }
    }
    save(); closeModal(); render(); toast(`Saved ${name}`);
  });
  openModal(isNew ? "Add category" : "Edit category", f);
}

async function deleteCategory(c) {
  const n = getTxns().filter(t => t.cat === c.name).length;
  if (!confirm(`Delete “${c.name}”? ${n} transaction(s) will move to “Other”.`)) return;
  state.categories = state.categories.filter(x => x !== c);
  for (const t of state.transactions) if (t.category === c.name) { t.category = "Other"; t.userSet = false; }
  state.budgets = state.budgets.filter(b => b.category !== c.name);
  state.rules = state.rules.filter(r => r.category !== c.name);
  for (const [k, v] of Object.entries(state.aliases)) if (v === c.name) delete state.aliases[k];
  const bank = bankTxns.filter(t => t.userSet && t.category === c.name);
  for (const t of bank) { t.category = "Other"; t.userSet = false; }
  save(); render(); toast(`Deleted ${c.name}`);
  if (bank.length) { try { await api("update_transaction", { updates: bank.slice(0, 500).map(t => ({ id: t.id, resetCategory: true })) }); } catch (e) {} }
}

/* ================= Modal forms ================= */

function openModal(title, formEl) {
  const root = document.getElementById("modal-root");
  root.innerHTML = "";
  const backdrop = el(`<div class="modal-backdrop"><div class="modal"><div class="modal-head"><h2>${esc(title)}</h2><button class="close-btn">✕</button></div></div></div>`);
  backdrop.querySelector(".modal").appendChild(formEl);
  backdrop.querySelector(".close-btn").onclick = closeModal;
  backdrop.onclick = (e) => { if (e.target === backdrop) closeModal(); };
  root.appendChild(backdrop);
  const first = formEl.querySelector("input:not([type=hidden]), select");
  if (first) first.focus();
}
function closeModal() { document.getElementById("modal-root").innerHTML = ""; }
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

const field = (label, inner) => `<div class="form-field"><label>${label}</label>${inner}</div>`;
const catOptions = (sel, kind) => catNames(kind).map(c => `<option ${c === sel ? "selected" : ""}>${esc(c)}</option>`).join("");
const formActions = (submit = "Add", extra = "") => `<div class="form-actions ${extra ? "between" : ""}">${extra}<span style="display:flex;gap:10px"><button type="button" class="btn ghost" data-cancel>Cancel</button><button type="submit" class="btn primary">${submit}</button></span></div>`;

function wireForm(f, onSubmit) {
  f.onsubmit = (e) => { e.preventDefault(); onSubmit(new FormData(f)); };
  f.querySelector("[data-cancel]").onclick = closeModal;
}

function addTxnForm() {
  const f = el(`<form>
    ${field("Name", `<input name="name" required placeholder="e.g. Target">`)}
    <div class="form-row">
      ${field("Amount ($)", `<input name="amount" type="number" step="0.01" min="0.01" required placeholder="0.00">`)}
      ${field("Type", `<select name="type"><option value="expense">Expense</option><option value="income">Income</option></select>`)}
    </div>
    ${field("Category <span class='tiny muted' id='catHint'></span>", `<select name="category">${catOptions("Other")}</select>`)}
    ${field("Date", `<input name="date" type="date" value="${todayISO()}" required>`)}
    ${field("Notes", `<input name="notes" placeholder="optional">`)}
    ${formActions("Add")}</form>`);
  // auto-suggest category from keyword rules while typing
  let touched = false;
  f.querySelector('[name="category"]').onchange = () => (touched = true);
  f.querySelector('[name="name"]').oninput = (e) => {
    if (touched) return;
    const c = ruleMatch(e.target.value);
    if (c) { f.querySelector('[name="category"]').value = c; f.querySelector("#catHint").textContent = "(auto)"; }
  };
  wireForm(f, (d) => {
    const type = d.get("type");
    state.transactions.push({
      id: id(), name: d.get("name"), amount: parseFloat(d.get("amount")), type,
      category: type === "income" ? "Income" : d.get("category"), userSet: touched,
      date: d.get("date"), notes: String(d.get("notes") || "").trim(),
    });
    save(); closeModal(); location.hash = "#transactions"; render(); toast("Transaction added");
  });
  openModal("Add transaction", f);
}

function editTxnForm(t) {
  const bank = t.source === "bank";
  const sameName = getTxns().filter(x => x.id !== t.id && String(x.name).toLowerCase() === String(t.name).toLowerCase());
  const f = el(`<form>
    ${field("Name", `<input name="name" required value="${esc(t.name)}">`)}
    ${bank ? `<p class="tiny muted" style="margin:-6px 0 12px">Bank description: ${esc(t.originalName || t.name)} · ${accountName(t.accountId)}</p>` : ""}
    <div class="form-row">
      ${field("Amount ($)", `<input name="amount" type="number" step="0.01" min="0.01" required value="${t.amount}" ${bank ? "disabled" : ""}>`)}
      ${field("Type", `<select name="type" ${bank ? "disabled" : ""}><option value="expense" ${t.type === "expense" ? "selected" : ""}>Expense</option><option value="income" ${t.type === "income" ? "selected" : ""}>Income</option></select>`)}
    </div>
    ${field("Category", `<select name="category">${catOptions(t.cat)}</select>`)}
    ${field("Date", `<input name="date" type="date" value="${t.date}" required ${bank ? "disabled" : ""}>`)}
    ${field("Notes", `<input name="notes" value="${esc(t.notes || "")}" placeholder="optional">`)}
    ${sameName.length ? `<label class="switch" style="margin-bottom:8px"><input type="checkbox" name="applyAll"><i></i> Also apply this category to ${sameName.length} other “${esc(t.name)}” transaction(s)</label>` : ""}
    <label class="switch" style="margin-bottom:14px"><input type="checkbox" name="addRule"><i></i> Always use this category for “${esc(t.name)}” (adds a rule)</label>
    ${formActions("Save", `<button type="button" class="btn danger" data-delete>Delete</button>`)}</form>`);
  f.querySelector("[data-delete]").onclick = () => { closeModal(); deleteTxn(t); };
  wireForm(f, async (d) => {
    const category = d.get("category");
    const name = String(d.get("name")).trim();
    const notes = String(d.get("notes") || "").trim();
    const catChanged = category !== t.cat;
    if (bank) {
      const patch = { id: t.id, name, notes };
      if (catChanged) patch.category = category;
      try { await api("update_transaction", patch); } catch (e) { toast(e.message); return; }
      const b = bankTxns.find(x => x.id === t.id);
      if (b) { b.name = name; b.notes = notes; if (catChanged) { b.category = category; b.userSet = true; } }
    } else {
      const m = state.transactions.find(x => x.id === t.id);
      if (m) {
        m.name = name; m.notes = notes; m.amount = parseFloat(d.get("amount")); m.type = d.get("type"); m.date = d.get("date");
        if (catChanged) { m.category = category; m.userSet = true; }
      }
    }
    save();
    const extra = d.get("applyAll") === "on" ? sameName : [];
    await setCategory(extra, category, { addRule: d.get("addRule") === "on", ruleKeyword: name.toLowerCase() });
    closeModal(); render();
    toast(extra.length ? `Updated ${extra.length + 1} transactions` : "Transaction saved");
  });
  openModal(bank ? "Edit bank transaction" : "Edit transaction", f);
}

function addRecurringForm() {
  const f = el(`<form>
    ${field("Name", `<input name="name" required placeholder="e.g. Hulu">`)}
    ${field("Amount ($)", `<input name="amount" type="number" step="0.01" min="0.01" required placeholder="0.00">`)}
    ${field("Cadence", `<select name="cadence"><option>monthly</option><option>yearly</option><option>weekly</option></select>`)}
    ${field("Next due", `<input name="nextDue" type="date" value="${todayISO(7)}" required>`)}
    ${formActions("Add")}</form>`);
  wireForm(f, (d) => {
    state.recurring.push({ id: id(), name: d.get("name"), amount: parseFloat(d.get("amount")), cadence: d.get("cadence"), nextDue: d.get("nextDue") });
    save(); closeModal(); render(); toast("Recurring charge added");
  });
  openModal("Add recurring charge", f);
}

function addBudgetForm(b) {
  const used = new Set(state.budgets.filter(x => !b || x.id !== b.id).map(x => x.category));
  const avail = catNames("expense").filter(c => !used.has(c));
  const f = el(`<form>
    ${field("Category", `<select name="category">${avail.map(c => `<option ${b && b.category === c ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>`)}
    ${field("Monthly limit ($)", `<input name="limit" type="number" step="1" min="1" required value="${b ? b.limit : ""}" placeholder="e.g. 300">`)}
    ${formActions(b ? "Save" : "Add")}</form>`);
  wireForm(f, (d) => {
    if (b) { b.category = d.get("category"); b.limit = parseFloat(d.get("limit")); }
    else state.budgets.push({ id: id(), category: d.get("category"), limit: parseFloat(d.get("limit")) });
    save(); closeModal(); render(); toast(b ? "Budget saved" : "Budget added");
  });
  openModal(b ? "Edit budget" : "Add budget", f);
}

function addAccountForm(a) {
  const typeOpts = Object.entries(GROUPS).map(([k, g]) => `<option value="${k}" ${a && a.type === k ? "selected" : ""}>${g.icon} ${g.label}</option>`).join("");
  const f = el(`<form>
    ${field("Name", `<input name="name" required value="${esc(a ? a.name : "")}" placeholder="e.g. HSA — Fidelity">`)}
    ${field("Type", `<select name="type">${typeOpts}</select>`)}
    ${field("Balance ($) <span class='tiny muted'>— enter debts as a positive amount owed</span>", `<input name="balance" type="number" step="0.01" required value="${a ? a.balance : ""}" placeholder="0.00">`)}
    ${formActions(a ? "Save" : "Add")}</form>`);
  wireForm(f, (d) => {
    const data = { name: d.get("name"), balance: Math.abs(parseFloat(d.get("balance"))), type: d.get("type") };
    if (a) Object.assign(a, data); else state.accounts.push({ id: id(), ...data });
    save(); closeModal(); render(); toast(a ? "Account saved" : "Account added");
  });
  openModal(a ? "Edit account" : "Add manual account", f);
}

/* ================= Init ================= */

document.querySelector('[data-action="add-tx"]').onclick = () => {
  if (!session) { toast("Sign in first"); return; }
  if (viewingAs) { toast("Read-only while viewing someone else's data"); return; }
  addTxnForm();
};
document.getElementById("globalSearch").onsubmit = (e) => {
  e.preventDefault();
  if (!session) return;
  const q = e.target.q.value.trim();
  gotoTransactions({ q });
  e.target.q.value = "";
};

load();
render();
if (session) refreshServer().then(() => { render(); autoSync(); });
