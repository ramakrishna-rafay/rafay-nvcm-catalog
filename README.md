# nvcm-rafay-core-repo

**Shared, customer-agnostic** GitOps content for NVCM/Nautobot. Registered as a Git Repository data
source in *every* customer's Nautobot, with **Provided Contents** =
`extras.job` + `extras.configcontext` + `extras.configcontextschema` (+ `extras.exporttemplate`).

## What belongs here

- `jobs/` — Nautobot Jobs (foundation load, discovery, tenant lifecycle, drift)
- config-context **schemas** (not values)
- export templates

## What does NOT belong here

- **Any customer's data.** Config-context *values* and foundation data live in that customer's own
  data repo (e.g. `nvcm-stc-data-repo`). Nautobot imports config-contexts from a fixed path inside a
  repo, so per-customer directories here would load into *every* customer's instance.
- **Any secret.** This repo is public. Credentials are referenced by environment-variable name through
  Nautobot Secrets, never committed.

## Why it is separate

This is the reusable core. Forking it per customer would fork the code too, and every fix would then
have to be made N times — the exact outcome the parameterized-config work exists to prevent.

Registration is automated from the blueprint's `gitops:` section by
`stc_deploy_scripts/rafay-nvcm-enable.sh`; see `stc_productization_plan.md` §12.24.
