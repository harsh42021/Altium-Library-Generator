"""
Markdown-based pin table extraction.

Assumes the user has converted the datasheet to markdown (e.g. via
pymupdf4llm or `marker`), which renders tables as standard
pipe-delimited markdown tables. This is far more reliable than
coordinate-based PDF table extraction.

Strategy: rather than assuming one fixed column schema (every vendor
names columns differently), we fuzzy-match column headers to known
concepts, then normalize into Pin objects.
"""
from __future__ import annotations
import re
from parsers.fuzzy import partial_ratio

from models.pin import Pin, AlternateFunction, ElectricalType, DriveStructure, DiffPairRole

# Column header -> concept mapping. Each concept lists likely header
# phrases; we fuzzy-match against these rather than requiring exact text.
HEADER_HINTS = {
    "pin_number": ["pin no", "pin number", "pin/ball", "ball no", "no."],
    "pin_name": ["pin name", "signal name", "name", "symbol", "designation"],
    "type": ["type", "i/o", "io type", "signal type", "direction"],
    "structure": ["structure", "i/o structure", "pin structure", "drive"],
    "description": ["description", "function", "pin description", "alternate function"],
}

ELECTRICAL_TYPE_HINTS = {
    ElectricalType.INPUT: ["input", "in", "i"],
    ElectricalType.OUTPUT: ["output", "out", "o"],
    ElectricalType.IO: ["i/o", "io", "bidirectional", "bidir"],
    ElectricalType.POWER: ["power", "supply", "vdd", "vss", "gnd", "ground"],
    ElectricalType.OPEN_COLLECTOR: ["open collector", "open-collector", "oc"],
    ElectricalType.PASSIVE: ["passive", "analog", "nc", "no connect"],
}

DRIVE_STRUCTURE_HINTS = {
    DriveStructure.PUSH_PULL: ["push-pull", "push pull", "pp"],
    DriveStructure.OPEN_DRAIN: ["open-drain", "open drain", "od"],
    DriveStructure.OPEN_SOURCE: ["open-source", "open source"],
    DriveStructure.ANALOG: ["analog"],
    DriveStructure.TRISTATE: ["tri-state", "tristate", "3-state"],
    DriveStructure.SCHMITT: ["schmitt"],
}


def _best_header_match(header: str, min_score: int = 70) -> str | None:
    header_clean = header.strip().lower()
    best_concept, best_score = None, 0
    for concept, hints in HEADER_HINTS.items():
        for hint in hints:
            score = partial_ratio(header_clean, hint)
            if score > best_score:
                best_concept, best_score = concept, score
    return best_concept if best_score >= min_score else None


def _match_enum(text: str, hint_map: dict, default) -> tuple:
    """Returns (matched_enum, confidence 0-1)."""
    text_clean = text.strip().lower()
    if not text_clean or text_clean in ("-", "—", "–", "n/a", "na"):
        return default, 1.0
    best_val, best_score = default, 0
    for enum_val, hints in hint_map.items():
        for hint in hints:
            score = partial_ratio(text_clean, hint)
            if score > best_score:
                best_val, best_score = enum_val, score
    confidence = 1.0 if best_score >= 85 else (0.6 if best_score >= 60 else 0.3)
    return best_val, confidence


def _split_markdown_table(md_block: str) -> list[list[str]]:
    """Turns a markdown table block into rows of cell strings.
    Skips the header-separator line (---|---|---)."""
    rows = []
    for line in md_block.strip().splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        if re.match(r"^\|?[\s:|-]+\|?$", line):
            continue  # separator row
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)
    return rows


def find_markdown_tables(markdown_text: str) -> list[str]:
    """Extracts all table blocks (contiguous groups of pipe-delimited lines)."""
    tables = []
    current: list[str] = []
    for line in markdown_text.splitlines():
        if line.strip().startswith("|"):
            current.append(line)
        else:
            if len(current) >= 2:
                tables.append("\n".join(current))
            current = []
    if len(current) >= 2:
        tables.append("\n".join(current))
    return tables


