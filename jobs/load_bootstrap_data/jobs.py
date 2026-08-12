#
# Copyright (c) 2026  Rafay Systems, All rights reserved
# Author: Ramakrishna, Rafay
#
"""0.1 · Load foundation catalog — apply the GENERIC catalog from `data/` into Nautobot.

THE DOOR. Every decision — what to load, in what order, which fields are legal, what must never be here —
lives in `core.py`, which is pure and gated offline. This file only *applies* the plan the core computes, so
there is nothing to test here that is not already tested there.

WHAT THIS OWNS, AND WHAT IT DOES NOT.

    owns    statuses · manufacturers · location_types · namespaces · roles · platforms · device_types/
            — the GENERIC catalog. Identical for every customer. The FALLBACK when a blueprint is silent.

    NOT     locations · provider tenants — SITE INSTANCES. The blueprint owns these (`location_path` +
            `foundation`) and '2.0 · Foundation' applies them. `core.plan()` REFUSES to run if either file
            appears here, because a shared catalog supplying a site identity is how one customer's devices
            end up in another customer's site.

ORDER MATTERS, and this job is the reason. It carries each device-type's interface template; the blueprint
carries only a model NAME. Run this BEFORE any device is created, or devices come up with no interfaces for
the cabling to connect. The runbook order is 0.1 (this) -> 2.0 · Foundation -> 2.1 · Devices.

IDEMPOTENT AND NON-PRUNING: every object is update_or_create keyed on `name`, and nothing is ever deleted.
So this is safe on a live fabric, safe to re-run, and safe to run alongside the blueprint's own foundation —
whichever runs last wins on a field they both set, and by design the blueprint runs last.
"""
import os

from nautobot.apps.jobs import BooleanVar, Job, register_jobs

from .core import CatalogError, plan, unresolved_references

name = "0 · Foundation"


def _resolve_model(dotted):
    """'dcim.Manufacturer' -> the model class. Imported lazily so core.py stays importable offline."""
    from django.apps import apps

    app_label, model_name = dotted.split(".")
    return apps.get_model(app_label, model_name)


def _content_types(values):
    """['dcim.device', ...] -> ContentType instances, skipping any this Nautobot does not have."""
    from django.contrib.contenttypes.models import ContentType

    out = []
    for v in values or []:
        try:
            app_label, model = v.split(".")
            out.append(ContentType.objects.get(app_label=app_label, model=model))
        except (ValueError, ContentType.DoesNotExist):
            continue
    return out


class LoadFoundationCatalog(Job):
    """Apply the generic catalog (`data/`) into Nautobot — idempotent, non-pruning."""

    # An explicit BooleanVar defaulting to True, matching FabricDiscovery's convention — Nautobot passes Var
    # values as kwargs, so the var and the kwargs default must agree. An earlier draft relied on
    # `Meta.dryrun_default` with no declared var: nothing surfaced in the UI, `kwargs.get("dryrun")` was
    # never set, and the job COMMITTED on every run while advertising dry-run-by-default. Default to the
    # safe side, and make it visible.
    dry_run = BooleanVar(
        default=True,
        description="DRY-RUN (default, safe): log every object that WOULD be created/updated and write "
                    "nothing. UNCHECK to apply. Applying is idempotent and non-pruning (update_or_create, "
                    "never deletes), so it is safe to re-run on a live fabric.")

    class Meta:
        """Metadata."""

        name = "0.1 · Load foundation catalog (generic)"
        description = (
            "Prereq: none. Does: create/update the GENERIC Nautobot catalog this deployment shares across "
            "customers — statuses, manufacturers, location types, namespaces, roles, platforms, device "
            "types — from the catalog repo's data/. DRY-RUN by default. Idempotent + non-pruning "
            "(update_or_create, never deletes). Site INSTANCES are NOT loaded here: the blueprint owns "
            "those. Next: 2.0 · Foundation."
        )
        has_sensitive_variables = False

    def run(self, *args, **kwargs):
        """Compute the plan (pure), then upsert it in dependency order."""
        deployment_type = os.environ.get("NV_CONFIG_MANAGER_DEPLOYMENT_TYPE")
        try:
            steps = plan(deployment_type=deployment_type)
        except CatalogError as e:
            # Fail loudly and specifically. A catalog that is absent, malformed, or carrying a site instance
            # must not degrade into a partial load — that is the silent half-provisioning §17 forbids.
            self.logger.error("catalog is unusable: %s", e)
            raise

        for warn in unresolved_references(steps):
            self.logger.warning("%s", warn)

        dry = kwargs.get("dry_run", True)      # default SAFE: a missing kwarg must not mean "commit"
        created = updated = checked = 0
        for step in steps:
            model = _resolve_model(step["model"])
            for row in step["rows"]:
                fields = {k: v for k, v in row.items() if k != "deployment_types"}
                cts = fields.pop("content_types", None)
                parent_name = fields.pop("parent", None)
                mfr_name = fields.pop("manufacturer", None)
                key = {"name": fields.pop("name")}

                if dry:
                    self.logger.info("would upsert %s '%s'", step["model"], key["name"])
                    checked += 1
                    continue

                # Resolve by-name references. Both are within-catalog and ordered before their referrer, so a
                # miss here means the catalog itself is inconsistent — and the core validated that offline.
                # FAIL rather than write the object with the field unset: a LocationType with no parent is a
                # BROKEN hierarchy that every later location silently inherits, which is exactly the silent
                # half-provisioning §17 forbids. An earlier draft logged a warning and continued.
                if parent_name:
                    got = model.objects.filter(name=parent_name).first()
                    if not got:
                        raise CatalogError(
                            f"{step['model']} '{key['name']}': parent '{parent_name}' does not exist. The "
                            f"catalog is loaded in dependency order, so this means the parent is missing "
                            f"from the catalog or ordered after its child — refusing to create a "
                            f"parentless object and break the hierarchy.")
                    fields["parent"] = got
                if mfr_name:
                    from nautobot.dcim.models import Manufacturer

                    got = Manufacturer.objects.filter(name=mfr_name).first()
                    if not got:
                        raise CatalogError(
                            f"{step['model']} '{key['name']}': manufacturer '{mfr_name}' does not exist — "
                            f"manufacturers.yaml is ordered before platforms/device_types, so this means it "
                            f"is absent from the catalog. Refusing to create it unattributed.")
                    fields["manufacturer"] = got

                obj, was_created = model.objects.update_or_create(defaults=fields, **key)
                if cts:
                    resolved = _content_types(cts)
                    if resolved and hasattr(obj, "content_types"):
                        obj.content_types.add(*resolved)     # ADD, never set() — never narrows an existing object
                if was_created:
                    created += 1
                    self.logger.info("created %s '%s'", step["model"], obj.name)
                else:
                    updated += 1

        verb = "would load" if dry else "loaded"
        self.logger.success("%s %d object(s) across %d step(s) — created %d, updated %d, checked %d",
                            verb, sum(len(s["rows"]) for s in steps), len(steps), created, updated, checked)
        return f"{verb}: created={created} updated={updated} checked={checked}"


register_jobs(LoadFoundationCatalog)
