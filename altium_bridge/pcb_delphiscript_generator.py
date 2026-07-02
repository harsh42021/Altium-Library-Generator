"""
PCB footprint (PcbLib) DelphiScript generator.

WORKFLOW (mirrors the SchLib generator):
    1. In Altium, File > New > Library > PCB Library (or open an
       existing .PcbLib you want to add this footprint to).
    2. Keep that document focused/active.
    3. DXP > Run Script... > browse to the generated .pas file >
       select CreateFootprint > Run.
    4. Save the library (Ctrl+S).

ACCURACY NOTE: unlike the schematic generator (which went through
several rounds of trial-and-error against undocumented/mis-documented
API behavior), the core object-creation sequence here comes from a
SINGLE complete, non-truncated example that appears identically across
three independent Altium documentation mirrors — meaningfully higher
confidence than the schematic generator started with:
    CurrentLib := PCBServer.GetCurrentPCBLibrary
    NewComp := PCBServer.CreatePCBLibComp
    CurrentLib.RegisterComponent(NewComp)
    NewPad := PCBServer.PCBObjectFactory(ePadObject, eNoDimension, eCreate_Default)
    NewComp.AddPCBObject(NewPad)
    PCBServer.SendMessageToRobots(..., PCBM_BoardRegisteration, ...)
Still worth verifying on first run, same as always — "higher
confidence" isn't "verified working in your Altium version" until
it's actually run there.

SCOPE: only square/near-square QFN/DFN-style (perimeter-pad,
optional center thermal pad) packages are supported by the
pin-placement geometry below, using the standard JEDEC counter-
clockwise numbering (pin 1 at the top-left, proceeding down-left,
across-bottom, up-right, across-top) — confirmed against the actual
LAN8842 pinout, not assumed. A package that doesn't divide evenly into
4 equal sides (non-square, or pin count not divisible by 4) will
raise a clear error rather than silently produce wrong geometry.
"""
from __future__ import annotations
import re

MM_TO_MIL = 1000 / 25.4  # Altium's MilsToCoord expects mils; datasheet dims are in mm


def _mm(mm_value: float) -> float:
    return round(mm_value * MM_TO_MIL, 2)


def _pas_string_escape(s: str) -> str:
    return (s or "").replace("'", "''")


def _compute_qfn_pad_positions(pin_count: int, pitch_mil: float, span_x_mil: float, span_y_mil: float):
    """Computes (x_mil, y_mil, rotated) for each pin position (1-indexed)
    around a square/rectangular QFN/DFN perimeter, JEDEC counter-
    clockwise numbering (pin 1 top-left, down the left side first).
    span_x/span_y are the pad-center-to-pad-center distances between
    opposite sides (the datasheet's C1/C2 'Contact Pad Spacing').
    'rotated' is True for top/bottom-side pads, meaning X/Y pad size
    should be swapped from the left/right-side default so the pad's
    long axis runs along the package edge on every side."""
    if pin_count % 4 != 0:
        raise ValueError(
            f"Pin count {pin_count} isn't divisible by 4 — this package doesn't fit the "
            f"standard square QFN perimeter layout this generator supports. Manual footprint "
            f"placement needed for this part."
        )
    per_side = pin_count // 4
    positions = []

    half_x = span_x_mil / 2
    half_y = span_y_mil / 2

    # Side order matches confirmed JEDEC CCW numbering: left (top->bottom),
    # bottom (left->right), right (bottom->top), top (right->left)
    # Pin spacing centers on each side, symmetric about the midpoint.
    def side_offsets(n):
        # returns offsets from the side's center, evenly spaced by pitch
        start = -(n - 1) * pitch_mil / 2
        return [start + i * pitch_mil for i in range(n)]

    offsets = side_offsets(per_side)

    # Left side: pin 1 at top, going down => y decreases as pin number increases
    for off in offsets:
        positions.append((-half_x, -off, False))
    # Bottom side: left -> right => x increases
    for off in offsets:
        positions.append((off, -half_y, True))
    # Right side: bottom -> top => y increases
    for off in offsets:
        positions.append((half_x, off, False))
    # Top side: right -> left => x decreases
    for off in offsets:
        positions.append((-off, half_y, True))

    return positions  # index 0 == pin 1


