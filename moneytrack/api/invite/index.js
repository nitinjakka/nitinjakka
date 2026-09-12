const { jsonRes, errRes } = require("../shared/plaid");
const { table, ensureTables } = require("../shared/db");
const { requireAuth, normContact } = require("../shared/auth");

// POST { contact } (email OR phone number) to invite; POST { contact, revoke: true } to revoke.
// `email` is still accepted as an alias of `contact`.
module.exports = async function (context, req) {
  try {
    await ensureTables();
    const user = await requireAuth(req);
    if (!user) return jsonRes(context, 401, { error: "Not logged in" });

    const raw = (req.body && (req.body.contact || req.body.email)) || "";
    const c = normContact(raw);
    if (!c) return jsonRes(context, 400, { error: "Enter a valid email address or phone number" });
    if (c.kind === "email" && c.value === user.email) return jsonRes(context, 400, { error: "You already see your own data" });

    if (req.body && req.body.revoke) {
      try { await table("invites").deleteEntity(user.userId, c.value); } catch (e) {}
      return jsonRes(context, 200, { ok: true, revoked: c.value });
    }

    const ent = {
      partitionKey: user.userId,
      rowKey: c.value,
      ownerEmail: user.email,
      createdAt: new Date().toISOString(),
    };
    if (c.kind === "email") ent.viewerEmail = c.value; else ent.viewerPhone = c.value;
    await table("invites").upsertEntity(ent, "Replace");
    jsonRes(context, 200, { ok: true, invited: c.value, kind: c.kind });
  } catch (e) {
    errRes(context, e);
  }
};
