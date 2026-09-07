// Minimal Plaid REST helper — no SDK needed, Node 18+ global fetch.
const PLAID_HOSTS = {
  sandbox: "https://sandbox.plaid.com",
  production: "https://production.plaid.com",
};

async function plaidPost(path, body) {
  const env = process.env.PLAID_ENV || "sandbox";
  const res = await fetch(PLAID_HOSTS[env] + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: process.env.PLAID_CLIENT_ID,
      secret: process.env.PLAID_SECRET,
      ...body,
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    const err = new Error(data.error_message || "Plaid error");
    err.plaid = data;
    err.status = res.status;
    throw err;
  }
  return data;
}

function jsonRes(context, status, body) {
  context.res = {
    status,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

function errRes(context, e) {
  jsonRes(context, e.status || 500, {
    error: e.message,
    plaid: e.plaid || null,
  });
}

module.exports = { plaidPost, jsonRes, errRes };
