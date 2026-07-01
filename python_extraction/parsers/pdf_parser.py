"""
PDF-based extraction — fallback path for pin tables (when no markdown is
supplied) and primary path for mechanical/package dimension extraction,
since markdown conversion usually drops vector drawings.

Pin table extraction here is intentionally conservative: pdfplumber's
table detection is unreliable across vendor PDF layouts, so rows below
a confidence threshold get source_confidence penalized rather than
silently trusted. The markdown path should be preferred when available.
"""
from __future__ import annotations
import re
import pdfplumber

from parsers.markdown_parser import (
    _best_header_match, _match_enum, ELECTRICAL_TYPE_HINTS, DRIVE_STRUCTURE_HINTS,
)
from models.pin import Pin, ElectricalType, DriveStructure, DiffPairRole


def extract_pin_tables_from_pdf(pdf_path: str) -> tuple[list[Pin], list[str]]:
    warnings: list[str] = []
    pins: list[Pin] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                header_row = [c or "" for c in table[0]]
                col_map = {}
                for idx, header in enumerate(header_row):
                    concept = _best_header_match(header)
                    if concept:
                        col_map[idx] = concept

                if "pin_number" not in col_map.values() or "pin_name" not in col_map.values():
                    continue  # not a pin table

                for row in table[1:]:
                    row = [c or "" for c in row]
                    record = {}
                    for idx, cell in enumerate(row):
                        concept = col_map.get(idx)
                        if concept:
                            record[concept] = cell.strip()

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

                    # PDF-extracted tables get a confidence penalty vs markdown,
                    # since coordinate-based extraction misaligns cells more often
                    base_conf = min(type_conf, struct_conf) if record.get("structure") else type_conf
                    penalized_conf = base_conf * 0.85

                    pins.append(Pin(
                        pin_number=pin_number,
                        primary_name=pin_name,
                        electrical_type=elec_type,
                        drive_structure=drive_struct,
                        diff_pair_role=diff_role,
                        source_confidence=penalized_conf,
                        raw_source_text=f"p{page_num}: " + " | ".join(row),
                    ))

    if not pins:
        warnings.append(
            "No pin table detected via PDF extraction. Markdown conversion "
            "is strongly recommended for this datasheet."
        )
    return pins, warnings


def extract_mechanical_dimensions(pdf_path: str, package_hint: str | None = None) -> dict:
    """
    Placeholder for mechanical/package dimension extraction.

    Real implementation plan: search pages near text like 'Package
    Information', 'Mechanical Data', or the package name (e.g. 'LQFP-48')
    for a dimension table (pitch, body X/Y, lead width, thermal pad),
    since most modern datasheets tabulate these even when the drawing
    itself is a vector graphic markdown conversion can't parse.

    Returns a dict of raw dimension strings for now; unit normalization
    and IPC-7351 land pattern calculation happens in the footprint
    generator stage (not yet built).
    """
    dimensions = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if re.search(r"mechanical|package (data|information|dimensions)", text, re.I):
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        row_text = " ".join(c or "" for c in row).lower()
                        for dim_key in ["pitch", "body width", "body length", "lead width",
                                        "thermal pad", "stand-off", "overall height"]:
                            if dim_key in row_text:
                                dimensions[dim_key] = row
    return dimensions
