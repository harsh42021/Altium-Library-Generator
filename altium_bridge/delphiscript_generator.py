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

ACCURACY NOTE / DEBUGGING HISTORY (read this if pins still don't appear):
Object creation uses direct assignment (SchComponent := SchServer.
SchObjectFactory(...)) rather than the Supports(...) interface-query
pattern shown in some Altium doc examples — that pattern threw
"Undeclared identifier" errors for ISch_Lib, ISch_Component, etc. in
real-world testing against Altium 24/25.

For attaching pins/rectangles to the component, two different Altium
doc pages show two different-looking patterns for two different
contexts (defining a library symbol vs. placing a component instance
on a sheet). An earlier version of this generator switched to
CurrentLib.RegisterSchObjectInContainer(...), based on the
sheet-placement pattern, and that produced a component with the
correct part count but zero visible/selectable pins. This version
reverts to SchComponent.AddSchObject(...) — confirmed directly in
Altium's ISch_GraphicalObject documentation ("Component.AddSchObject
(Rect); Component.AddSchObject(Pin);") — combined with each object's
OwnerPartId property (also directly documented) for correct multi-part
assignment, which was the other candidate missing piece.

If pins STILL don't appear after this version, the next thing to try
is Altium's own bundled example scripts rather than another inference
from documentation: search your Altium install directory for *.pas
files (may require enabling an "Examples" component via Altium's
installer/updater if none are found), or pull a real working example
from https://github.com/Altium-Designer-addons/scripting-reference
— specifically anything under "Delphiscript Scripts/Sch" that creates
a library component. A verified-working example beats further
inference at this point.

One property (Pin.PinLength) and the document-save call still could
not be confirmed against current docs and are marked BEST-EFFORT
below.
"""
from __future__ import annotations

# Pin layout constants, in mils (Altium's native grid unit is 100 mil = 0.1")
GRID = 100
PIN_LENGTH = 200          # BEST-EFFORT: verify Pin.Length / PinLength property name in Altium
PIN_SPACING = 100
MIN_BODY_DIM = 200
CHAR_WIDTH_ESTIMATE = 60  # rough mils/character at default Altium pin-name font size —
                           # used only to size the body wide enough that left- and right-
                           # side pin name labels don't overlap in the middle; doesn't need
                           # to be exact, just generous enough to avoid collisions
LABEL_MARGIN = 200        # extra clearance beyond the longest label on each side

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
    Horizontal only (0°/180°) — vertical sides are never assigned
    upstream, so top/bottom aren't handled here.
    BEST-EFFORT: verify pin direction visually on first run and swap
    0/180 here if pins point the wrong way for your Altium version."""
    return {
        "left": "eRotate180",   # pin extends further left, body is to its right
        "right": "eRotate0",    # pin extends further right, body is to its left
    }.get(side, "eRotate180")


def _estimate_label_width(label: str) -> int:
    """Rough mils-width estimate for a pin name label, used only to
    size the component body wide enough to prevent left/right pin
    labels from overlapping in the middle — doesn't need to be exact."""
    return len(label or "") * CHAR_WIDTH_ESTIMATE


def _layout_pins(component: dict) -> dict:
    """Computes (x, y, side) for every pin in every sub-part, grid-
    snapped, and the bounding rectangle for each sub-part's body.
    Left/right (horizontal) placement only. Body width is sized from
    the longest pin label on either side, not a fixed minimum — a
    fixed-width body is what caused left- and right-side pin name
    labels to overlap in the middle when labels were longer than the
    (previously hardcoded) body width could accommodate.
    Returns {part_index: {"pins": [...], "body": (x1,y1,x2,y2)}}."""
    parts: dict[int, dict] = {}

    pins_by_part: dict[int, dict[str, list]] = {}
    for group in component["groups"]:
        part_idx = group["part_index"]
        pins_by_part.setdefault(part_idx, {"left": [], "right": []})
        side = group["side"] if group["side"] in ("left", "right") else "left"
        for pin in group["pins"]:
            pins_by_part[part_idx][side].append((pin, group["name"]))

    for part_idx, sides in pins_by_part.items():
        left_pins = sides["left"]
        right_pins = sides["right"]

        body_height = max(MIN_BODY_DIM, (max(len(left_pins), len(right_pins)) + 1) * PIN_SPACING)
        body_height = ((body_height + GRID - 1) // GRID) * GRID

        all_labels = [
            (pin.get("display_label") or pin["primary_name"])
            for pin, _ in left_pins + right_pins
        ]
        max_label_width = max((_estimate_label_width(lbl) for lbl in all_labels), default=0)
        body_width = max(MIN_BODY_DIM, max_label_width + LABEL_MARGIN)
        body_width = ((body_width + GRID - 1) // GRID) * GRID

        placed = []

        def place_side(pins, x_body_edge, direction_sign, side_name):
            n = len(pins)
            start_y = body_height - (body_height - (n - 1) * PIN_SPACING) // 2 if n > 1 else body_height // 2
            for i, (pin, group_name) in enumerate(pins):
                y = start_y - i * PIN_SPACING
                y = (y // GRID) * GRID
                x_tip = x_body_edge + direction_sign * PIN_LENGTH
                placed.append((pin, group_name, x_tip, y, side_name))

        place_side(left_pins, 0, -1, "left")
        place_side(right_pins, body_width, 1, "right")

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
    lines.append("     - Part Number/Manufacturer/Build parameters were added with BLANK values —")
    lines.append("       fill these in via the Properties panel after the component is created")
    lines.append("       (Param.Text is BEST-EFFORT — if it errors, try Param.SetState_Text(''))")
    lines.append("}")
    lines.append("")
    lines.append("Procedure CreateComponent;")
    lines.append("Var")
    lines.append("    CurrentLib   : ISch_Lib;")
    lines.append("    SchComponent : ISch_Component;")
    lines.append("    R            : ISch_Rectangle;")
    lines.append("    Pin          : ISch_Pin;")
    lines.append("    Param        : ISch_Parameter;")
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
    lines.append("    SchComponent := SchServer.SchObjectFactory(eSchComponent, eCreate_Default);")
    lines.append("    If SchComponent = Nil Then Exit;")
    lines.append(f"    SchComponent.LibReference := '{part_number}';")
    lines.append(f"    SchComponent.ComponentDescription := 'Auto-generated from datasheet extraction — VERIFY before use';")
    lines.append(f"    SchComponent.PartCount := {len(layout)};  {{ BEST-EFFORT property name — verify }}")
    lines.append("    SchComponent.DisplayMode := 0;")
    lines.append("    { NOTE: SchComponent is NOT added to the library yet — every pin and")
    lines.append("      rectangle below is built into this in-memory component object first.")
    lines.append("      AddSchComponent is called ONCE at the very end, after everything is")
    lines.append("      in place. Registering it earlier risked the library storing an empty")
    lines.append("      snapshot while pins were added to an orphaned copy — which is the")
    lines.append("      most likely explanation if a previous run showed 'component created'")
    lines.append("      but nothing appeared in the library. }")
    lines.append("")

    for part_idx in sorted(layout.keys()):
        data = layout[part_idx]
        x1, y1, x2, y2 = data["body"]
        lines.append(f"    { '{' } --- Part {part_idx} --- { '}' }")
        lines.append(f"    SchComponent.CurrentPartID := {part_idx};")
        lines.append("    R := SchServer.SchObjectFactory(eRectangle, eCreate_Default);")
        lines.append("    If R = Nil Then Exit;")
        lines.append(f"    R.Location := Point(MilsToCoord({x1}), MilsToCoord({y1}));")
        lines.append(f"    R.Corner   := Point(MilsToCoord({x2}), MilsToCoord({y2}));")
        lines.append("    R.LineWidth := eSmall;")
        lines.append("    R.AreaColor := $00E0E0E0;")
        lines.append("    R.IsSolid := True;")
        lines.append(f"    R.OwnerPartId := {part_idx};")
        lines.append("    SchComponent.AddSchObject(R);")
        lines.append("")

        for pin, group_name, x, y, side in data["pins"]:
            elec = ELECTRICAL_TYPE_MAP.get(pin["electrical_type"], "eElectricPassive")
            label = _pas_string_escape(pin.get("display_label") or pin["primary_name"])
            designator = _pas_string_escape(str(pin["pin_number"]))
            orientation = _side_orientation(side)
            lines.append(f"    { '{' } Pin {designator} ({label}) — group: {group_name} { '}' }")
            lines.append("    Pin := SchServer.SchObjectFactory(ePin, eCreate_Default);")
            lines.append("    If Pin = Nil Then Exit;")
            lines.append(f"    Pin.Designator := '{designator}';")
            lines.append(f"    Pin.Name := '{label}';")
            lines.append(f"    Pin.Electrical := {elec};")
            lines.append(f"    Pin.Orientation := {orientation};")
            lines.append(f"    Pin.Location := Point(MilsToCoord({x}), MilsToCoord({y}));")
            lines.append(f"    Pin.PinLength := MilsToCoord({PIN_LENGTH});  {{ BEST-EFFORT property name — verify }}")
            lines.append(f"    Pin.OwnerPartId := {part_idx};")
            lines.append("    SchComponent.AddSchObject(Pin);")
            lines.append("")

    lines.append("    SchComponent.CurrentPartID := 1;")
    lines.append("    CurrentLib.AddSchComponent(SchComponent);")
    lines.append("    CurrentLib.CurrentSchComponent := SchComponent;")
    lines.append("")
    lines.append("    { Component parameters — values intentionally left blank for you to fill in }")
    lines.append("    Param := SchServer.SchObjectFactory(eParameter, eCreate_Default);")
    lines.append("    If Param = Nil Then Exit;")
    lines.append("    Param.Name := 'Part Number';")
    lines.append("    Param.Text := '';")
    lines.append("    SchComponent.AddSchObject(Param);")
    lines.append("")
    lines.append("    Param := SchServer.SchObjectFactory(eParameter, eCreate_Default);")
    lines.append("    If Param = Nil Then Exit;")
    lines.append("    Param.Name := 'Manufacturer';")
    lines.append("    Param.Text := '';")
    lines.append("    SchComponent.AddSchObject(Param);")
    lines.append("")
    lines.append("    Param := SchServer.SchObjectFactory(eParameter, eCreate_Default);")
    lines.append("    If Param = Nil Then Exit;")
    lines.append("    Param.Name := 'Build';")
    lines.append("    Param.Text := '';")
    lines.append("    SchComponent.AddSchObject(Param);")
    lines.append("")
    lines.append("    CurrentLib.GraphicallyInvalidate;")
    lines.append("")
    lines.append("    ShowMessage('Component created. Press Ctrl+S to save the library.' + #13#10#13#10 +")
    lines.append("        'If nothing is visible: open the SCH Library panel (View > Workspace Panels > SCH > SCH Library),' + #13#10 +")
    lines.append(f'        \'select "{part_number}" in the list, then View > Fit Document to zoom to it.\');')
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
