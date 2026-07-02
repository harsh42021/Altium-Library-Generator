"""
Structured datasheet parser — handles the common real-world pattern where:

1. A master "Pin Assignments" table lists Pin Number <-> Pin Name only
   (often laid out as multiple side-by-side Number/Name column pairs to
   save vertical space — e.g. pins 1-28 in columns 0-1, pins 29-56 in
   columns 2-3 of the SAME row).

2. Separate "Pin Description" tables, one per functional group
   (Power/Ground, JTAG, SGMII Interface, etc.), give Symbol + Buffer
   Type + Description — but NOT pin number. These must be cross-
   referenced back to the master table by symbol name.

3. A generic buffer-type legend table (e.g. "AI = Analog input",
   "VOD4 = open-drain output with 4mA sink") defines short codes used
   in the Buffer Type column. We parse this generically via keyword
   matching rather than hardcoding vendor-specific codes, so it works
   across vendors without a maintained lookup table.

4. Compound pin names in the master table (e.g. "GPIO10/RCVRD_CLK_OUT2/
   TCK") encode alt-function muxing directly — first token is the
   primary function, remaining tokens are alternate functions. This is
   the same information a separate pinmux table would carry.

This is distinct from markdown_parser.py's single-big-table strategy,
which remains the fallback for datasheets that list everything in one
flat table (Pin# / Name / Type / Structure / Description columns).
"""
from __future__ import annotations
import re

from models.pin import Pin, AlternateFunction, ElectricalType, DriveStructure
from parsers.fuzzy import partial_ratio
from parsers.markdown_parser import _split_markdown_table, _best_header_match


def clean_cell(text: str) -> str:
    """Strips markdown bold markers, converts <br> tags to newlines
    (preserving multi-value cells like stacked pin names or multi-line
    buffer type codes), and trims stray whitespace."""
    text = text.replace("<br>", "\n").replace("<BR>", "\n")
    text = text.replace("**", "")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def find_titled_tables(markdown_text: str) -> list[tuple[str, str]]:
    """Scans the document line by line and returns (title, table_block)
    pairs, where title is the nearest preceding heading/bold line
    (e.g. 'TABLE 3-2: ETHERNET MEDIA INTERFACE PINS'). Falls back to
    empty title if no heading precedes the table."""
    lines = markdown_text.splitlines()
    results: list[tuple[str, str]] = []
    last_heading = ""
    current_table: list[str] = []

    def flush():
        if len(current_table) >= 2:
            results.append((last_heading, "\n".join(current_table)))

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|"):
            current_table.append(line)
            continue
        else:
            if current_table:
                flush()
                current_table = []
            # Track headings: markdown headers, bold-only lines, or
            # lines that look like "TABLE X-Y: ..." even without # markup
            text_clean = clean_cell(stripped).strip("#").strip()
            if text_clean and (
                stripped.startswith("#") or re.match(r"^TABLE\s+[\dA-Z]", text_clean, re.I)
            ):
                last_heading = text_clean

    if current_table:
        flush()

    return results


def _pin_number_looks_valid(val: str) -> bool:
    val = val.strip()
    return bool(val) and bool(re.match(r"^[A-Za-z]{0,2}\d+$", val))


def parse_master_pin_table(md_block: str) -> list[tuple[str, str]]:
    """Parses a Pin Number / Pin Name master table, handling the common
    side-by-side dual-column (or N-column) layout where multiple
    Number/Name pairs appear in the same row. Returns a flat list of
    (pin_number, compound_name) tuples.

    Malformed trailing rows (e.g. an 'Exposed Pad must be connected to
    ground' footnote row that breaks the column structure) are silently
    skipped rather than raising, since pin_number validation filters
    them out naturally."""
    rows = _split_markdown_table(md_block)
    if len(rows) < 2:
        return []

    header_row = [clean_cell(c) for c in rows[0]]
    col_concepts = [_best_header_match(h) for h in header_row]

    # Find sequential (pin_number, pin_name) column pairs
    pairs: list[tuple[int, int]] = []
    i = 0
    while i < len(col_concepts) - 1:
        if col_concepts[i] == "pin_number" and col_concepts[i + 1] == "pin_name":
            pairs.append((i, i + 1))
            i += 2
        else:
            i += 1

    if not pairs:
        return []

    results: list[tuple[str, str]] = []
    for row in rows[1:]:
        for num_idx, name_idx in pairs:
            if num_idx >= len(row) or name_idx >= len(row):
                continue
            pin_number = clean_cell(row[num_idx])
            pin_name = clean_cell(row[name_idx]).replace("\n", "")
            if _pin_number_looks_valid(pin_number) and pin_name:
                results.append((pin_number, pin_name))

    return results


