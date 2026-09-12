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

// Phone → "+<digits>" (US 10-digit numbers get +1). Returns "" if not a phone.
function normPhone(p) {
  let d = String(p || "").replace(/[^\d]/g, "");
  if (d.length === 10) d = "1" + d;
  if (d.length < 10 || d.length > 15) return "";
  return "+" + d;
}

// Accepts an email or a phone; returns { kind: "email"|"phone", value } or null.
function normContact(c) {
  const raw = String(c || "").trim();
  if (raw.includes("@")) { const e = normEmail(raw); return validEmail(e) ? { kind: "email", value: e } : null; }
  const p = normPhone(raw);
  return p ? { kind: "phone", value: p } : null;
}

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

// True if `ownerId` has invited this user (by email or by the phone on their profile).
async function canView(user, ownerId) {
  if (ownerId === user.userId) return true;
  if (await getEntity("invites", ownerId, user.email)) return true;
  const u = await getEntity("users", "user", user.email);
  if (u && u.phone && await getEntity("invites", ownerId, u.phone)) return true;
  return false;
}

module.exports = {
  hashPassword, newSalt, newToken, newUserId, normEmail, validEmail, normPhone, normContact,
  createSession, requireAuth, canView,
};
