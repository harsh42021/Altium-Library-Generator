"""
Generates a human-readable review report from a component dict (as
produced by pipeline.run_pipeline + dataclasses.asdict, or loaded from
a saved JSON file). Returns a string so both the CLI and the GUI can
use it — the CLI prints it, the GUI puts it in a text widget.

CLI usage:
    python review_report.py component.json
"""
from __future__ import annotations
import json
import sys


def build_report(data: dict) -> str:
    lines: list[str] = []
    pins = data["pins"]

    lines.append("=" * 70)
    lines.append(f"REVIEW REPORT: {data['part_number']}")
    lines.append("=" * 70)

    lines.append(f"\nTotal pins extracted: {len(pins)}")
    lines.append(f"Multi-part symbol: {data['is_multi_part']}")

    if data.get("extraction_warnings"):
        lines.append(f"\n--- Extraction warnings ({len(data['extraction_warnings'])}) ---")
        for w in data["extraction_warnings"]:
            lines.append(f"  ! {w}")

    lines.append(f"\n--- Groups / sub-parts ({len(data['groups'])}) ---")
    for g in sorted(data["groups"], key=lambda g: (g["part_index"], g["name"])):
        lines.append(f"  part {g['part_index']:>2} | {g['name']:<35} | side={g['side']:<7} | {len(g['pins'])} pins")

    diff_pins = [p for p in pins if p["diff_pair_role"] != "none"]
    lines.append(f"\n--- Differential pairs ({len(diff_pins)} pins) ---")
    if diff_pins:
        for p in sorted(diff_pins, key=lambda p: p["primary_name"]):
            lines.append(f"  {p['pin_number']:>4}  {p['display_label'] or p['primary_name']:<35} [{p['diff_pair_role']}]")
        if len(diff_pins) % 2 != 0:
            lines.append("  *** ODD COUNT — a differential pair is missing its partner. Check manually. ***")
    else:
        lines.append("  (none detected — verify this is correct for the part; a missed diff pair is a common failure mode)")

    low_conf = [p for p in pins if p["source_confidence"] < 0.6]
    lines.append(f"\n--- Low-confidence pins requiring manual review ({len(low_conf)}) ---")
    for p in low_conf:
        lines.append(f"  {p['pin_number']:>4}  {p['display_label'] or p['primary_name']:<35} "
                      f"conf={p['source_confidence']:.2f}  type={p['electrical_type']}  struct={p['drive_structure']}")

    no_connect = [p for p in pins if p["is_no_connect"]]
    lines.append(f"\n--- No-connect pins ({len(no_connect)}) ---")
    for p in no_connect:
        lines.append(f"  {p['pin_number']:>4}  {p['primary_name']}")

    placeholder = [p for p in pins if str(p["pin_number"]).startswith("EP")]
    if placeholder:
        lines.append(f"\n--- Placeholder pin numbers — VERIFY against package drawing ({len(placeholder)}) ---")
        for p in placeholder:
            lines.append(f"  {p['pin_number']:>4}  {p['primary_name']}  (no numbered row in master pin table)")

    power_pins = [p for p in pins if p["electrical_type"] == "Power"]
    lines.append(f"\n--- Power/ground pins ({len(power_pins)}) — cross-check against absolute max ratings table ---")
    for p in power_pins:
        lines.append(f"  {p['pin_number']:>4}  {p['primary_name']}")

    lines.append("\n" + "=" * 70)
    lines.append("CHECKLIST before trusting this extraction:")
    lines.append("  [ ] Total pin count matches the package pin count in the datasheet title/package section")
    lines.append("  [ ] Differential pair count is even, and each pair's P/N assignment matches the datasheet")
    lines.append("  [ ] Every low-confidence pin above has been manually checked against the pin description table")
    lines.append("  [ ] Placeholder ('EP'-style) pin numbers verified against the mechanical/package drawing")
    lines.append("  [ ] Power pin voltage domains match what you intend to route on your board")
    lines.append("=" * 70)

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python review_report.py component.json")
        sys.exit(1)
    data = json.loads(open(sys.argv[1], encoding="utf-8").read())
    print(build_report(data))
