#!/usr/bin/env python3
"""
Acceptance check script (Feature 14)

Computes acceptance metrics per tenant and exits non‑zero on failure.

Env:
  - POSTGRES_DSN: database DSN
  - ACCEPT_DOMAIN_RATE (default 0.70)
  - ACCEPT_ABOUT_RATE (default 0.60)
  - ACCEPT_EMAIL_RATE (default 0.40)
  - ACCEPT_BUCKET_MAX (default 0.70)

Usage:
  python3 scripts/acceptance_check.py [--tenant 1034]
"""
from __future__ import annotations
import os
import sys
import json
import argparse
import asyncio
import asyncpg
from pathlib import Path
try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None  # type: ignore


async def _metrics_for_tenant(conn: asyncpg.Connection, tenant_id: int, *, scope: str = "latest", since_hours: int = 24) -> dict:
    await conn.execute("SELECT set_config('request.tenant_id', $1, true)", str(int(tenant_id)))

    async def one(sql: str, *args, default=0):
        try:
            row = await conn.fetchrow(sql, *args)
            return int(row[0] or 0) if row else default
        except Exception:
            return default

    async def ratio(num_sql: str, den_sql: str) -> float:
        try:
            rn = await conn.fetchrow(num_sql)
            num = float(rn[0] or 0) if rn else 0.0
        except Exception:
            num = 0.0
        try:
            rd = await conn.fetchrow(den_sql)
            den = float(rd[0] or 0) if rd else 0.0
        except Exception:
            den = 0.0
        return (num / den) if den > 0 else 0.0

    # Determine window
    start_ts = None
    end_ts = None
    if scope == "latest":
        try:
            row = await conn.fetchrow("SELECT started_at, COALESCE(ended_at, NOW()) FROM enrichment_runs ORDER BY started_at DESC LIMIT 1")
            if row and row[0]:
                start_ts, end_ts = row[0], row[1]
        except Exception:
            start_ts = None
    if start_ts is None:
        row = await conn.fetchrow("SELECT NOW() - ($1 || ' hours')::interval AS start, NOW() AS finish", str(int(since_hours)))
        start_ts, end_ts = row[0], row[1]

    window = (start_ts, end_ts)

    mv_candidates = await one("SELECT COUNT(*) FROM icp_candidate_companies")
    shortlisted = await one("SELECT COUNT(*) FROM lead_scores WHERE created_at BETWEEN $1 AND $2", *window)
    domain_rate = await ratio(
        "SELECT SUM(CASE WHEN c.website_domain IS NOT NULL AND c.website_domain<>'' THEN 1 ELSE 0 END) FROM companies c JOIN lead_scores s ON s.company_id=c.company_id WHERE s.created_at BETWEEN $1 AND $2",
        "SELECT COUNT(*) FROM companies c JOIN lead_scores s ON s.company_id=c.company_id WHERE s.created_at BETWEEN $1 AND $2",
    )
    about_rate = await ratio(
        "SELECT SUM(CASE WHEN COALESCE(NULLIF(TRIM(r.about_text), ''), NULL) IS NOT NULL THEN 1 ELSE 0 END) FROM company_enrichment_runs r JOIN lead_scores s ON s.company_id=r.company_id WHERE s.created_at BETWEEN $1 AND $2",
        "SELECT COUNT(*) FROM company_enrichment_runs r JOIN lead_scores s ON s.company_id=r.company_id WHERE s.created_at BETWEEN $1 AND $2",
    )
    email_rate = await ratio(
        "SELECT SUM(CASE WHEN EXISTS (SELECT 1 FROM lead_emails e WHERE e.company_id=s.company_id AND COALESCE(e.verification_status,'unknown') IN ('valid','unknown')) THEN 1 ELSE 0 END) FROM lead_scores s WHERE s.created_at BETWEEN $1 AND $2",
        "SELECT COUNT(*) FROM lead_scores s WHERE s.created_at BETWEEN $1 AND $2",
    )
    bucket_counts = {}
    try:
        rows = await conn.fetch("SELECT LOWER(COALESCE(bucket,'')) AS b, COUNT(*) FROM lead_scores WHERE created_at BETWEEN $1 AND $2 GROUP BY 1", *window)
        for r in rows:
            bucket_counts[str(r[0] or "")] = int(r[1] or 0)
    except Exception:
        bucket_counts = {}
    rationale_rate = await ratio(
        "SELECT SUM(CASE WHEN NULLIF(TRIM(rationale),'') IS NOT NULL THEN 1 ELSE 0 END) FROM lead_scores WHERE created_at BETWEEN $1 AND $2",
        "SELECT COUNT(*) FROM lead_scores WHERE created_at BETWEEN $1 AND $2",
    )
    return {
        "tenant_id": tenant_id,
        "mv_candidates": mv_candidates,
        "shortlisted": shortlisted,
        "domain_rate": round(domain_rate, 4),
        "about_rate": round(about_rate, 4),
        "email_rate": round(email_rate, 4),
        "bucket_counts": bucket_counts,
        "rationale_rate": round(rationale_rate, 4),
        "window": {"start": start_ts, "end": end_ts, "scope": scope, "since_hours": since_hours},
    }


