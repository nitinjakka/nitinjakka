// Azure Table Storage access. Uses the function app's own storage connection string.
const { TableClient } = require("@azure/data-tables");

const CONN = process.env.AzureWebJobsStorage;
const clients = {};

function table(name) {
  if (!clients[name]) {
    clients[name] = TableClient.fromConnectionString(CONN, name);
  }
  return clients[name];
}

let ensured = false;
async function ensureTables() {
  if (ensured) return;
  for (const name of ["users", "sessions", "items", "txns", "invites", "accounts", "tokens", "snapshots"]) {
    try { await table(name).createTable(); } catch (e) { /* already exists */ }
  }
  ensured = true;
}

async function getEntity(tableName, pk, rk) {
  try {
    return await table(tableName).getEntity(pk, rk);
  } catch (e) {
    if (e.statusCode === 404) return null;
    throw e;
  }
}

async function listEntities(tableName, filter) {
  const out = [];
  const iter = table(tableName).listEntities(filter ? { queryOptions: { filter } } : undefined);
  for await (const ent of iter) out.push(ent);
  return out;
}

// One page of entities. Returns { items, continuation } — pass continuation back for the next page.
async function listPage(tableName, filter, pageSize, continuation) {
  const iter = table(tableName)
    .listEntities(filter ? { queryOptions: { filter } } : undefined)
    .byPage({ maxPageSize: pageSize, continuationToken: continuation || undefined });
  const page = await iter.next();
  const items = page.value ? Array.from(page.value) : [];
  return { items, continuation: (page.value && page.value.continuationToken) || null };
}

async function deleteEntity(tableName, pk, rk) {
  try { await table(tableName).deleteEntity(pk, rk); return true; } catch (e) { return false; }
}

// Table Storage rejects null property values — drop them.
function clean(obj) {
  const out = {};
  for (const [k, v] of Object.entries(obj)) if (v !== null && v !== undefined) out[k] = v;
  return out;
}

module.exports = { table, ensureTables, getEntity, listEntities, listPage, deleteEntity, clean };
