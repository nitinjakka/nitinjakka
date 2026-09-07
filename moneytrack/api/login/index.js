const crypto = require("crypto");
const { jsonRes, errRes } = require("../shared/plaid");
const { ensureTables, getEntity } = require("../shared/db");
const { hashPassword, normEmail, createSession } = require("../shared/auth");
const { totpVerify } = require("../shared/totp");

module.exports = async function (context, req) {
  try {
    await ensureTables();
    const email = normEmail(req.body && req.body.email);
    const password = (req.body && req.body.password) || "";
    const user = await getEntity("users", "user", email);
    const bad = () => jsonRes(context, 401, { error: "Invalid email or password" });
    if (!user) return bad();
    const hash = hashPassword(password, user.salt);
    const a = Buffer.from(hash), b = Buffer.from(user.passHash);
    if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return bad();
    if (user.totpSecret) {
      const code = req.body && req.body.code;
      if (!code) return jsonRes(context, 200, { requires_2fa: true });
      if (!totpVerify(user.totpSecret, code)) return jsonRes(context, 401, { error: "Invalid 2FA code" });
    }
    const token = await createSession(user);
    jsonRes(context, 200, { token, email, userId: user.userId });
  } catch (e) {
    errRes(context, e);
  }
};
