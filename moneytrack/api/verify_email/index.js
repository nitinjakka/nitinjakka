const { jsonRes, errRes } = require("../shared/plaid");
const { table, ensureTables, getEntity, deleteEntity } = require("../shared/db");

// POST { token } — from the link in the verification email. No login required.
module.exports = async function (context, req) {
  try {
    await ensureTables();
    const token = String((req.body && req.body.token) || "").trim();
    if (!token) return jsonRes(context, 400, { error: "token required" });
    const t = await getEntity("tokens", "verify", token);
    if (!t) return jsonRes(context, 400, { error: "This verification link is invalid or was already used" });
    if (new Date(t.expires) < new Date()) { await deleteEntity("tokens", "verify", token); return jsonRes(context, 400, { error: "This verification link has expired — request a new one from Settings" }); }
    await table("users").updateEntity({ partitionKey: "user", rowKey: t.email, emailVerified: true, emailVerifiedAt: new Date().toISOString() }, "Merge");
    await deleteEntity("tokens", "verify", token);
    jsonRes(context, 200, { ok: true, email: t.email });
  } catch (e) {
    errRes(context, e);
  }
};
