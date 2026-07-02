"""
Reference schematic parser — extracts per-sheet functional grouping
from a reference design schematic PDF (converted to markdown), and
uses it to override datasheet-table-based grouping where available.

Rationale: a reference design's own schematic reflects how the
designer actually organized and intended pins to be used (e.g. a GPIO
pin wired to an LED on the "Ethernet Ports" sheet has a real primary
function of LED1, not generic GPIO/Miscellaneous — information the
datasheet's own pin tables can't capture since GPIO muxing is
board-specific). Priority order, per explicit design decision: use
reference-schematic grouping for any pin it resolves; fall back to
the datasheet-table grouping (already computed) for every other pin.

WORKS GENERICALLY across EDA tools (not just Altium), as long as the
source PDF has extractable text (vector text, not a scanned image) —
the approach is just "does this pin's name appear as text on this
sheet", it doesn't depend on Altium-specific PDF export conventions.

LIMITATION: sheet-level granularity only. This tells you which
functional SECTION of the reference design a pin belongs to, not
exact schematic symbol pin-grouping within that section. Good enough
for the "which functional group" question this tool needs to answer;
not a full schematic-diff tool.
"""
from __future__ import annotations
import re

from models.pin import Pin, ComponentRecord
from parsers.structured_datasheet_parser import side_for_group_name


def extract_schematic_section(markdown_text: str, filename_hint: str | None = None) -> str:
    """If given a COMBINED document (datasheet + reference schematic
    concatenated with '--- START OF FILE ... ---' / '--- END OF FILE
    ... ---' markers, as produced by some PDF-to-markdown pipelines),
    isolates just the reference schematic portion so its page headers
    don't collide with the datasheet's own section headers during
    sheet-splitting. If no such markers are found, assumes the entire
    input IS the reference schematic (i.e. it was uploaded as its own
    separate file) and returns it unchanged."""
    start_pattern = r"---\s*START OF FILE:\s*(.+?Schematic.*?)\s*---"
    end_pattern = r"---\s*END OF FILE:\s*(.+?Schematic.*?)\s*---"

    start_match = re.search(start_pattern, markdown_text, re.IGNORECASE)
    if not start_match:
        return markdown_text  # no combined-file markers — treat whole input as the schematic

    end_match = re.search(end_pattern, markdown_text[start_match.end():], re.IGNORECASE)
    if not end_match:
        return markdown_text[start_match.end():]  # no end marker — take everything after start

    return markdown_text[start_match.end():start_match.end() + end_match.start()]


def _clean_sheet_title(raw_header: str, chunk_text: str) -> str:
    """Prefers cleaning up a filename-style page header like
    '2-Power_UNG10102_B' into 'Power' — this is far more reliably
    formatted than the schematic's own 'Sheet Title' text block, whose
    position in PDF-to-markdown OCR output varies unpredictably
    (sometimes before 'Designed with', sometimes after, sometimes
    buried after unrelated title-block text) and isn't safe to
    pattern-match directly. Falls back to searching for an explicit
    'Sheet Title' label only if the header isn't in that filename
    format (e.g. schematics from other EDA tools/export conventions)."""
    m2 = re.match(r"^\d+[-_](.+?)_[A-Za-z0-9]+_[A-Za-z0-9]$", raw_header.strip())
    if m2:
        return m2.group(1).replace("+", " + ").strip()

    m = re.search(r"Sheet\s*Title\s*(?:<br>)?\s*([A-Za-z0-9+ _/-]{2,40}?)(?:<br>|Designed with|Size\s)", chunk_text)
    if m and m.group(1).strip():
        return m.group(1).strip()

    return raw_header.strip()[:40]


_INLINE_PAGE_MARKER = re.compile(r"\b(\d+-[A-Za-z][A-Za-z0-9+]*_[A-Za-z0-9]+_[A-Za-z0-9])\b")


def _secondary_split(title: str, chunk: str) -> list[tuple[str, str]]:
    """Catches page boundaries the source PDF-to-markdown conversion
    missed (no H1 inserted between pages, so two sheets' content ends
    up merged into one chunk) by looking for the same filename-style
    page marker appearing INLINE rather than as its own header —
    it still reliably appears at the start of the sheet's own content
    even when the page-break formatting was lost."""
    matches = list(_INLINE_PAGE_MARKER.finditer(chunk))
    if not matches:
        return [(title, chunk)]

    pieces: list[tuple[str, str]] = []
    last_end = 0
    current_title = title
    for m in matches:
        candidate_title = _clean_sheet_title(m.group(1), chunk[m.start():m.start() + 300])
        if candidate_title == current_title:
            continue  # same sheet referencing itself (e.g. its own footer) — not a real boundary
        piece_text = chunk[last_end:m.start()]
        if piece_text.strip():
            pieces.append((current_title, piece_text))
        current_title = candidate_title
        last_end = m.start()
    pieces.append((current_title, chunk[last_end:]))
    return pieces


