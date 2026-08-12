# `device_types/<Manufacturer>/<model>.yaml` — deliberately empty

This directory ships the **mechanism** with no content, on purpose.

## Why it is empty

A device-type definition's value is its **interface template** — the full port list for that model. Nothing
available to this repo knows it: the blueprint carries only a model *name* (`Cumulus VX`), and the cabling
tells you which ports one site happens to use, not which ports the model *has*.
`deploy_scripts/foundation_data.py` refuses to emit these files for exactly this reason — "the blueprint
carries only the model name, so emitting it would fabricate a port list."

Fabricating one would be worse than shipping nothing: a wrong template creates devices with wrong
interfaces, and cabling to `swp1..swpN` then fails on data that *looks* authoritative.

Same posture as the version→template-tree resolver, which shipped its mechanism with the tree content
deliberately absent: the machinery and its guard land first, so the content is a drop-in.

## Why this is still the strongest case for a GitOps catalog

Per-**model**, not per-customer — a ConnectX-7 has the same ports everywhere. New hardware becomes one
reviewed pull request by whoever actually knows the port map: no code release, no PVC re-seed, no restart.

## Adding one

Layout is `device_types/<Manufacturer>/<model>.yaml`, and the manufacturer directory name must match a
`name:` in `../manufacturers.yaml` — the loader resolves `manufacturer` by name and fails loudly otherwise.
Take the port list from the vendor's own data sheet or a `nv show interface` on a real unit; do not infer it
from a site's cabling.

Nothing here is required for the reference site to work today: the fabric designs create `Cumulus VX` and
`Generic Server` bare via `create_or_update`, and the switches' `swp` interfaces are created explicitly by
the underlay design rather than inherited from a template.
