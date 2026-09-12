const { jsonRes, errRes } = require("../shared/plaid");
const { table, ensureTables, getEntity } = require("../shared/db");
const { normEmail, newToken } = require("../shared/auth");
const { configured, sendEmail, resetEmail } = require("../shared/email");

// POST { email } — always answers ok (never reveals whether the email exists).
module.exports = async function (context, req) {
  try {
    await ensureTables();
    const email = normEmail(req.body && req.body.email);
    if (!email) return jsonRes(context, 400, { error: "Email required" });
    if (!configured()) return jsonRes(context, 503, { error: "Email sending is not configured on the server" });
    const user = await getEntity("users", "user", email);
    if (user) {
      const token = newToken();
      await table("tokens").upsertEntity({
        partitionKey: "reset", rowKey: token, email,
        expires: new Date(Date.now() + 3600 * 1000).toISOString(),
      }, "Replace");
      const m = resetEmail(token);
      try { await sendEmail(email, m.subject, m.html); }
      catch (e) { context.log("reset email failed: " + e.message); return jsonRes(context, 502, { error: "Could not send the email: " + e.message }); }
    }
    jsonRes(context, 200, { ok: true, message: "If that email has an account, a reset link is on its way." });
  } catch (e) {
    errRes(context, e);
  }
};
