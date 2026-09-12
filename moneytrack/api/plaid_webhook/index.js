const crypto = require("crypto");
const { plaidPost, jsonRes } = require("../shared/plaid");
const { table, ensureTables } = require("../shared/db");
const { syncItem, refreshAccounts, writeSnapshot, findItem } = require("../shared/sync");

// ---- Plaid webhook signature verification (JWT in Plaid-Verification header, ES256) ----
// https://plaid.com/docs/api/webhooks/webhook-verification/
const keyCache = {}; // key_id -> { jwk, fetchedAt }

function b64url(s) { return Buffer.from(String(s).replace(/-/g, "+").replace(/_/g, "/"), "base64"); }

async function verifyPlaidSignature(req) {
  const jwt = req.headers && (req.headers["plaid-verification"] || req.headers["Plaid-Verification"]);
  if (!jwt) return { ok: false, reason: "missing Plaid-Verification header" };
  const parts = jwt.split(".");
  if (parts.length !== 3) return { ok: false, reason: "malformed JWT" };
  let header, claims;
  try { header = JSON.parse(b64url(parts[0]).toString()); claims = JSON.parse(b64url(parts[1]).toString()); }
  catch (e) { return { ok: false, reason: "undecodable JWT" }; }
  if (header.alg !== "ES256" || !header.kid) return { ok: false, reason: "unexpected alg/kid" };

  let entry = keyCache[header.kid];
  if (!entry || Date.now() - entry.fetchedAt > 24 * 3600 * 1000) {
    const data = await plaidPost("/webhook_verification_key/get", { key_id: header.kid });
    entry = { jwk: data.key, fetchedAt: Date.now() };
    keyCache[header.kid] = entry;
  }
  if (entry.jwk.expired_at) return { ok: false, reason: "key expired" };

  const pub = crypto.createPublicKey({ key: entry.jwk, format: "jwk" });
  const ok = crypto.verify("sha256", Buffer.from(parts[0] + "." + parts[1]),
    { key: pub, dsaEncoding: "ieee-p1363" }, b64url(parts[2]));
  if (!ok) return { ok: false, reason: "bad signature" };
  if (!claims.iat || Math.abs(Date.now() / 1000 - claims.iat) > 5 * 60) return { ok: false, reason: "stale token" };

  const raw = typeof req.rawBody === "string" ? req.rawBody : JSON.stringify(req.body || {});
  const sha = crypto.createHash("sha256").update(raw).digest("hex");
  if (sha !== claims.request_body_sha256) return { ok: false, reason: "body hash mismatch" };
  return { ok: true };
}

// Plaid → us. Registered on every link token (see create_link_token). When Plaid finishes the
// initial / historical pull or has new transactions, we sync that item immediately, so the
// user never has to press "Sync". Always answers 200 for handled/ignored events so Plaid does
// not retry forever; a bad signature is rejected with 401.
module.exports = async function (context, req) {
  const body = req.body || {};
  const type = body.webhook_type || "";
  const code = body.webhook_code || "";
  const itemId = body.item_id || "";
  context.log(`plaid_webhook ${type}/${code} item=${itemId}`);
  try {
    await ensureTables();
    if (process.env.PLAID_WEBHOOK_VERIFY !== "off") {
      const v = await verifyPlaidSignature(req);
      if (!v.ok) { context.log.warn("plaid_webhook rejected: " + v.reason); return jsonRes(context, 401, { error: "invalid signature", reason: v.reason }); }
    }
    if (!itemId) return jsonRes(context, 200, { ok: true, ignored: "no item_id" });
    const item = await findItem(itemId);
    if (!item) return jsonRes(context, 200, { ok: true, ignored: "unknown item" });
    const userId = item.partitionKey;

    if (type === "TRANSACTIONS") {
      // SYNC_UPDATES_AVAILABLE / INITIAL_UPDATE / HISTORICAL_UPDATE / DEFAULT_UPDATE / TRANSACTIONS_REMOVED
      try { await refreshAccounts(userId, item); } catch (e) {}
      const r = await syncItem(userId, item);
      try { await writeSnapshot(userId); } catch (e) {}
      return jsonRes(context, 200, { ok: true, added: r.added, removed: r.removed });
    }
    if (type === "ITEM") {
      if (code === "ERROR" && body.error) {
        await table("items").updateEntity(
          { partitionKey: userId, rowKey: itemId, lastError: String(body.error.error_code || "ITEM_ERROR") }, "Merge");
      }
      if (code === "LOGIN_REPAIRED") {
        await table("items").updateEntity({ partitionKey: userId, rowKey: itemId, lastError: "" }, "Merge");
      }
      return jsonRes(context, 200, { ok: true });
    }
    jsonRes(context, 200, { ok: true, ignored: type });
  } catch (e) {
    context.log.error("plaid_webhook failed: " + e.message);
    jsonRes(context, 200, { ok: false, error: e.message });
  }
};
module.exports.verifyPlaidSignature = verifyPlaidSignature;