BUFFER_LEGEND_HEADER_HINTS = ["buffer", "type", "symbol"]


def is_buffer_legend_table(title: str, header_row: list[str]) -> bool:
    title_l = title.lower()
    if "buffer type" in title_l:
        return True
    # Fallback: a 2-column table whose first header matches 'buffer'/'symbol'/'type'
    if len(header_row) == 2:
        h0 = header_row[0].lower()
        return any(hint in h0 for hint in ("buffer", "symbol", "code"))
    return False


def parse_buffer_legend(md_block: str) -> dict[str, tuple[str, str]]:
    """Generically parses a buffer-type legend table into
    {code: (ElectricalType value, DriveStructure value)} by keyword-
    matching the legend's own description text, rather than hardcoding
    vendor-specific codes. This keeps the parser useful across vendors
    (ST uses different codes than Microchip, TI different again) since
    it reads the vendor's own definitions."""
    rows = _split_markdown_table(md_block)
    if len(rows) < 2:
        return {}

    legend: dict[str, tuple[str, str]] = {}
    for row in rows[1:]:
        if len(row) < 2:
            continue
        code = clean_cell(row[0]).strip().upper()
        desc = clean_cell(row[1]).replace("\n", " ").lower()
        if not code or not desc:
            continue

        # Electrical type inference
        has_input = "input" in desc
        has_output = "output" in desc
        if "bidirectional" in desc or "i/o" in desc:
            elec = ElectricalType.IO
        elif "ground" in desc or "power pin" in desc or desc.strip() == "power":
            elec = ElectricalType.POWER
        elif has_input and has_output:
            elec = ElectricalType.IO
        elif has_input:
            elec = ElectricalType.INPUT
        elif has_output:
            elec = ElectricalType.OUTPUT
        else:
            elec = ElectricalType.UNKNOWN

        # Drive structure inference
        if "open-drain" in desc or "open drain" in desc:
            struct = DriveStructure.OPEN_DRAIN
        elif "open-source" in desc or "open source" in desc:
            struct = DriveStructure.OPEN_SOURCE
        elif "schmitt" in desc:
            struct = DriveStructure.SCHMITT
        elif "analog" in desc:
            struct = DriveStructure.ANALOG
        elif "push-pull" in desc or "push/pull" in desc:
            struct = DriveStructure.PUSH_PULL
        else:
            struct = DriveStructure.UNKNOWN

        legend[code] = (elec.value, struct.value)

    return legend


GROUPED_TABLE_NAME_CONCEPTS = {"pin_name", "description"}  # 'Symbol' maps to pin_name via fuzzy match


def is_grouped_pin_description_table(header_row: list[str]) -> bool:
    concepts = {_best_header_match(h) for h in header_row}
    has_symbol_col = any(
        _best_header_match(h) == "pin_name" or h.strip().lower() == "symbol"
        for h in header_row
    )
    has_buffer_col = any("buffer" in h.lower() for h in header_row)
    return has_symbol_col and has_buffer_col


def parse_grouped_pin_description_table(
    title: str, md_block: str, buffer_legend: dict[str, tuple[str, str]]
) -> list[dict]:
    """Parses one function-grouped pin description table (Name/Symbol/
    Buffer Type/Description columns) into raw pin records. Does not yet
    know pin numbers — that cross-reference happens in the orchestrator.

    Handles two real-world quirks:
    - Multi-name cells (e.g. 'LED1_POL\\nLED2_POL' sharing one
      description row) split into separate pin records.
    - Continuation rows (Symbol cell empty, meaning the markdown
      converter split one logical table row across two lines) are
      merged into the previous record's buffer-type info rather than
      treated as new (blank) pins.
    """
    rows = _split_markdown_table(md_block)
    if len(rows) < 2:
        return []

    header_row = [clean_cell(c) for c in rows[0]]
    symbol_idx = None
    buffer_idx = None
    # First pass: literal 'Symbol' header takes priority — 'Name' (long
    # descriptive text) also fuzzy-matches pin_name but is not the
    # actual pin identifier we need to cross-reference against.
    for idx, h in enumerate(header_row):
        if h.strip().lower() == "symbol":
            symbol_idx = idx
            break
    if symbol_idx is None:
        for idx, h in enumerate(header_row):
            if _best_header_match(h) == "pin_name":
                symbol_idx = idx
                break
    for idx, h in enumerate(header_row):
        if "buffer" in h.lower():
            buffer_idx = idx
            break

    if symbol_idx is None:
        return []

    records: list[dict] = []
    for row in rows[1:]:
        symbol_cell = clean_cell(row[symbol_idx]) if symbol_idx < len(row) else ""
        names = [n.strip() for n in symbol_cell.split("\n") if n.strip()]

        buffer_raw = ""
        if buffer_idx is not None and buffer_idx < len(row):
            buffer_raw = clean_cell(row[buffer_idx]).replace("\n", " ")

        if not names:
            # Continuation row: merge buffer-type tokens into the last record
            if records and buffer_raw:
                records[-1]["buffer_type_raw"] = (records[-1]["buffer_type_raw"] + " " + buffer_raw).strip()
            continue

        for name in names:
            name_clean = name.strip().upper()
            if not name_clean:
                continue
            records.append({
                "symbol": name_clean,
                "buffer_type_raw": buffer_raw,
                "group_title": title,
            })

    return records


