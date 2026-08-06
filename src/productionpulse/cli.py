"""Command line interface.

`productionpulse hero` runs the complete hero workflow offline: storm event to
Confluent, digital-twin scope, parallel expert assessment, deterministic
planning, robustness simulation, human approval, saga execution across thirteen
systems, reconciliation, a genuine verification block, resolution, and the
lineage and replay proofs. Nine assertions have to pass or it exits non-zero.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .agents.coordinator import ProductionCoordinator
from .agents.core import build_reasoner
from .constraints.registry import CONSTRAINTS, active_constraints, constraint_set_hash
from .contracts import TargetSystem
from .disruptions import STORM_SCENARIO, build_source_event, scenario_problem
from .production import world as w
from .stream import governance
from .stream.bus import build_bus
from .systems import build_systems
from .twin import build_twin, certify_baseline

app = typer.Typer(add_completion=False, help="ProductionPulse Inclusive")
console = Console()


def _rule(title: str) -> None:
    console.print()
    console.rule(f"[bold]{title}", style="cyan")


@app.command()
def hero(
    reasoning: str = typer.Option("offline", help="offline | gemini"),
    scenarios: int = typer.Option(200, help="simulation ensemble size"),
    json_out: Path = typer.Option(None, "--json", help="write the run record here"),
) -> None:
    """Run the complete hero disruption end to end."""
    assertions: list[tuple[str, bool, str]] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        assertions.append((name, passed, detail))

    _rule("1. Production baseline")
    twin = build_twin()
    baseline = certify_baseline(twin)
    console.print(
        f"Production: [bold]{w.PRODUCTION_TITLE}[/] — {len(twin.entities)} entities, "
        f"{len(twin.relationships)} relationships, "
        f"{sum(len(v) for v in twin.facts.values())} temporal facts"
    )
    console.print(
        f"Baseline certification: [bold]{baseline.state}[/] "
        f"({baseline.checked} checks, {len(baseline.issues)} issues)"
    )
    check("baseline certifies ready", baseline.state == "ready",
          f"{len(baseline.blocking)} blocking issue(s)")

    bus = build_bus(w.PRODUCTION_ID)
    console.print(
        f"Event backbone: [bold]{bus.name}[/] | schema registry: "
        f"[bold]{bus.registry.name}[/] | {len(bus.registry.subjects())} governed subjects"
    )
    console.print(
        f"Constraint registry: {len(CONSTRAINTS)} constraints, "
        f"hash {constraint_set_hash(active_constraints())[:16]}"
    )

    _rule("2. The disruption")
    problem = scenario_problem(STORM_SCENARIO, twin=twin)
    source = build_source_event(bus, STORM_SCENARIO)
    console.print(
        f"[bold]{STORM_SCENARIO.title}[/]\n{STORM_SCENARIO.description}"
    )
    console.print(
        f"Event {source.envelope.event_id} on topic "
        f"[cyan]{source.envelope.event_type.value}[/] "
        f"(authority: {source.envelope.authority.value})"
    )

    _rule("3. Assessment, planning and decision")
    systems = build_systems(w.PRODUCTION_ID, hold_department="props")
    coordinator = ProductionCoordinator(
        bus, systems, reasoner=build_reasoner(reasoning)
    )
    outcome = coordinator.handle(
        problem, source, title=STORM_SCENARIO.title,
        scenario_id=STORM_SCENARIO.scenario_id, scenarios=scenarios,
    )

    findings = Table(title="Expert findings", show_lines=False)
    for column in ("Agent", "Status", "Headline"):
        findings.add_column(column, overflow="fold")
    for finding in outcome.findings:
        colour = {
            "blocking": "red", "at_risk": "yellow",
            "clear": "green", "abstained": "dim",
        }.get(finding.status.value, "white")
        findings.add_row(
            finding.producer.replace("_agent", "").replace("_", " "),
            f"[{colour}]{finding.status.value}[/]",
            finding.headline[:110],
        )
    console.print(findings)

    abstained = [f for f in outcome.findings if f.status.value == "abstained"]
    console.print(
        f"{len(outcome.findings)} findings from {len({f.producer for f in outcome.findings})} "
        f"agents; {len(abstained)} correct abstention(s)"
    )

    _rule("4. Plans")
    table = Table(title="Feasible plans (Pareto front marked)")
    # Simulated columns are expected delay, worst credible delay and recovery
    # margin. On-time probability is deliberately not shown: it is 0.00 for
    # every plan under the configured uncertainty, so as a comparison column it
    # would look like information and carry none. See robust.compare().
    for column in ("", "Strategy", "Delay", "Cost", "Overtime", "Changed", "Risk",
                   "Sim. delay", "Worst", "Margin"):
        table.add_column(column, overflow="fold")
    for plan in outcome.plans:
        report = outcome.robustness.get(plan.plan_id)
        table.add_row(
            "*" if plan.plan_id in outcome.pareto_front else " ",
            plan.label,
            f"{plan.objectives.delay_minutes:.0f}",
            f"{plan.objectives.cost_delta:,.0f}",
            f"{plan.objectives.overtime_minutes:.0f}",
            str(plan.objectives.changed_assignments),
            f"{plan.objectives.operational_risk:.0f}",
            f"{report.expected_delay_minutes:.0f}" if report else "-",
            f"{report.worst_credible_delay_minutes:.0f}" if report else "-",
            f"{report.recovery_margin_minutes:.0f}" if report else "-",
        )
    console.print(table)

    rejected = Table(title="Rejected plans, with the minimal conflict set")
    for column in ("Strategy", "Conflict", "Why", "Permitted?"):
        rejected.add_column(column, overflow="fold")
    for plan in outcome.rejected:
        for conflict in plan.conflicts:
            rejected.add_row(
                plan.label,
                ", ".join(conflict.constraint_ids),
                conflict.production_language[:150],
                "no" if conflict.change_permitted is False else
                ("yes" if conflict.change_permitted else "-"),
            )
    console.print(rejected)

    check("at least one feasible plan", bool(outcome.plans), f"{len(outcome.plans)} feasible")
    check("plans are structurally diverse",
          len({p.strategy for p in outcome.plans}) >= 2,
          f"{len({p.strategy for p in outcome.plans})} distinct strategies")
    check("every rejected plan carries a conflict set",
          all(p.conflicts for p in outcome.rejected),
          f"{len(outcome.rejected)} rejected")
    check("no published feasible plan violates a hard constraint",
          all(p.proof and p.proof.validated and p.feasible for p in outcome.plans),
          "independently revalidated")

    selected = outcome.selected
    if selected is None:
        console.print("[red]No plan was approved.[/]")
        raise typer.Exit(1)

    _rule("5. Decision and execution")
    console.print(
        Panel(
            f"[bold]{selected.label}[/]\n{selected.rationale}\n\n"
            f"Approved by: "
            f"{', '.join(a.role.value for a in outcome.disruption.approvals)}\n"
            f"Plan hash {selected.content_hash()[:16]} bound to constraint hash "
            f"{constraint_set_hash(active_constraints())[:16]}",
            title="Approved plan",
        )
    )

    saga = outcome.saga
    commands = Table(title="Command execution")
    for column in ("Target", "Action", "Status", "Detail"):
        commands.add_column(column, overflow="fold")
    for step in (saga.steps if saga else []):
        colour = {"completed": "green", "rejected": "red"}.get(step.status.value, "yellow")
        commands.add_row(
            step.command.target.value, step.command.action,
            f"[{colour}]{step.status.value}[/]",
            (step.result.detail if step.result else "")[:80],
        )
    console.print(commands)

    check("every command completed",
          bool(saga) and saga.all_complete,
          f"{saga.completed}/{len(saga.steps)} completed" if saga else "no saga")

    _rule("6. Verification")
    report = outcome.verification
    verification_table = Table(title="Verification assertions")
    for column in ("", "Assertion", "Expected", "Observed"):
        verification_table.add_column(column, overflow="fold")
    for assertion in (report.assertions if report else []):
        mark = "[green]PASS[/]" if assertion.passed else (
            "[red]FAIL[/]" if assertion.critical else "[yellow]warn[/]"
        )
        verification_table.add_row(
            mark, assertion.name, assertion.expected[:44], assertion.observed[:44]
        )
    console.print(verification_table)

    if outcome.blocked_then_resolved:
        console.print(
            "[yellow]Verification blocked readiness on a missing department acceptance, "
            "then cleared once the department accepted.[/]"
        )
    check("verification blocked on a real missing acceptance",
          outcome.blocked_then_resolved, "props had not accepted")
    check("production is ready", bool(report and report.ready),
          f"{report.passed}/{len(report.assertions)} assertions" if report else "")

    _rule("7. Access arrangements")
    access = Table(title="Approved arrangements under the approved plan")
    for column in ("Requirement", "Status", "Mechanism"):
        access.add_column(column, overflow="fold")
    for implementation in selected.access:
        access.add_row(
            implementation.requirement,
            "[green]preserved[/]" if implementation.satisfied else "[red]AT RISK[/]",
            implementation.mechanism[:70],
        )
    console.print(access)
    check("every approved access arrangement preserved",
          all(a.satisfied for a in selected.access),
          f"{sum(1 for a in selected.access if a.satisfied)}/{len(selected.access)}")

    _rule("8. Stream governance, lineage and replay")
    events = bus.all_events()
    chain_ok, chain_problems = bus.verify_chain()
    lineage = governance.trace(events, source.envelope.event_id)
    replay = governance.verify_replay(events, coordinator.views)
    summary = governance.catalog_summary()

    console.print(
        f"Events: {len(events)} across {len(bus.topics)} topics | "
        f"contracts: {summary['contracts']} governing {summary['governed_by_contract']}"
        f"/{summary['topics']} subjects"
    )
    console.print(
        f"Dead letters: {len(bus.dead_letters)} | duplicates suppressed: "
        f"{bus.duplicates_suppressed} | inbox suppressed: "
        f"{coordinator.saga.inbox.suppressed}"
    )
    console.print(f"Hash chain: {'intact' if chain_ok else 'BROKEN'}")
    console.print(
        f"Lineage from the storm event: {len(lineage.nodes)} downstream events, "
        f"depth {lineage.depth}"
    )
    for line in lineage.path_summary()[:8]:
        console.print(f"  [dim]{line[:120]}[/]")
    console.print(
        f"Replay: {replay.replayed_events} events reproduce the live state "
        f"{'exactly' if replay.identical else 'with differences'}"
    )
    check("hash chain intact", chain_ok, "; ".join(chain_problems[:2]))
    check("replay reproduces live state exactly", replay.identical,
          "; ".join(replay.differences[:2]))

    _rule("9. IBM Bob-modernized call-sheet connector")
    connector = systems[TargetSystem.CALL_SHEET]
    state = connector.state()
    console.print(json.dumps(state, indent=2)[:700])

    _rule("Result")
    results = Table()
    for column in ("", "Assertion", "Detail"):
        results.add_column(column, overflow="fold")
    for name, passed, detail in assertions:
        results.add_row("[green]PASS[/]" if passed else "[red]FAIL[/]", name, detail[:60])
    console.print(results)

    passed = sum(1 for _n, ok, _d in assertions if ok)
    console.print(
        f"\n[bold]{passed}/{len(assertions)} assertions passed[/] | "
        f"{len(events)} events | reasoning plane: {coordinator.reasoner.plane} | "
        f"{outcome.timings.get('total_ms', 0):.0f} ms"
    )

    if json_out:
        record = {
            "assertions": [
                {"name": n, "passed": ok, "detail": d} for n, ok, d in assertions
            ],
            "events": len(events),
            "plans_feasible": len(outcome.plans),
            "plans_rejected": len(outcome.rejected),
            "selected": selected.plan_id,
            "ready": bool(report and report.ready),
            "timings": outcome.timings,
            "reasoning_plane": coordinator.reasoner.plane,
        }
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(record, indent=2), encoding="utf-8")
        console.print(f"Run record written to {json_out}")

    if passed != len(assertions):
        raise typer.Exit(1)


@app.command()
def baseline() -> None:
    """Certify the production baseline and print the digital twin summary."""
    twin = build_twin()
    report = certify_baseline(twin)
    console.print(f"State: [bold]{report.state}[/] after {report.checked} checks")
    console.print(f"Twin state hash: {report.state_hash[:32]}")
    table = Table(title="Baseline issues")
    for column in ("Severity", "Code", "Subject", "Message"):
        table.add_column(column, overflow="fold")
    for issue in report.issues:
        table.add_row(issue.severity, issue.code, issue.subject, issue.message[:90])
    console.print(table if report.issues else "[green]No issues.[/]")


@app.command()
def contracts() -> None:
    """Print the stream catalogue and data contracts."""
    summary = governance.catalog_summary()
    console.print(json.dumps(summary, indent=2))
    table = Table(title="Stream catalogue")
    for column in ("Domain", "Topic", "Owner", "Classification"):
        table.add_column(column, overflow="fold")
    for entry in governance.catalog():
        table.add_row(entry.domain, entry.topic, entry.owner, entry.classification)
    console.print(table)


@app.command()
def spatial(location: str = typer.Argument(..., help="e.g. LOC-BOATSHED")) -> None:
    """Print the spatial access assessment for one location."""
    from .production import spatial as sp

    console.print(json.dumps(sp.assess_location_access(location), indent=2, default=str))


def main() -> None:  # pragma: no cover - console entry point
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