def _thresholds():
    def f(name: str, default: float) -> float:
        try:
            return float(os.getenv(name, str(default)) or default)
        except Exception:
            return default
    return {
        "domain": f("ACCEPT_DOMAIN_RATE", 0.70),
        "about": f("ACCEPT_ABOUT_RATE", 0.60),
        "email": f("ACCEPT_EMAIL_RATE", 0.40),
        "bucket_max": f("ACCEPT_BUCKET_MAX", 0.70),
    }


def _passes(m: dict, thr: dict) -> tuple[bool, dict]:
    ok = True
    reasons = {}
    if m.get("domain_rate", 0.0) < thr["domain"]:
        ok = False; reasons["domain_rate"] = f"{m['domain_rate']} < {thr['domain']}"
    if m.get("about_rate", 0.0) < thr["about"]:
        ok = False; reasons["about_rate"] = f"{m['about_rate']} < {thr['about']}"
    if m.get("email_rate", 0.0) < thr["email"]:
        ok = False; reasons["email_rate"] = f"{m['email_rate']} < {thr['email']}"
    # bucket sanity
    total = sum(m.get("bucket_counts", {}).values()) or 0
    if total > 0:
        for b, c in m.get("bucket_counts", {}).items():
            share = c / total
            if share > thr["bucket_max"]:
                ok = False; reasons["bucket_counts"] = f"bucket '{b}' share {share:.2f} > {thr['bucket_max']}"
                break
    return ok, reasons


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", type=int, help="Single tenant id to check")
    parser.add_argument("--scope", choices=["latest","since"], default="latest")
    parser.add_argument("--since-hours", type=int, default=24)
    args = parser.parse_args()
    # Load .env files similar to src/settings.py so running from scripts/ works
    if load_dotenv is not None:
        try:
            load_dotenv()  # default search (cwd)
            this = Path(__file__).resolve()
            root = this.parents[1]
            load_dotenv(root / ".env")
            load_dotenv(root / "src/.env")
        except Exception:
            pass
    dsn = os.getenv("POSTGRES_DSN")
    if not dsn:
        print("POSTGRES_DSN is required", file=sys.stderr)
        return 2
    conn = await asyncpg.connect(dsn)
    tenants = []
    if args.tenant:
        tenants = [int(args.tenant)]
    else:
        try:
            rows = await conn.fetch("SELECT DISTINCT tenant_id FROM enrichment_runs WHERE tenant_id IS NOT NULL ORDER BY tenant_id")
            tenants = [int(r[0]) for r in rows] if rows else []
        except Exception:
            tenants = []
        if not tenants:
            raw = os.getenv("DEFAULT_TENANT_ID", "")
            if raw.isdigit():
                tenants = [int(raw)]
    results = []
    any_fail = False
    thr = _thresholds()
    for tid in tenants or [0]:
        m = await _metrics_for_tenant(conn, int(tid), scope=args.scope, since_hours=args.since_hours)
        ok, reasons = _passes(m, thr)
        m["pass"] = ok
        if not ok:
            any_fail = True
            m["fail_reasons"] = reasons
        results.append(m)
    await conn.close()
    print(json.dumps({"results": results, "thresholds": thr}, indent=2))
    return 0 if not any_fail else 2


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
