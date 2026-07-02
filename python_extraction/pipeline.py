"""
Core pipeline logic, shared by the CLI (main.py) and the GUI
(gui/app.py). Kept separate from both entry points so neither has to
shell out to the other — the GUI runs this in-process, which also
means PyInstaller only has to bundle one Python runtime.
"""
from __future__ import annotations
import json
import dataclasses
from pathlib import Path

from parsers.markdown_parser import extract_from_markdown
from parsers.structured_datasheet_parser import extract_structured
from parsers.pdf_parser import extract_pin_tables_from_pdf
from parsers.reference_schematic_parser import apply_reference_schematic_grouping, regroup_after_reference_override
from classifiers.functional_classifier import classify_component
from models.pin import ComponentRecord


def json_default(obj):
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if hasattr(obj, "value"):  # Enum
        return obj.value
    raise TypeError(f"Not serializable: {obj!r}")


def run_pipeline(
    part_number: str,
    markdown_path: str | None,
    pdf_path: str | None,
    reference_schematic_path: str | None = None,
) -> ComponentRecord:
    """Runs extraction + classification, returns a populated
    ComponentRecord (component.extraction_warnings carries every
    warning collected along the way — nothing is printed here so this
    is safe to call from a GUI thread).

    If reference_schematic_path is given (a markdown-converted
    reference design schematic, or a combined document containing one
    — see reference_schematic_parser.extract_schematic_section), pins
    found on a single sheet of that schematic get grouped by that
    sheet's title instead of the datasheet-table-derived group, since
    the reference design's own organization reflects actual intended
    usage (e.g. a muxed GPIO pin actually wired to an LED). Pins not
    resolved this way keep their datasheet-based grouping."""
    warnings: list[str] = []
    pins = []

    if markdown_path:
        md_text = Path(markdown_path).read_text(encoding="utf-8")
        pins, struct_warnings = extract_structured(md_text)
        if pins:
            warnings.append("Used structured (master table + grouped tables) extraction strategy")
            warnings.extend(struct_warnings)
        else:
            pins, md_warnings = extract_from_markdown(md_text)
            if pins:
                warnings.append("Used flat single-table extraction strategy")
            warnings.extend(md_warnings)

    if not pins and pdf_path:
        warnings.append("Falling back to PDF table extraction (no usable markdown)")
        pins, pdf_warnings = extract_pin_tables_from_pdf(pdf_path)
        warnings.extend(pdf_warnings)

    if not pins:
        warnings.append("EXTRACTION FAILED: no pins recovered from any source.")

    component = classify_component(part_number, pins)

    if reference_schematic_path and pins:
        ref_text = Path(reference_schematic_path).read_text(encoding="utf-8")
        ref_warnings = apply_reference_schematic_grouping(component, ref_text)
        warnings.extend(ref_warnings)
        regroup_after_reference_override(component)

    component.extraction_warnings = warnings
    return component


def save_component_json(component: ComponentRecord, out_path: str) -> None:
    out_data = dataclasses.asdict(component)
    Path(out_path).write_text(json.dumps(out_data, indent=2, default=json_default), encoding="utf-8")


def load_component_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
