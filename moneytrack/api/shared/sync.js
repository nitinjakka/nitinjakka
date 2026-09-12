// Shared Plaid → Table Storage sync: transactions + account balances + daily net-worth snapshots.
const { plaidPost } = require("./plaid");
const { table, listEntities, clean } = require("./db");

// Map Plaid personal_finance_category to MoneyTrack categories.
// Transfers / credit-card payments are tagged "Transfer" so they never count as spending.
function mapCategory(txn) {
  const pfc = txn.personal_finance_category || {};
  const primary = pfc.primary || "";
  const detailed = pfc.detailed || "";
  if (primary === "TRANSFER_IN" || primary === "TRANSFER_OUT") return "Transfer";
  if (detailed === "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT") return "Transfer";
  if (primary === "LOAN_PAYMENTS") return "Loan Payment";
  if (primary === "INCOME") return "Income";
  if (detailed.includes("GROCERIES")) return "Groceries";
  if (detailed === "RENT_AND_UTILITIES_RENT") return "Housing";
  if (detailed === "ENTERTAINMENT_TV_AND_MOVIES" || detailed === "ENTERTAINMENT_MUSIC_AND_AUDIO") return "Subscriptions";
  if (detailed === "GENERAL_SERVICES_INSURANCE") return "Services";
  const map = {
    FOOD_AND_DRINK: "Dining",
    GENERAL_MERCHANDISE: "Shopping",
    TRANSPORTATION: "Transport",
    TRAVEL: "Travel",
    RENT_AND_UTILITIES: "Utilities",
    MEDICAL: "Health",
    PERSONAL_CARE: "Health",
    ENTERTAINMENT: "Entertainment",
    HOME_IMPROVEMENT: "Housing",
    GENERAL_SERVICES: "Services",
    BANK_FEES: "Fees",
    GOVERNMENT_AND_NON_PROFIT: "Other",
  };
  return map[primary] || "Other";
}

// Same grouping the frontend uses (keep in sync with app.js groupOf).
function groupOf(type, subtype) {
  type = String(type || "").toLowerCase(); subtype = String(subtype || "").toLowerCase();
  if (type === "depository") return ["savings", "money market", "cd", "hsa", "gic"].includes(subtype) ? "savings" : "checking";
  if (type === "credit") return "credit";
  if (type === "investment" || type === "brokerage") return "investment";
  if (type === "loan") return "loan";
  return "other_asset";
}
const DEBT_GROUPS = new Set(["credit", "loan", "other_debt"]);

// Pull every account under an item (with cached balances) into the accounts table.
async function refreshAccounts(userId, item) {
  const data = await plaidPost("/accounts/get", { access_token: item.accessToken });
  const inst = item.institution || "Bank";
  for (const a of data.accounts) {
    const b = a.balances || {};
    await table("accounts").upsertEntity(clean({
      partitionKey: userId,
      rowKey: a.account_id,
      itemId: item.rowKey,
      institution: inst,
      name: a.name || a.official_name || "Account",
      officialName: a.official_name || "",
      mask: a.mask || "",
      type: a.type || "other",
      subtype: a.subtype || "",
      current: typeof b.current === "number" ? b.current : 0,
      available: typeof b.available === "number" ? b.available : undefined,
      limit: typeof b.limit === "number" ? b.limit : undefined,
      currency: b.iso_currency_code || "USD",
      updatedAt: new Date().toISOString(),
    }), "Replace");
  }
  return data.accounts.length;
}

