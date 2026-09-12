const { jsonRes, errRes } = require("../shared/plaid");
const { table, ensureTables, getEntity, clean } = require("../shared/db");
const { hashPassword, newSalt, newUserId, normEmail, validEmail, normPhone, createSession } = require("../shared/auth");

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
      createdAt: new Date().toISOString(),
    });
    await table("users").createEntity(user);
    const token = await createSession(user);
    jsonRes(context, 200, { token, email, userId: user.userId });
  } catch (e) {
    errRes(context, e);
  }
};
