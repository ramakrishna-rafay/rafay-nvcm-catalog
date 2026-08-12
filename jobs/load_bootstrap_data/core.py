#!/usr/bin/env python3
#
# Copyright (c) 2026  Rafay Systems, All rights reserved
# Author: Ramakrishna, Rafay
# Revision history:
#   2026-08-11  Ramakrishna, Rafay  Initial version — pure core for the generic catalog loader (W2).
#
"""Pure core of the catalog bootstrap loader — read, validate and dependency-order `data/`.

PURE. No Nautobot imports, no Django, no network, no writes. Everything here is a function of the files on
disk, so the whole thing is unit-testable offline; `jobs.py` is the thin Nautobot door that only *applies*
what this computes. Same core/door split as the rest of this project.

WHY A FRESH LOADER RATHER THAN THE LEGACY ONE. The retired `nvcm-rafay-bootstrap-repo` shipped a
`load_bootstrap_data.py` with 13 `load_*` methods, one documented bug ("locations never apply") and no
offline coverage. Under the agreed split this loader no longer handles locations AT ALL — the blueprint owns
site instances — so the buggy part is precisely the part being removed, and inheriting the rest would import
12 unaudited methods to keep one.

THE ONE RULE THIS FILE ENFORCES IN CODE, not in review:

    A shared catalog may not contain SITE INSTANCES.

`locations.yaml` or `tenants.yaml` here would let a shared fallback supply one customer's identity to
another customer's data centre. This project has shipped that bug class five times, so `plan()` raises
rather than trusting a convention — and a gate proves the raise still happens.

    python3 catalog/jobs/load_bootstrap_data/core.py                 # human summary of the plan
    python3 catalog/jobs/load_bootstrap_data/core.py --json          # machine-readable
"""
import json
import os
import sys

# Load order. Parents before children; anything referenced by name before its referrer. Mirrored in
# data/loading_dependency_order.txt, and a gate asserts the two agree so they cannot drift.
LOAD_ORDER = (
    "statuses.yaml",        # before locations (blueprint-owned) — every location carries status__name
    "manufacturers.yaml",   # before platforms + device_types
    "location_types.yaml",  # before locations; self-parented in chain order
    "namespaces.yaml",
    "roles.yaml",
    "platforms.yaml",       # needs manufacturers
)

# Files that must NEVER appear in a shared catalog, each with the reason — Axis B, a customer's own data.
# The design's fallback table names locations, provider tenants AND racks as "never"; an earlier draft of
# this list carried only the first two, which made the guard narrower than the rule it was enforcing.
FORBIDDEN_FILES = {
    "locations.yaml": ("a location instance is a SITE identity; the blueprint owns it via location_path, "
                       "applied by '2.0 · Foundation'"),
    "tenants.yaml": ("a provider tenant is the CUSTOMER identity; deriving it from a shared catalog is a "
                     "cross-customer grant"),
    "racks.yaml": "physical layout is site-specific and is not derivable from a shared catalog",
    "rack_groups.yaml": "physical layout is site-specific",
    "device_placements.yaml": "physical layout is site-specific",
    "vlans.yaml": ("VLANs are per-tenant NUMBERING — f(T) territory. A shared default here is the "
                   "'no reference numbering behind a customer's blueprint' bug this project shipped five "
                   "times"),
    "vrfs.yaml": "VRFs are per-tenant numbering; same reason as vlans.yaml",
    "prefixes.yaml": "IP plan is site-specific; the blueprint's supernets own it",
    "devices.yaml": "devices are operational objects, created by the Design Builder designs, not bootstrap",
    "cables.yaml": "cabling is operational and site-specific; the cables design owns it",
}

# Allowed fields per file. An unrecognised key is a TYPO and fails, consistent with the blueprint loader —
# silently ignoring it is how a misspelled field disables a setting while everything reads green.
SCHEMA = {
    "statuses.yaml": ({"name"}, {"color", "description", "content_types", "deployment_types"}),
    "manufacturers.yaml": ({"name"}, {"description", "deployment_types"}),
    "location_types.yaml": ({"name"}, {"description", "content_types", "parent", "deployment_types"}),
    "namespaces.yaml": ({"name"}, {"description", "deployment_types"}),
    "roles.yaml": ({"name"}, {"color", "description", "content_types", "deployment_types"}),
    "platforms.yaml": ({"name"}, {"manufacturer", "description", "network_driver", "napalm_driver",
                                  "deployment_types"}),
}

