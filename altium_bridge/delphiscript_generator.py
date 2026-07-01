"""
DelphiScript generator — turns a component.json (produced by
pipeline.py) into a .pas script that Altium Designer runs to build the
actual SchLib component.

WORKFLOW (see the header comment embedded in the generated script for
the same instructions, so they travel with the file):
    1. In Altium, File > New > Library > Schematic Library (or open an
       existing .SchLib you want to add this component to).
    2. Keep that document focused/active.
    3. DXP > Run Script... > browse to the generated .pas file > run
       the CreateComponent procedure.
    4. Save the library (Ctrl+S) — the script does not reliably save
       for you across all Altium versions; see notes below.

ACCURACY NOTE: the object-creation calls here (SchObjectFactory,
AddSchComponent, the TPinElectrical enum, TRotationBy90, Point/
MilsToCoord) are sourced directly from Altium's published Scripting
API documentation. A few properties (Pin.Length, SchComponent.
PartCount, and the save call) could not be confirmed against current
docs and are marked BEST-EFFORT below — verify these against Altium's
Script IDE autocomplete (Ctrl+Space on the object) before relying on
this for a production library, and report back what you find so this
generator can be corrected rather than guessed at twice.
"""
from __future__ import annotations

# Pin layout constants, in mils (Altium's native grid unit is 100 mil = 0.1")
GRID = 100
PIN_LENGTH = 200          # BEST-EFFORT: verify Pin.Length / PinLength property name in Altium
PIN_SPACING = 100
BODY_MARGIN = 100         # gap between pin tip row and body edge on the perpendicular axis
MIN_BODY_DIM = 200

# Maps our ElectricalType enum values (see models/pin.py) to Altium's
# verified TPinElectrical constants. UNKNOWN has no Altium equivalent —
# defaulting to ePassive is deliberate: it's the least likely to cause
# an incorrect ERC violation for a pin whose real type wasn't determined
# with confidence, and it's a visible, searchable placeholder in the
# generated script (grep for "eElectricPassive" against low-confidence
# pins from the review report to find what needs manual correction).
ELECTRICAL_TYPE_MAP = {
    "Input": "eElectricInput",
    "Output": "eElectricOutput",
    "IO": "eElectricIO",
    "OpenCollector": "eElectricOpenCollector",
    "Passive": "eElectricPassive",
    "HiZ": "eElectricHiZ",
    "OpenEmitter": "eElectricOpenEmitter",
    "Power": "eElectricPower",
    "Unknown": "eElectricPassive",  # see note above
}


def _pas_string_escape(s: str) -> str:
    return (s or "").replace("'", "''")


def _side_orientation(side: str) -> str:
    """Altium pin Orientation is the direction the pin's electrical
    (outer) end points AWAY from the body, per TRotationBy90.
    BEST-EFFORT mapping — verify pin direction visually on first run
    and swap 0/180 or 90/270 here if pins point the wrong way for your
    Altium version."""
    return {
        "left": "eRotate180",   # pin extends further left, body is to its right
        "right": "eRotate0",    # pin extends further right, body is to its left
        "top": "eRotate90",
        "bottom": "eRotate270",
    }.get(side, "eRotate180")


