const { jsonRes, errRes } = require("../shared/plaid");
const { table, ensureTables, getEntity } = require("../shared/db");
const { requireAuth } = require("../shared/auth");
const { totpVerify } = require("../shared/totp");

// Disabling 2FA requires a valid current code.
module.exports = async function (context, req) {
  try {
    await ensureTables();
    const user = await requireAuth(req);
    if (!user) return jsonRes(context, 401, { error: "Not logged in" });
    const u = await getEntity("users", "user", user.email);
    if (!u.totpSecret) return jsonRes(context, 400, { error: "2FA is not enabled" });
    const code = req.body && req.body.code;
    if (!totpVerify(u.totpSecret, code)) return jsonRes(context, 400, { error: "Invalid code" });

    await table("users").updateEntity(
      { partitionKey: "user", rowKey: user.email, totpSecret: "", totpPending: "" }, "Merge");
    jsonRes(context, 200, { ok: true, enabled: false });
  } catch (e) {
    errRes(context, e);
  }
};
