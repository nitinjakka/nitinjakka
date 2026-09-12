const { plaidPost, jsonRes, errRes } = require("../shared/plaid");
const { ensureTables, getEntity, listEntities, deleteEntity } = require("../shared/db");
const { requireAuth } = require("../shared/auth");

// Unlinks a bank: revokes the Plaid item, deletes its accounts + transactions.
// Needed to re-link a bank and get the full 730-day history without duplicates.
// POST { item_id }
module.exports = async function (context, req) {
  try {
    await ensureTables();
    const user = await requireAuth(req);
    if (!user) return jsonRes(context, 401, { error: "Not logged in" });
    const itemId = req.body && req.body.item_id;
    if (!itemId) return jsonRes(context, 400, { error: "item_id required" });
    const item = await getEntity("items", user.userId, itemId);
    if (!item) return jsonRes(context, 404, { error: "Bank not found" });

    try { await plaidPost("/item/remove", { access_token: item.accessToken }); } catch (e) { /* already gone */ }

    let txns = 0, accounts = 0;
    for (const t of await listEntities("txns", `PartitionKey eq '${user.userId}' and itemId eq '${itemId}'`)) {
      if (await deleteEntity("txns", user.userId, t.rowKey)) txns++;
    }
    for (const a of await listEntities("accounts", `PartitionKey eq '${user.userId}' and itemId eq '${itemId}'`)) {
      if (await deleteEntity("accounts", user.userId, a.rowKey)) accounts++;
    }
    await deleteEntity("items", user.userId, itemId);
    jsonRes(context, 200, { ok: true, removed: { transactions: txns, accounts } });
  } catch (e) {
    errRes(context, e);
  }
};