def normalize_symbol(name: str) -> str:
    """Strips bit-range suffixes like '[4:0]' and trailing digits so
    'PHYAD3' can be matched against a legend entry for 'PHYAD[4:0]',
    and 'GPIO0' against a generic 'GPIO[15:0]' entry."""
    name = re.sub(r"\[.*?\]", "", name)
    name = re.sub(r"\d+$", "", name)
    return name.strip("_").upper()


def resolve_buffer_type(buffer_raw: str, legend: dict[str, tuple[str, str]]) -> tuple[str, str, float]:
    """Takes a raw buffer-type cell (possibly multi-token like
    'VIS/VO12 VOD12' or 'SRL (PD)') and resolves it against the legend.
    Returns (electrical_type_value, drive_structure_value, confidence).
    Uses the first recognized code; pull-up/pull-down annotations like
    (PU)/(PD) are internal-resistor info, not the base electrical type,
    so they're skipped for classification purposes."""
    tokens = re.split(r"[/\s,]+", buffer_raw.upper())
    for tok in tokens:
        tok = tok.strip("()")
        if not tok or tok in ("PU", "PD"):
            continue
        if tok in legend:
            return legend[tok][0], legend[tok][1], 1.0
    return ElectricalType.UNKNOWN.value, DriveStructure.UNKNOWN.value, 0.3


def sanitize_group_title(title: str) -> str:
    """'TABLE 3-2: ETHERNET MEDIA INTERFACE PINS' -> 'ETHERNET_MEDIA_INTERFACE'"""
    t = re.sub(r"^TABLE\s+[\dA-Z.\-]+:?\s*", "", title, flags=re.I)
    t = re.sub(r"\(CONTINUED\)", "", t, flags=re.I)
    t = re.sub(r"\bPINS?\b", "", t, flags=re.I)
    t = re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_").upper()
    return t or "MISC"


def side_for_group_name(group: str) -> str:
    """Left/right only — no vertical (top/bottom) sides, so every pin
    renders at a horizontal (0°/180°) orientation."""
    g = group.upper()
    if any(k in g for k in ("SGMII", "SERDES", "ETHERNET", "PCIE", "MEDIA", "1588", "PTP")):
        return "right"
    return "left"


