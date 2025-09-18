#!/usr/bin/env python3
"""
RLS smoke test: compare counts for two tenants by setting request.tenant_id GUC.

Usage:
  POSTGRES_DSN=... python3 scripts/rls_smoke.py --a 1034 --b 2001
"""
import os
import sys
import argparse
import asyncio
import asyncpg


async def count_for_tenant(conn: asyncpg.Connection, tenant_id: int) -> int:
    await conn.execute("SELECT set_config('request.tenant_id', $1, true)", str(int(tenant_id)))
    row = await conn.fetchrow("SELECT COUNT(*) FROM lead_scores")
    return int(row[0] or 0) if row else 0


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--a", required=True, type=int)
    p.add_argument("--b", required=True, type=int)
    args = p.parse_args()
    dsn = os.getenv("POSTGRES_DSN")
    if not dsn:
        print("POSTGRES_DSN is required", file=sys.stderr)
        return 2
    conn = await asyncpg.connect(dsn)
    ca = await count_for_tenant(conn, args.a)
    cb = await count_for_tenant(conn, args.b)
    await conn.close()
    print(f"tenant {args.a} count={ca}; tenant {args.b} count={cb}")
    # Pass if counts differ (and both queries executed)
    return 0 if (ca != cb) else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