def generate_pcb_delphiscript(component: dict, footprint_dims: dict) -> str:
    """component: the same dict shape produced by pipeline.py (has
    'pins', each with 'pin_number').
    footprint_dims: output of mechanical_dimension_parser.extract_footprint_dimensions."""
    part_number = _pas_string_escape(component["part_number"])
    pins = component["pins"]
    pin_count = len(pins)

    pitch_mil = _mm(footprint_dims["pitch_mm"])
    pad_w_mil = _mm(footprint_dims["pad_width_mm"])
    pad_l_mil = _mm(footprint_dims["pad_length_mm"])
    span_x_mil = _mm(footprint_dims.get("pad_span_x_mm") or 0)
    span_y_mil = _mm(footprint_dims.get("pad_span_y_mm") or 0)
    thermal_w_mil = _mm(footprint_dims["thermal_pad_width_mm"]) if footprint_dims.get("thermal_pad_width_mm") else None
    thermal_l_mil = _mm(footprint_dims["thermal_pad_length_mm"]) if footprint_dims.get("thermal_pad_length_mm") else None

    # Numbered pins only (exclude placeholder 'EP'-style entries — the
    # exposed pad is handled separately as its own dedicated pad, not
    # part of the perimeter numbering). Must be sorted by actual pin
    # number — the pins list preserves the datasheet master table's
    # original read order (e.g. '1','29','2','30'... from a dual-
    # column table layout), NOT numeric pin order, so zipping against
    # position index without sorting first silently misassigns every
    # pad to the wrong physical location.
    numbered_pins = sorted(
        (p for p in pins if not str(p["pin_number"]).upper().startswith("EP")),
        key=lambda p: int(re.sub(r"[^0-9]", "", str(p["pin_number"])) or 0)
    )
    exposed_pad_pins = [p for p in pins if str(p["pin_number"]).upper().startswith("EP")]

    if not span_x_mil or not span_y_mil:
        raise ValueError(
            "Footprint dimensions are missing pad_span_x_mm/pad_span_y_mm (the 'Contact Pad "
            "Spacing' values) — required for perimeter pad placement. This generator currently "
            "requires a vendor-provided recommended land pattern table with these values; the "
            "IPC-7351-estimate fallback doesn't compute them yet."
        )

    positions = _compute_qfn_pad_positions(len(numbered_pins), pitch_mil, span_x_mil, span_y_mil)

    lines: list[str] = []
    lines.append(f"{{ Auto-generated PCB footprint DelphiScript for part: {component['part_number']} }}")
    lines.append("{ ")
    lines.append("  HOW TO RUN:")
    lines.append("  1. In Altium: File > New > Library > PCB Library")
    lines.append("     (or open an existing .PcbLib to add this footprint to).")
    lines.append("  2. Keep that document focused/active.")
    lines.append("  3. DXP > Run Script... > browse to this file > select CreateFootprint > Run.")
    lines.append("  4. Save the library (Ctrl+S) after the script finishes.")
    lines.append("  5. VERIFY before trusting this footprint:")
    lines.append(f"     - Pad dimensions/spacing against the datasheet's land pattern drawing")
    lines.append(f"       (source used: {footprint_dims['source']})")
    lines.append("     - Pin 1 orientation and numbering direction match the datasheet pinout")
    lines.append("     - Exposed pad (if present) size and any thermal via requirements —")
    lines.append("       this generator creates the thermal pad itself but does NOT add a")
    lines.append("       thermal via array; add those manually per your fab's thermal design")
    lines.append("     - Silkscreen/courtyard were NOT generated — add per your library standard")
    lines.append("}")
    lines.append("")
    lines.append("Procedure CreateFootprint;")
    lines.append("Var")
    lines.append("    CurrentLib   : IPCB_Library;")
    lines.append("    NewComp      : IPCB_LibComponent;")
    lines.append("    NewPad       : IPCB_Pad;")
    lines.append("Begin")
    lines.append("    If PCBServer = Nil Then Exit;")
    lines.append("    CurrentLib := PCBServer.GetCurrentPCBLibrary;")
    lines.append("    If CurrentLib = Nil Then Begin")
    lines.append("        ShowMessage('No PCB Library document is focused. Open/create a .PcbLib and try again.');")
    lines.append("        Exit;")
    lines.append("    End;")
    lines.append("")
    lines.append("    NewComp := PCBServer.CreatePCBLibComp;")
    lines.append("    If NewComp = Nil Then Exit;")
    lines.append(f"    NewComp.Name := '{part_number}';")
    lines.append("    CurrentLib.RegisterComponent(NewComp);")
    lines.append("    PCBServer.PreProcess;")
    lines.append("")

    for pin, (x, y, rotated) in zip(numbered_pins, positions):
        designator = _pas_string_escape(str(pin["pin_number"]))
        label = _pas_string_escape(pin.get("display_label") or pin["primary_name"])
        x, y = round(x, 2), round(y, 2)
        top_x = pad_l_mil if rotated else pad_w_mil
        top_y = pad_w_mil if rotated else pad_l_mil
        lines.append(f"    {{ Pin {designator} ({label}) }}")
        lines.append("    NewPad := PCBServer.PCBObjectFactory(ePadObject, eNoDimension, eCreate_Default);")
        lines.append("    If NewPad = Nil Then Exit;")
        lines.append(f"    NewPad.X := MilsToCoord({x});")
        lines.append(f"    NewPad.Y := MilsToCoord({y});")
        lines.append(f"    NewPad.TopXSize := MilsToCoord({top_x});")
        lines.append(f"    NewPad.TopYSize := MilsToCoord({top_y});")
        lines.append(f"    NewPad.BottomXSize := MilsToCoord({top_x});")
        lines.append(f"    NewPad.BottomYSize := MilsToCoord({top_y});")
        lines.append("    NewPad.HoleSize := MilsToCoord(0);  { SMD pad, no drill }")
        lines.append("    NewPad.Layer := eTopLayer;")
        lines.append(f"    NewPad.Name := '{designator}';")
        lines.append("    NewComp.AddPCBObject(NewPad);")
        lines.append("")

    if exposed_pad_pins and thermal_w_mil and thermal_l_mil:
        ep = exposed_pad_pins[0]
        designator = _pas_string_escape(str(ep["pin_number"]))
        lines.append(f"    {{ Exposed/thermal pad ({_pas_string_escape(ep['primary_name'])}) }}")
        lines.append("    { BEST-EFFORT: no thermal via array added — see header notes }")
        lines.append("    NewPad := PCBServer.PCBObjectFactory(ePadObject, eNoDimension, eCreate_Default);")
        lines.append("    If NewPad = Nil Then Exit;")
        lines.append("    NewPad.X := MilsToCoord(0);")
        lines.append("    NewPad.Y := MilsToCoord(0);")
        lines.append(f"    NewPad.TopXSize := MilsToCoord({thermal_w_mil});")
        lines.append(f"    NewPad.TopYSize := MilsToCoord({thermal_l_mil});")
        lines.append(f"    NewPad.BottomXSize := MilsToCoord({thermal_w_mil});")
        lines.append(f"    NewPad.BottomYSize := MilsToCoord({thermal_l_mil});")
        lines.append("    NewPad.HoleSize := MilsToCoord(0);")
        lines.append("    NewPad.Layer := eTopLayer;")
        lines.append(f"    NewPad.Name := '{designator}';")
        lines.append("    NewComp.AddPCBObject(NewPad);")
        lines.append("")

    lines.append("    PCBServer.SendMessageToRobots(CurrentLib.Board.I_ObjectAddress, c_Broadcast, "
                  "PCBM_BoardRegisteration, NewComp.I_ObjectAddress);")
    lines.append("    PCBServer.PostProcess;")
    lines.append("    CurrentLib.CurrentComponent := NewComp;")
    lines.append("    CurrentLib.Board.ViewManager_FullUpdate;")
    lines.append("")
    lines.append("    ShowMessage('Footprint created. Press Ctrl+S to save the library.');")
    lines.append("End;")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    import json
    from pathlib import Path
    if len(sys.argv) != 4:
        print("Usage: python pcb_delphiscript_generator.py component.json datasheet.md output.pas")
        sys.exit(1)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python_extraction"))
    from parsers.mechanical_dimension_parser import extract_footprint_dimensions

    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    md_text = Path(sys.argv[2]).read_text(encoding="utf-8")
    dims, warnings = extract_footprint_dimensions(md_text)
    for w in warnings:
        print("WARNING:", w)
    if not dims:
        print("No footprint dimensions found — cannot generate.")
        sys.exit(1)

    script = generate_pcb_delphiscript(data, dims)
    Path(sys.argv[3]).write_text(script, encoding="utf-8")
    print(f"Wrote {sys.argv[3]}")