def split_into_sheets(schematic_text: str) -> list[tuple[str, str]]:
    """Splits a reference schematic's markdown into (sheet_title, sheet_text)
    chunks, using top-level markdown headers as page boundaries (the
    common result of PDF-to-markdown conversion, where each PDF page
    becomes its own H1), then a secondary pass to catch any page
    boundary the conversion missed (see _secondary_split)."""
    lines = schematic_text.splitlines()
    sheets: list[tuple[str, str]] = []
    current_header = None
    current_lines: list[str] = []

    def flush():
        if current_header is not None:
            chunk = "\n".join(current_lines)
            title = _clean_sheet_title(current_header, chunk)
            if re.search(r"\btoc\b|table of contents", title, re.IGNORECASE):
                return  # skip entirely — don't secondary-split a TOC page, it
                        # lists every other sheet's filename and would fragment
            sheets.extend(_secondary_split(title, chunk))

    for line in lines:
        stripped = line.strip()
        if re.match(r"^#\s+\S", stripped) and not stripped.startswith("##"):
            flush()
            current_header = stripped.lstrip("#").strip()
            current_lines = []
        else:
            current_lines.append(line)
    flush()

    # Drop obviously non-content sheets (table of contents, cover pages)
    sheets = [
        (title, text) for title, text in sheets
        if not re.search(r"\btoc\b|table of contents", title, re.IGNORECASE)
    ]
    return sheets


_WORD_BOUNDARY_CACHE: dict[str, re.Pattern] = {}


def _name_appears_in(name: str, text: str) -> bool:
    """Whole-token match (not substring) so e.g. 'GPIO1' doesn't
    false-match inside 'GPIO14'. Case-insensitive."""
    if not name or len(name) < 2:
        return False
    pattern = _WORD_BOUNDARY_CACHE.get(name)
    if pattern is None:
        pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", re.IGNORECASE)
        _WORD_BOUNDARY_CACHE[name] = pattern
    return bool(pattern.search(text))


def apply_reference_schematic_grouping(
    component: ComponentRecord, reference_schematic_markdown: str
) -> list[str]:
    """Overrides each pin's functional_group with the reference
    schematic's sheet title, for any pin found on exactly one sheet.
    Pins found on zero sheets, or on multiple sheets (ambiguous —
    common for pins that legitimately appear in more than one section,
    e.g. a net referenced in a cross-sheet connector), keep their
    existing datasheet-derived grouping. Returns a list of info/warning
    messages summarizing what was overridden.

    NOTE: this mutates pin.functional_group directly but does NOT
    rebuild component.groups — call classify_component's grouping step
    again (or equivalent re-grouping) after this if you need
    component.groups to reflect the new assignments. See
    regroup_after_reference_override below for that step.
    """
    schematic_section = extract_schematic_section(reference_schematic_markdown)
    sheets = split_into_sheets(schematic_section)

    if not sheets:
        return ["Reference schematic provided but no sheets could be identified — "
                "keeping datasheet-based grouping for all pins."]

    messages = []
    overridden = 0
    ambiguous = 0
    not_found = 0

    for pin in component.pins:
        candidates = pin.all_names()
        matching_sheets = set()
        for name in candidates:
            for title, text in sheets:
                if _name_appears_in(name, text):
                    matching_sheets.add(title)

        if len(matching_sheets) == 1:
            new_group = next(iter(matching_sheets)).upper().replace(" ", "_").replace("+", "_")
            new_group = re.sub(r"_+", "_", new_group).strip("_")
            if new_group != pin.functional_group:
                overridden += 1
            pin.functional_group = new_group
            pin.side_hint = side_for_group_name(new_group)
        elif len(matching_sheets) > 1:
            ambiguous += 1
        else:
            not_found += 1

    messages.append(
        f"Reference schematic grouping: {overridden} pin(s) regrouped by sheet, "
        f"{ambiguous} pin(s) ambiguous (found on multiple sheets, kept datasheet grouping), "
        f"{not_found} pin(s) not found in reference schematic (kept datasheet grouping)"
    )
    return messages


def regroup_after_reference_override(component: ComponentRecord) -> None:
    """Rebuilds component.groups from the current pin.functional_group/
    side_hint values (after apply_reference_schematic_grouping has run),
    including re-running multi-part assignment. Mutates component in
    place. Import is deferred to avoid a circular import between this
    module and functional_classifier."""
    from classifiers.functional_classifier import build_groups, assign_multi_part

    groups = build_groups(component.pins)
    groups, is_multi = assign_multi_part(groups, len(component.pins))
    component.groups = groups
    component.is_multi_part = is_multi
