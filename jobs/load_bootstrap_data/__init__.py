#
# Copyright (c) 2026  Rafay Systems, All rights reserved
# Author: Ramakrishna, Rafay
#
"""Generic catalog loader — runbook group "0 · Foundation".

Delivered by GitOps: this package and the `data/` it reads ship in the SAME repo (`rafay-nvcm-catalog`), so
the loader resolves its data by relative path. Splitting them would mean looking up another
GitRepository's filesystem_path and handling not-registered / not-yet-synced / synced-but-stale.

Core/door split: `core.py` is pure (no Nautobot, no writes) and carries every decision — load order, field
schema, the deployment_types filter, and the refusal to load site instances. `jobs.py` only applies the
plan. The offline gate is `test/blueprint/test_catalog_bootstrap.py`.
"""
