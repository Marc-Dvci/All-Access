"""Spatial digital twin of each demonstration location.

Each location is a small navigable graph: nodes are places you can stand or park,
edges are the ways between them with the properties that decide whether a route
works — gradient, clear width, threshold height, surface, whether it is under
cover, whether it is inside a permit boundary.

This is what turns "is the replacement location accessible?" from an opinion into
a shortest-path query with edge filters. `step_free_route()` returns an actual
route or an actual reason there is none, naming the edge that fails and by how
much. The Accessibility and Accommodation Agent quotes that reason verbatim; it
does not paraphrase it, because "the doorway is 760 mm where 850 mm is required"
is a sentence a location manager can act on and "the location may not be suitable"
is not.

The geometry is invented for this fictional harbour. The *thresholds* against
which it is judged live in `STEP_FREE_LIMITS` and are configured production
values, not a claim about any building regulation.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Iterable

# Route acceptability limits for a step-free route, as configured for this
# production. Sourced from the production's access survey standard, which is a
# fictional document; the point is that they are configuration, visible and
# changeable, rather than numbers buried in a function.
STEP_FREE_LIMITS: dict[str, float] = {
    "max_gradient": 1 / 15,      # 1:15, expressed as rise/run
    "max_threshold_mm": 20.0,
    "min_clear_width_mm": 850.0,
    "max_cross_fall": 1 / 40,
    "max_unsheltered_metres": 120.0,
}

WALK_SPEED_M_PER_MIN = 66.0        # ordinary crew walking pace, loaded
EQUIPMENT_SPEED_M_PER_MIN = 28.0   # moving a flight case or a light on a cart
ASSISTED_SPEED_M_PER_MIN = 48.0


@dataclass(frozen=True)
class SpatialNode:
    node_id: str
    name: str
    kind: str          # parking | door | working_position | staging | egress | power | base
    location_id: str
    covered: bool = False
    capacity: int = 0
    notes: str = ""


@dataclass(frozen=True)
class SpatialEdge:
    edge_id: str
    a: str
    b: str
    metres: float
    gradient: float = 0.0        # rise/run, positive means uphill from a to b
    threshold_mm: float = 0.0
    clear_width_mm: float = 1200.0
    cross_fall: float = 0.0
    surface: str = "sealed"      # sealed | cobble | grating | slipway | pontoon | stair
    covered: bool = False
    steps: int = 0
    notes: str = ""

    def step_free(self) -> tuple[bool, str]:
        """Whether this edge can carry a step-free route, and if not, why not.

        Returns the failing measurement rather than a boolean alone. The whole
        value of the spatial twin is in that string.
        """
        if self.steps > 0:
            return False, f"{self.steps} step(s) with no alternative"
        if self.threshold_mm > STEP_FREE_LIMITS["max_threshold_mm"]:
            return (
                False,
                f"threshold {self.threshold_mm:.0f} mm exceeds the "
                f"{STEP_FREE_LIMITS['max_threshold_mm']:.0f} mm limit",
            )
        if abs(self.gradient) > STEP_FREE_LIMITS["max_gradient"]:
            return (
                False,
                f"gradient 1:{1 / abs(self.gradient):.0f} is steeper than the "
                f"1:{1 / STEP_FREE_LIMITS['max_gradient']:.0f} limit",
            )
        if self.clear_width_mm < STEP_FREE_LIMITS["min_clear_width_mm"]:
            return (
                False,
                f"clear width {self.clear_width_mm:.0f} mm is below the "
                f"{STEP_FREE_LIMITS['min_clear_width_mm']:.0f} mm minimum",
            )
        if abs(self.cross_fall) > STEP_FREE_LIMITS["max_cross_fall"]:
            return False, f"cross fall 1:{1 / abs(self.cross_fall):.0f} exceeds the limit"
        if self.surface in ("slipway", "stair"):
            return False, f"{self.surface} surface is not a step-free route"
        return True, ""

    def minutes(self, speed: float = WALK_SPEED_M_PER_MIN) -> float:
        # Gradient costs time in both directions: uphill is effort, downhill with
        # a loaded cart is caution.
        penalty = 1.0 + min(abs(self.gradient) * 6.0, 0.9)
        rough = 1.25 if self.surface in ("cobble", "grating", "pontoon") else 1.0
        return (self.metres / speed) * penalty * rough


@dataclass(frozen=True)
class RouteResult:
    found: bool
    nodes: tuple[str, ...] = ()
    edges: tuple[str, ...] = ()
    metres: float = 0.0
    minutes: float = 0.0
    blocked_by: tuple[str, ...] = ()
    reason: str = ""
    uncovered_metres: float = 0.0

    def describe(self) -> str:
        if self.found:
            # ASCII separator deliberately: these strings are printed to the
            # Windows console by the CLI, where cp1252 cannot encode an arrow.
            return f"{self.metres:.0f} m, {self.minutes:.1f} min via {' > '.join(self.nodes)}"
        return self.reason or "no route"


class SpatialTwin:
    """The navigable model of one or more locations.

    Edges are undirected but gradient is directional, so the graph stores each
    edge once and flips the sign when traversed the other way.
    """

    def __init__(self, nodes: Iterable[SpatialNode], edges: Iterable[SpatialEdge]) -> None:
        self.nodes: dict[str, SpatialNode] = {n.node_id: n for n in nodes}
        self.edges: dict[str, SpatialEdge] = {e.edge_id: e for e in edges}
        self._adj: dict[str, list[tuple[str, str]]] = {}
        for e in self.edges.values():
            self._adj.setdefault(e.a, []).append((e.b, e.edge_id))
            self._adj.setdefault(e.b, []).append((e.a, e.edge_id))
        self.blocked: set[str] = set()

    def block(self, edge_id: str) -> None:
        """Mark an edge impassable — a flooded approach, a lost loading zone."""
        self.blocked.add(edge_id)

    def unblock(self, edge_id: str) -> None:
        self.blocked.discard(edge_id)

    def nodes_at(self, location_id: str) -> tuple[SpatialNode, ...]:
        return tuple(n for n in self.nodes.values() if n.location_id == location_id)

    def _oriented(self, edge: SpatialEdge, frm: str) -> SpatialEdge:
        if edge.a == frm:
            return edge
        return SpatialEdge(
            edge_id=edge.edge_id, a=edge.b, b=edge.a, metres=edge.metres,
            gradient=-edge.gradient, threshold_mm=edge.threshold_mm,
            clear_width_mm=edge.clear_width_mm, cross_fall=edge.cross_fall,
            surface=edge.surface, covered=edge.covered, steps=edge.steps, notes=edge.notes,
        )

    def route(
        self,
        start: str,
        goal: str,
        *,
        step_free: bool = False,
        speed: float = WALK_SPEED_M_PER_MIN,
        min_width_mm: float = 0.0,
        require_covered: bool = False,
        forbidden_nodes: set[str] | None = None,
        excluded_edges: set[str] | None = None,
    ) -> RouteResult:
        """Shortest route by time, subject to edge filters.

        Dijkstra rather than A*: these graphs are tens of nodes, and an admissible
        heuristic would need coordinates the access surveys do not provide.
        """
        if start not in self.nodes or goal not in self.nodes:
            unknown = start if start not in self.nodes else goal
            return RouteResult(False, reason=f"unknown node: {unknown}")
        if start == goal:
            return RouteResult(True, nodes=(start,), metres=0.0, minutes=0.0)

        dist: dict[str, float] = {start: 0.0}
        prev: dict[str, tuple[str, str]] = {}
        seen: set[str] = set()
        rejected: dict[str, str] = {}
        heap: list[tuple[float, str]] = [(0.0, start)]

        while heap:
            cost, node = heapq.heappop(heap)
            if node in seen:
                continue
            seen.add(node)
            if node == goal:
                break
            for neighbour, edge_id in self._adj.get(node, []):
                if edge_id in self.blocked:
                    rejected[edge_id] = "blocked"
                    continue
                if excluded_edges and edge_id in excluded_edges:
                    continue
                # A forbidden node may still be the goal; it just cannot be a
                # stepping stone.
                if forbidden_nodes and neighbour in forbidden_nodes and neighbour != goal:
                    continue
                edge = self._oriented(self.edges[edge_id], node)
                if step_free:
                    ok, why = edge.step_free()
                    if not ok:
                        rejected[edge_id] = why
                        continue
                if min_width_mm and edge.clear_width_mm < min_width_mm:
                    rejected[edge_id] = (
                        f"clear width {edge.clear_width_mm:.0f} mm is below the "
                        f"{min_width_mm:.0f} mm required for this equipment"
                    )
                    continue
                if require_covered and not edge.covered:
                    rejected[edge_id] = "not under cover"
                    continue
                nxt = cost + edge.minutes(speed)
                if nxt < dist.get(neighbour, float("inf")):
                    dist[neighbour] = nxt
                    prev[neighbour] = (node, edge_id)
                    heapq.heappush(heap, (nxt, neighbour))

        if goal not in dist:
            # Report only the edges that actually stopped *this* search: ones
            # incident to a node the search reached. Without this filter the
            # blocker list is every unusable edge in the whole graph, which
            # names the wrong problem — and naming the wrong problem is worse
            # than saying nothing, because a location manager will go and fix it.
            frontier: list[tuple[int, str, str]] = []
            for eid, why in rejected.items():
                e = self.edges[eid]
                if e.a not in seen and e.b not in seen:
                    continue
                # An edge touching the goal is the most useful thing to report.
                rank = 0 if goal in (e.a, e.b) else 1
                frontier.append((rank, eid, why))
            frontier.sort()
            blockers = tuple(f"{eid}: {why}" for _, eid, why in frontier)
            reason = (
                f"no route from {start} to {goal} satisfying the requirement"
                + (f" -- {blockers[0]}" if blockers else "")
            )
            return RouteResult(False, blocked_by=blockers, reason=reason)

        path_nodes: list[str] = [goal]
        path_edges: list[str] = []
        metres = 0.0
        uncovered = 0.0
        cur = goal
        while cur != start:
            cur, edge_id = prev[cur]
            path_nodes.append(cur)
            path_edges.append(edge_id)
            e = self.edges[edge_id]
            metres += e.metres
            if not e.covered:
                uncovered += e.metres
        path_nodes.reverse()
        path_edges.reverse()
        return RouteResult(
            True, tuple(path_nodes), tuple(path_edges), metres, dist[goal],
            uncovered_metres=uncovered,
        )

    def step_free_route(self, start: str, goal: str) -> RouteResult:
        return self.route(start, goal, step_free=True, speed=ASSISTED_SPEED_M_PER_MIN)

    def equipment_route(self, start: str, goal: str, width_mm: float = 900.0) -> RouteResult:
        return self.route(start, goal, speed=EQUIPMENT_SPEED_M_PER_MIN, min_width_mm=width_mm)

    def egress_routes(self, frm: str) -> tuple[RouteResult, ...]:
        """Independent emergency egress routes from a working position.

        "Independent" means edge-disjoint, not merely ending somewhere different.
        Two exits reached down the same corridor are one means of escape once
        that corridor is blocked, which is the entire reason the requirement
        exists.

        Computed greedily: take the shortest route to any exit, remove its edges,
        take the shortest route to a *different* exit from what remains, and so
        on. Greedy edge-disjoint routing is not guaranteed to find the maximum
        possible number of disjoint routes, so this can undercount — which is the
        safe direction to be wrong in for a safety check.

        Egress nodes are also barred as intermediate hops: a route that escapes
        through one exit in order to reach another is not a second route, and
        treating it as one is how a single point of failure gets counted twice.
        """
        exits = [n.node_id for n in self.nodes.values() if n.kind == "egress"]
        if not exits:
            return ()
        results: list[RouteResult] = []
        used_edges: set[str] = set()
        remaining = set(exits)

        while remaining:
            best: RouteResult | None = None
            best_exit: str | None = None
            for exit_node in sorted(remaining):
                forbidden = {e for e in exits if e != exit_node}
                r = self.route(frm, exit_node, forbidden_nodes=forbidden,
                               excluded_edges=used_edges)
                if r.found and (best is None or r.minutes < best.minutes):
                    best, best_exit = r, exit_node
            if best is None or best_exit is None:
                break
            results.append(best)
            used_edges.update(best.edges)
            remaining.discard(best_exit)
        return tuple(results)

    def staging_capacity(self, location_id: str) -> int:
        return sum(n.capacity for n in self.nodes_at(location_id) if n.kind == "staging")


def _harbour_wall() -> tuple[list[SpatialNode], list[SpatialEdge]]:
    nodes = [
        SpatialNode("HW-PARK", "North car park", "parking", "LOC-HARBOUR-WALL", capacity=12),
        SpatialNode("HW-RAMP-TOP", "Ramp head", "staging", "LOC-HARBOUR-WALL", capacity=4),
        SpatialNode("HW-WALL-W", "Wall, west end", "staging", "LOC-HARBOUR-WALL", capacity=8),
        SpatialNode("HW-WALL-E", "Wall, east end", "working_position", "LOC-HARBOUR-WALL"),
        SpatialNode("HW-BASE", "Unit base", "base", "LOC-HARBOUR-WALL", capacity=45),
        SpatialNode("HW-GANGWAY", "Berth 3 gangway", "door", "LOC-HARBOUR-WALL"),
        SpatialNode("HW-EGRESS-N", "North gate", "egress", "LOC-HARBOUR-WALL"),
        SpatialNode("HW-EGRESS-S", "Slip gate", "egress", "LOC-HARBOUR-WALL"),
        SpatialNode("HW-POWER", "Generator position", "power", "LOC-HARBOUR-WALL"),
    ]
    edges = [
        SpatialEdge("HW-E1", "HW-PARK", "HW-RAMP-TOP", 34.0, gradient=1 / 18,
                    clear_width_mm=1400, surface="sealed"),
        SpatialEdge("HW-E2", "HW-RAMP-TOP", "HW-BASE", 26.0, clear_width_mm=1600),
        SpatialEdge("HW-E3", "HW-BASE", "HW-WALL-W", 41.0, clear_width_mm=2200, surface="sealed"),
        SpatialEdge("HW-E4", "HW-WALL-W", "HW-WALL-E", 88.0, clear_width_mm=2600,
                    surface="sealed", cross_fall=1 / 60),
        SpatialEdge("HW-E5", "HW-WALL-E", "HW-GANGWAY", 12.0, gradient=1 / 9,
                    clear_width_mm=900, surface="pontoon",
                    notes="Gangway gradient varies with tide; 1:9 at low water."),
        SpatialEdge("HW-E6", "HW-BASE", "HW-EGRESS-N", 30.0, clear_width_mm=1800),
        SpatialEdge("HW-E7", "HW-WALL-W", "HW-EGRESS-S", 55.0, clear_width_mm=1200),
        SpatialEdge("HW-E8", "HW-BASE", "HW-POWER", 22.0, clear_width_mm=1500),
        # Second means of escape from the east end and from the berth, so that
        # neither position depends on a single route back along the wall. Both
        # are surveyed; egress counting dedups by first leg, so these only count
        # because they genuinely diverge.
        SpatialEdge("HW-E9", "HW-WALL-E", "HW-EGRESS-S", 46.0, clear_width_mm=1100,
                    surface="sealed", notes="Steps and gate at the east end to the slip road."),
        SpatialEdge("HW-E10", "HW-GANGWAY", "HW-EGRESS-S", 38.0, clear_width_mm=900,
                    surface="pontoon", notes="Secondary means of escape from the berth."),
    ]
    return nodes, edges


def _net_loft() -> tuple[list[SpatialNode], list[SpatialEdge]]:
    nodes = [
        SpatialNode("NL-DOOR", "Loft door", "door", "LOC-NET-LOFT", covered=True),
        SpatialNode("NL-FLOOR", "Loft floor", "working_position", "LOC-NET-LOFT", covered=True),
        SpatialNode("NL-STAGE", "Loft staging", "staging", "LOC-NET-LOFT",
                    capacity=10, covered=True),
        SpatialNode("NL-QUIET", "Quiet room", "working_position", "LOC-NET-LOFT", covered=True),
        SpatialNode("NL-EGRESS-A", "Loft door egress", "egress", "LOC-NET-LOFT"),
        SpatialNode("NL-EGRESS-B", "Yard door egress", "egress", "LOC-NET-LOFT"),
    ]
    edges = [
        SpatialEdge("NL-E1", "HW-WALL-W", "NL-DOOR", 24.0, clear_width_mm=1800, surface="sealed"),
        SpatialEdge("NL-E2", "NL-DOOR", "NL-FLOOR", 6.0, threshold_mm=12.0,
                    clear_width_mm=1200, covered=True),
        SpatialEdge("NL-E3", "NL-FLOOR", "NL-STAGE", 14.0, clear_width_mm=1600, covered=True),
        SpatialEdge("NL-E4", "NL-FLOOR", "NL-QUIET", 11.0, clear_width_mm=900, covered=True),
        SpatialEdge("NL-E5", "NL-FLOOR", "NL-EGRESS-A", 8.0, clear_width_mm=1200, covered=True),
        SpatialEdge("NL-E6", "NL-STAGE", "NL-EGRESS-B", 17.0, clear_width_mm=1100, covered=True),
    ]
    return nodes, edges


def _boatshed() -> tuple[list[SpatialNode], list[SpatialEdge]]:
    """The replacement location that looks right and is not.

    Every failure below is a specific measurement: a 140 mm threshold, a 760 mm
    doorway, a 1:7 internal ramp. This is the data that lets the system say
    exactly why the obvious plan is rejected, instead of "accessibility concern".
    """
    nodes = [
        SpatialNode("BS-PARK", "Yard parking", "parking", "LOC-BOATSHED", capacity=8),
        SpatialNode("BS-APRON", "Yard apron", "staging", "LOC-BOATSHED", capacity=6),
        SpatialNode("BS-MAIN-DOOR", "Main shed door", "door", "LOC-BOATSHED"),
        SpatialNode("BS-SIDE-DOOR", "Side personnel door", "door", "LOC-BOATSHED"),
        SpatialNode("BS-FLOOR", "Shed floor", "working_position", "LOC-BOATSHED", covered=True),
        SpatialNode("BS-MEZZ", "Mezzanine", "staging", "LOC-BOATSHED", capacity=4, covered=True),
        SpatialNode("BS-EGRESS-A", "Main door egress", "egress", "LOC-BOATSHED"),
        SpatialNode("BS-EGRESS-B", "Yard egress", "egress", "LOC-BOATSHED"),
    ]
    edges = [
        # The yard apron itself is passable. The boatshed's problems are at the
        # two doors, and a route analysis that stopped in the car park would
        # hide them.
        SpatialEdge("BS-E1", "BS-PARK", "BS-APRON", 40.0, clear_width_mm=3000,
                    surface="cobble", cross_fall=1 / 55),
        # The main door: wide enough, but a 140 mm lip and a 1:7 ramp inside.
        SpatialEdge("BS-E2", "BS-APRON", "BS-MAIN-DOOR", 9.0, threshold_mm=140.0,
                    clear_width_mm=3600, surface="cobble",
                    notes="140 mm cill across the full width of the main door."),
        SpatialEdge("BS-E3", "BS-MAIN-DOOR", "BS-FLOOR", 7.0, gradient=1 / 7,
                    clear_width_mm=3600, covered=True,
                    notes="Internal ramp cast at 1:7 for boat trolleys."),
        # The side door: level, but 760 mm clear.
        SpatialEdge("BS-E4", "BS-APRON", "BS-SIDE-DOOR", 18.0, threshold_mm=15.0,
                    clear_width_mm=760.0, surface="cobble",
                    notes="Personnel door, 760 mm clear opening."),
        SpatialEdge("BS-E5", "BS-SIDE-DOOR", "BS-FLOOR", 5.0, clear_width_mm=760.0, covered=True),
        SpatialEdge("BS-E6", "BS-FLOOR", "BS-MEZZ", 6.0, steps=9, clear_width_mm=900,
                    surface="stair", covered=True),
        SpatialEdge("BS-E7", "BS-FLOOR", "BS-EGRESS-A", 12.0, threshold_mm=140.0,
                    clear_width_mm=3600),
        SpatialEdge("BS-E8", "BS-APRON", "BS-EGRESS-B", 25.0, clear_width_mm=2400,
                    surface="cobble"),
        SpatialEdge("BS-E9", "HW-PARK", "BS-PARK", 1400.0, clear_width_mm=3000, surface="sealed",
                    notes="Vehicle route around the head of the harbour."),
    ]
    return nodes, edges


def _slipway_and_quay() -> tuple[list[SpatialNode], list[SpatialEdge]]:
    nodes = [
        SpatialNode("SW-TOP", "Slip head", "staging", "LOC-SLIPWAY", capacity=5),
        SpatialNode("SW-FACE", "Slip face", "working_position", "LOC-SLIPWAY"),
        SpatialNode("SW-EGRESS", "Slip gate", "egress", "LOC-SLIPWAY"),
        SpatialNode("QS-NORTH", "North quay", "working_position", "LOC-QUAYSIDE"),
        SpatialNode("QS-PARK", "Quay parking", "parking", "LOC-QUAYSIDE", capacity=6),
        SpatialNode("QS-EGRESS", "Quay gate", "egress", "LOC-QUAYSIDE"),
    ]
    edges = [
        SpatialEdge("SW-E1", "HW-WALL-W", "SW-TOP", 210.0, clear_width_mm=2000, surface="sealed"),
        SpatialEdge("SW-E2", "SW-TOP", "SW-FACE", 30.0, gradient=1 / 8, clear_width_mm=4000,
                    surface="slipway", notes="Wet, weeded, 1:8. Not a step-free route."),
        SpatialEdge("SW-E3", "SW-TOP", "SW-EGRESS", 18.0, clear_width_mm=1400),
        SpatialEdge("QS-E1", "QS-PARK", "QS-NORTH", 45.0, clear_width_mm=2400, surface="sealed"),
        SpatialEdge("QS-E2", "QS-NORTH", "QS-EGRESS", 22.0, clear_width_mm=1800),
        SpatialEdge("QS-E3", "HW-WALL-W", "QS-NORTH", 260.0, clear_width_mm=2200, surface="sealed"),
    ]
    return nodes, edges


def build_twin() -> SpatialTwin:
    nodes: list[SpatialNode] = []
    edges: list[SpatialEdge] = []
    for part in (_harbour_wall(), _net_loft(), _boatshed(), _slipway_and_quay()):
        nodes.extend(part[0])
        edges.extend(part[1])
    return SpatialTwin(nodes, edges)


SPATIAL_TWIN = build_twin()


# Where a person or a piece of equipment arriving at a location actually lands,
# and where the work happens. Without this mapping the twin is a pretty graph
# nobody queries.
LOCATION_ARRIVAL: dict[str, str] = {
    "LOC-HARBOUR-WALL": "HW-PARK",
    "LOC-NET-LOFT": "HW-PARK",
    "LOC-BOATSHED": "BS-PARK",
    "LOC-SLIPWAY": "HW-PARK",
    "LOC-QUAYSIDE": "QS-PARK",
    "LOC-BOAT-WHEELHOUSE": "HW-PARK",
    "LOC-BOAT-ENGINE": "HW-PARK",
}

LOCATION_WORKING_POSITION: dict[str, str] = {
    "LOC-HARBOUR-WALL": "HW-WALL-E",
    "LOC-NET-LOFT": "NL-FLOOR",
    "LOC-BOATSHED": "BS-FLOOR",
    "LOC-SLIPWAY": "SW-FACE",
    "LOC-QUAYSIDE": "QS-NORTH",
    "LOC-BOAT-WHEELHOUSE": "HW-GANGWAY",
    "LOC-BOAT-ENGINE": "HW-GANGWAY",
}


# A declared step-free working position from which the same job can be done when
# the primary working position is not step-free.
#
# This is how productions actually solve it: the 1st AC works the boat sets from
# a monitor position on the wall rather than from inside the wheelhouse. It is a
# real, surveyed, approved arrangement — so the constraint is satisfied, and it
# is satisfied by naming the position, not by waving the requirement through.
#
# The boatshed has no entry, and that absence is the whole point of the hero
# scenario: there is nowhere on that site to put an equivalent position.
LOCATION_ACCESSIBLE_ALTERNATE: dict[str, str] = {
    "LOC-BOAT-WHEELHOUSE": "HW-WALL-E",
    "LOC-BOAT-ENGINE": "HW-WALL-E",
    "LOC-SLIPWAY": "SW-TOP",
}


def assess_location_access(location_id: str, twin: SpatialTwin | None = None) -> dict[str, object]:
    """Everything the access, safety and spatial agents need about one location.

    Returned as data, not prose, so the agents can cite it and the benchmark can
    check it.
    """
    tw = twin or SPATIAL_TWIN
    arrival = LOCATION_ARRIVAL.get(location_id)
    working = LOCATION_WORKING_POSITION.get(location_id)
    if not arrival or not working:
        return {"location_id": location_id, "modelled": False}

    step_free = tw.step_free_route(arrival, working)
    alternate_node = LOCATION_ACCESSIBLE_ALTERNATE.get(location_id)
    alternate = tw.step_free_route(arrival, alternate_node) if alternate_node else None
    walking = tw.route(arrival, working)
    equipment = tw.equipment_route(arrival, working, width_mm=900.0)
    heavy = tw.equipment_route(arrival, working, width_mm=1200.0)
    egress = tw.egress_routes(working)

    return {
        "location_id": location_id,
        "modelled": True,
        "arrival_node": arrival,
        "working_node": working,
        "step_free": step_free.found,
        "step_free_route": step_free.describe(),
        "step_free_blockers": list(step_free.blocked_by),
        "accessible_alternate_node": alternate_node,
        "accessible_alternate": bool(alternate and alternate.found),
        "accessible_alternate_route": alternate.describe() if alternate else None,
        # The requirement is satisfied if either the working position itself is
        # step-free or a surveyed step-free alternate position exists.
        "step_free_satisfied": step_free.found or bool(alternate and alternate.found),
        "walk_minutes": round(walking.minutes, 1) if walking.found else None,
        "walk_metres": round(walking.metres, 0) if walking.found else None,
        "equipment_minutes": round(equipment.minutes, 1) if equipment.found else None,
        "equipment_route_found": equipment.found,
        "heavy_equipment_route_found": heavy.found,
        "heavy_equipment_blockers": list(heavy.blocked_by),
        "egress_route_count": len(egress),
        "egress_minutes": [round(r.minutes, 1) for r in egress],
        "staging_capacity": tw.staging_capacity(location_id),
        "uncovered_metres": round(walking.uncovered_metres, 0) if walking.found else None,
    }
