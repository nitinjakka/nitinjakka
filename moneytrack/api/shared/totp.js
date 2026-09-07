// TOTP (RFC 6238) two-factor auth — pure Node crypto, works with Google Authenticator / Authy.
const crypto = require("crypto");

const B32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

function base32Encode(buf) {
  let bits = 0, value = 0, out = "";
  for (const byte of buf) {
    value = (value << 8) | byte;
    bits += 8;
    while (bits >= 5) {
      out += B32_ALPHABET[(value >>> (bits - 5)) & 31];
      bits -= 5;
    }
  }
  if (bits > 0) out += B32_ALPHABET[(value << (5 - bits)) & 31];
  return out;
}

function base32Decode(str) {
  const clean = str.toUpperCase().replace(/[^A-Z2-7]/g, "");
  let bits = 0, value = 0;
  const out = [];
  for (const ch of clean) {
    value = (value << 5) | B32_ALPHABET.indexOf(ch);
    bits += 5;
    if (bits >= 8) {
      out.push((value >>> (bits - 8)) & 255);
      bits -= 8;
    }
  }
  return Buffer.from(out);
}

function newSecret() {
  return base32Encode(crypto.randomBytes(20));
}

function hotp(secretB32, counter) {
  const key = base32Decode(secretB32);
  const msg = Buffer.alloc(8);
  msg.writeBigUInt64BE(BigInt(counter));
  const h = crypto.createHmac("sha1", key).update(msg).digest();
  const offset = h[h.length - 1] & 0x0f;
  const code = ((h[offset] & 0x7f) << 24) | (h[offset + 1] << 16) | (h[offset + 2] << 8) | h[offset + 3];
  return String(code % 1000000).padStart(6, "0");
}

function totpCode(secretB32, atMs = Date.now()) {
  return hotp(secretB32, Math.floor(atMs / 1000 / 30));
}

// Accepts the current 30s step ±1 step of clock drift.
function totpVerify(secretB32, code, window = 1) {
  const counter = Math.floor(Date.now() / 1000 / 30);
  const want = String(code || "").trim();
  for (let w = -window; w <= window; w++) {
    if (hotp(secretB32, counter + w) === want) return true;
  }
  return false;
}

function otpauthURI(secretB32, email) {
  return `otpauth://totp/MoneyTrack:${encodeURIComponent(email)}?secret=${secretB32}&issuer=MoneyTrack&algorithm=SHA1&digits=6&period=30`;
}

module.exports = { newSecret, totpCode, totpVerify, otpauthURI };
