const { jsonRes, errRes } = require("../shared/plaid");
const { table, ensureTables, getEntity, clean } = require("../shared/db");
const { requireAuth } = require("../shared/auth");

// Edit / hide bank transactions (owner only). Edits live in user* fields so a re-sync never
// overwrites them. POST { updates: [{ id, category?, name?, notes?, hidden?, resetCategory? }] }
// or a single { id, ... }.
module.exports = async function (context, req) {
  try {
    await ensureTables();
    const user = await requireAuth(req);
    if (!user) return jsonRes(context, 401, { error: "Not logged in" });

    const body = req.body || {};
    const updates = Array.isArray(body.updates) ? body.updates : (body.id ? [body] : []);
    if (!updates.length) return jsonRes(context, 400, { error: "Nothing to update" });
    if (updates.length > 500) return jsonRes(context, 400, { error: "Too many updates (max 500)" });

    let updated = 0;
    const missing = [];
    for (const u of updates) {
      if (!u || !u.id) continue;
      const existing = await getEntity("txns", user.userId, String(u.id));
      if (!existing) { missing.push(u.id); continue; }
      const patch = { partitionKey: user.userId, rowKey: String(u.id) };
      if (typeof u.category === "string" && u.category.trim()) patch.userCategory = u.category.trim().slice(0, 60);
      if (u.resetCategory) patch.userCategory = "";
      if (typeof u.name === "string") patch.userName = u.name.trim().slice(0, 200);
      if (typeof u.notes === "string") patch.userNotes = u.notes.trim().slice(0, 500);
      if (typeof u.hidden === "boolean") patch.hidden = u.hidden;
      await table("txns").updateEntity(clean(patch), "Merge");
      updated++;
    }
    jsonRes(context, 200, { ok: true, updated, missing });
  } catch (e) {
    errRes(context, e);
  }
};