# The Nautobot model each file upserts into. The door maps these; kept here so the plan is self-describing
# and the door carries no knowledge the core lacks.
MODEL_OF = {
    "statuses.yaml": "extras.Status",
    "manufacturers.yaml": "dcim.Manufacturer",
    "location_types.yaml": "dcim.LocationType",
    "namespaces.yaml": "ipam.Namespace",
    "roles.yaml": "extras.Role",
    "platforms.yaml": "dcim.Platform",
}

DEFAULT_DEPLOYMENT_TYPE = "all"


class CatalogError(ValueError):
    """The catalog on disk is missing, malformed, or contains something it must never contain."""


def data_dir(root=None):
    """The catalog's `data/` directory — resolved RELATIVE TO THIS FILE by default.

    That default is the whole reason the loader and its data ship in one repo: a git-synced Nautobot job
    reads its own checkout, so `data/` is two levels up from this module and needs no cross-repo lookup
    (which would mean resolving another GitRepository's filesystem_path, and handling not-registered /
    not-yet-synced / synced-but-stale).
    """
    if root:
        return root
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "data"))


def _load_yaml(path):
    import yaml  # imported lazily so --help and the audit tests work in a bare interpreter
    with open(path) as fh:
        return yaml.safe_load(fh)


def assert_no_site_instances(root=None):
    """Refuse a catalog that carries site instances. Called by `plan()`; safe to call directly."""
    d = data_dir(root)
    found = [(f, why) for f, why in FORBIDDEN_FILES.items() if os.path.exists(os.path.join(d, f))]
    if found:
        raise CatalogError(
            "this catalog is SHARED across customers and must not contain site instances: "
            + "; ".join(f"{f} — {why}" for f, why in found))
    return True


def assert_no_unknown_files(root=None):
    """Refuse ANY `.yaml` in `data/` that this loader does not know how to load.

    The named FORBIDDEN_FILES list above gives precise errors for the likely mistakes, but a denylist can
    always be evaded by a filename nobody predicted — and the thing being evaded is "no customer data in a
    shared, fallback catalog". So the real rule is an ALLOWLIST: `LOAD_ORDER` is what may exist, and anything
    else fails closed. Same posture as the blueprint loader's unknown-KEY rule, applied one level up at the
    FILE level.

    Silently ignoring an unrecognised file would be the worst outcome: someone adds `subnets.yaml`, sees the
    job succeed, and believes it loaded.
    """
    d = data_dir(root)
    if not os.path.isdir(d):
        return True
    known = set(LOAD_ORDER)
    unknown = sorted(f for f in os.listdir(d)
                     if f.endswith((".yaml", ".yml")) and f not in known)
    if unknown:
        detail = []
        for f in unknown:
            why = FORBIDDEN_FILES.get(f)
            detail.append(f"{f}" + (f" — {why}" if why else " — not a file this loader knows how to load"))
        raise CatalogError(
            "unrecognised file(s) in the shared catalog: " + "; ".join(detail)
            + f". Loadable files are exactly {list(LOAD_ORDER)}; add a new one to LOAD_ORDER + SCHEMA + "
              f"MODEL_OF (and loading_dependency_order.txt) so it is validated, not merely tolerated.")
    return True


def validate_rows(fname, rows):
    """Every row is a dict, carries the required keys, and carries no unrecognised key."""
    required, optional = SCHEMA[fname]
    allowed = required | optional
    problems = []
    if not isinstance(rows, list):
        raise CatalogError(f"{fname}: expected a LIST of objects, got {type(rows).__name__}")
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            problems.append(f"{fname}[{i}]: expected a mapping, got {type(row).__name__}")
            continue
        keys = set(row)
        for missing in sorted(required - keys):
            problems.append(f"{fname}[{i}]: missing required key '{missing}'")
        for unknown in sorted(keys - allowed):
            problems.append(f"{fname}[{i}] ('{row.get('name', '?')}'): unknown key '{unknown}' — treated as "
                            f"a typo, not forward-compatibility. Allowed: {sorted(allowed)}")
    if problems:
        raise CatalogError("; ".join(problems))
    return True


