const { jsonRes, errRes } = require("../shared/plaid");
const { table, ensureTables } = require("../shared/db");
const { requireAuth, normPhone } = require("../shared/auth");

// POST { phone } — sets (or clears with "") the phone number others can share data with you by.
module.exports = async function (context, req) {
  try {
    await ensureTables();
    const user = await requireAuth(req);
    if (!user) return jsonRes(context, 401, { error: "Not logged in" });
    const raw = req.body && req.body.phone;
    const phone = normPhone(raw);
    if (raw && !phone) return jsonRes(context, 400, { error: "Phone number looks invalid (use 10+ digits)" });
    await table("users").updateEntity({ partitionKey: "user", rowKey: user.email, phone: phone || "" }, "Merge");
    jsonRes(context, 200, { ok: true, phone: phone || "" });
  } catch (e) {
    errRes(context, e);
  }
};
