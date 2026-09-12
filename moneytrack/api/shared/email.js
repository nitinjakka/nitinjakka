// Transactional email via Resend's REST API (no SDK). Best-effort: callers decide whether a
// failure is fatal. Without RESEND_API_KEY the app still works — verification/reset just can't send.
const APP_URL = (process.env.APP_URL || "https://moneytracknitin.z19.web.core.windows.net/").replace(/\/?$/, "/");

function configured() { return !!process.env.RESEND_API_KEY; }

async function sendEmail(to, subject, html) {
  if (!configured()) throw new Error("Email is not configured on the server (RESEND_API_KEY missing)");
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + process.env.RESEND_API_KEY },
    body: JSON.stringify({ from: process.env.EMAIL_FROM || "MoneyTrack <onboarding@resend.dev>", to: [to], subject, html }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.message || data.error || `Email send failed (${res.status})`);
  return data.id;
}

function layout(title, body) {
  return `<div style="font-family:Segoe UI,system-ui,sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#1a1d2e">
    <h2 style="margin:0 0 12px">💸 MoneyTrack</h2><h3 style="margin:0 0 16px">${title}</h3>${body}
    <p style="color:#6b7280;font-size:12px;margin-top:28px">If you didn't request this, you can ignore this email.</p></div>`;
}

function verificationEmail(token) {
  const url = `${APP_URL}?verify=${encodeURIComponent(token)}`;
  return {
    subject: "Verify your MoneyTrack email",
    html: layout("Confirm your email address",
      `<p>Click the button to verify this email for your MoneyTrack account. The link is valid for 24 hours.</p>
       <p><a href="${url}" style="display:inline-block;background:#6d28d9;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none">Verify email</a></p>
       <p style="font-size:12px;color:#6b7280">Or open: ${url}</p>`),
  };
}

function resetEmail(token) {
  const url = `${APP_URL}?reset=${encodeURIComponent(token)}`;
  return {
    subject: "Reset your MoneyTrack password",
    html: layout("Password reset",
      `<p>Someone (hopefully you) asked to reset the password for this MoneyTrack account. The link is valid for 1 hour.</p>
       <p><a href="${url}" style="display:inline-block;background:#6d28d9;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none">Choose a new password</a></p>
       <p style="font-size:12px;color:#6b7280">Or open: ${url}</p>`),
  };
}

module.exports = { configured, sendEmail, verificationEmail, resetEmail, APP_URL };