def _wanted(row, deployment_type):
    """Honour NVIDIA's `deployment_types` filter — the platform's own way to serve variants from one repo."""
    if deployment_type is None:
        return True
    dts = row.get("deployment_types")
    if not dts:
        return True                      # unscoped objects load everywhere
    return deployment_type in dts or DEFAULT_DEPLOYMENT_TYPE in dts


def plan(root=None, deployment_type=None):
    """Ordered list of upserts: [{file, model, rows}] in LOAD_ORDER. Pure — reads, never writes.

    A file that is absent is SKIPPED, not an error: the catalog is a fallback, and a deployment that has no
    use for (say) platforms should not be forced to carry an empty file. A file that is PRESENT but
    malformed raises — absent and broken are different claims.
    """
    assert_no_site_instances(root)      # named files, with a precise reason each
    assert_no_unknown_files(root)       # everything else — allowlist, fail closed
    d = data_dir(root)
    if not os.path.isdir(d):
        raise CatalogError(f"catalog data directory not found: {d}")
    steps = []
    for fname in LOAD_ORDER:
        path = os.path.join(d, fname)
        if not os.path.exists(path):
            continue
        rows = _load_yaml(path)
        if rows is None:
            continue                     # an empty file is a no-op, not a failure
        validate_rows(fname, rows)
        keep = [r for r in rows if _wanted(r, deployment_type)]
        if keep:
            steps.append({"file": fname, "model": MODEL_OF[fname], "rows": keep})
    if not steps:
        raise CatalogError(
            f"no catalog objects resolved from {d} — refusing to report success for an empty load. Either "
            f"the directory is wrong or every object was filtered out by deployment_type="
            f"{deployment_type!r}")
    return steps


def unresolved_references(steps):
    """Names referenced by the plan that the plan does not create BEFORE the row that needs them.

    Two kinds, and both are about ORDER as much as existence — the door resolves each reference against
    Nautobot at the moment it processes the row, so a reference satisfied *later* in the same file is not
    satisfied at all:

      * `platforms[].manufacturer` -> a name in manufacturers.yaml (an earlier file)
      * `location_types[].parent`  -> a name EARLIER IN THE SAME FILE. The hierarchy is a chain
        (Provider -> Region -> Site -> Building -> Room), so reordering the file silently breaks it. An
        earlier draft of this function checked only the manufacturer case, so a reordered
        location_types.yaml would have passed every offline check and then raised at apply time.

    Reported, not raised: the loader is additive and an object created by some other means is legitimate.
    The door raises if the reference is genuinely absent at apply time; this is the offline early warning.
    """
    created = {s["file"]: {r["name"] for r in s["rows"]} for s in steps}
    mfrs = created.get("manufacturers.yaml", set())
    out = []
    for s in steps:
        if s["file"] == "platforms.yaml":
            for r in s["rows"]:
                m = r.get("manufacturer")
                if m and m not in mfrs:
                    out.append(f"platforms.yaml '{r['name']}' references manufacturer '{m}', which this "
                               f"catalog does not create")
        elif s["file"] == "location_types.yaml":
            seen = []
            for r in s["rows"]:
                p = r.get("parent")
                if p and p not in seen:
                    out.append(f"location_types.yaml '{r['name']}' has parent '{p}', which does not appear "
                               f"EARLIER in the same file — the chain is applied top-down, so the parent "
                               f"would not exist yet")
                seen.append(r["name"])
    return out


def _main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="Show the catalog load plan (read-only, no Nautobot).")
    ap.add_argument("--data", help="catalog data/ directory (default: alongside this module)")
    ap.add_argument("--deployment-type", default=os.environ.get("NV_CONFIG_MANAGER_DEPLOYMENT_TYPE"),
                    help="only load objects whose deployment_types include this (or 'all')")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        steps = plan(a.data, a.deployment_type)
    except CatalogError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(steps, indent=2, sort_keys=True))
        return 0
    total = 0
    for s in steps:
        print(f"  {s['file']:22s} -> {s['model']:20s} {len(s['rows'])} object(s): "
              f"{', '.join(r['name'] for r in s['rows'])}")
        total += len(s["rows"])
    print(f"  {total} object(s) in {len(steps)} step(s), in dependency order.")
    for warn in unresolved_references(steps):
        print(f"  WARNING: {warn}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
