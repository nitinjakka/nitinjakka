const { jsonRes, errRes } = require("../shared/plaid");
const { ensureTables, listEntities, getEntity } = require("../shared/db");
const { requireAuth } = require("../shared/auth");

// Returns the caller's bank transactions, or another user's if they invited the caller.
// POST { owner_id? }
module.exports = async function (context, req) {
  try {
    await ensureTables();
    const user = await requireAuth(req);
    if (!user) return jsonRes(context, 401, { error: "Not logged in" });

    let ownerId = user.userId;
    const requested = req.body && req.body.owner_id;
    if (requested && requested !== user.userId) {
      const invite = await getEntity("invites", requested, user.email);
      if (!invite) return jsonRes(context, 403, { error: "You are not authorized to view this user's data" });
      ownerId = requested;
    }

    const txns = await listEntities("txns", `PartitionKey eq '${ownerId}'`);
    txns.sort((a, b) => String(b.date).localeCompare(String(a.date)));
    jsonRes(context, 200, {
      owner_id: ownerId,
      transactions: txns.slice(0, 2000).map(t => ({
        id: t.rowKey, name: t.name, amount: t.amount, type: t.type,
        category: t.category, date: t.date, pending: t.pending, source: "bank",
      })),
    });
  } catch (e) {
    errRes(context, e);
  }
};
