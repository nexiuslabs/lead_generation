#!/usr/bin/env python3
"""
SSO & Isolation smoke checks

Checks:
  - /info without auth → expect 401/403
  - /info with Authorization: Bearer <ID_TOKEN> (env ID_TOKEN) → expect 200/OK (or 401 if server cookie-only)

Usage:
  BASE_URL=http://localhost:8001 ID_TOKEN=<token> python3 scripts/sso_isolation_check.py
"""
import os
import sys
import requests


def main():
    base = os.getenv("BASE_URL", "http://localhost:8001").rstrip("/")
    url = f"{base}/info"
    # Unauth
    r1 = requests.get(url)
    print(f"/info unauth status={r1.status_code}")
    ok1 = r1.status_code in (401, 403)
    # Auth via bearer (optional)
    token = os.getenv("ID_TOKEN")
    ok2 = True
    if token:
        r2 = requests.get(url, headers={"Authorization": f"Bearer {token}"})
        print(f"/info bearer status={r2.status_code}")
        ok2 = (200 <= r2.status_code < 300)
    else:
        print("ID_TOKEN not set; skipping bearer check")
    print(f"PASS unauth={ok1} auth={ok2}")
    return 0 if (ok1 and ok2) else 2


if __name__ == "__main__":
    sys.exit(main())

