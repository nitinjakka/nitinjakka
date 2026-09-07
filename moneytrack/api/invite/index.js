const { jsonRes, errRes } = require("../shared/plaid");
const { table, ensureTables } = require("../shared/db");
const { requireAuth, normEmail, validEmail } = require("../shared/auth");

// POST { email } to invite; POST { email, revoke: true } to revoke.
module.exports = async function (context, req) {
  try {
    await ensureTables();
    const user = await requireAuth(req);
    if (!user) return jsonRes(context, 401, { error: "Not logged in" });

    const viewerEmail = normEmail(req.body && req.body.email);
    if (!validEmail(viewerEmail)) return jsonRes(context, 400, { error: "Valid email required" });
    if (viewerEmail === user.email) return jsonRes(context, 400, { error: "You already see your own data" });

    if (req.body && req.body.revoke) {
      try { await table("invites").deleteEntity(user.userId, viewerEmail); } catch (e) {}
      return jsonRes(context, 200, { ok: true, revoked: viewerEmail });
    }

    await table("invites").upsertEntity({
      partitionKey: user.userId,
      rowKey: viewerEmail,
      viewerEmail,
      ownerEmail: user.email,
      createdAt: new Date().toISOString(),
    }, "Replace");
    jsonRes(context, 200, { ok: true, invited: viewerEmail });
  } catch (e) {
    errRes(context, e);
  }
};
