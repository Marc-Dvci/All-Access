"""Build the production digital twin from the authorised production records.

This is §4.1 of the plan — production setup and baseline certification. Every
entity and relationship in the twin traces to a record in `production/`, and the
build ends with a consistency check that must pass before the day is allowed to
start. The checks are real: they find double-booked resources, impossible
travel, missing access arrangements, inconsistent call times and permit gaps in
the *baseline* schedule, before any disruption happens.

The baseline schedule in `world.py` is deliberately clean, so `certify_baseline()`
returns READY on an untouched world. The benchmark then perturbs it, and the
same function is what detects the damage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..contracts import Authority, Classification
from ..production import script as scr
from ..production import world as w
from .graph import ProductionTwin

BUILD_SOURCE = "production_records"


def _register_entities(twin: ProductionTwin) -> None:
    """Declare every entity the build will reference. No facts, no edges."""
    for unit in w.UNITS:
        twin.add_entity(unit.unit_id, "unit", unit.name)
    for dept in {c.department for c in w.CREW}:
        twin.add_entity(f"DEPT-{dept.value}", "department", dept.value.replace("_", " ").title())
    twin.add_entity("SCRIPT-1", "script", scr.TITLE)
    for day in scr.STORY_DAYS:
        twin.add_entity(f"STORYDAY-{day.number}", "story_day", day.label)
    for character_id, meta in scr.CHARACTERS.items():
        twin.add_entity(character_id, "character", str(meta["name"]))
    for scene in scr.SCENES:
        twin.add_entity(scene.scene_id, "scene", f"{scene.number}. {scene.slugline}")
    for performer in w.PERFORMERS:
        twin.add_entity(performer.performer_id, "performer", performer.name,
                        classification=Classification.PERSONAL)
    for crew in w.CREW:
        twin.add_entity(crew.crew_id, "crew_member", crew.name,
                        classification=Classification.PERSONAL)
    for req in w.ACCESS_REQUIREMENTS:
        kind = "caregiving_requirement" if req.category == "caregiving" else "access_requirement"
        twin.add_entity(req.requirement_id, kind, req.requirement,
                        classification=Classification.OPERATIONAL_REQUIREMENT)
    for loc in w.LOCATIONS:
        twin.add_entity(loc.location_id, "location", loc.name)
        twin.add_entity(f"ZONE-{loc.location_id}", "location_zone", f"{loc.name} working zone")
    for permit in w.PERMITS:
        twin.add_entity(permit.permit_id, "permit", permit.name)
    for eq in w.EQUIPMENT:
        twin.add_entity(eq.equipment_id, "equipment", eq.name)
    for veh in w.VEHICLES:
        twin.add_entity(veh.vehicle_id, "vehicle", veh.name)
    for res in w.SUPPORT_RESOURCES:
        twin.add_entity(res.resource_id, "support_resource", res.name)
    for booking in w.SERVICE_BOOKINGS:
        kind = ("interpreter_booking" if booking.kind == "sign_language_interpretation"
                else "service_booking")
        twin.add_entity(booking.booking_id, kind, f"{booking.provider} ({booking.kind})")
    for vendor in w.VENDORS:
        twin.add_entity(vendor.vendor_id, "vendor", vendor.name)
    twin.add_entity("SVC-BRIEFING", "briefing", "Safety briefing service")
    twin.add_entity("CALLSHEET-1", "call_sheet", "Call sheet, day 14")
    twin.add_entity("BRIEFING-1", "briefing", "Safety briefing, day 14")
    twin.add_entity("DAYLIGHT-1", "daylight_window", "Daylight window")
    for i, win in enumerate(w.BASELINE_WEATHER, start=1):
        twin.add_entity(f"WEATHER-{i:02d}", "weather_window",
                        f"{win.condition} {win.start:%H:%M}-{win.end:%H:%M}")


def build_twin(production_id: str = w.PRODUCTION_ID) -> ProductionTwin:
    """Construct the full twin. Deterministic: same inputs, same state hash."""
    t0 = w.at(0, 0)
    # Baseline records are known from the start of the production day, on the
    # production's own clock rather than the wall clock of whoever runs this.
    twin = ProductionTwin(production_id, clock=t0)

    twin.add_entity(production_id, "production", w.PRODUCTION_TITLE)
    twin.assert_fact(production_id, "title", w.PRODUCTION_TITLE, valid_from=t0,
                     source=BUILD_SOURCE)
    twin.assert_fact(production_id, "shoot_date", w.SHOOT_DATE.isoformat(), valid_from=t0,
                     source=BUILD_SOURCE)

    # Phase 1: register every entity before any relationship is drawn.
    #
    # `relate()` rejects unknown endpoints on purpose — a dangling edge is how a
    # twin quietly loses a dependency — so the build cannot be written as a
    # single pass in record order. Registering first makes the ordering explicit
    # instead of leaving it as an accident of how the sections happen to be
    # arranged. `add_entity` is idempotent, so the sections below re-declare
    # their own entities for readability.
    _register_entities(twin)

    # -- units -------------------------------------------------------------
    for unit in w.UNITS:
        twin.add_entity(unit.unit_id, "unit", unit.name)
        twin.assert_fact(unit.unit_id, "active", unit.active, valid_from=t0, source=BUILD_SOURCE)
        twin.assert_fact(unit.unit_id, "base_location", unit.base_location, valid_from=t0,
                         source=BUILD_SOURCE)
        twin.relate(unit.unit_id, production_id, "belongs_to_production", valid_from=t0)

    # -- departments -------------------------------------------------------
    for dept in {c.department for c in w.CREW}:
        twin.add_entity(f"DEPT-{dept.value}", "department", dept.value.replace("_", " ").title())
        twin.relate(f"DEPT-{dept.value}", production_id, "belongs_to_production", valid_from=t0)

    # -- script ------------------------------------------------------------
    twin.add_entity("SCRIPT-1", "script", scr.TITLE)
    twin.assert_fact("SCRIPT-1", "page_eighths", scr.total_page_eighths(), valid_from=t0,
                     source=BUILD_SOURCE)

    for day in scr.STORY_DAYS:
        sd = f"STORYDAY-{day.number}"
        twin.add_entity(sd, "story_day", day.label)

    for character_id, meta in scr.CHARACTERS.items():
        twin.add_entity(character_id, "character", str(meta["name"]))
        twin.assert_fact(character_id, "child_role", bool(meta["child_performer"]),
                         valid_from=t0, source=BUILD_SOURCE)

    for scene in scr.SCENES:
        twin.add_entity(scene.scene_id, "scene", f"{scene.number}. {scene.slugline}")
        for attr, val in (
            ("slugline", scene.slugline),
            ("story_day", scene.story_day),
            ("interior", scene.interior),
            ("exterior", scene.exterior),
            ("day_night", scene.day_night),
            ("page_eighths", scene.page_eighths),
            ("setup_minutes", scene.setup_minutes),
            ("shoot_minutes", scene.shoot_minutes),
            ("weather_sensitivity", scene.weather_sensitivity),
            ("daylight_required", scene.daylight_required),
            ("night_required", scene.night_required),
            ("special_requirements", list(scene.special_requirements)),
            ("wardrobe_state", scene.wardrobe_state),
            ("makeup_state", scene.makeup_state),
            ("unit", scene.unit),
        ):
            twin.assert_fact(scene.scene_id, attr, val, valid_from=t0, source=BUILD_SOURCE)

        twin.relate(scene.scene_id, "SCRIPT-1", "belongs_to_production", valid_from=t0)
        twin.relate(scene.scene_id, f"STORYDAY-{scene.story_day}", "follows_continuity",
                    valid_from=t0)
        twin.relate(scene.scene_id, scene.location_id, "requires_location", valid_from=t0)
        for character_id in scene.characters:
            performer = w.PERFORMER_BY_CHARACTER.get(character_id)
            if performer:
                twin.relate(scene.scene_id, performer.performer_id, "requires_performer",
                            valid_from=t0)
        for eq in scene.equipment_ids:
            twin.relate(scene.scene_id, eq, "requires_equipment", valid_from=t0)

    # Continuity precedence: a scene that carries state forward depends on the
    # scene that established it. These are the edges the critical path runs on.
    continuity_chains = (
        ("SC-008", "SC-009"), ("SC-009", "SC-014"), ("SC-014", "SC-017"),
        ("SC-017", "SC-018"), ("SC-018", "SC-022"), ("SC-004", "SC-007"),
        ("SC-001", "SC-002"), ("SC-025", "SC-026"), ("SC-026", "SC-027"),
        ("SC-027", "SC-029"), ("SC-029", "SC-030"), ("SC-030", "SC-031"),
        ("SC-031", "SC-032"), ("SC-021", "SC-025"), ("SC-023", "SC-025"),
    )
    for earlier, later in continuity_chains:
        twin.relate(earlier, later, "follows_continuity", valid_from=t0,
                    attributes={"reason": "state carried forward"})

    # -- people ------------------------------------------------------------
    for performer in w.PERFORMERS:
        twin.add_entity(performer.performer_id, "performer", performer.name,
                        classification=Classification.PERSONAL)
        for attr, val in (
            ("name", performer.name),
            ("minor", performer.minor),
            ("available_from", performer.available_from.isoformat()),
            ("available_to", performer.available_to.isoformat()),
            ("prep_minutes", performer.prep_minutes),
            ("daily_rate", performer.daily_rate),
            ("overtime_rate", performer.overtime_rate),
            ("languages", list(performer.languages)),
            ("turnaround_hours", performer.turnaround_hours),
        ):
            twin.assert_fact(performer.performer_id, attr, val, valid_from=t0,
                             source=BUILD_SOURCE, classification=Classification.PERSONAL)
        twin.relate(performer.performer_id, performer.character_id, "derived_from", valid_from=t0)
        if performer.minor:
            twin.add_entity(f"LIMIT-{performer.performer_id}", "constraint",
                            f"Child performer limits for {performer.name}")
            twin.relate(performer.performer_id, f"LIMIT-{performer.performer_id}",
                        "subject_to_limit", valid_from=t0)

    for crew in w.CREW:
        twin.add_entity(crew.crew_id, "crew_member", crew.name,
                        classification=Classification.PERSONAL)
        for attr, val in (
            ("name", crew.name),
            ("role_title", crew.role_title),
            ("department", crew.department.value),
            ("authority_role", crew.authority_role.value),
            ("call_time", crew.call_time.isoformat()),
            ("wrap_time", crew.wrap_time.isoformat()),
            ("hourly_rate", crew.hourly_rate),
            ("critical", crew.critical),
            ("languages", list(crew.languages)),
            ("certifications", list(crew.certifications)),
            ("turnaround_hours", crew.turnaround_hours),
        ):
            twin.assert_fact(crew.crew_id, attr, val, valid_from=t0, source=BUILD_SOURCE,
                             classification=Classification.PERSONAL)
        twin.relate(crew.crew_id, f"DEPT-{crew.department.value}", "owned_by_department",
                    valid_from=t0)
        for unit_id in crew.units:
            twin.relate(crew.crew_id, unit_id, "member_of_unit", valid_from=t0)
            # Membership alone does not propagate — a second grip being late does
            # not stop the unit. Being *critical* to the unit does, and it is the
            # same fact C-RES-007 is written against: the unit may not work
            # without these people. Drawing it as a requirement rather than as
            # membership is what lets a critical-crew disruption reach the scenes
            # that cannot now be shot, while leaving everyone else a leaf.
            if crew.critical:
                twin.relate(unit_id, crew.crew_id, "requires_crew", valid_from=t0)

    # -- approved access requirements --------------------------------------
    for req in w.ACCESS_REQUIREMENTS:
        kind = "caregiving_requirement" if req.category == "caregiving" else "access_requirement"
        twin.add_entity(req.requirement_id, kind, req.requirement,
                        classification=Classification.OPERATIONAL_REQUIREMENT)
        for attr, val in (
            ("requirement", req.requirement),
            ("category", req.category),
            ("mechanism", req.mechanism),
            ("approved_by", req.approved_by.value),
            ("critical", req.critical),
            ("visible_to", [r.value for r in req.visible_to]),
            ("window_start", req.window[0].isoformat() if req.window else None),
            ("window_end", req.window[1].isoformat() if req.window else None),
        ):
            twin.assert_fact(req.requirement_id, attr, val, valid_from=t0, source=BUILD_SOURCE,
                             classification=Classification.OPERATIONAL_REQUIREMENT,
                             approval_state="approved")
        # The person -> requirement edge is the only place the association lives,
        # and it is classified. Redaction removes the edge, not just the label.
        twin.relate(req.person_id, req.requirement_id, "subject_to_limit", valid_from=t0,
                    classification=Classification.OPERATIONAL_REQUIREMENT)
        for dep in req.depends_on:
            if dep in twin.entities or dep in {
                *(v.vehicle_id for v in w.VEHICLES),
                *(c.crew_id for c in w.CREW),
                *(b.booking_id for b in w.SERVICE_BOOKINGS),
                *(r.resource_id for r in w.SUPPORT_RESOURCES),
                "SVC-BRIEFING",
            }:
                if dep == "SVC-BRIEFING":
                    twin.add_entity("SVC-BRIEFING", "briefing", "Safety briefing service")
                twin.relate(req.requirement_id, dep, "requires_support", valid_from=t0)

    # -- locations, permits, routes ----------------------------------------
    for loc in w.LOCATIONS:
        twin.add_entity(loc.location_id, "location", loc.name)
        for attr, val in (
            ("name", loc.name),
            ("interior", loc.interior),
            ("step_free", loc.step_free),
            ("step_free_notes", loc.step_free_notes),
            ("travel_minutes_from_base", loc.travel_minutes_from_base),
            ("capacity_crew", loc.capacity_crew),
            ("power", loc.power),
            ("loading_zone", loc.loading_zone),
            ("weather_exposed", loc.weather_exposed),
            ("quiet_space", loc.quiet_space),
            ("refrigeration", loc.refrigeration),
            ("egress_routes", loc.egress_routes),
            ("available_from", loc.available_from.isoformat() if loc.available_from else None),
            ("available_to", loc.available_to.isoformat() if loc.available_to else None),
            ("noise_curfew", loc.noise_curfew.isoformat() if loc.noise_curfew else None),
            ("status", "available"),
        ):
            twin.assert_fact(loc.location_id, attr, val, valid_from=t0, source=BUILD_SOURCE)

        zone_id = f"ZONE-{loc.location_id}"
        twin.add_entity(zone_id, "location_zone", f"{loc.name} working zone")
        twin.relate(loc.location_id, zone_id, "provides_access_route", valid_from=t0)

    for permit in w.PERMITS:
        twin.add_entity(permit.permit_id, "permit", permit.name)
        for attr, val in (
            ("name", permit.name),
            ("valid_from", permit.valid_from.isoformat()),
            ("valid_to", permit.valid_to.isoformat()),
            ("status", permit.status),
            ("conditions", list(permit.conditions)),
            ("max_crew", permit.max_crew),
            ("prohibits_setup_after",
             permit.prohibits_setup_after.isoformat() if permit.prohibits_setup_after else None),
        ):
            twin.assert_fact(permit.permit_id, attr, val, valid_from=t0, source=BUILD_SOURCE)
        for loc_id in permit.location_ids:
            if loc_id in twin.entities:
                twin.relate(loc_id, permit.permit_id, "requires_permit", valid_from=t0)

    # -- resources ---------------------------------------------------------
    for eq in w.EQUIPMENT:
        twin.add_entity(eq.equipment_id, "equipment", eq.name)
        for attr, val in (
            ("name", eq.name),
            ("category", eq.category),
            ("department", eq.department.value),
            ("exclusive", eq.exclusive),
            ("assigned_unit", eq.assigned_unit),
            ("prep_minutes", eq.prep_minutes),
            ("available_from", eq.available_from.isoformat()),
            ("available_to", eq.available_to.isoformat()),
            ("status", eq.status),
            ("requires_certification", list(eq.requires_certification)),
            ("substitutes", list(eq.substitutes)),
            ("day_rate", eq.day_rate),
        ):
            twin.assert_fact(eq.equipment_id, attr, val, valid_from=t0, source=BUILD_SOURCE)
        twin.relate(eq.equipment_id, f"DEPT-{eq.department.value}", "owned_by_department",
                    valid_from=t0)
        twin.relate(eq.equipment_id, eq.assigned_unit, "assigns_resource", valid_from=t0)

    for veh in w.VEHICLES:
        twin.add_entity(veh.vehicle_id, "vehicle", veh.name)
        for attr, val in (
            ("name", veh.name),
            ("capacity", veh.capacity),
            ("step_free", veh.step_free),
            ("lift_equipped", veh.lift_equipped),
            ("driver_id", veh.driver_id),
            ("available_from", veh.available_from.isoformat()),
            ("available_to", veh.available_to.isoformat()),
            ("status", veh.status),
            ("load_minutes", veh.load_minutes),
            ("hourly_rate", veh.hourly_rate),
        ):
            twin.assert_fact(veh.vehicle_id, attr, val, valid_from=t0, source=BUILD_SOURCE)
        twin.relate(veh.vehicle_id, veh.driver_id, "requires_crew", valid_from=t0)
        for rq in veh.supports_requirements:
            twin.relate(veh.vehicle_id, rq, "supports_requirement", valid_from=t0)

    for res in w.SUPPORT_RESOURCES:
        twin.add_entity(res.resource_id, "support_resource", res.name)
        for attr, val in (
            ("name", res.name),
            ("kind", res.kind),
            ("location_id", res.location_id),
            ("available_from", res.available_from.isoformat()),
            ("available_to", res.available_to.isoformat()),
            ("status", res.status),
            ("portable", res.portable),
            ("setup_minutes", res.setup_minutes),
        ):
            twin.assert_fact(res.resource_id, attr, val, valid_from=t0, source=BUILD_SOURCE)
        if res.location_id in twin.entities:
            twin.relate(res.resource_id, res.location_id, "requires_location", valid_from=t0)

    for booking in w.SERVICE_BOOKINGS:
        kind = ("interpreter_booking" if booking.kind == "sign_language_interpretation"
                else "service_booking")
        twin.add_entity(booking.booking_id, kind, f"{booking.provider} ({booking.kind})")
        for attr, val in (
            ("kind", booking.kind),
            ("provider", booking.provider),
            ("start", booking.start.isoformat()),
            ("end", booking.end.isoformat()),
            ("status", booking.status),
            ("extendable_to",
             booking.extendable_to.isoformat() if booking.extendable_to else None),
            ("extension_notice_minutes", booking.extension_notice_minutes),
            ("hourly_rate", booking.hourly_rate),
        ):
            twin.assert_fact(booking.booking_id, attr, val, valid_from=t0, source=BUILD_SOURCE)
        for person_id in booking.person_ids:
            if person_id in twin.entities:
                twin.relate(booking.booking_id, person_id, "requires_crew", valid_from=t0)
        for rq in booking.supports_requirements:
            twin.relate(booking.booking_id, rq, "supports_requirement", valid_from=t0)

    for vendor in w.VENDORS:
        twin.add_entity(vendor.vendor_id, "vendor", vendor.name)
        for attr, val in (
            ("name", vendor.name),
            ("supplies", list(vendor.supplies)),
            ("lead_time_minutes", vendor.lead_time_minutes),
            ("reachable_until", vendor.reachable_until.isoformat()),
            ("call_out_fee", vendor.call_out_fee),
            ("reliability", vendor.reliability),
        ):
            twin.assert_fact(vendor.vendor_id, attr, val, valid_from=t0, source=BUILD_SOURCE)

    # -- weather and daylight ---------------------------------------------
    for i, win in enumerate(w.BASELINE_WEATHER, start=1):
        wid = f"WEATHER-{i:02d}"
        twin.add_entity(wid, "weather_window", f"{win.condition} {win.start:%H:%M}-{win.end:%H:%M}")
        for attr, val in (
            ("start", win.start.isoformat()),
            ("end", win.end.isoformat()),
            ("condition", win.condition),
            ("wind_kph", win.wind_kph),
            ("precipitation_mm", win.precipitation_mm),
            ("precipitation_probability", win.precipitation_probability),
            ("sea_state", win.sea_state),
            ("lightning_risk", win.lightning_risk),
        ):
            twin.assert_fact(wid, attr, val, valid_from=win.start, valid_to=win.end,
                             source="weather_service", authority=Authority.AUTHORITATIVE)

    twin.add_entity("DAYLIGHT-1", "daylight_window", "Daylight window")
    for attr, val in (
        ("sunrise", w.DAYLIGHT_SUNRISE.isoformat()),
        ("sunset", w.DAYLIGHT_SUNSET.isoformat()),
        ("civil_dawn", w.CIVIL_DAWN.isoformat()),
        ("civil_dusk", w.CIVIL_DUSK.isoformat()),
    ):
        twin.assert_fact("DAYLIGHT-1", attr, val, valid_from=t0, source="almanac")

    # -- the published schedule and its documents --------------------------
    twin.add_entity("CALLSHEET-1", "call_sheet", "Call sheet, day 14")
    twin.assert_fact("CALLSHEET-1", "revision", 1, valid_from=t0, source="call_sheet_system")
    twin.assert_fact("CALLSHEET-1", "published_at", w.at(-12).isoformat(), valid_from=t0,
                     source="call_sheet_system")

    twin.add_entity("BRIEFING-1", "briefing", "Safety briefing, day 14")
    twin.assert_fact("BRIEFING-1", "formats", ["spoken", "written", "captioned"], valid_from=t0,
                     source="safety_briefing_service")
    twin.assert_fact("BRIEFING-1", "issued_at", w.at(5, 45).isoformat(), valid_from=t0,
                     source="safety_briefing_service")
    twin.assert_fact("BRIEFING-1", "covers_locations",
                     sorted({s.location_id for s in w.BASELINE_SCHEDULE}), valid_from=t0,
                     source="safety_briefing_service")

    for sched in w.BASELINE_SCHEDULE:
        twin.assert_fact(sched.scene_id, "scheduled_start", sched.start.isoformat(),
                         valid_from=t0, source="scheduling_system")
        twin.assert_fact(sched.scene_id, "scheduled_end", sched.end.isoformat(),
                         valid_from=t0, source="scheduling_system")
        twin.assert_fact(sched.scene_id, "setup_start", sched.setup_start.isoformat(),
                         valid_from=t0, source="scheduling_system")
        twin.assert_fact(sched.scene_id, "assigned_unit", sched.unit_id, valid_from=t0,
                         source="scheduling_system")
        twin.assert_fact(sched.scene_id, "scheduled", True, valid_from=t0,
                         source="scheduling_system")
        twin.relate(sched.unit_id, sched.scene_id, "schedules_scene", valid_from=t0)
        twin.relate(sched.scene_id, "CALLSHEET-1", "documented_in", valid_from=t0)
        twin.relate(sched.scene_id, "BRIEFING-1", "documented_in", valid_from=t0)
        for eq_id in sched.equipment_ids:
            twin.relate(sched.scene_id, eq_id, "assigns_resource", valid_from=sched.setup_start,
                        valid_to=sched.end)

    # Transport assignments implied by the published plan.
    twin.relate("VEH-ACC-1", "CREW-AC1", "supports_requirement", valid_from=t0)

    # -- departmental ownership -------------------------------------------
    #
    # Fourteen departments were registered above, but before this block only six
    # of them could ever appear in a blast radius: the four that own equipment,
    # plus transport and access services, reached through a driver and an
    # interpreter. The other eight existed as entities with no propagating
    # relationship from anything a disruption touches, so a scene move could not
    # reach the costume department that has to re-dress it. The benchmark scored
    # that as affected-department recall of 0.333.
    #
    # Every edge below is an ownership or requirement that exists in the
    # production records; none of them was added to reach a department. Where
    # the records do not support an edge, none is drawn — see the note at the
    # end of this block.
    twin.relate("VEH-ACC-1", "LOC-HARBOUR-WALL", "requires_location", valid_from=t0)

    for loc in w.LOCATIONS:
        # The locations department holds the agreement, the access arrangements
        # and the relationship with the owner. Anything that happens to a
        # location is theirs.
        twin.relate(loc.location_id, "DEPT-locations", "owned_by_department", valid_from=t0)

    for req in w.ACCESS_REQUIREMENTS:
        # The accessibility coordinator's department owns every approved
        # arrangement — that is the `approved_by` role on the record, and it is
        # the department that has to re-establish the arrangement when its
        # mechanism fails.
        twin.relate(req.requirement_id, "DEPT-access_services", "owned_by_department",
                    valid_from=t0)

    # The production office owns the call sheet and issues every revision; the
    # safety lead owns the briefing. Both are already linked to each scheduled
    # scene by `documented_in`, so this is the last hop between a scene change
    # and the two departments that have to reissue the documents it invalidates.
    twin.relate("CALLSHEET-1", "DEPT-production", "owned_by_department", valid_from=t0)
    twin.relate("BRIEFING-1", "DEPT-safety", "owned_by_department", valid_from=t0)

    for scene in scr.SCENES:
        # A scene carries a wardrobe and a makeup continuity state, and those
        # states are established and maintained by their departments. Moving the
        # scene moves their work; this is the same fact the continuity
        # constraints are written against.
        if scene.wardrobe_state:
            twin.relate(scene.scene_id, "CREW-WARD", "requires_crew", valid_from=t0)
        if scene.makeup_state:
            twin.relate(scene.scene_id, "CREW-MAKEUP", "requires_crew", valid_from=t0)

        # The prop breakdown. `Scene.props` has carried this all along -- 27
        # items across 27 of the 32 scenes -- and the twin was simply not
        # registering it, so a continuity report naming a prop had nothing to
        # point at.
        #
        # Dressing goes to the art department and action props to the property
        # master, which is the ordinary split: the art department dresses the
        # set, and the property master is responsible for what a performer
        # handles.
        for prop_id in scene.props:
            department = "art" if prop_id.endswith("-DRESSING") else "props"
            twin.add_entity(prop_id, "prop",
                            prop_id.removeprefix("PROP-").replace("-", " ").title())
            twin.relate(scene.scene_id, prop_id, "requires_prop", valid_from=t0)
            twin.relate(prop_id, f"DEPT-{department}", "owned_by_department", valid_from=t0)

    # Not drawn: DEPT-catering. Catering is on the crew list and in the
    # working-hours policy's meal-break rules, but the production records carry
    # no catering plan -- no meal service, no location, no covers -- so there is
    # nothing to hang a propagating edge on. Nothing in the corpus labels
    # catering either, so this is a gap in the authored world rather than in the
    # traversal. Reported in docs/BENCHMARK.md §7.

    return twin


# ---------------------------------------------------------------------------
# Baseline certification
# ---------------------------------------------------------------------------


#: Crew who are at the working position regardless of which departments the
#: scene needs: the first AD and the unit medic.
BASE_PARTY = 2
#: Typical bodies per department at the working position.
PER_DEPARTMENT_PARTY = 2


def departments_for(equipment_ids: tuple[str, ...]) -> set[str]:
    """The departments a scene puts at the working position, from its equipment."""
    out: set[str] = set()
    for eq_id in equipment_ids:
        eq = w.EQUIPMENT_BY_ID.get(eq_id)
        if eq is not None:
            out.add(eq.department.value)
    return out


def working_party_size(equipment_ids: tuple[str, ...]) -> int:
    return BASE_PARTY + PER_DEPARTMENT_PARTY * len(departments_for(equipment_ids))


@dataclass(frozen=True)
class BaselineIssue:
    code: str
    severity: str          # blocking | warning
    subject: str
    message: str
    evidence: str = ""


@dataclass(frozen=True)
class BaselineReport:
    production_id: str
    state: str             # ready | ready_with_warnings | not_ready
    issues: tuple[BaselineIssue, ...]
    checked: int
    state_hash: str
    version: int = 1

    @property
    def blocking(self) -> tuple[BaselineIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "blocking")


def certify_baseline(twin: ProductionTwin, when: datetime | None = None) -> BaselineReport:
    """The pre-day consistency check from §4.1.

    Twelve checks, each of which can actually fail — the disruption library
    contains scenarios that trip every one of them. A check that cannot fail is
    a check that is lying to you about your coverage.
    """
    moment = when or w.at(5, 0)
    issues: list[BaselineIssue] = []
    checks = 0

    scheduled = list(w.BASELINE_SCHEDULE)

    # 1. Double-booked exclusive resources.
    checks += 1
    for eq in w.EQUIPMENT:
        if not eq.exclusive:
            continue
        uses = [s for s in scheduled if eq.equipment_id in s.equipment_ids]
        for i, a in enumerate(uses):
            for b in uses[i + 1:]:
                if a.setup_start < b.end and b.setup_start < a.end:
                    issues.append(BaselineIssue(
                        "B-001", "blocking", eq.equipment_id,
                        f"{eq.name} is assigned to {a.scene_id} and {b.scene_id} at the same time",
                        f"{a.scene_id} {a.setup_start:%H:%M}-{a.end:%H:%M} overlaps "
                        f"{b.scene_id} {b.setup_start:%H:%M}-{b.end:%H:%M}",
                    ))

    # 2. Impossible travel between consecutive scenes for a unit.
    #
    # Measured wrap-to-*start*, not wrap-to-setup. Setup is routinely pre-rigged
    # at the next location by a department that is not with the shooting
    # company, so requiring the whole travel time before setup opens would
    # forbid the single most common thing a lighting crew does all day. What
    # actually has to fit in the gap is the company move.
    checks += 1
    for unit in w.UNITS:
        rows = sorted((s for s in scheduled if s.unit_id == unit.unit_id), key=lambda s: s.start)
        for a, b in zip(rows, rows[1:]):
            need = w.travel_minutes(a.location_id, b.location_id)
            gap = (b.start - a.end).total_seconds() / 60.0
            if a.location_id != b.location_id and gap < need:
                issues.append(BaselineIssue(
                    "B-002", "blocking", unit.unit_id,
                    f"{unit.name} cannot travel from {a.scene_id} to {b.scene_id}: "
                    f"{need} min needed, {gap:.0f} min available",
                    f"{a.location_id} -> {b.location_id}",
                ))

    # 2b. A performer cannot be in two scenes at once.
    checks += 1
    by_performer: dict[str, list[w.ScheduledScene]] = {}
    for s in scheduled:
        for cast_id in s.cast_calls:
            by_performer.setdefault(cast_id, []).append(s)
    for cast_id, rows in by_performer.items():
        rows.sort(key=lambda s: s.start)
        for a, b in zip(rows, rows[1:]):
            if b.start < a.end:
                performer = w.PERFORMERS_BY_ID[cast_id]
                issues.append(BaselineIssue(
                    "B-013", "blocking", cast_id,
                    f"{performer.name} is required by {a.scene_id} "
                    f"({a.start:%H:%M}-{a.end:%H:%M}) and {b.scene_id} "
                    f"({b.start:%H:%M}-{b.end:%H:%M}) at the same time",
                    f"{a.unit_id} / {b.unit_id}",
                ))
            elif a.location_id != b.location_id:
                need = w.travel_minutes(a.location_id, b.location_id)
                gap = (b.start - a.end).total_seconds() / 60.0
                if gap < need:
                    performer = w.PERFORMERS_BY_ID[cast_id]
                    issues.append(BaselineIssue(
                        "B-013", "blocking", cast_id,
                        f"{performer.name} cannot reach {b.scene_id} from {a.scene_id}: "
                        f"{need} min travel, {gap:.0f} min available",
                        f"{a.location_id} -> {b.location_id}",
                    ))

    # 3. Approved access requirements with a missing or unavailable mechanism.
    checks += 1
    for req in w.ACCESS_REQUIREMENTS:
        for dep in req.depends_on:
            available = (
                dep in w.VEHICLES_BY_ID and w.VEHICLES_BY_ID[dep].status == "available"
                or dep in w.CREW_BY_ID
                or dep in w.BOOKINGS_BY_ID and w.BOOKINGS_BY_ID[dep].status == "confirmed"
                or dep in w.SUPPORT_BY_ID and w.SUPPORT_BY_ID[dep].status == "available"
                or dep == "SVC-BRIEFING"
            )
            if not available:
                issues.append(BaselineIssue(
                    "B-003", "blocking", req.requirement_id,
                    f"Approved arrangement '{req.requirement}' depends on {dep}, "
                    "which is not available",
                    req.mechanism,
                ))

    # 4. Missing safety briefing coverage for a scheduled location.
    checks += 1
    covered = set(twin.value("BRIEFING-1", "covers_locations", moment) or [])
    for s in scheduled:
        if s.location_id not in covered:
            issues.append(BaselineIssue(
                "B-004", "blocking", s.location_id,
                f"No safety briefing covers {s.location_id}, scheduled for {s.scene_id}",
                "BRIEFING-1",
            ))

    # 5. Inconsistent call times: a cast call after the scene it serves.
    checks += 1
    for s in scheduled:
        for cast_id, call in s.cast_calls.items():
            performer = w.PERFORMERS_BY_ID.get(cast_id)
            if call >= s.start:
                issues.append(BaselineIssue(
                    "B-005", "blocking", cast_id,
                    f"Call time {call:%H:%M} is not before {s.scene_id} start {s.start:%H:%M}",
                    s.scene_id,
                ))
            elif performer and (s.start - call).total_seconds() / 60.0 < performer.prep_minutes:
                issues.append(BaselineIssue(
                    "B-005", "warning", cast_id,
                    f"{performer.name} has "
                    f"{(s.start - call).total_seconds() / 60.0:.0f} min before {s.scene_id}, "
                    f"less than the {performer.prep_minutes} min prep allowance",
                    s.scene_id,
                ))

    # 6. Permit coverage and validity for every scheduled location and time.
    checks += 1
    for s in scheduled:
        loc = w.LOCATIONS_BY_ID[s.location_id]
        for permit_id in loc.permits:
            permit = w.PERMITS_BY_ID[permit_id]
            if permit.status != "valid":
                issues.append(BaselineIssue(
                    "B-006", "blocking", permit_id,
                    f"{permit.name} is {permit.status} but is required for {s.scene_id}",
                    s.location_id,
                ))
            elif not (permit.valid_from <= s.setup_start and s.end <= permit.valid_to):
                issues.append(BaselineIssue(
                    "B-006", "blocking", permit_id,
                    f"{permit.name} does not cover {s.scene_id} "
                    f"({s.setup_start:%H:%M}-{s.end:%H:%M}); permit runs "
                    f"{permit.valid_from:%H:%M}-{permit.valid_to:%H:%M}",
                    s.location_id,
                ))
            if permit.prohibits_setup_after and s.setup_start > permit.prohibits_setup_after:
                issues.append(BaselineIssue(
                    "B-006", "blocking", permit_id,
                    f"{permit.name} prohibits setup after "
                    f"{permit.prohibits_setup_after:%H:%M}; {s.scene_id} sets up at "
                    f"{s.setup_start:%H:%M}",
                    s.location_id,
                ))

    # 7. Equipment availability windows.
    checks += 1
    for s in scheduled:
        for eq_id in s.equipment_ids:
            eq = w.EQUIPMENT_BY_ID.get(eq_id)
            if eq is None:
                issues.append(BaselineIssue("B-007", "blocking", eq_id,
                                            f"{s.scene_id} requires unknown equipment {eq_id}", ""))
                continue
            prep_start = s.setup_start - timedelta(minutes=eq.prep_minutes)
            if prep_start < eq.available_from or s.end > eq.available_to:
                issues.append(BaselineIssue(
                    "B-007", "blocking", eq_id,
                    f"{eq.name} is required for {s.scene_id} from {prep_start:%H:%M} "
                    f"but is available {eq.available_from:%H:%M}-{eq.available_to:%H:%M}",
                    s.scene_id,
                ))

    # 8. Continuity: a scene must not be scheduled before the scene it follows.
    checks += 1
    order = {s.scene_id: s.start for s in scheduled}
    for rel in twin.relationships.values():
        if rel.kind != "follows_continuity" or not rel.attributes.get("reason"):
            continue
        a, b = rel.source_id, rel.target_id
        if a in order and b in order and order[b] < order[a]:
            issues.append(BaselineIssue(
                "B-008", "blocking", b,
                f"{b} carries state from {a} but is scheduled first "
                f"({order[b]:%H:%M} before {order[a]:%H:%M})",
                str(rel.attributes.get("reason")),
            ))

    # 9. Child performer window.
    checks += 1
    policy = w.POLICIES["child_performer"]
    for s in scheduled:
        for cast_id, call in s.cast_calls.items():
            performer = w.PERFORMERS_BY_ID.get(cast_id)
            if not performer or not performer.minor:
                continue
            if call < policy["earliest_call"] or s.end > policy["latest_wrap"]:  # type: ignore[operator]
                issues.append(BaselineIssue(
                    "B-009", "blocking", cast_id,
                    f"{performer.name} is scheduled {call:%H:%M}-{s.end:%H:%M} on {s.scene_id}, "
                    f"outside the configured window "
                    f"{policy['earliest_call']:%H:%M}-{policy['latest_wrap']:%H:%M}",  # type: ignore[index]
                    "POLICIES['child_performer']",
                ))

    # 10. Location capacity against the working party the scene actually needs.
    #
    # Not against the whole unit. A confined practical set runs a reduced party
    # — that is what "confined" means operationally — and comparing a boat
    # wheelhouse against a twenty-four-person unit head count flags every
    # interior in the production as over capacity, which trains everyone to
    # ignore the check.
    checks += 1
    for s in scheduled:
        loc = w.LOCATIONS_BY_ID[s.location_id]
        party = working_party_size(s.equipment_ids)
        if party > loc.capacity_crew:
            issues.append(BaselineIssue(
                "B-010", "warning", s.location_id,
                f"{loc.name} capacity {loc.capacity_crew} is below the {party}-person "
                f"working party {s.scene_id} requires",
                f"departments: {', '.join(sorted(departments_for(s.equipment_ids)))}",
            ))

    # 11. Working-hour exposure on the published plan.
    checks += 1
    limit = float(w.POLICIES["working_hours"]["max_crew_day_minutes"])  # type: ignore[arg-type]
    for unit in w.UNITS:
        rows = [s for s in scheduled if s.unit_id == unit.unit_id]
        if not rows:
            continue
        call = min(s.crew_call for s in rows)
        wrap = max(s.end for s in rows)
        span = (wrap - call).total_seconds() / 60.0
        if span > limit:
            issues.append(BaselineIssue(
                "B-011", "warning", unit.unit_id,
                f"{unit.name} spans {span:.0f} min against a {limit:.0f} min configured day",
                f"{call:%H:%M}-{wrap:%H:%M}",
            ))

    # 12. Stale source data.
    checks += 1
    published = twin.value("CALLSHEET-1", "published_at", moment)
    if published:
        age_h = (moment - datetime.fromisoformat(published)).total_seconds() / 3600.0
        if age_h > 24:
            issues.append(BaselineIssue(
                "B-012", "warning", "CALLSHEET-1",
                f"Call sheet was published {age_h:.1f} h ago", published,
            ))

    structural = twin.check_invariants()
    for problem in structural:
        issues.append(BaselineIssue("B-000", "blocking", "twin", problem))

    if any(i.severity == "blocking" for i in issues):
        state = "not_ready"
    elif issues:
        state = "ready_with_warnings"
    else:
        state = "ready"

    return BaselineReport(
        production_id=twin.production_id,
        state=state,
        issues=tuple(issues),
        checked=checks,
        state_hash=twin.state_hash(moment),
    )
