const { jsonRes, errRes } = require("../shared/plaid");
const { ensureTables, listEntities, getEntity } = require("../shared/db");
const { requireAuth, canView } = require("../shared/auth");
const { configured } = require("../shared/email");

// Profile + linked banks + every individual account (with balances) + net-worth snapshots + sharing info.
// POST { owner_id? } — with owner_id (someone who invited you) returns THEIR accounts/snapshots instead.
module.exports = async function (context, req) {
  try {
    await ensureTables();
    const user = await requireAuth(req);
    if (!user) return jsonRes(context, 401, { error: "Not logged in" });
    const u = await getEntity("users", "user", user.email);

    let ownerId = user.userId;
    const requested = req.body && req.body.owner_id;
    if (requested && requested !== user.userId) {
      if (!(await canView(user, requested))) return jsonRes(context, 403, { error: "Not authorized" });
      ownerId = requested;
    }

    // People I have invited to view my data
    const myInvites = await listEntities("invites", `PartitionKey eq '${user.userId}'`);
    // Data shared with me by others (matched by my email, or by the phone on my profile)
    let sharedWithMe = await listEntities("invites", `viewerEmail eq '${user.email}'`);
    if (u && u.phone) {
      const byPhone = await listEntities("invites", `viewerPhone eq '${u.phone}'`);
      sharedWithMe = sharedWithMe.concat(byPhone);
    }
    const seen = new Set();
    sharedWithMe = sharedWithMe.filter(i => {
      if (i.partitionKey === user.userId || seen.has(i.partitionKey)) return false;
      seen.add(i.partitionKey); return true;
    });

    const [items, accounts, snapshots] = await Promise.all([
      listEntities("items", `PartitionKey eq '${ownerId}'`),
      listEntities("accounts", `PartitionKey eq '${ownerId}'`),
      listEntities("snapshots", `PartitionKey eq '${ownerId}'`),
    ]);
    snapshots.sort((a, b) => String(a.rowKey).localeCompare(String(b.rowKey)));

    jsonRes(context, 200, {
      email: user.email,
      userId: user.userId,
      phone: (u && u.phone) || "",
      emailVerified: !!(u && u.emailVerified),
      emailConfigured: configured(),
      twoFA: !!(u && u.totpSecret),
      plaidEnv: process.env.PLAID_ENV || "sandbox",
      invited: myInvites.map(i => i.viewerEmail || i.viewerPhone || i.rowKey),
      sharedWithMe: sharedWithMe.map(i => ({ ownerId: i.partitionKey, ownerEmail: i.ownerEmail })),
      banks: items.map(i => ({
        itemId: i.rowKey,
        institution: i.institution || "Bank",
        lastSync: i.lastSync || "",
        syncStatus: i.syncStatus || "",
        error: i.lastError || "",
        createdAt: i.createdAt || "",
      })),
      accounts: accounts.map(a => ({
        accountId: a.rowKey,
        itemId: a.itemId,
        institution: a.institution || "Bank",
        name: a.name,
        officialName: a.officialName || "",
        mask: a.mask == null ? "" : String(a.mask),
        type: a.type || "other",
        subtype: a.subtype || "",
        current: typeof a.current === "number" ? a.current : 0,
        available: typeof a.available === "number" ? a.available : null,
        limit: typeof a.limit === "number" ? a.limit : null,
        updatedAt: a.updatedAt || "",
      })),
      snapshots: snapshots.slice(-400).map(s => ({
        date: s.rowKey, assets: s.assets || 0, debts: s.debts || 0, net: s.net || 0,
        checking: s.checking || 0, savings: s.savings || 0, credit: s.credit || 0,
        investment: s.investment || 0, loan: s.loan || 0,
      })),
    });
  } catch (e) {
    errRes(context, e);
  }
};
