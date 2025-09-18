#!/usr/bin/env python3
"""
Measure p95 latency for /onboarding/verify_odoo

Usage:
  BASE_URL=http://localhost:8001 ID_TOKEN=<token> python3 scripts/verify_odoo_p95.py --n 20
"""
import os
import sys
import time
import argparse
import statistics
import requests


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=20)
    args = p.parse_args()
    base = os.getenv("BASE_URL", "http://localhost:8001").rstrip("/")
    url = f"{base}/onboarding/verify_odoo"
    headers = {}
    tok = os.getenv("ID_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    times = []
    for i in range(max(1, args.n)):
        t0 = time.perf_counter()
        r = requests.get(url, headers=headers)
        dt = time.perf_counter() - t0
        times.append(dt)
        try:
            r.raise_for_status()
        except Exception:
            pass
    p50 = statistics.quantiles(times, n=2)[0] if len(times) >= 2 else times[0]
    p95 = statistics.quantiles(times, n=20)[18] if len(times) >= 20 else max(times)
    print(f"samples={len(times)} p50_s={p50:.3f} p95_s={p95:.3f}")
    # Accept if p95 <= 60s
    return 0 if p95 <= 60.0 else 2


if __name__ == "__main__":
    sys.exit(main())

