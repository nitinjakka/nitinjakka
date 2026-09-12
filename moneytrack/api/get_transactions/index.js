const { jsonRes, errRes } = require("../shared/plaid");
const { ensureTables, listEntities } = require("../shared/db");
const { requireAuth, canView } = require("../shared/auth");

// Returns the caller's bank transactions, or another user's if they invited the caller
// (by email or phone). User edits (userCategory/userName/userNotes) override Plaid values;
// hidden (user-deleted) transactions are excluded.
// POST { owner_id? }
module.exports = async function (context, req) {
  try {
    await ensureTables();
    const user = await requireAuth(req);
    if (!user) return jsonRes(context, 401, { error: "Not logged in" });

    let ownerId = user.userId;
    const requested = req.body && req.body.owner_id;
    if (requested && requested !== user.userId) {
      if (!(await canView(user, requested))) {
        return jsonRes(context, 403, { error: "You are not authorized to view this user's data" });
      }
      ownerId = requested;
    }

    const txns = (await listEntities("txns", `PartitionKey eq '${ownerId}'`)).filter(t => !t.hidden);
    txns.sort((a, b) => String(b.date).localeCompare(String(a.date)));
    jsonRes(context, 200, {
      owner_id: ownerId,
      transactions: txns.slice(0, 10000).map(t => ({
        id: t.rowKey,
        name: t.userName || t.name,
        originalName: t.name,
        amount: t.amount,
        type: t.type,
        category: t.userCategory || t.category,
        autoCategory: t.category,
        userSet: !!t.userCategory,
        notes: t.userNotes || "",
        date: t.date,
        pending: !!t.pending,
        accountId: t.accountId || "",
        itemId: t.itemId || "",
        source: "bank",
      })),
    });
  } catch (e) {
    errRes(context, e);
  }
};
