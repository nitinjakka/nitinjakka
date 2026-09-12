const { plaidPost, jsonRes, errRes } = require("../shared/plaid");
const { ensureTables } = require("../shared/db");
const { requireAuth } = require("../shared/auth");

// Creates a Plaid Link token. Asks for the maximum transaction history Plaid allows (730 days)
// and registers our webhook so new transactions are pulled without the user pressing Sync.
module.exports = async function (context, req) {
  try {
    await ensureTables();
    const user = await requireAuth(req);
    if (!user) return jsonRes(context, 401, { error: "Not logged in" });
    const body = {
      user: { client_user_id: user.userId },
      client_name: "MoneyTrack",
      products: ["transactions"],
      transactions: { days_requested: 730 },
      country_codes: ["US"],
      language: "en",
    };
    // Production OAuth banks (Chase, BofA, …) require a redirect URI registered in the Plaid dashboard.
    if (process.env.PLAID_REDIRECT_URI) body.redirect_uri = process.env.PLAID_REDIRECT_URI;
    const webhook = process.env.PLAID_WEBHOOK_URL
      || (req.headers && req.headers.host ? `https://${req.headers.host}/api/plaid_webhook` : "");
    if (webhook) body.webhook = webhook;
    const data = await plaidPost("/link/token/create", body);
    jsonRes(context, 200, { link_token: data.link_token });
  } catch (e) {
    errRes(context, e);
  }
};
