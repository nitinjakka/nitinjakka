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

async function ensureTables() {
  for (const name of ["users", "sessions", "items", "txns", "invites"]) {
    try { await table(name).createTable(); } catch (e) { /* already exists */ }
  }
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

module.exports = { table, ensureTables, getEntity, listEntities };
