const { plaidPost, jsonRes, errRes } = require("../shared/plaid");
const { table, ensureTables } = require("../shared/db");
const { requireAuth } = require("../shared/auth");
const { syncItem } = require("../shared/sync");

// Exchanges a public token, stores the access token SERVER-SIDE, runs initial sync.
module.exports = async function (context, req) {
  try {
    await ensureTables();
    const user = await requireAuth(req);
    if (!user) return jsonRes(context, 401, { error: "Not logged in" });
    const publicToken = req.body && req.body.public_token;
    if (!publicToken) return jsonRes(context, 400, { error: "public_token required" });

    const data = await plaidPost("/item/public_token/exchange", { public_token: publicToken });
    const item = {
      partitionKey: user.userId,
      rowKey: data.item_id,
      accessToken: data.access_token,
      institution: (req.body && req.body.institution) || "Bank",
      cursor: null,
      createdAt: new Date().toISOString(),
    };
    await table("items").upsertEntity(item, "Replace");
    const counts = await syncItem(user.userId, item);
    jsonRes(context, 200, { ok: true, item_id: data.item_id, synced: counts.added });
  } catch (e) {
    errRes(context, e);
  }
};
