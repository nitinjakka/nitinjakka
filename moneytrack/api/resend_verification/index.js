const { jsonRes, errRes } = require("../shared/plaid");
const { table, ensureTables, getEntity } = require("../shared/db");
const { requireAuth, newToken } = require("../shared/auth");
const { configured, sendEmail, verificationEmail } = require("../shared/email");

// Logged-in user asks for a fresh verification email.
module.exports = async function (context, req) {
  try {
    await ensureTables();
    const user = await requireAuth(req);
    if (!user) return jsonRes(context, 401, { error: "Not logged in" });
    if (!configured()) return jsonRes(context, 503, { error: "Email sending is not configured on the server" });
    const u = await getEntity("users", "user", user.email);
    if (u && u.emailVerified) return jsonRes(context, 200, { ok: true, alreadyVerified: true });
    const token = newToken();
    await table("tokens").upsertEntity({
      partitionKey: "verify", rowKey: token, email: user.email,
      expires: new Date(Date.now() + 24 * 3600 * 1000).toISOString(),
    }, "Replace");
    const m = verificationEmail(token);
    await sendEmail(user.email, m.subject, m.html);
    jsonRes(context, 200, { ok: true, sent: true });
  } catch (e) {
    errRes(context, e);
  }
};
