const { jsonRes, errRes } = require("../shared/plaid");
const { ensureTables } = require("../shared/db");
const { requireAuth } = require("../shared/auth");
const { syncUser } = require("../shared/sync");

module.exports = async function (context, req) {
  try {
    await ensureTables();
    const user = await requireAuth(req);
    if (!user) return jsonRes(context, 401, { error: "Not logged in" });
    const result = await syncUser(user.userId);
    jsonRes(context, 200, result);
  } catch (e) {
    errRes(context, e);
  }
};
