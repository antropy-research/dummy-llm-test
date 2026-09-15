"""Compatibility boundaries, independent of package and presentation versions."""

from .core import PACKAGE, digest, grading_hash

SCHEMA = 2
RUNTIME_TARGET_FIELDS = {"concurrency", "input_price_per_million", "output_price_per_million"}


def source_hash(*names):
    return digest({name: (PACKAGE / name).read_text() for name in names})


def versions():
    return {
        "schema": SCHEMA,
        "question": source_hash("catalog.py", "fingerprint.py", "core.py"),
        "scorer": grading_hash(),
        "adapter": source_hash("adapters.py", "streaming.py", "core.py"),
        "scheduler": source_hash("scheduler.py", "runner.py"),
        "measurement": source_hash("performance.py"),
        "compatibility": source_hash("contracts.py"),
    }


def experiment_target(target):
    return {k: v for k, v in target.items() if k not in RUNTIME_TARGET_FIELDS}


def target_signature(target, identity, mode, components):
    return digest(
        {
            "schema": SCHEMA,
            "target": experiment_target(target),
            "identity": identity,
            "mode": mode,
            "adapter": components["adapter"],
            "compatibility": components["compatibility"],
        }
    )


def resume_signature(config, plan, cases, identities, components, bank=None):
    # Only explicitly harmless changes are allowed; budgets, retries, timeout and
    # model parameters remain locked. Unselected targets/levels are irrelevant.
    excluded = {
        "output_dir",
        "progress_interval",
        "concurrency",
        "targets",
        "levels",
        "default_target",
        "bank",
        "challenges",
        "custom_cases",
    }
    settings = {k: v for k, v in config.items() if k not in excluded}
    settings["targets"] = {
        name: {k: v for k, v in config["targets"][name].items() if k != "concurrency"}
        for name in plan["targets"]
    }
    return digest(
        {
            "settings": settings,
            "plan": {k: v for k, v in plan.items() if k not in {"concurrency", "target_concurrency"}},
            "cases": [c.hash for c in cases],
            "identities": identities,
            "components": components,
            "bank": bank,
        }
    )


def performance_conditions(config, targets, name, identity, components):
    return {
        "schema": SCHEMA,
        "target": experiment_target(config["targets"][name]),
        "identity": identity,
        "concurrency": config["concurrency"],
        "target_concurrency": {
            t: config["targets"][t].get("concurrency", config["concurrency"]) for t in targets
        },
        "targets": list(targets),
        "retries": config["retries"],
        "timeout": config["timeout"],
        "adapter": components["adapter"],
        "scheduler": components["scheduler"],
        "measurement": components["measurement"],
        "compatibility": components["compatibility"],
    }
