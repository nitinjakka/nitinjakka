const { jsonRes, errRes } = require("../shared/plaid");
const { table, ensureTables, getEntity } = require("../shared/db");
const { hashPassword, newSalt, newUserId, normEmail, validEmail, createSession } = require("../shared/auth");

module.exports = async function (context, req) {
  try {
    await ensureTables();
    const email = normEmail(req.body && req.body.email);
    const password = (req.body && req.body.password) || "";
    if (!validEmail(email)) return jsonRes(context, 400, { error: "Valid email required" });
    if (password.length < 8) return jsonRes(context, 400, { error: "Password must be at least 8 characters" });

    const existing = await getEntity("users", "user", email);
    if (existing) return jsonRes(context, 409, { error: "An account with this email already exists" });

    const salt = newSalt();
    const user = {
      partitionKey: "user", rowKey: email,
      userId: newUserId(),
      salt,
      passHash: hashPassword(password, salt),
      createdAt: new Date().toISOString(),
    };
    await table("users").createEntity(user);
    const token = await createSession(user);
    jsonRes(context, 200, { token, email, userId: user.userId });
  } catch (e) {
    errRes(context, e);
  }
};
