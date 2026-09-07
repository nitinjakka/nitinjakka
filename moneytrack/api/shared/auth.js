const crypto = require("crypto");
const { table, getEntity } = require("./db");

const SESSION_DAYS = 30;

function hashPassword(password, salt) {
  return crypto.scryptSync(password, salt, 64).toString("hex");
}

function newSalt() { return crypto.randomBytes(16).toString("hex"); }
function newToken() { return crypto.randomBytes(32).toString("hex"); }
function newUserId() { return "u_" + crypto.randomBytes(8).toString("hex"); }

function normEmail(e) { return String(e || "").trim().toLowerCase(); }

function validEmail(e) { return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e); }

async function createSession(user) {
  const token = newToken();
  const expires = new Date(Date.now() + SESSION_DAYS * 86400000).toISOString();
  await table("sessions").createEntity({
    partitionKey: "session", rowKey: token,
    email: user.rowKey, userId: user.userId, expires,
  });
  return token;
}

// Returns { userId, email } or null.
async function requireAuth(req) {
  const auth = req.headers && (req.headers.authorization || req.headers.Authorization);
  if (!auth || !auth.startsWith("Bearer ")) return null;
  const token = auth.slice(7);
  const sess = await getEntity("sessions", "session", token);
  if (!sess) return null;
  if (new Date(sess.expires) < new Date()) return null;
  return { userId: sess.userId, email: sess.email };
}

module.exports = { hashPassword, newSalt, newToken, newUserId, normEmail, validEmail, createSession, requireAuth };
