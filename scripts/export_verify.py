#!/usr/bin/env python3
"""
Export verification: compare API export row count with DB count windowed by limit.

Usage:
  BASE_URL=http://localhost:8001 POSTGRES_DSN=... python3 scripts/export_verify.py --limit 100
  Optionally set ID_TOKEN for Authorization.
"""
import os
import sys
import json
import argparse
import asyncio
import asyncpg
import requests


async def count_db(conn: asyncpg.Connection) -> int:
    # Count scored rows for current tenant (GUC assumed set via RLS if desired)
    row = await conn.fetchrow("SELECT COUNT(*) FROM lead_scores")
    return int(row[0] or 0)


def fetch_api(limit: int, base: str) -> int:
    base = base.rstrip("/")
    url = f"{base}/export/latest_scores.json?limit={limit}"
    headers = {}
    tok = os.getenv("ID_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    r = requests.get(url, headers=headers)
    if r.status_code >= 300:
        print(f"API status={r.status_code}", file=sys.stderr)
        return -1
    try:
        arr = r.json()
    except Exception:
        print("Invalid JSON", file=sys.stderr)
        return -1
    return len(arr)


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=100)
    args = p.parse_args()
    dsn = os.getenv("POSTGRES_DSN")
    if not dsn:
        print("POSTGRES_DSN is required", file=sys.stderr)
        return 2
    base = os.getenv("BASE_URL", "http://localhost:8001")
    conn = await asyncpg.connect(dsn)
    db_count = await count_db(conn)
    api_count = fetch_api(args.limit, base)
    await conn.close()
    print(json.dumps({"db_count": db_count, "api_count": api_count, "limit": args.limit}))
    # Expect api_count <= min(limit, db_count)
    ok = (api_count >= 0 and api_count <= args.limit and (db_count == 0 or api_count > 0))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