def parse_pin_table(md_table_block: str) -> list[Pin]:
    """Parses one markdown table block into Pin objects.
    Returns [] if the table doesn't look like a pin description table
    (i.e. we couldn't confidently map pin_number + pin_name columns)."""
    rows = _split_markdown_table(md_table_block)
    if len(rows) < 2:
        return []

    header_row = rows[0]
    data_rows = rows[1:]

    col_map: dict[int, str] = {}
    for idx, header in enumerate(header_row):
        concept = _best_header_match(header)
        if concept:
            col_map[idx] = concept

    if "pin_number" not in col_map.values() or "pin_name" not in col_map.values():
        return []  # not a pin table we recognize

    pins: list[Pin] = []
    for row in data_rows:
        record = {}
        for idx, cell in enumerate(row):
            concept = col_map.get(idx)
            if concept:
                record[concept] = cell

        pin_number = record.get("pin_number", "").strip()
        pin_name = record.get("pin_name", "").strip()
        if not pin_number or not pin_name:
            continue

        elec_type, type_conf = _match_enum(
            record.get("type", ""), ELECTRICAL_TYPE_HINTS, ElectricalType.UNKNOWN
        )
        drive_struct, struct_conf = _match_enum(
            record.get("structure", ""), DRIVE_STRUCTURE_HINTS, DriveStructure.UNKNOWN
        )

        diff_role = DiffPairRole.NONE
        name_upper = pin_name.upper()
        if re.search(r"(^|[_-])P($|[_-])", name_upper) or name_upper.endswith("+"):
            diff_role = DiffPairRole.POSITIVE
        elif re.search(r"(^|[_-])N($|[_-])", name_upper) or name_upper.endswith("-"):
            diff_role = DiffPairRole.NEGATIVE

        overall_confidence = min(type_conf, struct_conf) if record.get("structure") else type_conf

        pin = Pin(
            pin_number=pin_number,
            primary_name=pin_name,
            electrical_type=elec_type,
            drive_structure=drive_struct,
            diff_pair_role=diff_role,
            is_no_connect=("no connect" in pin_name.lower() or pin_name.upper() in ("NC", "N.C.")),
            source_confidence=overall_confidence,
            raw_source_text=" | ".join(row),
        )

        # Many datasheets embed alt-functions inline in the description
        # column (e.g. "GPIO / SPI1_SCK") rather than in a separate
        # pinmux table. Capture these as candidate alternate functions;
        # a dedicated pinmux table (if present) still takes precedence
        # and adds richer entries via parse_pinmux_table.
        description = record.get("description", "")
        if description:
            for token in re.split(r"[/,]", description):
                token = token.strip()
                if not token or token.upper() == pin_name.upper():
                    continue
                if token.upper() in ("GPIO", "-", "N/A", "RESERVED"):
                    continue
                if re.match(r"^[A-Z][A-Z0-9_]{1,}$", token.upper()):
                    pin.alternate_functions.append(
                        AlternateFunction(function_name=token, notes="from description column")
                    )

        pins.append(pin)

    return pins


def parse_pinmux_table(md_table_block: str, pins_by_number: dict[str, Pin],
                        pins_by_name: dict[str, Pin] | None = None) -> list[str]:
    """Parses a separate pinmux/alt-function table and attaches
    AlternateFunction entries to the matching Pin objects. Matches by
    pin number first, falling back to pin name, since vendors key these
    tables inconsistently (e.g. TI often uses ball/pin number, ST often
    uses the GPIO name like 'PA5' as the row key).
    Returns a list of warnings (e.g. pin references not found in the
    main pin table — usually signals an OCR mismatch)."""
    pins_by_name = pins_by_name or {}
    rows = _split_markdown_table(md_table_block)
    if len(rows) < 2:
        return []

    header_row = rows[0]
    data_rows = rows[1:]

    pin_col = None
    af_cols: list[int] = []
    for idx, header in enumerate(header_row):
        h = header.strip().lower()
        if _best_header_match(header) == "pin_number":
            pin_col = idx
        elif any(k in h for k in ["af", "alt", "function", "mux"]):
            af_cols.append(idx)

    if pin_col is None or not af_cols:
        return []

    warnings = []
    for row in data_rows:
        if pin_col >= len(row):
            continue
        pin_key = row[pin_col].strip()
        target_pin = pins_by_number.get(pin_key) or pins_by_name.get(pin_key.upper())
        if not target_pin:
            warnings.append(f"Pinmux table references pin '{pin_key}' not found in pin table")
            continue
        for col in af_cols:
            if col >= len(row):
                continue
            val = row[col].strip()
            if val and val not in ("-", "—", "N/A"):
                existing_names = {af.function_name.upper() for af in target_pin.alternate_functions}
                if val.upper() not in existing_names:
                    target_pin.alternate_functions.append(
                        AlternateFunction(function_name=val, mux_code=header_row[col].strip())
                    )
    return warnings


def extract_from_markdown(markdown_text: str) -> tuple[list[Pin], list[str]]:
    """Top-level entry point: finds all tables in the markdown, identifies
    which are pin tables vs pinmux tables, and merges them.
    Returns (pins, warnings)."""
    warnings: list[str] = []
    table_blocks = find_markdown_tables(markdown_text)

    pins: list[Pin] = []
    pinmux_blocks: list[str] = []

    for block in table_blocks:
        candidate_pins = parse_pin_table(block)
        if candidate_pins:
            pins.extend(candidate_pins)
        else:
            pinmux_blocks.append(block)  # try as pinmux later

    if not pins:
        warnings.append("No pin description table found — check markdown conversion quality")
        return pins, warnings

    pins_by_number = {p.pin_number: p for p in pins}
    pins_by_name = {p.primary_name.upper(): p for p in pins}
    for block in pinmux_blocks:
        warnings.extend(parse_pinmux_table(block, pins_by_number, pins_by_name))

    low_confidence = [p for p in pins if p.source_confidence < 0.6]
    if low_confidence:
        warnings.append(
            f"{len(low_confidence)} pin(s) have low-confidence type/structure classification "
            f"— flagged for manual review"
        )

    return pins, warnings
