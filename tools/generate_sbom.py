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

`--check` is what CI runs. It asserts the two things that are actually true of a
correct SBOM regardless of when it is run:

* the committed file parses and carries a content digest, and
* **every runtime dependency declared in `pyproject.toml` appears in it**, so a
  new dependency added without regenerating the SBOM fails the build.

It then *reports* version drift against the current environment without failing
on it. That is a deliberate change from the original behaviour, which compared
the content digest exactly and returned non-zero on any difference. Exact
comparison cannot pass in CI: this project pins no versions, so pip resolves the
latest release of everything, and a patch release of `ruff` or `starlette` --
neither of which anyone here chose -- turned the build red. It also failed on any
Python minor version other than the one the file was generated on, because
`tomli`, `exceptiongroup` and `backports.asyncio.runner` exist on 3.10 and not on
3.12. A check that cannot pass teaches a team to ignore a red build, which is
worse than not having the check.

`--strict` restores the exact digest comparison. It is the right check when you
are asking "is this the environment the committed benchmark numbers were produced
in?", which is a real question -- just not one a CI runner can answer, since it
never was that environment.

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
import re
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
                {"name": "allaccess:licence", "value": "not declared by the package"}
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
            "tools": [{"vendor": "All-Access", "name": "tools/generate_sbom.py"}],
            "component": {
                "type": "application",
                "bom-ref": "allaccess",
                "name": "allaccess",
                "version": _self_version(),
                "description": (
                    "All-Access -- real-time production decision "
                    "and execution infrastructure"
                ),
                "licenses": [{"license": {"id": "Apache-2.0"}}],
            },
            "properties": [
                {"name": "allaccess:python", "value": platform.python_version()},
                {"name": "allaccess:platform", "value": platform.platform()},
                {"name": "allaccess:content-digest", "value": digest},
            ],
        },
        "components": components,
    }


def _self_version() -> str:
    try:
        return metadata.version("allaccess")
    except metadata.PackageNotFoundError:
        # Not pip-installed in this environment; read the declared version.
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.strip().startswith("version"):
                return line.split("=", 1)[1].strip().strip('"')
        return "0.0.0"


def _normalise(name: str) -> str:
    """PEP 503 normalisation. `PyYAML`, `pyyaml` and `Py_YAML` are one package."""
    return re.sub(r"[-_.]+", "-", name).lower()


def declared_runtime_dependencies() -> set[str]:
    """The runtime dependency names from `pyproject.toml`, normalised.

    Only `[project].dependencies` — not the optional extras, which are by
    definition not installed in every environment. Parsed with `tomllib` where
    it exists (3.11+) and by a small reader where it does not, so this tool has
    no dependency of its own.
    """
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    try:
        import tomllib

        raw = tomllib.loads(text).get("project", {}).get("dependencies", [])
    except ModuleNotFoundError:  # pragma: no cover - Python 3.10
        raw = []
        inside = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("dependencies") and stripped.endswith("["):
                inside = True
                continue
            if inside:
                if stripped.startswith("]"):
                    break
                if stripped.startswith('"') or stripped.startswith("'"):
                    raw.append(stripped.strip(",").strip("\"'"))
    # "uvicorn[standard]>=0.30" -> "uvicorn"
    return {
        _normalise(re.split(r"[\[<>=!~; ]", item, maxsplit=1)[0])
        for item in raw
        if item.strip()
    }


def _digest_of(document: dict[str, Any]) -> str:
    for prop in document.get("metadata", {}).get("properties", []):
        if prop.get("name") == "allaccess:content-digest":
            return str(prop.get("value"))
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CycloneDX SBOM for All-Access")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true",
                        help="verify the committed SBOM covers every declared dependency")
    parser.add_argument("--strict", action="store_true",
                        help="with --check, also require an exact content-digest match "
                             "against this environment")
    args = parser.parse_args(argv)

    fresh = build()
    if args.check:
        if not args.out.exists():
            print(f"{args.out} does not exist; run tools/generate_sbom.py", file=sys.stderr)
            return 1
        try:
            committed = json.loads(args.out.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"{args.out.name} is not valid JSON: {exc}", file=sys.stderr)
            return 1
        if not _digest_of(committed):
            print(f"{args.out.name} carries no content digest", file=sys.stderr)
            return 1

        recorded = {_normalise(str(c["name"])): str(c["version"])
                    for c in committed.get("components", [])}
        missing = sorted(declared_runtime_dependencies() - set(recorded))
        if missing:
            print(
                f"{args.out.name} does not cover every declared runtime dependency.\n"
                f"  missing: {', '.join(missing)}\n"
                "Install the project and regenerate with `python tools/generate_sbom.py`.",
                file=sys.stderr,
            )
            return 1

        current = {_normalise(str(c["name"])): str(c["version"])
                   for c in fresh["components"]}
        drift = sorted(
            (name, recorded[name], current[name])
            for name in set(recorded) & set(current)
            if recorded[name] != current[name]
        )
        print(f"{args.out.name} covers all {len(declared_runtime_dependencies())} declared "
              f"runtime dependencies ({len(recorded)} components recorded)")
        if drift:
            # Reported, never fatal without --strict. See the module docstring.
            print(f"  {len(drift)} component(s) differ from this environment:")
            for name, was, now in drift[:12]:
                print(f"    {name}: recorded {was}, installed {now}")
            if len(drift) > 12:
                print(f"    ... and {len(drift) - 12} more")

        if args.strict and _digest_of(committed) != _digest_of(fresh):
            print(
                f"--strict: {args.out.name} does not describe this environment.\n"
                f"  committed digest {_digest_of(committed)[:16]}\n"
                f"  current   digest {_digest_of(fresh)[:16]}",
                file=sys.stderr,
            )
            return 1
        return 0

    args.out.write_text(json.dumps(fresh, indent=2) + "\n", encoding="utf-8")
    unknown = sum(1 for c in fresh["components"] if not c["licenses"])
    print(f"Wrote {args.out} -- {len(fresh['components'])} components, "
          f"{unknown} with no declared licence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
