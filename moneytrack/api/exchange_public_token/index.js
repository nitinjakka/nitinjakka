const { plaidPost, jsonRes, errRes } = require("../shared/plaid");
const { table, ensureTables, clean } = require("../shared/db");
const { requireAuth } = require("../shared/auth");
const { syncItem, refreshAccounts } = require("../shared/sync");

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// Exchanges a public token, stores the access token SERVER-SIDE, pulls the account list,
// then runs the initial transaction sync — retrying a few times because Plaid's first pull
// is usually not ready the instant Link completes. The webhook finishes the job later if needed.
module.exports = async function (context, req) {
  try {
    await ensureTables();
    const user = await requireAuth(req);
    if (!user) return jsonRes(context, 401, { error: "Not logged in" });
    const publicToken = req.body && req.body.public_token;
    if (!publicToken) return jsonRes(context, 400, { error: "public_token required" });

    const data = await plaidPost("/item/public_token/exchange", { public_token: publicToken });
    const item = clean({
      partitionKey: user.userId,
      rowKey: data.item_id,
      accessToken: data.access_token,
      institution: (req.body && req.body.institution) || "Bank",
      institutionId: (req.body && req.body.institution_id) || "",
      createdAt: new Date().toISOString(),
    });
    await table("items").upsertEntity(item, "Replace");

    let accounts = 0;
    try { accounts = await refreshAccounts(user.userId, item); } catch (e) { /* best effort */ }

    let synced = 0, status = "";
    for (let attempt = 0; attempt < 4; attempt++) {
      const r = await syncItem(user.userId, item);
      synced += r.added; status = r.status;
      if (r.added > 0 && status !== "TRANSACTIONS_UPDATE_STATUS_NOT_READY") break;
      await sleep(3000);
    }
    jsonRes(context, 200, {
      ok: true, item_id: data.item_id, accounts, synced, status,
      pending: synced === 0, // frontend keeps polling sync_transactions while true
    });
  } catch (e) {
    errRes(context, e);
  }
};
