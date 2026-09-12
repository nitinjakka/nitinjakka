const { jsonRes, errRes } = require("../shared/plaid");
const { table, ensureTables, getEntity, clean } = require("../shared/db");
const { hashPassword, newSalt, newUserId, newToken, normEmail, validEmail, normPhone, createSession } = require("../shared/auth");
const { configured, sendEmail, verificationEmail } = require("../shared/email");

module.exports = async function (context, req) {
  try {
    await ensureTables();
    const email = normEmail(req.body && req.body.email);
    const password = (req.body && req.body.password) || "";
    const phone = normPhone(req.body && req.body.phone); // optional — lets others share with you by phone
    if (!validEmail(email)) return jsonRes(context, 400, { error: "Valid email required" });
    if (password.length < 8) return jsonRes(context, 400, { error: "Password must be at least 8 characters" });
    if (req.body && req.body.phone && !phone) return jsonRes(context, 400, { error: "Phone number looks invalid" });

    const existing = await getEntity("users", "user", email);
    if (existing) return jsonRes(context, 409, { error: "An account with this email already exists" });

    const salt = newSalt();
    const user = clean({
      partitionKey: "user", rowKey: email,
      userId: newUserId(),
      salt,
      passHash: hashPassword(password, salt),
      phone: phone || undefined,
      emailVerified: false,
      createdAt: new Date().toISOString(),
    });
    await table("users").createEntity(user);

    // Verification email — best effort; the account works either way (soft verification).
    let verificationSent = false;
    if (configured()) {
      try {
        const token = newToken();
        await table("tokens").upsertEntity({
          partitionKey: "verify", rowKey: token, email,
          expires: new Date(Date.now() + 24 * 3600 * 1000).toISOString(),
        }, "Replace");
        const m = verificationEmail(token);
        await sendEmail(email, m.subject, m.html);
        verificationSent = true;
      } catch (e) { context.log("verification email failed: " + e.message); }
    }

    const token = await createSession(user);
    jsonRes(context, 200, { token, email, userId: user.userId, verificationSent });
  } catch (e) {
    errRes(context, e);
  }
};
