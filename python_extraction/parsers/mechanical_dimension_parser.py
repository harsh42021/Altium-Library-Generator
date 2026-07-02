"""
Mechanical/footprint dimension extraction.

Two-tier strategy, in priority order:
1. VENDOR RECOMMENDED LAND PATTERN — many modern datasheets (this
   Microchip one included) publish their own recommended PCB land
   pattern table directly (pad width/length, pitch, thermal pad size,
   pad-to-pad spacing). This is strictly better than computing our own
   IPC-7351 estimate — it's the vendor's actual validated
   recommendation, not an inference — so it's always preferred when
   present. Same principle used throughout this tool: trust
   vendor-provided ground truth over our own calculation wherever the
   vendor actually provides it.
2. IPC-7351 NOMINAL CALCULATION from raw package dimensions (N, e, D,
   E, D2/E2, b, L for a QFN; similarly for other package families) —
   used only when no recommended land pattern table exists. This is a
   first-pass estimate using the "nominal" (not most/least material
   condition) formulas and should be treated as a starting point for
   review, not a final footprint, same caveat as the schematic symbol
   generator.

Only QFN/DFN-style (dual/quad flat no-lead) packages are handled by
the IPC-7351 fallback for now — other package families (SOIC, QFP,
BGA) will fall through with a warning rather than produce a wrong
footprint silently.
"""
from __future__ import annotations
import re

from parsers.structured_datasheet_parser import find_titled_tables
from parsers.markdown_parser import _split_markdown_table


