"""Generate a CycloneDX software bill of materials for the installed environment.

    python tools/generate_sbom.py                  # write sbom.json
    python tools/generate_sbom.py --check          # non-zero if sbom.json is stale
    python tools/generate_sbom.py --out other.json

The SBOM describes **what is installed in this environment**, read from the
distribution metadata, not what `pyproject.toml` asks for. Those are different
documents and only one of them is evidence: a dependency declaration is an
intention, and a bill of materials is a statement about the artifact that was
actually built and run. Every version here is the version the committed
benchmark numbers were produced with.

`--check` is what CI runs. It regenerates in memory and compares against the
committed file, ignoring the timestamp, so a dependency that changes without the
SBOM being regenerated fails the build rather than drifting quietly.

Licence fields come from the package metadata as published. Where a package
declares no licence, it is recorded as `unknown` rather than guessed at -- an
SBOM that fills in a plausible licence is worse than one with a gap in it,
because the gap is actionable and the guess is not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "sbom.json"

#: Distributions that belong to the tooling rather than to the product. They are
#: recorded, but flagged, so a reader can tell the runtime surface from the
#: development surface.
DEV_MARKERS = frozenset({
    "pytest", "pytest-asyncio", "ruff", "iniconfig", "pluggy", "coverage",
    "setuptools", "wheel", "pip", "packaging",
})


def _licence_of(dist: metadata.Distribution) -> str:
    """Best available licence string, or 'unknown'. Never inferred."""
    meta = dist.metadata
    declared = meta.get("License-Expression") or meta.get("License")
    if declared and declared.strip() and declared.strip().lower() not in ("unknown", "none"):
        # Long licence texts are sometimes pasted into this field wholesale.
        text = declared.strip()
        return text if len(text) <= 64 else text.splitlines()[0][:64]
    for classifier in meta.get_all("Classifier") or []:
        if classifier.startswith("License ::"):
            return classifier.rsplit("::", 1)[-1].strip()
    return "unknown"


def _components() -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        if not name:
            continue
        version = dist.version or "unknown"
        licence = _licence_of(dist)
        component: dict[str, Any] = {
            "type": "library",
            "bom-ref": f"pkg:pypi/{name.lower()}@{version}",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name.lower()}@{version}",
            "scope": "excluded" if name.lower() in DEV_MARKERS else "required",
        }
        if licence == "unknown":
            component["licenses"] = []
            component["properties"] = [
                {"name": "productionpulse:licence", "value": "not declared by the package"}
            ]
        else:
            component["licenses"] = [{"license": {"name": licence}}]
        components.append(component)
    return sorted(components, key=lambda c: str(c["name"]).lower())


def build(timestamp: str | None = None) -> dict[str, Any]:
    components = _components()
    # A content digest over name/version/licence only. It is what `--check`
    # compares, so regenerating the SBOM without changing a dependency is not a
    # diff and does not churn the repository.
    digest = hashlib.sha256(
        json.dumps(
            [[c["name"], c["version"], c["licenses"]] for c in components], sort_keys=True
        ).encode()
    ).hexdigest()
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tools": [{"vendor": "ProductionPulse", "name": "tools/generate_sbom.py"}],
            "component": {
                "type": "application",
                "bom-ref": "productionpulse",
                "name": "productionpulse",
                "version": _self_version(),
                "description": (
                    "ProductionPulse Inclusive -- real-time production decision "
                    "and execution infrastructure"
                ),
                "licenses": [{"license": {"id": "Apache-2.0"}}],
            },
            "properties": [
                {"name": "productionpulse:python", "value": platform.python_version()},
                {"name": "productionpulse:platform", "value": platform.platform()},
                {"name": "productionpulse:content-digest", "value": digest},
            ],
        },
        "components": components,
    }


def _self_version() -> str:
    try:
        return metadata.version("productionpulse")
    except metadata.PackageNotFoundError:
        # Not pip-installed in this environment; read the declared version.
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.strip().startswith("version"):
                return line.split("=", 1)[1].strip().strip('"')
        return "0.0.0"


def _digest_of(document: dict[str, Any]) -> str:
    for prop in document.get("metadata", {}).get("properties", []):
        if prop.get("name") == "productionpulse:content-digest":
            return str(prop.get("value"))
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CycloneDX SBOM for ProductionPulse")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if the committed SBOM is out of date")
    args = parser.parse_args(argv)

    fresh = build()
    if args.check:
        if not args.out.exists():
            print(f"{args.out} does not exist; run tools/generate_sbom.py", file=sys.stderr)
            return 1
        committed = json.loads(args.out.read_text(encoding="utf-8"))
        if _digest_of(committed) != _digest_of(fresh):
            print(
                f"{args.out.name} is stale: installed dependencies no longer match.\n"
                f"  committed digest {_digest_of(committed)[:16]}\n"
                f"  current   digest {_digest_of(fresh)[:16]}\n"
                "Regenerate with `python tools/generate_sbom.py`.",
                file=sys.stderr,
            )
            return 1
        print(f"{args.out.name} is current ({len(committed['components'])} components)")
        return 0

    args.out.write_text(json.dumps(fresh, indent=2) + "\n", encoding="utf-8")
    unknown = sum(1 for c in fresh["components"] if not c["licenses"])
    print(f"Wrote {args.out} -- {len(fresh['components'])} components, "
          f"{unknown} with no declared licence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
