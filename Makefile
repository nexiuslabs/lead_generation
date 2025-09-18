PY := python3

# Base URL for API; override per env
BASE ?= http://localhost:8001

.PHONY: accept accept-tenant sso rls export-verify odoo-p95

accept:
	BASE_URL=$(BASE) $(PY) scripts/acceptance_check.py --scope latest

accept-tenant:
	@if [ -z "$(T)" ]; then echo "Usage: make accept-tenant T=<tenant_id>"; exit 2; fi
	BASE_URL=$(BASE) $(PY) scripts/acceptance_check.py --tenant $(T) --scope latest

sso:
	BASE_URL=$(BASE) $(PY) scripts/sso_isolation_check.py

rls:
	@if [ -z "$(A)" ] || [ -z "$(B)" ]; then echo "Usage: make rls A=<tenantA> B=<tenantB>"; exit 2; fi
	$(PY) scripts/rls_smoke.py --a $(A) --b $(B)

export-verify:
	BASE_URL=$(BASE) $(PY) scripts/export_verify.py --limit 100

odoo-p95:
	BASE_URL=$(BASE) $(PY) scripts/verify_odoo_p95.py --n 20

