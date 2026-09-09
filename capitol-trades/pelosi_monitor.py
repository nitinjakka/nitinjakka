#!/usr/bin/env python3
"""Monitor for new Nancy Pelosi stock-trade disclosures (House PTR filings).

Data source: the official House Clerk financial-disclosure index
(https://disclosures-clerk.house.gov). This is the primary source that
sites like capitoltrades.com are built on.

Usage:
  pelosi_monitor.py check [--delay SECONDS] [--rounds N]
      Fetch the disclosure index N times (default 3), require all fetches
      to agree, and print JSON describing any Pelosi PTR filings that are
      not yet recorded in seen_filings.json. Does NOT modify state.

  pelosi_monitor.py ack
      Record all currently published Pelosi PTR filings as seen, so future
      `check` runs only report filings newer than now.

Stdlib only — no third-party dependencies.
"""
import argparse
import io
import json
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import date
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parent / "seen_filings.json"
FILER_LAST = "pelosi"
FILER_FIRST = "nancy"
INDEX_URL = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
PDF_URL = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc_id}.pdf"


def fetch_index(year):
    """Download one year's disclosure index and return Pelosi PTR filings."""
    url = INDEX_URL.format(year=year)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = resp.read()
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
        # FilingType "P" = Periodic Transaction Report (stock trades)
        if g("FilingType") != "P":
            continue
        doc_id = g("DocID")
        filings.append({
            "doc_id": doc_id,
            "name": f'{g("First")} {g("Last")}',
            "state_district": g("StateDst"),
            "filing_date": g("FilingDate"),
            "year": year,
            "pdf_url": PDF_URL.format(year=year, doc_id=doc_id),
        })
    return filings


def years_to_scan():
    today = date.today()
    # In January, the prior year's index may still receive late filings.
    return [today.year - 1, today.year] if today.month == 1 else [today.year]


def gather():
    filings = []
    for year in years_to_scan():
        try:
            filings.extend(fetch_index(year))
        except urllib.error.HTTPError as e:
            if e.code != 404:  # index for a brand-new year may not exist yet
                raise
    return sorted(filings, key=lambda f: (f["year"], f["doc_id"]))


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"seen_doc_ids": []}


def cmd_check(delay, rounds):
    fetches = []
    for i in range(rounds):
        if i:
            time.sleep(delay)
        fetches.append(gather())
    id_sets = [{f["doc_id"] for f in run} for run in fetches]
    consistent = all(s == id_sets[0] for s in id_sets)
    seen = set(load_state()["seen_doc_ids"])
    new = [f for f in fetches[-1] if f["doc_id"] not in seen]
    result = {
        "verification_rounds": rounds,
        "consistent_across_fetches": consistent,
        "total_pelosi_ptr_filings": len(fetches[-1]),
        "new_filings": new if consistent else [],
    }
    if not consistent:
        result["note"] = ("Index fetches disagreed with each other; likely a "
                          "transient source issue. Re-run check before acting.")
    print(json.dumps(result, indent=2))
    return 0 if consistent else 1


def cmd_ack():
    state = load_state()
    seen = set(state["seen_doc_ids"])
    current = gather()
    added = [f["doc_id"] for f in current if f["doc_id"] not in seen]
    seen.update(f["doc_id"] for f in current)
    state["seen_doc_ids"] = sorted(seen)
    state["last_ack"] = date.today().isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")
    print(json.dumps({"newly_recorded": added, "total_seen": len(seen)}, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_check = sub.add_parser("check")
    p_check.add_argument("--delay", type=int, default=30,
                         help="seconds between verification fetches (default 30)")
    p_check.add_argument("--rounds", type=int, default=3,
                         help="number of verification fetches (default 3)")
    sub.add_parser("ack")
    args = ap.parse_args()
    if args.cmd == "check":
        sys.exit(cmd_check(args.delay, args.rounds))
    sys.exit(cmd_ack())


if __name__ == "__main__":
    main()
