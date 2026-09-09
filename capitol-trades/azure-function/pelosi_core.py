"""Core logic for the Azure-hosted Nancy Pelosi trade-disclosure monitor.

Flow per run:
  1. Fetch the official House Clerk disclosure index 3 separate times
     (triple verification) and require all fetches to agree.
  2. Diff against seen-filings state stored in Azure Blob Storage.
  3. For each new Pelosi PTR filing: download the PDF, extract every trade.
  4. Email a summary via the Resend API.
  5. Only after the email succeeds, record the filings as seen.
"""
import io
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timezone

FILER_LAST = "pelosi"
FILER_FIRST = "nancy"
INDEX_URL = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
PDF_URL = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc_id}.pdf"
VERIFY_ROUNDS = 3

STATE_CONTAINER = "pelosi-monitor"
STATE_BLOB = "seen_filings.json"

log = logging.getLogger("pelosi_monitor")


# ---------------------------------------------------------------- index fetch

def _http_get(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_index(year):
    data = _http_get(INDEX_URL.format(year=year))
    zf = zipfile.ZipFile(io.BytesIO(data))
    xml_name = next(n for n in zf.namelist() if n.endswith(".xml"))
    root = ET.fromstring(zf.read(xml_name))
    filings = []
    for m in root.findall("Member"):
        def g(tag):
            return (m.findtext(tag) or "").strip()
        if g("Last").lower() != FILER_LAST:
            continue
        if FILER_FIRST not in g("First").lower():
            continue
        if g("FilingType") != "P":  # P = Periodic Transaction Report
            continue
        filings.append({
            "doc_id": g("DocID"),
            "name": f'{g("First")} {g("Last")}',
            "state_district": g("StateDst"),
            "filing_date": g("FilingDate"),
            "year": year,
            "pdf_url": PDF_URL.format(year=year, doc_id=g("DocID")),
        })
    return filings


def years_to_scan():
    today = date.today()
    return [today.year - 1, today.year] if today.month == 1 else [today.year]


def gather():
    filings = []
    for year in years_to_scan():
        try:
            filings.extend(fetch_index(year))
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
    return sorted(filings, key=lambda f: (f["year"], f["doc_id"]))


def verified_gather(rounds=VERIFY_ROUNDS, delay=45):
    """Fetch the index `rounds` separate times; all must agree."""
    fetches = []
    for i in range(rounds):
        if i:
            time.sleep(delay)
        fetches.append(gather())
        log.info("verification fetch %d/%d: %d Pelosi PTR filings",
                 i + 1, rounds, len(fetches[-1]))
    id_sets = [{f["doc_id"] for f in run} for run in fetches]
    consistent = all(s == id_sets[0] for s in id_sets)
    return consistent, fetches[-1]


# --------------------------------------------------------------------- state

def _blob_client():
    from azure.storage.blob import BlobServiceClient
    conn = os.environ["AzureWebJobsStorage"]
    svc = BlobServiceClient.from_connection_string(conn)
    try:
        svc.create_container(STATE_CONTAINER)
    except Exception:
        pass  # already exists
    return svc.get_blob_client(STATE_CONTAINER, STATE_BLOB)


def load_state():
    try:
        return json.loads(_blob_client().download_blob().readall())
    except Exception:
        return {"seen_doc_ids": []}


def save_state(state):
    _blob_client().upload_blob(json.dumps(state, indent=2), overwrite=True)


# --------------------------------------------------------------- PDF parsing

# Transaction start line, e.g.
#   "SP Bloom Energy Corporation Class A P 07/24/2026 07/24/2026 $1,000,001 -"
# The asset name and upper amount bound wrap onto the following line(s).
TXN_START_RE = re.compile(
    r"^(?P<owner>SP|JT|DC|SE)\s+(?P<asset>.+?)\s+"
    r"(?P<ttype>S \(partial\)|P|S|E)\s+"
    r"(?P<txn_date>\d{2}/\d{2}/\d{4})\s+(?P<notif_date>\d{2}/\d{2}/\d{4})\s+"
    r"\$(?P<amt_lo>[\d,]+(?:\.\d{2})?)\s*(?:(?P<dash>-)\s*(?:\$(?P<amt_hi>[\d,]+))?)?$"
)
# "F S: New" (garbled "Filing Status:") / "D: description" / repeated headers
FS_LINE_RE = re.compile(r"^F\s*S\s*:")
DESC_LINE_RE = re.compile(r"^D\s*:\s*(.*)$")
# Table headers repeat at page breaks mid-entry: skip them, don't end the entry.
TABLE_HEADER_RE = re.compile(r"^(ID Owner Asset|Type Date Gains|\$200\?$|"
                             r"Filing ID #|P T R$|Clerk of the House|"
                             r"Name: |Status: |State/District: )")
FOOTER_RE = re.compile(r"^(\* For the complete list|I CERTIFY|Digitally Signed|"
                       r"I P O$|Yes No$|C S$)")
TTYPE_LABEL = {"P": "BUY", "S": "SELL", "S (partial)": "SELL (partial)", "E": "EXCHANGE"}


def extract_pdf_text(pdf_bytes):
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def parse_trades(text):
    """Parse the transaction table of an e-filed House PTR (line-based)."""
    lines = [ln.strip() for ln in text.replace("\x00", "").splitlines()]
    trades = []
    i = 0
    while i < len(lines):
        m = TXN_START_RE.match(lines[i])
        if not m:
            i += 1
            continue
        asset_parts = [m.group("asset")]
        amt_hi = m.group("amt_hi")
        desc_parts = []
        i += 1
        # Continuation lines: rest of asset name and/or the upper amount bound,
        # until the status/description lines or the next transaction.
        while i < len(lines):
            ln = lines[i]
            if TABLE_HEADER_RE.match(ln):
                i += 1
                continue
            if (TXN_START_RE.match(ln) or FS_LINE_RE.match(ln)
                    or DESC_LINE_RE.match(ln) or FOOTER_RE.match(ln)):
                break
            amt_m = re.search(r"\$([\d,]+)\s*$", ln)
            if amt_m and amt_hi is None and m.group("dash"):
                amt_hi = amt_m.group(1)
                ln = ln[:amt_m.start()].strip()
            if ln:
                asset_parts.append(ln)
            i += 1
        # Optional "F S: ..." then "D: ..." description (may wrap).
        while i < len(lines) and (FS_LINE_RE.match(lines[i])
                                  or TABLE_HEADER_RE.match(lines[i])):
            i += 1
        dm = DESC_LINE_RE.match(lines[i]) if i < len(lines) else None
        if dm:
            desc_parts.append(dm.group(1))
            i += 1
            while i < len(lines):
                if TABLE_HEADER_RE.match(lines[i]):
                    i += 1
                    continue
                if (TXN_START_RE.match(lines[i]) or FOOTER_RE.match(lines[i])
                        or FS_LINE_RE.match(lines[i])
                        or DESC_LINE_RE.match(lines[i])):
                    break
                desc_parts.append(lines[i])
                i += 1
        asset = re.sub(r"\s+", " ", " ".join(asset_parts)).strip()
        ticker_m = re.search(r"\(([A-Z][A-Z.\-]{0,7})\)", asset)
        kind = ("option" if "[OP]" in asset else
                "stock" if "[ST]" in asset else "other")
        if amt_hi:
            amount = f'${m.group("amt_lo")} - ${amt_hi}'
        elif m.group("dash"):
            amount = f'${m.group("amt_lo")}+'
        else:
            amount = f'${m.group("amt_lo")} (exact)'
        trades.append({
            "owner": m.group("owner"),
            "asset": re.sub(r"\s*\[[A-Z]{2}\]\s*", " ", asset).strip(),
            "ticker": ticker_m.group(1) if ticker_m else "",
            "kind": kind,
            "action": TTYPE_LABEL.get(m.group("ttype"), m.group("ttype")),
            "date": m.group("txn_date"),
            "amount": amount,
            "description": re.sub(r"\s+", " ", " ".join(desc_parts)).strip(),
        })
    return trades


# --------------------------------------------------------------------- email

def send_email(subject, text, html):
    import requests
    api_key = os.environ["RESEND_API_KEY"]
    payload = {
        "from": os.environ.get("EMAIL_FROM", "Pelosi Monitor <onboarding@resend.dev>"),
        "to": [os.environ["EMAIL_TO"]],
        "subject": subject,
        "text": text,
        "html": html,
    }
    r = requests.post("https://api.resend.com/emails",
                      headers={"Authorization": f"Bearer {api_key}"},
                      json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


def build_email(new_filings):
    dates = ", ".join(f["filing_date"] for f in new_filings)
    subject = f"New Nancy Pelosi trade disclosure — filed {dates}"
    text_parts, html_parts = [], []
    html_parts.append("<h2>🚨 New Nancy Pelosi trade disclosure</h2>")
    for f in new_filings:
        head = (f'Filing of {f["filing_date"]} by {f["name"]} '
                f'({f["state_district"]}), DocID {f["doc_id"]}')
        text_parts.append(head)
        html_parts.append(f"<h3>{head}</h3>")
        trades = f.get("trades") or []
        if trades:
            html_parts.append(
                '<table border="1" cellpadding="6" cellspacing="0" '
                'style="border-collapse:collapse">'
                '<tr style="background:#f0f0f0"><th>Owner</th><th>Asset</th>'
                "<th>Action</th><th>Trade date</th><th>Amount</th><th>Details</th></tr>")
            for t in trades:
                line = (f'  {t["owner"]}  {t["asset"]}  {t["action"]}  '
                        f'{t["date"]}  {t["amount"]}  {t["description"]}')
                text_parts.append(line)
                html_parts.append(
                    f'<tr><td>{t["owner"]}</td><td>{t["asset"]}</td>'
                    f'<td><b>{t["action"]}</b></td><td>{t["date"]}</td>'
                    f'<td>{t["amount"]}</td><td>{t["description"]}</td></tr>')
            html_parts.append("</table>")
        else:
            note = ("  (Could not auto-parse individual trades — "
                    "see the official PDF below.)")
            text_parts.append(note)
            html_parts.append(f"<p><i>{note}</i></p>")
        text_parts.append(f'Official PDF: {f["pdf_url"]}\n')
        html_parts.append(f'<p><a href="{f["pdf_url"]}">Official filing PDF</a></p>')
    footer = ("Data verified across 3 separate fetches of "
              "disclosures-clerk.house.gov before this email was sent. "
              "Sent by your Azure-hosted Pelosi trade monitor.")
    text_parts.append(footer)
    html_parts.append(f'<p style="color:#666;font-size:0.9em">{footer}</p>')
    return subject, "\n".join(text_parts), "".join(html_parts)


# ----------------------------------------------------------------- main run

def run_monitor(delay=45, send=True):
    """One full monitor cycle. Returns a JSON-serializable summary."""
    consistent, filings = verified_gather(delay=delay)
    summary = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "verification_rounds": VERIFY_ROUNDS,
        "consistent_across_fetches": consistent,
        "total_pelosi_ptr_filings": len(filings),
        "new_filings": [],
        "email_sent": False,
    }
    if not consistent:
        summary["note"] = "Index fetches disagreed; skipping this run (will retry)."
        log.warning(summary["note"])
        return summary

    state = load_state()
    seen = set(state.get("seen_doc_ids", []))
    new = [f for f in filings if f["doc_id"] not in seen]
    if not new:
        summary["note"] = "No new filings."
        return summary

    for f in new:
        try:
            pdf = _http_get(f["pdf_url"])
            f["trades"] = parse_trades(extract_pdf_text(pdf))
        except Exception:
            log.exception("PDF parse failed for %s", f["doc_id"])
            f["trades"] = []
    summary["new_filings"] = new

    if send:
        subject, text, html = build_email(new)
        resp = send_email(subject, text, html)
        summary["email_sent"] = True
        summary["email_id"] = resp.get("id")
        # Record as seen ONLY after the email went out successfully.
        seen.update(f["doc_id"] for f in new)
        state["seen_doc_ids"] = sorted(seen)
        state["last_ack"] = datetime.now(timezone.utc).isoformat()
        save_state(state)
    return summary
