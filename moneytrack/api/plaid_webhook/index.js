const { jsonRes } = require("../shared/plaid");
const { table, ensureTables } = require("../shared/db");
const { syncItem, refreshAccounts, findItem } = require("../shared/sync");

// Plaid → us. Registered on every link token (see create_link_token). When Plaid finishes the
// initial / historical pull or has new transactions, we sync that item immediately, so the
// user never has to press "Sync". Always answers 200 so Plaid does not retry forever.
// NOTE: prototype — webhook signature (Plaid-Verification JWT) is not checked; the worst a
// forged call can do is trigger an extra sync.
module.exports = async function (context, req) {
  const body = req.body || {};
  const type = body.webhook_type || "";
  const code = body.webhook_code || "";
  const itemId = body.item_id || "";
  context.log(`plaid_webhook ${type}/${code} item=${itemId}`);
  try {
    await ensureTables();
    if (!itemId) return jsonRes(context, 200, { ok: true, ignored: "no item_id" });
    const item = await findItem(itemId);
    if (!item) return jsonRes(context, 200, { ok: true, ignored: "unknown item" });
    const userId = item.partitionKey;

    if (type === "TRANSACTIONS") {
      // SYNC_UPDATES_AVAILABLE / INITIAL_UPDATE / HISTORICAL_UPDATE / DEFAULT_UPDATE / TRANSACTIONS_REMOVED
      try { await refreshAccounts(userId, item); } catch (e) {}
      const r = await syncItem(userId, item);
      return jsonRes(context, 200, { ok: true, added: r.added, removed: r.removed });
    }
    if (type === "ITEM") {
      if (code === "ERROR" && body.error) {
        await table("items").updateEntity(
          { partitionKey: userId, rowKey: itemId, lastError: String(body.error.error_code || "ITEM_ERROR") }, "Merge");
      }
      if (code === "LOGIN_REPAIRED") {
        await table("items").updateEntity({ partitionKey: userId, rowKey: itemId, lastError: "" }, "Merge");
      }
      return jsonRes(context, 200, { ok: true });
    }
    jsonRes(context, 200, { ok: true, ignored: type });
  } catch (e) {
    context.log.error("plaid_webhook failed: " + e.message);
    jsonRes(context, 200, { ok: false, error: e.message });
  }
};
