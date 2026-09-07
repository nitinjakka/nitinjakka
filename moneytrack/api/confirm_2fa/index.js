const { jsonRes, errRes } = require("../shared/plaid");
const { table, ensureTables, getEntity } = require("../shared/db");
const { requireAuth } = require("../shared/auth");
const { totpVerify } = require("../shared/totp");

// Step 2 of enabling 2FA: verify a code from the authenticator app, then activate.
module.exports = async function (context, req) {
  try {
    await ensureTables();
    const user = await requireAuth(req);
    if (!user) return jsonRes(context, 401, { error: "Not logged in" });
    const u = await getEntity("users", "user", user.email);
    if (!u.totpPending) return jsonRes(context, 400, { error: "No pending 2FA setup — start again" });
    const code = req.body && req.body.code;
    if (!totpVerify(u.totpPending, code)) return jsonRes(context, 400, { error: "Invalid code — try again" });

    await table("users").updateEntity(
      { partitionKey: "user", rowKey: user.email, totpSecret: u.totpPending, totpPending: "" }, "Merge");
    jsonRes(context, 200, { ok: true, enabled: true });
  } catch (e) {
    errRes(context, e);
  }
};
