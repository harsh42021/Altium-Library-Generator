"""
CLI entry point for the extraction engine.

Usage:
    python main.py --part "STM32F103C8T6" --markdown datasheet.md --pdf datasheet.pdf --out component.json
"""
from __future__ import annotations
import argparse

from pipeline import run_pipeline, save_component_json


def run(part_number: str, markdown_path: str | None, pdf_path: str | None, out_path: str) -> None:
    component = run_pipeline(part_number, markdown_path, pdf_path)
    save_component_json(component, out_path)

    print(f"Extracted {len(component.pins)} pins for {part_number}")
    print(f"Groups: {[g.name for g in component.groups]}")
    print(f"Multi-part: {component.is_multi_part}")
    if component.extraction_warnings:
        print("Warnings:")
        for w in component.extraction_warnings:
            print(f"  - {w}")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", required=True)
    parser.add_argument("--markdown", default=None)
    parser.add_argument("--pdf", default=None)
    parser.add_argument("--out", default="component.json")
    args = parser.parse_args()
    run(args.part, args.markdown, args.pdf, args.out)
