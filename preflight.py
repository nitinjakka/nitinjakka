#!/usr/bin/env python3
"""Clean live-auth preflight (no apport noise from `python3 -c`).

Usage on the server, after exporting the KALSHI_* env vars:
  python3 preflight.py
"""
import os
import sys

kid = os.environ.get("KALSHI_API_KEY_ID", "")
if kid in ("", "paste-your-key-id-here", "your-actual-key-id-from-kalshi"):
    print("STOP: KALSHI_API_KEY_ID is empty or still the placeholder.")
    print("      Set it to your REAL Kalshi Key ID and re-run.")
    sys.exit(2)

try:
    import kalshi_live as k
    print(k.preflight())
except Exception as e:
    print(f"PREFLIGHT FAILED: {e}")
    sys.exit(1)
