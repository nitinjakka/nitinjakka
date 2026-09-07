// Shared Plaid → Table Storage transaction sync.
const { plaidPost } = require("./plaid");
const { table, listEntities } = require("./db");

// Map Plaid personal_finance_category to MoneyTrack categories.
function mapCategory(txn) {
  const pfc = txn.personal_finance_category || {};
  const primary = pfc.primary || "";
  const detailed = pfc.detailed || "";
  if (detailed.includes("GROCERIES")) return "Groceries";
  const map = {
    FOOD_AND_DRINK: "Dining",
    GENERAL_MERCHANDISE: "Shopping",
    TRANSPORTATION: "Transport",
    TRAVEL: "Transport",
    RENT_AND_UTILITIES: "Utilities",
    MEDICAL: "Health",
    ENTERTAINMENT: "Entertainment",
    INCOME: "Income",
    LOAN_PAYMENTS: "Housing",
    HOME_IMPROVEMENT: "Housing",
    PERSONAL_CARE: "Health",
  };
  return map[primary] || "Other";
}

// Sync one Plaid item's transactions into the txns table. Returns counts.
async function syncItem(userId, item) {
  let cursor = item.cursor || null;
  let added = 0, removed = 0;
  let hasMore = true, guard = 0;
  while (hasMore && guard++ < 30) {
    const body = { access_token: item.accessToken, count: 500 };
    if (cursor) body.cursor = cursor;
    const data = await plaidPost("/transactions/sync", body);
    for (const t of [...data.added, ...data.modified]) {
      await table("txns").upsertEntity({
        partitionKey: userId,
        rowKey: t.transaction_id,
        name: t.merchant_name || t.name,
        amount: Math.abs(t.amount),
        // Plaid: positive amount = money out.
        type: t.amount >= 0 ? "expense" : "income",
        category: t.amount < 0 ? "Income" : mapCategory(t),
        date: t.date,
        accountId: t.account_id,
        pending: !!t.pending,
        itemId: item.rowKey,
      }, "Replace");
      added++;
    }
    for (const r of data.removed) {
      try { await table("txns").deleteEntity(userId, r.transaction_id); removed++; } catch (e) {}
    }
    cursor = data.next_cursor;
    hasMore = data.has_more;
  }
  await table("items").updateEntity(
    { partitionKey: userId, rowKey: item.rowKey, cursor }, "Merge");
  return { added, removed };
}

// Sync all items belonging to a user.
async function syncUser(userId) {
  const items = await listEntities("items", `PartitionKey eq '${userId}'`);
  let added = 0, removed = 0;
  for (const item of items) {
    const r = await syncItem(userId, item);
    added += r.added; removed += r.removed;
  }
  return { added, removed, items: items.length };
}

module.exports = { syncUser, syncItem, mapCategory };
