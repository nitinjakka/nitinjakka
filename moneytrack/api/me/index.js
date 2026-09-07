const { jsonRes, errRes } = require("../shared/plaid");
const { ensureTables, listEntities, getEntity } = require("../shared/db");
const { requireAuth } = require("../shared/auth");

module.exports = async function (context, req) {
  try {
    await ensureTables();
    const user = await requireAuth(req);
    if (!user) return jsonRes(context, 401, { error: "Not logged in" });

    // People I have invited to view my data
    const myInvites = await listEntities("invites", `PartitionKey eq '${user.userId}'`);
    // Data shared with me by others
    const sharedWithMe = await listEntities("invites", `viewerEmail eq '${user.email}'`);
    // My linked bank items
    const items = await listEntities("items", `PartitionKey eq '${user.userId}'`);
    const u = await getEntity("users", "user", user.email);

    jsonRes(context, 200, {
      email: user.email,
      userId: user.userId,
      twoFA: !!(u && u.totpSecret),
      plaidEnv: process.env.PLAID_ENV || "sandbox",
      invited: myInvites.map(i => i.viewerEmail),
      sharedWithMe: sharedWithMe
        .filter(i => i.partitionKey !== user.userId)
        .map(i => ({ ownerId: i.partitionKey, ownerEmail: i.ownerEmail })),
      banks: items.map(i => ({ itemId: i.rowKey, institution: i.institution || "Bank" })),
    });
  } catch (e) {
    errRes(context, e);
  }
};