def _parse_dim_value(raw: str) -> float | None:
    """Parses a dimension cell like '0.50 BSC', '5.90', '0.20 REF',
    '–', '-', '' into a float in mm, or None if not a numeric value."""
    if not raw:
        return None
    cleaned = raw.strip().upper()
    cleaned = re.sub(r"\b(BSC|REF|MAX|MIN|TYP)\b", "", cleaned).strip()
    if cleaned in ("", "-", "–", "—", "N/A"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_dimension_table(md_block: str) -> dict[str, dict]:
    """Parses a 5-column (Name, Symbol, MIN, NOM, MAX) dimension table,
    skipping any junk header rows (e.g. a leading 'Units | MILLIMETERS'
    row) until it finds the real header containing MIN/MAX. Returns
    {symbol_upper: {"name": ..., "min": float|None, "nom": ..., "max": ...}}."""
    rows = _split_markdown_table(md_block)
    header_idx = None
    for i, row in enumerate(rows):
        row_upper = [c.strip().upper() for c in row]
        if "MIN" in row_upper and "MAX" in row_upper:
            header_idx = i
            break
    if header_idx is None:
        return {}

    header = [c.strip().upper() for c in rows[header_idx]]
    try:
        min_idx = header.index("MIN")
        max_idx = header.index("MAX")
        nom_idx = header.index("NOM") if "NOM" in header else None
    except ValueError:
        return {}

    result: dict[str, dict] = {}
    needed_len = max(min_idx, max_idx, nom_idx or 0) + 1
    for row in rows[header_idx + 1:]:
        if len(row) < 2:
            continue
        # Trailing empty cells are commonly dropped in PDF-to-markdown
        # table conversion (a row ending in an empty MAX column loses
        # its trailing '|' entirely) — pad rather than skip, since
        # skipping silently drops real data rows like 'Contact Pitch'.
        if len(row) < needed_len:
            row = row + [""] * (needed_len - len(row))
        name = row[0].strip() if len(row) > 0 else ""
        symbol = row[1].strip().upper() if len(row) > 1 else ""
        if not symbol:
            continue
        min_v = _parse_dim_value(row[min_idx])
        max_v = _parse_dim_value(row[max_idx])
        nom_v = _parse_dim_value(row[nom_idx]) if nom_idx is not None else None
        result[symbol] = {"name": name, "min": min_v, "nom": nom_v, "max": max_v}
    return result


def find_land_pattern_dimensions(markdown_text: str) -> dict[str, dict] | None:
    """Finds and parses a 'RECOMMENDED LAND PATTERN' table if present."""
    for title, block in find_titled_tables(markdown_text):
        if re.search(r"RECOMMENDED\s+LAND\s+PATTERN", title, re.IGNORECASE):
            parsed = _parse_dimension_table(block)
            if parsed:
                return parsed
    return None


def find_package_dimensions(markdown_text: str) -> dict[str, dict] | None:
    """Finds and parses the raw package/mechanical dimension table
    (e.g. 'FIGURE X-Y: NN-VQFN PACKAGE (DIMENSIONS)')."""
    for title, block in find_titled_tables(markdown_text):
        if re.search(r"PACKAGE\s*\(DIMENSIONS\)|MECHANICAL\s+DATA|PACKAGE\s+DIMENSIONS", title, re.IGNORECASE):
            parsed = _parse_dimension_table(block)
            if parsed:
                return parsed
    return None


def compute_qfn_land_pattern_ipc7351(pkg_dims: dict[str, dict]) -> dict | None:
    """IPC-7351 nominal-density land pattern estimate for a QFN/DFN
    package, from raw package body dimensions. Formulas (nominal
    density level):
        Pad width  = b(max) + 0.05mm (slight toe extension)
        Pad length = 0.35mm to 0.5mm typical, derived from lead length
                     L: pad_length ≈ L(max) + 0.6mm (toe + heel fillet)
        Pad pitch  = e (lead pitch), unchanged
        Pad span (pad centerline to pad centerline, opposite sides)
                   ≈ D(max) [or E(max)] + pad_length - lead_length_overlap
    These are approximations; a vendor-published land pattern (see
    find_land_pattern_dimensions) is always preferred over this when
    available. Returns None if required symbols aren't present."""
    required = ["E", "D", "B", "L"]  # pitch, body length, lead width, lead length
    if not all(sym in pkg_dims for sym in required):
        return None

    def val(sym, prefer="nom"):
        entry = pkg_dims.get(sym, {})
        return entry.get(prefer) or entry.get("max") or entry.get("min")

    pitch = val("E")
    body_d = val("D", "max") or val("D")
    body_e = val("E2") and val("E")  # not used directly; body width handled via D/E BSC symbols separately
    lead_width = val("B", "max") or val("B")
    lead_length = val("L", "max") or val("L")
    epad_d2 = val("D2", "max") or val("D2")
    epad_e2 = val("E2", "max") or val("E2")

    if not all([pitch, lead_width, lead_length]):
        return None

    pad_width_mm = lead_width + 0.05
    pad_length_mm = lead_length + 0.6
    thermal_pad_width_mm = epad_e2 if epad_e2 else None
    thermal_pad_length_mm = epad_d2 if epad_d2 else None

    return {
        "source": "ipc7351_nominal_estimate",
        "pitch_mm": pitch,
        "pad_width_mm": round(pad_width_mm, 3),
        "pad_length_mm": round(pad_length_mm, 3),
        "thermal_pad_width_mm": round(thermal_pad_width_mm, 3) if thermal_pad_width_mm else None,
        "thermal_pad_length_mm": round(thermal_pad_length_mm, 3) if thermal_pad_length_mm else None,
        "body_length_mm": body_d,
    }


def extract_footprint_dimensions(markdown_text: str) -> tuple[dict | None, list[str]]:
    """Top-level entry point. Returns (dimensions_dict, warnings).
    dimensions_dict is normalized regardless of source:
        {
            "source": "vendor_land_pattern" | "ipc7351_nominal_estimate",
            "pitch_mm": float,
            "pad_width_mm": float,
            "pad_length_mm": float,
            "pad_span_x_mm": float | None,   # contact pad spacing, X axis (only from vendor table)
            "pad_span_y_mm": float | None,
            "thermal_pad_width_mm": float | None,
            "thermal_pad_length_mm": float | None,
        }
    Returns (None, warnings) if no usable dimension data was found.
    """
    warnings: list[str] = []

    land_pattern = find_land_pattern_dimensions(markdown_text)
    if land_pattern:
        def g(sym):
            e = land_pattern.get(sym, {})
            return e.get("max") or e.get("nom") or e.get("min")

        pitch = g("E")
        pad_width = g("X1")
        pad_length = g("Y1")
        pad_span_x = g("C1")
        pad_span_y = g("C2")
        thermal_w = g("X2")
        thermal_l = g("Y2")

        if pitch and pad_width and pad_length:
            return {
                "source": "vendor_land_pattern",
                "pitch_mm": pitch,
                "pad_width_mm": pad_width,
                "pad_length_mm": pad_length,
                "pad_span_x_mm": pad_span_x,
                "pad_span_y_mm": pad_span_y,
                "thermal_pad_width_mm": thermal_w,
                "thermal_pad_length_mm": thermal_l,
            }, warnings
        warnings.append("Found a 'Recommended Land Pattern' table but couldn't parse required "
                         "columns (pitch/pad width/pad length) — falling back to package dimensions.")

    pkg_dims = find_package_dimensions(markdown_text)
    if pkg_dims:
        computed = compute_qfn_land_pattern_ipc7351(pkg_dims)
        if computed:
            warnings.append("No vendor-provided land pattern table found — using an IPC-7351 "
                             "nominal-density ESTIMATE computed from raw package dimensions. "
                             "This is a first-pass footprint; verify pad geometry against the "
                             "package drawing before use.")
            return computed, warnings
        warnings.append("Found a package dimension table but couldn't compute a land pattern from "
                         "it (missing required symbols, or not a recognized QFN/DFN-style package).")
    else:
        warnings.append("No package dimension table or recommended land pattern table found in "
                         "the datasheet — footprint cannot be generated automatically for this part.")

    return None, warnings