def extract_structured(markdown_text: str) -> tuple[list[Pin], list[str]]:
    """Top-level entry point for the structured (master table +
    cross-referenced grouped tables) extraction strategy. Returns
    (pins, warnings). Returns an empty pin list if this pattern isn't
    detected, signaling the caller to fall back to the flat single-
    table strategy in markdown_parser.py."""
    warnings: list[str] = []
    titled_tables = find_titled_tables(markdown_text)

    legend: dict[str, tuple[str, str]] = {}
    master_pairs: list[tuple[str, str]] = []
    grouped_records: list[dict] = []

    for title, block in titled_tables:
        rows = _split_markdown_table(block)
        if not rows:
            continue
        header_row = [clean_cell(c) for c in rows[0]]

        if is_buffer_legend_table(title, header_row):
            legend.update(parse_buffer_legend(block))
            continue

        master_result = parse_master_pin_table(block)
        if master_result:
            master_pairs.extend(master_result)
            continue

        if is_grouped_pin_description_table(header_row):
            grouped_records.extend(parse_grouped_pin_description_table(title, block, legend))

    if not master_pairs:
        return [], []  # signal fallback

    # dedupe master pairs (continuation tables may repeat headers)
    seen_numbers = set()
    deduped_pairs = []
    for num, name in master_pairs:
        if num not in seen_numbers:
            seen_numbers.add(num)
            deduped_pairs.append((num, name))
    master_pairs = deduped_pairs

    symbol_lookup: dict[str, dict] = {}
    normalized_lookup: dict[str, list[dict]] = {}
    for rec in grouped_records:
        symbol_lookup.setdefault(rec["symbol"], rec)
        normalized_lookup.setdefault(normalize_symbol(rec["symbol"]), []).append(rec)

    unmatched_primary: list[str] = []
    consumed_symbols: set[str] = set()
    pins: list[Pin] = []

    for pin_number, compound_name in master_pairs:
        tokens = [t.strip() for t in compound_name.split("/") if t.strip()]
        if not tokens:
            continue
        primary = tokens[0].upper()
        alt_tokens = tokens[1:]

        record = symbol_lookup.get(primary)
        if not record:
            candidates = normalized_lookup.get(normalize_symbol(primary))
            record = candidates[0] if candidates else None
        if record:
            consumed_symbols.add(record["symbol"])

        if record:
            elec_val, struct_val, conf = resolve_buffer_type(record["buffer_type_raw"], legend)
            functional_group = sanitize_group_title(record["group_title"])
        else:
            elec_val, struct_val, conf = ElectricalType.UNKNOWN.value, DriveStructure.UNKNOWN.value, 0.3
            functional_group = None
            unmatched_primary.append(primary)

        pin = Pin(
            pin_number=pin_number,
            primary_name=primary,
            electrical_type=ElectricalType(elec_val),
            drive_structure=DriveStructure(struct_val),
            functional_group=functional_group,
            side_hint=side_for_group_name(functional_group) if functional_group else None,
            is_no_connect=(primary in ("NC", "N.C.", "NO_CONNECT")),
            source_confidence=conf,
            raw_source_text=f"{pin_number} | {compound_name}",
        )

        for alt in alt_tokens:
            alt_upper = alt.strip().upper()
            if not alt_upper:
                continue
            alt_record = symbol_lookup.get(alt_upper)
            if not alt_record:
                candidates = normalized_lookup.get(normalize_symbol(alt_upper))
                alt_record = candidates[0] if candidates else None
            if alt_record:
                consumed_symbols.add(alt_record["symbol"])
            pin.alternate_functions.append(AlternateFunction(
                function_name=alt_upper,
                notes=sanitize_group_title(alt_record["group_title"]) if alt_record else None,
            ))

        pins.append(pin)

    # Grouped-table entries never referenced by the master table are
    # commonly exposed pads / paddle grounds, which datasheets often
    # describe in a footnote ("Exposed Pad must be connected to
    # ground...") rather than a numbered master-table row. Surface
    # these as synthetic pins rather than silently dropping them —
    # missing a thermal pad connection is a real bring-up risk, not a
    # cosmetic gap.
    orphan_warnings: list[str] = []
    ep_counter = 0
    for symbol, rec in symbol_lookup.items():
        if symbol in consumed_symbols:
            continue
        elec_val, struct_val, conf = resolve_buffer_type(rec["buffer_type_raw"], legend)
        ep_counter += 1
        pin_number = "EP" if ep_counter == 1 else f"EP{ep_counter}"
        pins.append(Pin(
            pin_number=pin_number,
            primary_name=symbol,
            electrical_type=ElectricalType(elec_val),
            drive_structure=DriveStructure(struct_val),
            functional_group=sanitize_group_title(rec["group_title"]),
            side_hint=side_for_group_name(sanitize_group_title(rec["group_title"])),
            source_confidence=min(conf, 0.5),  # no numbered master-table row to confirm against
            raw_source_text=f"(no master-table row) | {symbol}",
        ))
        orphan_warnings.append(
            f"'{symbol}' found in grouped description table but has no numbered row in the "
            f"master pin table (likely an exposed pad/footnote) — assigned placeholder pin "
            f"number '{pin_number}', VERIFY against the package drawing before use"
        )

    if unmatched_primary:
        warnings.append(
            f"{len(unmatched_primary)} pin(s) had no matching entry in any grouped "
            f"description table (classified generically, flagged low-confidence): "
            f"{', '.join(sorted(set(unmatched_primary))[:10])}"
            + (" ..." if len(set(unmatched_primary)) > 10 else "")
        )
    warnings.extend(orphan_warnings)
    if not legend:
        warnings.append("No buffer-type legend table found — electrical types may be less reliable")

    return pins, warnings
