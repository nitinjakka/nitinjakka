const { jsonRes, errRes } = require("../shared/plaid");
const { table, ensureTables, getEntity, deleteEntity, listEntities } = require("../shared/db");
const { hashPassword, newSalt } = require("../shared/auth");

// POST { token, password } — sets a new password, invalidates all existing sessions for that user.
module.exports = async function (context, req) {
  try {
    await ensureTables();
    const token = String((req.body && req.body.token) || "").trim();
    const password = (req.body && req.body.password) || "";
    if (!token) return jsonRes(context, 400, { error: "token required" });
    if (password.length < 8) return jsonRes(context, 400, { error: "Password must be at least 8 characters" });
    const t = await getEntity("tokens", "reset", token);
    if (!t) return jsonRes(context, 400, { error: "This reset link is invalid or was already used" });
    if (new Date(t.expires) < new Date()) { await deleteEntity("tokens", "reset", token); return jsonRes(context, 400, { error: "This reset link has expired — request a new one" }); }

    const salt = newSalt();
    await table("users").updateEntity({
      partitionKey: "user", rowKey: t.email, salt, passHash: hashPassword(password, salt),
      emailVerified: true, // they proved control of the mailbox
      passwordChangedAt: new Date().toISOString(),
    }, "Merge");
    await deleteEntity("tokens", "reset", token);
    // log out everywhere
    for (const s of await listEntities("sessions", `PartitionKey eq 'session' and email eq '${t.email}'`)) {
      await deleteEntity("sessions", "session", s.rowKey);
    }
    jsonRes(context, 200, { ok: true, email: t.email });
  } catch (e) {
    errRes(context, e);
  }
};
