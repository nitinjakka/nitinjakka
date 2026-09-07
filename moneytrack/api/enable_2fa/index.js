const { jsonRes, errRes } = require("../shared/plaid");
const { table, ensureTables, getEntity } = require("../shared/db");
const { requireAuth } = require("../shared/auth");
const { newSecret, otpauthURI } = require("../shared/totp");

// Step 1 of enabling 2FA: generate a pending secret; confirmed via confirm_2fa.
module.exports = async function (context, req) {
  try {
    await ensureTables();
    const user = await requireAuth(req);
    if (!user) return jsonRes(context, 401, { error: "Not logged in" });
    const u = await getEntity("users", "user", user.email);
    if (u.totpSecret) return jsonRes(context, 400, { error: "2FA is already enabled" });

    const secret = newSecret();
    await table("users").updateEntity(
      { partitionKey: "user", rowKey: user.email, totpPending: secret }, "Merge");
    jsonRes(context, 200, { secret, otpauth: otpauthURI(secret, user.email) });
  } catch (e) {
    errRes(context, e);
  }
};
