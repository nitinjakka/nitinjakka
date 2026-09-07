const { plaidPost, jsonRes, errRes } = require("../shared/plaid");
const { ensureTables } = require("../shared/db");
const { requireAuth } = require("../shared/auth");

module.exports = async function (context, req) {
  try {
    await ensureTables();
    const user = await requireAuth(req);
    if (!user) return jsonRes(context, 401, { error: "Not logged in" });
    const body = {
      user: { client_user_id: user.userId },
      client_name: "MoneyTrack",
      products: ["transactions"],
      country_codes: ["US"],
      language: "en",
    };
    // Production OAuth banks (Chase, BofA, …) require a redirect URI registered in the Plaid dashboard.
    if (process.env.PLAID_REDIRECT_URI) body.redirect_uri = process.env.PLAID_REDIRECT_URI;
    const data = await plaidPost("/link/token/create", body);
    jsonRes(context, 200, { link_token: data.link_token });
  } catch (e) {
    errRes(context, e);
  }
};
