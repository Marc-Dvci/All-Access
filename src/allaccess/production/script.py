"""*Salt and Light* — the original screenplay this demonstration shoots.

Written for this project. There is no third-party material anywhere in it: no
adapted work, no licensed music, no real locations, no real people. That matters
for a submission whose rules forbid third-party content, and it is also why the
production data downstream can be as detailed as it needs to be — nothing here
has to be redacted or hand-waved. See docs/MEDIA_RIGHTS.md.

The script is not decoration. Scene metadata below is the ground truth for the
whole system: `story_day` drives continuity constraints, `exterior` and
`weather_sensitivity` drive the weather and daylight constraints, `characters`
drives cast availability and the child-performer limits, and `page_eighths`
drives the duration model. Change a scene here and the solver sees a different
problem.

Logline: on the last working weekend of a failing harbour, a deaf teenager and
the grandfather who never learned to sign have to sell the boat that is the only
language they still share.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Scene:
    scene_id: str
    number: str
    slugline: str
    story_day: int
    interior: bool
    day_night: str
    location_id: str
    set_name: str
    characters: tuple[str, ...]
    page_eighths: int
    synopsis: str
    action: str
    dialogue: tuple[tuple[str, str], ...] = ()
    weather_sensitivity: str = "none"  # none | moderate | high | prohibitive
    daylight_required: bool = False
    night_required: bool = False
    special_requirements: tuple[str, ...] = ()
    equipment_ids: tuple[str, ...] = ()
    props: tuple[str, ...] = ()
    wardrobe_state: str = ""
    makeup_state: str = ""
    continuity_notes: tuple[str, ...] = ()
    setup_minutes: int = 45
    shoot_minutes: int = 60
    unit: str = "main"

    @property
    def exterior(self) -> bool:
        return not self.interior

    @property
    def pages(self) -> float:
        return self.page_eighths / 8.0


TITLE = "Salt and Light"
FORM = "Short film"
WRITER = "All-Access demonstration — original work, written for this project"
LOGLINE = (
    "On the last working weekend of a failing harbour, a deaf teenager and the "
    "grandfather who never learned to sign have to sell the boat that is the only "
    "language they still share."
)

SYNOPSIS = """\
MAREN, sixteen and deaf since birth, has spent every summer aboard the LIGHTKEEPER,
a forty-year-old inshore trawler, reading her grandfather ARVO's hands on the wheel
and the tilt of the deck. Arvo is seventy-one and has never learned to sign; they
have built, across sixteen years, a private grammar of gesture, engine noise felt
through the hull, and the angle of a torch beam.

The harbour is closing. The berth licence transfers on Monday. A buyer is coming
Saturday night to see the boat run.

