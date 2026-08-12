# `catalog/` — the GENERIC Nautobot catalog (Axis A)

**Copyright (c) 2026  Rafay Systems, All rights reserved**

This is the content of the **`rafay-nvcm-catalog`** GitOps repository, authored here so the gate suite can
validate it offline. Publishing to that repo is a copy step — the same relationship a customer's folder
(`<customer>/`) has to that customer's own data repo.
Design: [`../docs/gitops_repo_design.md`](../docs/gitops_repo_design.md).

## What belongs here

Definitions that are **identical for every customer**: the location-type *hierarchy shape*, statuses, roles,
manufacturers, platforms, namespaces, and per-**model** device-type interface templates. This is the
generic half of what the retired `nvcm-rafay-bootstrap-repo` carried.

Three directories are specified but **not yet present**, and their absence is deliberate:

| Directory | Why not yet |
|---|---|
| `config_context_schemas/` | exists only in the legacy repo and was never inspected — to be recovered, not invented |
| `export_templates/` | same |
| `templates/customer-data-layout/` | the scaffold a new engagement copies; deferred until a second customer exists, rather than guessing a layout nobody has used |

## What must NEVER live here — enforced, not asked

> **No site instances.** No `data/locations.yaml`, no `data/tenants.yaml`.

A location instance (`blr-dc01`) or a provider tenant *is a customer's identity*. This repo is shared and
acts as the **fallback** when a blueprint is silent, so a site instance here could silently place one
customer's devices in another customer's site. That is a bug class this project has hit five times ("no
reference-site default behind a customer's blueprint"), so it is made structurally impossible rather than
remembered:

* `jobs/load_bootstrap_data/core.py` **raises** `CatalogError` if either file appears, and
* `test/blueprint/test_catalog_bootstrap.py` fails the build if either exists.

Site instances come from the **blueprint** (`location_path` + `foundation`), applied by
`2.0 · Foundation`, whose closure is proven by `test/blueprint/test_foundation_closure.py`.

## The resolution model

Two idempotent, non-pruning appliers in a fixed order — no merge engine:

| Blueprint state | Result |
|---|---|
| declares the object | the blueprint wins (it runs last) |
| silent on the object | this catalog is the only source — **the fallback** |
| missing a site instance | **raises** — the blueprint cannot be silent about its own identity |

**Ordering is load-bearing.** The blueprint carries a device-type *model name*; this catalog carries that
model's *interface template*. Load this catalog **before** any device is created, or devices come up with no
interfaces for cabling to connect.

## `deployment_types`

Every object carries `deployment_types: [all]` — NVIDIA's own filter, selected at load time by
`$NV_CONFIG_MANAGER_DEPLOYMENT_TYPE`. It is how one shared catalog serves several deployment shapes without
forking the repo. Nothing filters today (everything is `[all]`); the field is present so a variant is a data
change rather than a fork.

## Provenance of the values here

| File | Source |
|---|---|
| `manufacturers.yaml`, `location_types.yaml`, `namespaces.yaml`, `roles.yaml`, `platforms.yaml` | the live `LoadBootstrapData` snapshot captured read-only on 2026-08-06 (`test/blueprint/_fixtures/foundation_live/`), **minus** site instances |
| `statuses.yaml` | **derived** from the status names the committed designs actually reference — nothing in this repo created Statuses before, so the designs relied on Nautobot's defaults |
| `device_types/` | **deliberately empty** — see its README |