def _layout_pins(component: dict) -> dict:
    """Computes (x, y, side) for every pin in every sub-part, grid-
    snapped, and the bounding rectangle for each sub-part's body.
    Returns {part_index: {"pins": [...], "body": (x1,y1,x2,y2)}}."""
    parts: dict[int, dict] = {}

    # group pins by part_index, then by side within each part
    pins_by_part: dict[int, dict[str, list]] = {}
    for group in component["groups"]:
        part_idx = group["part_index"]
        pins_by_part.setdefault(part_idx, {"left": [], "right": [], "top": [], "bottom": []})
        side = group["side"] if group["side"] in ("left", "right", "top", "bottom") else "left"
        for pin in group["pins"]:
            pins_by_part[part_idx][side].append((pin, group["name"]))

    for part_idx, sides in pins_by_part.items():
        left_n = len(sides["left"])
        right_n = len(sides["right"])
        top_n = len(sides["top"])
        bottom_n = len(sides["bottom"])

        body_height = max(MIN_BODY_DIM, (max(left_n, right_n) + 1) * PIN_SPACING)
        body_width = max(MIN_BODY_DIM, (max(top_n, bottom_n) + 1) * PIN_SPACING)
        # snap to grid
        body_height = ((body_height + GRID - 1) // GRID) * GRID
        body_width = ((body_width + GRID - 1) // GRID) * GRID

        placed = []

        def place_vertical_side(pins, x_body_edge, direction_sign, side_name):
            n = len(pins)
            start_y = body_height - (body_height - (n - 1) * PIN_SPACING) // 2 if n > 1 else body_height // 2
            for i, (pin, group_name) in enumerate(pins):
                y = start_y - i * PIN_SPACING
                y = (y // GRID) * GRID
                x_tip = x_body_edge + direction_sign * PIN_LENGTH
                placed.append((pin, group_name, x_tip, y, side_name))

        def place_horizontal_side(pins, y_body_edge, direction_sign, side_name):
            n = len(pins)
            start_x = -( (n - 1) * PIN_SPACING ) // 2 if n > 1 else 0
            for i, (pin, group_name) in enumerate(pins):
                x = start_x + i * PIN_SPACING
                x = (x // GRID) * GRID
                y_tip = y_body_edge + direction_sign * PIN_LENGTH
                placed.append((pin, group_name, x, y_tip, side_name))

        place_vertical_side(sides["left"], 0, -1, "left")
        place_vertical_side(sides["right"], body_width, 1, "right")
        place_horizontal_side(sides["top"], body_height, 1, "top")
        place_horizontal_side(sides["bottom"], 0, -1, "bottom")

        parts[part_idx] = {
            "pins": placed,
            "body": (0, 0, body_width, body_height),
        }

    return parts


def generate_delphiscript(component: dict) -> str:
    part_number = _pas_string_escape(component["part_number"])
    layout = _layout_pins(component)
    lines: list[str] = []

    lines.append(f"{{ Auto-generated DelphiScript for part: {component['part_number']} }}")
    lines.append("{ ")
    lines.append("  HOW TO RUN:")
    lines.append("  1. In Altium: File > New > Library > Schematic Library")
    lines.append("     (or open an existing .SchLib to add this component to).")
    lines.append("  2. Keep that document focused/active.")
    lines.append("  3. DXP > Run Script... > browse to this file > select CreateComponent > Run.")
    lines.append("  4. Save the library (Ctrl+S) after the script finishes.")
    lines.append("  5. VERIFY before trusting this component:")
    lines.append("     - Pin directions look correct (tip pointing away from body)")
    lines.append("     - Any pin using eElectricPassive as a fallback (search for it below)")
    lines.append("       was actually classified correctly upstream — check the review report")
    lines.append("     - PartCount / multi-part switching works as expected in your Altium version")
    lines.append("}")
    lines.append("")
    lines.append("Procedure CreateComponent;")
    lines.append("Var")
    lines.append("    CurrentLib   : ISch_Lib;")
    lines.append("    SchComponent : ISch_Component;")
    lines.append("    R            : ISch_Rectangle;")
    lines.append("    Pin          : ISch_Pin;")
    lines.append("    PartIdx      : Integer;")
    lines.append("Begin")
    lines.append("    If SchServer = Nil Then Exit;")
    lines.append("    CurrentLib := SchServer.GetCurrentSchDocument;")
    lines.append("    If CurrentLib = Nil Then Begin")
    lines.append("        ShowMessage('No document is focused. Open/create a .SchLib and try again.');")
    lines.append("        Exit;")
    lines.append("    End;")
    lines.append("    If CurrentLib.ObjectID <> eSchLib Then Begin")
    lines.append("        ShowMessage('The focused document is not a Schematic Library (.SchLib). Open/create one and try again.');")
    lines.append("        Exit;")
    lines.append("    End;")
    lines.append("")
    lines.append("    If Not Supports(SchServer.SchObjectFactory(eSchComponent, eCreate_Default), ISch_Component, SchComponent) Then Exit;")
    lines.append(f"    SchComponent.LibReference := '{part_number}';")
    lines.append(f"    SchComponent.ComponentDescription := 'Auto-generated from datasheet extraction — VERIFY before use';")
    lines.append("    SchComponent.CurrentPartID := 1;")
    lines.append(f"    SchComponent.PartCount := {len(layout)};  {{ BEST-EFFORT property name — verify }}")
    lines.append("    SchComponent.DisplayMode := 0;")
    lines.append("    CurrentLib.AddSchComponent(SchComponent);")
    lines.append("    CurrentLib.CurrentSchComponent := SchComponent;")
    lines.append("")

    for part_idx in sorted(layout.keys()):
        data = layout[part_idx]
        x1, y1, x2, y2 = data["body"]
        lines.append(f"    { '{' } --- Part {part_idx} --- { '}' }")
        lines.append(f"    SchComponent.CurrentPartID := {part_idx};")
        lines.append("    If Not Supports(SchServer.SchObjectFactory(eRectangle, eCreate_Default), ISch_Rectangle, R) Then Exit;")
        lines.append(f"    R.Location := Point(MilsToCoord({x1}), MilsToCoord({y1}));")
        lines.append(f"    R.Corner   := Point(MilsToCoord({x2}), MilsToCoord({y2}));")
        lines.append("    R.LineWidth := eSmall;")
        lines.append("    R.AreaColor := $00E0E0E0;")
        lines.append("    R.IsSolid := True;")
        lines.append("    SchComponent.AddSchObject(R);")
        lines.append("")

        for pin, group_name, x, y, side in data["pins"]:
            elec = ELECTRICAL_TYPE_MAP.get(pin["electrical_type"], "eElectricPassive")
            label = _pas_string_escape(pin.get("display_label") or pin["primary_name"])
            designator = _pas_string_escape(str(pin["pin_number"]))
            orientation = _side_orientation(side)
            lines.append(f"    { '{' } Pin {designator} ({label}) — group: {group_name} { '}' }")
            lines.append("    If Not Supports(SchServer.SchObjectFactory(ePin, eCreate_Default), ISch_Pin, Pin) Then Exit;")
            lines.append(f"    Pin.Designator := '{designator}';")
            lines.append(f"    Pin.Name := '{label}';")
            lines.append(f"    Pin.Electrical := {elec};")
            lines.append(f"    Pin.Orientation := {orientation};")
            lines.append(f"    Pin.Location := Point(MilsToCoord({x}), MilsToCoord({y}));")
            lines.append(f"    Pin.PinLength := MilsToCoord({PIN_LENGTH});  {{ BEST-EFFORT property name — verify }}")
            lines.append("    SchComponent.AddSchObject(Pin);")
            lines.append("")

    lines.append("    SchComponent.CurrentPartID := 1;")
    lines.append("    CurrentLib.GraphicallyInvalidate;")
    lines.append("")
    lines.append("    ShowMessage('Component created. Press Ctrl+S to save the library.');")
    lines.append("End;")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) != 3:
        print("Usage: python delphiscript_generator.py component.json output.pas")
        sys.exit(1)
    data = json.loads(open(sys.argv[1], encoding="utf-8").read())
    script = generate_delphiscript(data)
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(script)
    print(f"Wrote {sys.argv[2]}")