// One row per user per day: totals by group + assets/debts/net (bank accounts only).
async function writeSnapshot(userId) {
  const accounts = await listEntities("accounts", `PartitionKey eq '${userId}'`);
  if (!accounts.length) return null;
  const groups = { checking: 0, savings: 0, credit: 0, investment: 0, loan: 0, other_asset: 0, other_debt: 0 };
  for (const a of accounts) groups[groupOf(a.type, a.subtype)] += (typeof a.current === "number" ? a.current : 0);
  let assets = 0, debts = 0;
  for (const [g, v] of Object.entries(groups)) { if (DEBT_GROUPS.has(g)) debts += v; else assets += v; }
  const snap = clean({
    partitionKey: userId,
    rowKey: new Date().toISOString().slice(0, 10),
    assets: Math.round(assets * 100) / 100,
    debts: Math.round(debts * 100) / 100,
    net: Math.round((assets - debts) * 100) / 100,
    ...Object.fromEntries(Object.entries(groups).map(([k, v]) => [k, Math.round(v * 100) / 100])),
    accounts: accounts.length,
    at: new Date().toISOString(),
  });
  await table("snapshots").upsertEntity(snap, "Replace");
  return snap;
}

// Sync one Plaid item's transactions into the txns table. Returns counts + readiness.
// Base (Plaid-derived) fields are MERGED so user edits (userCategory/userName/userNotes/hidden) survive.
async function syncItem(userId, item) {
  let cursor = item.cursor || null;
  let added = 0, removed = 0, status = "";
  let hasMore = true, guard = 0;
  while (hasMore && guard++ < 40) {
    const body = { access_token: item.accessToken, count: 500 };
    if (cursor) body.cursor = cursor;
    const data = await plaidPost("/transactions/sync", body);
    status = data.transactions_update_status || status;
    for (const t of [...data.added, ...data.modified]) {
      const pfc = t.personal_finance_category || {};
      await table("txns").upsertEntity(clean({
        partitionKey: userId,
        rowKey: t.transaction_id,
        name: t.merchant_name || t.name,
        rawName: t.name || "",
        amount: Math.abs(t.amount),
        // Plaid: positive amount = money out.
        type: t.amount >= 0 ? "expense" : "income",
        category: mapCategory(t),
        pfcPrimary: pfc.primary || "",
        pfcDetailed: pfc.detailed || "",
        date: t.date,
        accountId: t.account_id,
        pending: !!t.pending,
        itemId: item.rowKey,
      }), "Merge");
      added++;
    }
    for (const r of data.removed) {
      try { await table("txns").deleteEntity(userId, r.transaction_id); removed++; } catch (e) {}
    }
    cursor = data.next_cursor;
    hasMore = data.has_more;
  }
  await table("items").updateEntity(clean({
    partitionKey: userId, rowKey: item.rowKey, cursor,
    lastSync: new Date().toISOString(), syncStatus: status, lastError: "",
  }), "Merge");
  return { added, removed, status };
}

// Sync all items belonging to a user (accounts + transactions + snapshot). Never throws for one bad item.
async function syncUser(userId) {
  const items = await listEntities("items", `PartitionKey eq '${userId}'`);
  let added = 0, removed = 0, accounts = 0, notReady = false;
  const errors = [];
  for (const item of items) {
    try { accounts += await refreshAccounts(userId, item); } catch (e) { /* balances are best-effort */ }
    try {
      const r = await syncItem(userId, item);
      added += r.added; removed += r.removed;
      if (r.status === "TRANSACTIONS_UPDATE_STATUS_NOT_READY" || r.status === "NOT_READY") notReady = true;
    } catch (e) {
      const code = (e.plaid && e.plaid.error_code) || e.message;
      errors.push({ itemId: item.rowKey, institution: item.institution, error: code });
      try {
        await table("items").updateEntity({ partitionKey: userId, rowKey: item.rowKey, lastError: String(code) }, "Merge");
      } catch (e2) {}
    }
  }
  try { if (items.length) await writeSnapshot(userId); } catch (e) { /* best effort */ }
  return { added, removed, accounts, items: items.length, notReady, errors };
}

// Locate an item by Plaid item_id (used by webhooks — partition unknown).
async function findItem(itemId) {
  const rows = await listEntities("items", `RowKey eq '${itemId}'`);
  return rows[0] || null;
}

module.exports = { syncUser, syncItem, refreshAccounts, writeSnapshot, mapCategory, findItem, groupOf };