Over one weekend Maren discovers her grandfather has already signed the papers, that
the buyer intends to break the boat for parts, and that the only thing standing
between the LIGHTKEEPER and the yard is a sea trial her grandfather can no longer
physically complete alone. The film ends on the harbour wall at night, in a storm
coming in, with Maren at the wheel and Arvo — for the first time, badly, hands
shaking — signing the word for 'starboard'.
"""

CHARACTERS: dict[str, dict[str, object]] = {
    "CHAR-MAREN": {
        "name": "MAREN",
        "age": 16,
        "description": "Deaf since birth. Signs fluently. Reads the boat through her feet.",
        "child_performer": False,
    },
    "CHAR-ARVO": {
        "name": "ARVO",
        "age": 71,
        "description": "Her grandfather. Skipper of the LIGHTKEEPER for forty years. Does not sign.",
        "child_performer": False,
    },
    "CHAR-PIA": {
        "name": "PIA",
        "age": 9,
        "description": "Maren's cousin. Interprets for Arvo without being asked, badly.",
        "child_performer": True,
    },
    "CHAR-TOIVO": {
        "name": "TOIVO",
        "age": 54,
        "description": "Harbour master. Has the licence transfer in his coat pocket all weekend.",
        "child_performer": False,
    },
    "CHAR-BUYER": {
        "name": "THE BUYER",
        "age": 47,
        "description": "Come to see the boat run. Has no intention of running it.",
        "child_performer": False,
    },
    "CHAR-SIRI": {
        "name": "SIRI",
        "age": 38,
        "description": "Maren's mother. Sells the harbour's last catch from a folding table.",
        "child_performer": False,
    },
}


SCENES: tuple[Scene, ...] = (
    Scene(
        scene_id="SC-001",
        number="1",
        slugline="EXT. HARBOUR WALL - DAWN",
        story_day=1,
        interior=False,
        day_night="DAWN",
        location_id="LOC-HARBOUR-WALL",
        set_name="Harbour wall, east end",
        characters=("CHAR-MAREN",),
        page_eighths=4,
        synopsis="Maren walks the wall counting berths. Eleven empty, three not.",
        action=(
            "Grey light. The wall runs out into fog. MAREN, 16, walks its length with one hand "
            "trailing the rail, counting berths with the other. Eleven empty. Three not. She "
            "stops at the third and looks down at the LIGHTKEEPER, forty feet of tired white paint."
        ),
        weather_sensitivity="moderate",
        daylight_required=True,
        special_requirements=("dawn_window",),
        equipment_ids=("EQ-CAM-A", "EQ-LIGHT-BOUNCE", "EQ-SOUND-A"),
        props=("PROP-COUNTING-TALLY",),
        wardrobe_state="MAREN: oilskin over school jumper, day 1",
        makeup_state="MAREN: clean, cold-flushed",
        setup_minutes=55,
        shoot_minutes=50,
    ),
    Scene(
        scene_id="SC-002",
        number="2",
        slugline="INT. LIGHTKEEPER - WHEELHOUSE - DAY",
        story_day=1,
        interior=True,
        day_night="DAY",
        location_id="LOC-BOAT-WHEELHOUSE",
        set_name="Wheelhouse",
        characters=("CHAR-MAREN", "CHAR-ARVO"),
        page_eighths=10,
        synopsis="Arvo teaches nothing and everything. Maren reads the engine through the deck.",
        action=(
            "ARVO, 71, has both hands on the wheel and does not turn around. MAREN comes up the "
            "three steps and puts her palm flat on the housing. She feels the engine. She holds "
            "up four fingers. Arvo eases the throttle back a quarter turn without looking."
        ),
        dialogue=(
            ("ARVO", "You're early."),
            ("ARVO", "(not turning) Wind's backing. We'll not go far."),
        ),
        equipment_ids=("EQ-CAM-A", "EQ-LIGHT-KIT-1", "EQ-SOUND-A", "EQ-GRIP-BOAT")
        ,
        props=("PROP-WHEEL", "PROP-CHART-BOOK"),
        wardrobe_state="ARVO: navy smock, day 1; MAREN: oilskin, day 1",
        makeup_state="continuous with SC-001",
        continuity_notes=("MAREN's hair salt-damp from SC-001",),
        setup_minutes=75,
        shoot_minutes=110,
    ),
    Scene(
        scene_id="SC-003",
        number="3",
        slugline="EXT. FISH TABLE - DAY",
        story_day=1,
        interior=False,
        day_night="DAY",
        location_id="LOC-QUAYSIDE",
        set_name="Quayside, folding table",
        characters=("CHAR-SIRI", "CHAR-PIA"),
        page_eighths=6,
        synopsis="Siri sells the last of it. Pia counts change and gets it wrong twice.",
        action=(
            "A folding table, a plastic tub, ice going to water. SIRI, 38, wraps two fish in "
            "newspaper. PIA, 9, works the cash tin with enormous seriousness and no arithmetic."
        ),
        dialogue=(
            ("PIA", "That's four eighty."),
            ("SIRI", "It's six."),
            ("PIA", "It's four eighty if she's nice."),
        ),
        weather_sensitivity="moderate",
        daylight_required=True,
        special_requirements=("child_performer",),
        equipment_ids=("EQ-CAM-B", "EQ-SOUND-B"),
        props=("PROP-CASH-TIN", "PROP-FISH-DRESSING"),
        wardrobe_state="SIRI: apron, day 1; PIA: yellow coat, day 1",
        makeup_state="PIA: clean",
        setup_minutes=40,
        shoot_minutes=55,
        unit="second",
    ),
    Scene(
        scene_id="SC-004",
        number="4",
        slugline="INT. HARBOUR OFFICE - DAY",
        story_day=1,
        interior=True,
        day_night="DAY",
        location_id="LOC-HARBOUR-OFFICE",
        set_name="Harbour master's office",
        characters=("CHAR-TOIVO", "CHAR-ARVO"),
        page_eighths=9,
        synopsis="Toivo has the transfer papers. Arvo signs them and says nothing about it.",
        action=(
            "A room of pinned notices going yellow. TOIVO, 54, slides a single sheet across a desk "
            "and looks at the window while it is signed."
        ),
        dialogue=(
            ("TOIVO", "Monday it's not your berth."),
            ("ARVO", "I can read."),
            ("TOIVO", "You can. She can't hear you say it, though, can she."),
        ),
        equipment_ids=("EQ-CAM-A", "EQ-LIGHT-KIT-1", "EQ-SOUND-A"),
        props=("PROP-TRANSFER-PAPERS", "PROP-DESK-DRESSING"),
        wardrobe_state="ARVO: navy smock, day 1; TOIVO: harbour coat",
        makeup_state="continuous",
        continuity_notes=("PROP-TRANSFER-PAPERS must be unsigned entering, signed leaving",),
        setup_minutes=60,
        shoot_minutes=85,
    ),
    Scene(
        scene_id="SC-005",
        number="5",
        slugline="EXT. HARBOUR WALL - DAY",
        story_day=1,
        interior=False,
        day_night="DAY",
        location_id="LOC-HARBOUR-WALL",
        set_name="Harbour wall, mid",
        characters=("CHAR-MAREN", "CHAR-PIA"),
        page_eighths=7,
        synopsis="Pia interprets a conversation Maren can already see the shape of.",
        action=(
            "PIA signs — clumsily, half-remembered, thumb in the wrong place. MAREN corrects the "
            "handshape with two fingers and lets her carry on being wrong."
        ),
        dialogue=(("PIA", "(signing badly) Grandad. Paper. Toivo. Sad?"),),
        weather_sensitivity="moderate",
        daylight_required=True,
        special_requirements=("child_performer", "sign_language_content"),
        equipment_ids=("EQ-CAM-A", "EQ-SOUND-A", "EQ-LIGHT-BOUNCE"),
        props=(),
        wardrobe_state="MAREN: oilskin day 1; PIA: yellow coat day 1",
        makeup_state="continuous",
        setup_minutes=45,
        shoot_minutes=70,
    ),
    Scene(
        scene_id="SC-006",
        number="6",
        slugline="INT. MAREN'S ROOM - NIGHT",
        story_day=1,
        interior=True,
        day_night="NIGHT",
        location_id="LOC-HOUSE-UPSTAIRS",
        set_name="Maren's room",
        characters=("CHAR-MAREN",),
        page_eighths=5,
        synopsis="Maren practises the sign for 'starboard' at a dark window.",
        action=(
            "A single lamp. MAREN makes the sign, watches her own reflection make it back, and "
            "corrects the angle of the wrist a fraction. Again. Again."
        ),
        night_required=True,
        special_requirements=("sign_language_content",),
        equipment_ids=("EQ-CAM-A", "EQ-LIGHT-KIT-1", "EQ-SOUND-A"),
        props=("PROP-LAMP",),
        wardrobe_state="MAREN: sleep clothes, day 1 night",
        makeup_state="MAREN: clean",
        setup_minutes=50,
        shoot_minutes=45,
    ),
    Scene(
        scene_id="SC-007",
        number="7",
        slugline="INT. KITCHEN - NIGHT",
        story_day=1,
        interior=True,
        day_night="NIGHT",
        location_id="LOC-HOUSE-KITCHEN",
        set_name="Kitchen",
        characters=("CHAR-ARVO", "CHAR-SIRI"),
        page_eighths=8,
        synopsis="Siri finds out. Arvo does not defend himself.",
        action=(
            "SIRI has the transfer copy flat on the table under one hand. ARVO eats standing up, "
            "at the counter, facing the wall."
        ),
        dialogue=(
            ("SIRI", "Saturday. You let her plan the whole of Saturday."),
            ("ARVO", "She'd have found a way to stop it."),
            ("SIRI", "She would have. That's not a reason, Dad, that's the opposite of one."),
        ),
        night_required=True,
        equipment_ids=("EQ-CAM-A", "EQ-LIGHT-KIT-1", "EQ-SOUND-A"),
        props=("PROP-TRANSFER-PAPERS", "PROP-KITCHEN-DRESSING"),
        wardrobe_state="ARVO: undershirt + smock, day 1 night; SIRI: day 1",
        makeup_state="continuous",
        setup_minutes=65,
        shoot_minutes=90,
    ),
    Scene(
        scene_id="SC-008",
        number="8",
        slugline="EXT. SLIPWAY - DAWN",
        story_day=2,
        interior=False,
        day_night="DAWN",
        location_id="LOC-SLIPWAY",
        set_name="Slipway, low water",
        characters=("CHAR-MAREN", "CHAR-ARVO"),
        page_eighths=6,
        synopsis="They scrape the hull in silence. It is the closest thing to a conversation.",
        action="Two scrapers. Two rhythms. They fall into the same one and neither acknowledges it.",
        weather_sensitivity="high",
        daylight_required=True,
        special_requirements=("dawn_window", "tide_dependent"),
        equipment_ids=("EQ-CAM-A", "EQ-LIGHT-BOUNCE", "EQ-SOUND-A"),
        props=("PROP-SCRAPERS",),
        wardrobe_state="MAREN: overalls, day 2; ARVO: navy smock, day 2",
        makeup_state="MAREN + ARVO: hull paint on hands",
        continuity_notes=("Paint on hands must persist into SC-009 and SC-010",),
        setup_minutes=70,
        shoot_minutes=65,
    ),
    Scene(
        scene_id="SC-009",
        number="9",
        slugline="INT. LIGHTKEEPER - ENGINE SPACE - DAY",
        story_day=2,
        interior=True,
        day_night="DAY",
        location_id="LOC-BOAT-ENGINE",
        set_name="Engine space",
        characters=("CHAR-MAREN", "CHAR-ARVO"),
        page_eighths=11,
        synopsis="The starter fails. Maren finds it by hand before Arvo finds it by ear.",
        action=(
            "Cramped. Hot. ARVO listens. MAREN puts the flat of her hand on the block and moves it "
            "twelve inches at a time. She stops. She taps twice. He looks where she is touching."
        ),
        special_requirements=("confined_space", "hot_works_adjacent"),
        equipment_ids=("EQ-CAM-B", "EQ-LIGHT-KIT-2", "EQ-SOUND-A", "EQ-GRIP-BOAT"),
        props=("PROP-STARTER-MOTOR", "PROP-TOOLS"),
        wardrobe_state="continuous with SC-008",
        makeup_state="paint on hands + engine grease",
        continuity_notes=("Grease is added here and must persist forward",),
        setup_minutes=90,
        shoot_minutes=120,
    ),
    Scene(
        scene_id="SC-010",
        number="10",
        slugline="EXT. CHANDLERY - DAY",
        story_day=2,
        interior=False,
        day_night="DAY",
        location_id="LOC-CHANDLERY",
        set_name="Chandlery front",
        characters=("CHAR-MAREN", "CHAR-PIA"),
        page_eighths=5,
        synopsis="No starter in the county. Pia offers to phone people and does.",
        action="A shuttered front. A handwritten card. PIA already has the phone out.",
        weather_sensitivity="moderate",
        daylight_required=True,
        special_requirements=("child_performer",),
        equipment_ids=("EQ-CAM-B", "EQ-SOUND-B"),
        props=("PROP-PHONE", "PROP-SHOP-CARD"),
        wardrobe_state="MAREN: overalls day 2; PIA: yellow coat day 2",
        makeup_state="continuous, grease on MAREN's hands",
        setup_minutes=40,
        shoot_minutes=50,
        unit="second",
    ),
    Scene(
        scene_id="SC-011",
        number="11",
        slugline="INT. HARBOUR OFFICE - DAY",
        story_day=2,
        interior=True,
        day_night="DAY",
        location_id="LOC-HARBOUR-OFFICE",
        set_name="Harbour master's office",
        characters=("CHAR-MAREN", "CHAR-TOIVO"),
        page_eighths=9,
        synopsis="Maren asks Toivo for one more day. He writes his answers on a pad.",
        action=(
            "TOIVO reaches for a pad without being asked, which is the kindest thing anyone does "
            "in the film. He writes. She reads. She writes back. He laughs once."
        ),
        dialogue=(("TOIVO", "(writing) Monday is Monday. But Sunday is still Sunday."),),
        special_requirements=("written_communication_content",),
        equipment_ids=("EQ-CAM-A", "EQ-LIGHT-KIT-1", "EQ-SOUND-A"),
        props=("PROP-NOTEPAD", "PROP-DESK-DRESSING"),
        wardrobe_state="continuous day 2",
        makeup_state="continuous",
        setup_minutes=55,
        shoot_minutes=80,
    ),
    Scene(
        scene_id="SC-012",
        number="12",
        slugline="EXT. QUAYSIDE - DAY",
        story_day=2,
        interior=False,
        day_night="DAY",
        location_id="LOC-QUAYSIDE",
        set_name="Quayside, north",
        characters=("CHAR-SIRI", "CHAR-MAREN"),
        page_eighths=7,
        synopsis="Siri tells Maren the truth about Saturday. Maren already knew.",
        action="SIRI signs. She is not fluent but she is careful, and careful is enough.",
        dialogue=(("SIRI", "(signing) He signed it Thursday. I'm sorry."),),
        weather_sensitivity="moderate",
        daylight_required=True,
        special_requirements=("sign_language_content",),
        equipment_ids=("EQ-CAM-A", "EQ-SOUND-A", "EQ-LIGHT-BOUNCE"),
        props=(),
        wardrobe_state="continuous day 2",
        makeup_state="continuous",
        setup_minutes=45,
        shoot_minutes=70,
    ),
    Scene(
        scene_id="SC-013",
        number="13",
        slugline="INT. CHANDLERY BACK ROOM - DAY",
        story_day=2,
        interior=True,
        day_night="DAY",
        location_id="LOC-CHANDLERY-BACK",
        set_name="Chandlery back room",
        characters=("CHAR-MAREN", "CHAR-PIA"),
        page_eighths=6,
        synopsis="A starter off a scrapped boat. Wrong year. Close enough.",
        action="Shelves of things that no longer have boats. PIA finds it because she is short.",
        special_requirements=("child_performer",),
        equipment_ids=("EQ-CAM-B", "EQ-LIGHT-KIT-2", "EQ-SOUND-B"),
        props=("PROP-STARTER-MOTOR-B", "PROP-SHELF-DRESSING"),
        wardrobe_state="continuous day 2",
        makeup_state="continuous",
        setup_minutes=55,
        shoot_minutes=60,
        unit="second",
    ),
    Scene(
        scene_id="SC-014",
        number="14",
        slugline="INT. LIGHTKEEPER - ENGINE SPACE - DUSK",
        story_day=2,
        interior=True,
        day_night="DUSK",
        location_id="LOC-BOAT-ENGINE",
        set_name="Engine space",
        characters=("CHAR-MAREN", "CHAR-ARVO", "CHAR-PIA"),
        page_eighths=10,
        synopsis="The fit is wrong by four millimetres. Arvo files it. His hands shake.",
        action=(
            "The new starter will not seat. ARVO takes a file to it. Twenty minutes of a man's "
            "hands not being what they were, in one unbroken take if the performance allows."
        ),
        special_requirements=("confined_space", "child_performer"),
        equipment_ids=("EQ-CAM-B", "EQ-LIGHT-KIT-2", "EQ-SOUND-A", "EQ-GRIP-BOAT"),
        props=("PROP-STARTER-MOTOR-B", "PROP-FILE", "PROP-TOOLS"),
        wardrobe_state="continuous day 2",
        makeup_state="grease heavy, both hands",
        continuity_notes=("ARVO's right hand cut in this scene; dressing must appear in SC-018+",),
        setup_minutes=85,
        shoot_minutes=115,
    ),
    Scene(
        scene_id="SC-015",
        number="15",
        slugline="EXT. HARBOUR WALL - NIGHT",
        story_day=2,
        interior=False,
        day_night="NIGHT",
        location_id="LOC-HARBOUR-WALL",
        set_name="Harbour wall, east end",
        characters=("CHAR-MAREN",),
        page_eighths=4,
        synopsis="Maren signals the boat with a torch. Nobody answers.",
        action="Three long, one short. The fog takes it. She does it again anyway.",
        weather_sensitivity="high",
        night_required=True,
        special_requirements=("night_exterior", "water_adjacent"),
        equipment_ids=("EQ-CAM-A", "EQ-LIGHT-KIT-3", "EQ-SOUND-A", "EQ-GENERATOR-A"),
        props=("PROP-TORCH",),
        wardrobe_state="MAREN: oilskin, day 2 night",
        makeup_state="continuous",
        setup_minutes=95,
        shoot_minutes=60,
    ),
    Scene(
        scene_id="SC-016",
        number="16",
        slugline="INT. KITCHEN - NIGHT",
        story_day=2,
        interior=True,
        day_night="NIGHT",
        location_id="LOC-HOUSE-KITCHEN",
        set_name="Kitchen",
        characters=("CHAR-MAREN", "CHAR-SIRI", "CHAR-PIA"),
        page_eighths=8,
        synopsis="Three of them plan a sea trial nobody has permission to run.",
        action="A chart, a tide table and a nine-year-old's felt-tip annotations.",
        night_required=True,
        special_requirements=("child_performer",),
        equipment_ids=("EQ-CAM-A", "EQ-LIGHT-KIT-1", "EQ-SOUND-A"),
        props=("PROP-CHART-BOOK", "PROP-TIDE-TABLE", "PROP-FELT-TIPS"),
        wardrobe_state="day 2 night",
        makeup_state="continuous",
        setup_minutes=60,
        shoot_minutes=85,
    ),
    Scene(
        scene_id="SC-017",
        number="17",
        slugline="EXT. HARBOUR WALL - DAWN",
        story_day=3,
        interior=False,
        day_night="DAWN",
        location_id="LOC-HARBOUR-WALL",
        set_name="Harbour wall, east end",
        characters=("CHAR-ARVO",),
        page_eighths=4,
        synopsis="Arvo alone, early, looking at a boat he has already sold.",
        action="He does not touch it. That is the whole scene.",
        weather_sensitivity="moderate",
        daylight_required=True,
        special_requirements=("dawn_window",),
        equipment_ids=("EQ-CAM-A", "EQ-LIGHT-BOUNCE", "EQ-SOUND-A"),
        props=(),
        wardrobe_state="ARVO: navy smock, day 3",
        makeup_state="ARVO: right hand dressed",
        continuity_notes=("Hand dressing from SC-014 required",),
        setup_minutes=50,
        shoot_minutes=40,
    ),
    Scene(
        scene_id="SC-018",
        number="18",
        slugline="INT. LIGHTKEEPER - WHEELHOUSE - DAY",
        story_day=3,
        interior=True,
        day_night="DAY",
        location_id="LOC-BOAT-WHEELHOUSE",
        set_name="Wheelhouse",
        characters=("CHAR-MAREN", "CHAR-ARVO"),
        page_eighths=12,
        synopsis="The engine starts. Neither of them says anything for a long time.",
        action=(
            "It catches on the fourth turn. MAREN feels it before she sees the gauge. She puts "
            "both hands flat on the housing. ARVO watches her hands, not the gauge."
        ),
        equipment_ids=("EQ-CAM-A", "EQ-LIGHT-KIT-1", "EQ-SOUND-A", "EQ-GRIP-BOAT"),
        props=("PROP-WHEEL", "PROP-STARTER-MOTOR-B"),
        wardrobe_state="day 3",
        makeup_state="ARVO: right hand dressed; grease reduced",
        continuity_notes=("Hand dressing continuous from SC-017",),
        setup_minutes=75,
        shoot_minutes=120,
    ),
    Scene(
        scene_id="SC-019",
        number="19",
        slugline="EXT. QUAYSIDE - DAY",
        story_day=3,
        interior=False,
        day_night="DAY",
        location_id="LOC-QUAYSIDE",
        set_name="Quayside, north",
        characters=("CHAR-BUYER", "CHAR-TOIVO"),
        page_eighths=7,
        synopsis="The buyer arrives early and asks what the engine weighs.",
        action="He asks about weight. He does not ask about the boat.",
        dialogue=(
            ("BUYER", "What's the block weigh, roughly?"),
            ("TOIVO", "You'd have to ask the man selling it."),
            ("BUYER", "I'm asking the man who'll still be here Monday."),
        ),
        weather_sensitivity="moderate",
        daylight_required=True,
        equipment_ids=("EQ-CAM-A", "EQ-SOUND-A", "EQ-LIGHT-BOUNCE"),
        props=("PROP-CLIPBOARD",),
        wardrobe_state="BUYER: town coat; TOIVO: harbour coat day 3",
        makeup_state="clean",
        setup_minutes=45,
        shoot_minutes=70,
    ),
    Scene(
        scene_id="SC-020",
        number="20",
        slugline="INT. HARBOUR OFFICE - DAY",
        story_day=3,
        interior=True,
        day_night="DAY",
        location_id="LOC-HARBOUR-OFFICE",
        set_name="Harbour master's office",
        characters=("CHAR-TOIVO", "CHAR-SIRI"),
        page_eighths=6,
        synopsis="Toivo finds a rule. It buys them four hours.",
        action="He reads a paragraph twice, then a third time, out loud, to nobody.",
        equipment_ids=("EQ-CAM-A", "EQ-LIGHT-KIT-1", "EQ-SOUND-A"),
        props=("PROP-RULEBOOK", "PROP-DESK-DRESSING"),
        wardrobe_state="day 3",
        makeup_state="continuous",
        setup_minutes=50,
        shoot_minutes=65,
    ),
    Scene(
        scene_id="SC-021",
        number="21",
        slugline="EXT. SLIPWAY - DAY",
        story_day=3,
        interior=False,
        day_night="DAY",
        location_id="LOC-SLIPWAY",
        set_name="Slipway, high water",
        characters=("CHAR-MAREN", "CHAR-PIA", "CHAR-SIRI"),
        page_eighths=8,
        synopsis="They load the boat for a trial they may not be allowed to run.",
        action="Fenders, fuel cans, a flask. PIA carries one thing and supervises everything.",
        weather_sensitivity="high",
        daylight_required=True,
        special_requirements=("child_performer", "tide_dependent", "water_adjacent"),
        equipment_ids=("EQ-CAM-A", "EQ-CAM-B", "EQ-SOUND-A", "EQ-LIGHT-BOUNCE"),
        props=("PROP-FENDERS", "PROP-FUEL-CANS", "PROP-FLASK"),
        wardrobe_state="day 3",
        makeup_state="continuous",
        setup_minutes=70,
        shoot_minutes=85,
    ),
    Scene(
        scene_id="SC-022",
        number="22",
        slugline="INT. LIGHTKEEPER - WHEELHOUSE - DAY",
        story_day=3,
        interior=True,
        day_night="DAY",
        location_id="LOC-BOAT-WHEELHOUSE",
        set_name="Wheelhouse",
        characters=("CHAR-ARVO", "CHAR-BUYER"),
        page_eighths=9,
        synopsis="The buyer says the word 'parts' and Arvo hears it properly.",
        action="ARVO's hand stops on the throttle. It stays stopped for four seconds.",
        dialogue=(
            ("BUYER", "The hull's tired. It's the block and the gear I'm after, honestly."),
            ("ARVO", "Honestly."),
        ),
        equipment_ids=("EQ-CAM-A", "EQ-LIGHT-KIT-1", "EQ-SOUND-A", "EQ-GRIP-BOAT"),
        props=("PROP-WHEEL",),
        wardrobe_state="day 3",
        makeup_state="ARVO: hand dressed",
        setup_minutes=70,
        shoot_minutes=95,
    ),
    Scene(
        scene_id="SC-023",
        number="23",
        slugline="EXT. QUAYSIDE - DAY",
        story_day=3,
        interior=False,
        day_night="DAY",
        location_id="LOC-QUAYSIDE",
        set_name="Quayside, north",
        characters=("CHAR-MAREN", "CHAR-ARVO"),
        page_eighths=5,
        synopsis="Arvo tries to explain and uses his hands wrongly for the first time.",
        action=(
            "He gestures. It is not a sign, it is not speech, it is a man reaching for a language "
            "at seventy-one. MAREN waits. She does not help him."
        ),
        weather_sensitivity="moderate",
        daylight_required=True,
        special_requirements=("sign_language_content",),
        equipment_ids=("EQ-CAM-A", "EQ-SOUND-A", "EQ-LIGHT-BOUNCE"),
        props=(),
        wardrobe_state="day 3",
        makeup_state="continuous",
        setup_minutes=45,
        shoot_minutes=75,
    ),
    Scene(
        scene_id="SC-024",
        number="24",
        slugline="INT. KITCHEN - DUSK",
        story_day=3,
        interior=True,
        day_night="DUSK",
        location_id="LOC-HOUSE-KITCHEN",
        set_name="Kitchen",
        characters=("CHAR-SIRI", "CHAR-PIA"),
        page_eighths=5,
        synopsis="Pia asks what 'parts' means and Siri tells her the truth.",
        action="A nine-year-old receiving an adult answer and visibly deciding to be angry about it.",
        special_requirements=("child_performer",),
        equipment_ids=("EQ-CAM-B", "EQ-LIGHT-KIT-2", "EQ-SOUND-B"),
        props=("PROP-KITCHEN-DRESSING",),
        wardrobe_state="day 3",
        makeup_state="continuous",
        setup_minutes=50,
        shoot_minutes=60,
        unit="second",
    ),
    Scene(
        scene_id="SC-025",
        number="25",
        slugline="EXT. HARBOUR WALL - NIGHT",
        story_day=3,
        interior=False,
        day_night="NIGHT",
        location_id="LOC-HARBOUR-WALL",
        set_name="Harbour wall, east end — storm",
        characters=("CHAR-MAREN", "CHAR-ARVO", "CHAR-TOIVO"),
        page_eighths=14,
        synopsis="THE SEA TRIAL. Weather coming in. Maren takes the wheel. Arvo signs 'starboard'.",
        action=(
            "Wind rising. TOIVO on the wall with a torch, officially not watching. MAREN at the "
            "wheel. ARVO beside her with his hands empty. Then he lifts them and makes the shape. "
            "It is wrong. She corrects it with two fingers, the way she corrected PIA. He makes it "
            "again. Correctly. She turns the wheel."
        ),
        weather_sensitivity="prohibitive",
        night_required=True,
        special_requirements=(
            "night_exterior",
            "water_adjacent",
            "sign_language_content",
            "marine_safety_supervision",
        ),
        equipment_ids=(
            "EQ-CAM-A",
            "EQ-CAM-B",
            "EQ-LIGHT-KIT-3",
            "EQ-SOUND-A",
            "EQ-GENERATOR-A",
            "EQ-GRIP-BOAT",
        ),
        props=("PROP-TORCH", "PROP-WHEEL"),
        wardrobe_state="MAREN + ARVO: oilskins, day 3 night, wet",
        makeup_state="wet-down, ARVO hand dressed",
        continuity_notes=(
            "Wet-down is irreversible within the day: once played wet, SC-025 cannot be intercut "
            "with any dry day-3 exterior.",
        ),
        setup_minutes=120,
        shoot_minutes=120,
    ),
    Scene(
        scene_id="SC-026",
        number="26",
        slugline="EXT. OPEN WATER - NIGHT",
        story_day=3,
        interior=False,
        day_night="NIGHT",
        location_id="LOC-OPEN-WATER",
        set_name="Open water, one mile out",
        characters=("CHAR-MAREN", "CHAR-ARVO"),
        page_eighths=8,
        synopsis="The boat runs. It runs well. Neither of them looks back at the harbour.",
        action="Black water, a wake, two people who have stopped needing to explain anything.",
        weather_sensitivity="prohibitive",
        night_required=True,
        special_requirements=("night_exterior", "marine_safety_supervision", "water_adjacent"),
        equipment_ids=("EQ-CAM-B", "EQ-LIGHT-KIT-3", "EQ-SOUND-A", "EQ-GENERATOR-A"),
        props=("PROP-WHEEL",),
        wardrobe_state="continuous with SC-025, wet",
        makeup_state="wet-down continuous",
        setup_minutes=120,
        shoot_minutes=110,
    ),
    Scene(
        scene_id="SC-027",
        number="27",
        slugline="INT. LIGHTKEEPER - WHEELHOUSE - NIGHT",
        story_day=3,
        interior=True,
        day_night="NIGHT",
        location_id="LOC-BOAT-WHEELHOUSE",
        set_name="Wheelhouse, night",
        characters=("CHAR-MAREN", "CHAR-ARVO"),
        page_eighths=10,
        synopsis="Arvo asks her to teach him. He asks in the only way he can, badly.",
        action="He holds his hands up, open, and waits. It is the first question he has ever asked her.",
        night_required=True,
        special_requirements=("sign_language_content",),
        equipment_ids=("EQ-CAM-A", "EQ-LIGHT-KIT-2", "EQ-SOUND-A", "EQ-GRIP-BOAT"),
        props=("PROP-WHEEL",),
        wardrobe_state="continuous, drying",
        makeup_state="wet-down drying, hand dressed",
        setup_minutes=80,
        shoot_minutes=105,
    ),
    Scene(
        scene_id="SC-028",
        number="28",
        slugline="EXT. HARBOUR WALL - NIGHT",
        story_day=3,
        interior=False,
        day_night="NIGHT",
        location_id="LOC-HARBOUR-WALL",
        set_name="Harbour wall, east end",
        characters=("CHAR-TOIVO", "CHAR-BUYER"),
        page_eighths=6,
        synopsis="Toivo tells the buyer the trial was not authorised and therefore did not happen.",
        action="A small, precise, deniable act of sabotage performed entirely with paperwork.",
        dialogue=(("TOIVO", "There's no record of a trial. So there's no trial to have passed."),),
        weather_sensitivity="high",
        night_required=True,
        special_requirements=("night_exterior",),
        equipment_ids=("EQ-CAM-A", "EQ-LIGHT-KIT-3", "EQ-SOUND-A", "EQ-GENERATOR-A"),
        props=("PROP-CLIPBOARD", "PROP-TORCH"),
        wardrobe_state="day 3 night",
        makeup_state="clean",
        setup_minutes=85,
        shoot_minutes=70,
    ),
    Scene(
        scene_id="SC-029",
        number="29",
        slugline="INT. HOUSE - HALL - NIGHT",
        story_day=3,
        interior=True,
        day_night="NIGHT",
        location_id="LOC-HOUSE-HALL",
        set_name="Hall",
        characters=("CHAR-MAREN", "CHAR-SIRI", "CHAR-PIA"),
        page_eighths=6,
        synopsis="They come home wet. Pia has been waiting up and pretends she has not.",
        action="PIA is on the stairs in a coat, having very obviously been on the stairs for hours.",
        night_required=True,
        special_requirements=("child_performer",),
        equipment_ids=("EQ-CAM-B", "EQ-LIGHT-KIT-2", "EQ-SOUND-B"),
        props=("PROP-HALL-DRESSING",),
        wardrobe_state="MAREN wet, day 3 night; PIA: yellow coat over sleep clothes",
        makeup_state="wet-down",
        setup_minutes=55,
        shoot_minutes=65,
    ),
    Scene(
        scene_id="SC-030",
        number="30",
        slugline="INT. MAREN'S ROOM - NIGHT",
        story_day=3,
        interior=True,
        day_night="NIGHT",
        location_id="LOC-HOUSE-UPSTAIRS",
        set_name="Maren's room",
        characters=("CHAR-MAREN", "CHAR-ARVO"),
        page_eighths=9,
        synopsis="First lesson. He learns four words. He gets two of them wrong.",
        action="Two chairs, one lamp, four words. She is a patient teacher and he is a bad student.",
        night_required=True,
        special_requirements=("sign_language_content",),
        equipment_ids=("EQ-CAM-A", "EQ-LIGHT-KIT-1", "EQ-SOUND-A"),
        props=("PROP-LAMP",),
        wardrobe_state="dry clothes, day 3 night",
        makeup_state="clean, ARVO hand dressed",
        setup_minutes=60,
        shoot_minutes=95,
    ),
    Scene(
        scene_id="SC-031",
        number="31",
        slugline="EXT. HARBOUR WALL - DAWN",
        story_day=4,
        interior=False,
        day_night="DAWN",
        location_id="LOC-HARBOUR-WALL",
        set_name="Harbour wall, east end",
        characters=("CHAR-MAREN", "CHAR-ARVO"),
        page_eighths=5,
        synopsis="Monday. The berth is not theirs. The boat is still in it.",
        action="Nobody has moved it. Nobody is going to. Toivo's office light is off.",
        weather_sensitivity="moderate",
        daylight_required=True,
        special_requirements=("dawn_window",),
        equipment_ids=("EQ-CAM-A", "EQ-LIGHT-BOUNCE", "EQ-SOUND-A"),
        props=(),
        wardrobe_state="day 4",
        makeup_state="clean",
        setup_minutes=50,
        shoot_minutes=45,
    ),
    Scene(
        scene_id="SC-032",
        number="32",
        slugline="EXT. OPEN WATER - DAY",
        story_day=4,
        interior=False,
        day_night="DAY",
        location_id="LOC-OPEN-WATER",
        set_name="Open water",
        characters=("CHAR-MAREN", "CHAR-ARVO"),
        page_eighths=4,
        synopsis="Final image. Arvo signs 'starboard'. Correctly. She turns.",
        action="Wide. Held. No dialogue. Cut to black on the turn.",
        weather_sensitivity="high",
        daylight_required=True,
        special_requirements=("marine_safety_supervision", "sign_language_content"),
        equipment_ids=("EQ-CAM-A", "EQ-SOUND-A", "EQ-LIGHT-BOUNCE"),
        props=("PROP-WHEEL",),
        wardrobe_state="day 4",
        makeup_state="clean",
        setup_minutes=90,
        shoot_minutes=70,
    ),
)


SCENES_BY_ID: dict[str, Scene] = {s.scene_id: s for s in SCENES}


@dataclass(frozen=True)
class StoryDay:
    number: int
    label: str
    scene_ids: tuple[str, ...] = field(default_factory=tuple)


STORY_DAYS: tuple[StoryDay, ...] = tuple(
    StoryDay(
        number=n,
        label=f"Story day {n}",
        scene_ids=tuple(s.scene_id for s in SCENES if s.story_day == n),
    )
    for n in sorted({s.story_day for s in SCENES})
)


def total_page_eighths() -> int:
    return sum(s.page_eighths for s in SCENES)


def scenes_for_location(location_id: str) -> tuple[Scene, ...]:
    return tuple(s for s in SCENES if s.location_id == location_id)


def scenes_with_character(character_id: str) -> tuple[Scene, ...]:
    return tuple(s for s in SCENES if character_id in s.characters)


def child_performer_scenes() -> tuple[Scene, ...]:
    child_ids = {cid for cid, c in CHARACTERS.items() if c["child_performer"]}
    return tuple(s for s in SCENES if child_ids & set(s.characters))
