"""
Altium Library Generator — desktop GUI.

Wraps the extraction pipeline (pipeline.py) and review report
(review_report.py) in a single-window Tkinter app. Runs extraction on
a background thread so the UI doesn't freeze on large datasheets.

NOTE ON SCOPE: this GUI currently covers datasheet -> pin extraction
-> classification -> review report -> JSON export. It does NOT yet
generate actual Altium .SchLib/.PcbLib files — that stage (the
DelphiScript bridge) hasn't been built. The "Export JSON" button here
produces the same component.json that stage will eventually consume.
"""
from __future__ import annotations
import sys
import os
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# Make sibling modules (pipeline.py, parsers/, classifiers/, models/)
# importable whether running from source or from a PyInstaller bundle.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    ALTIUM_BRIDGE_DIR = BASE_DIR
else:
    BASE_DIR = Path(__file__).resolve().parent.parent / "python_extraction"
    ALTIUM_BRIDGE_DIR = Path(__file__).resolve().parent.parent / "altium_bridge"
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(ALTIUM_BRIDGE_DIR))

from pipeline import run_pipeline, save_component_json, json_default  # noqa: E402
from review_report import build_report  # noqa: E402
from delphiscript_generator import generate_delphiscript  # noqa: E402
import dataclasses  # noqa: E402


APP_TITLE = "Altium Library Generator"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("900x700")
        self.minsize(760, 560)

        self.markdown_path = tk.StringVar()
        self.pdf_path = tk.StringVar()
        self.reference_schematic_path = tk.StringVar()
        self.part_number = tk.StringVar()
        self.status_text = tk.StringVar(value="Ready.")
        self._component = None  # last successful ComponentRecord

        self._build_widgets()

    def _build_widgets(self):
        pad = {"padx": 8, "pady": 6}

        frm_inputs = ttk.LabelFrame(self, text="1. Inputs")
        frm_inputs.pack(fill="x", **pad)

        ttk.Label(frm_inputs, text="Part Number:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frm_inputs, textvariable=self.part_number, width=40).grid(row=0, column=1, sticky="w", **pad)

        ttk.Label(frm_inputs, text="Datasheet (Markdown):").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frm_inputs, textvariable=self.markdown_path, width=60).grid(row=1, column=1, sticky="w", **pad)
        ttk.Button(frm_inputs, text="Browse...", command=self._browse_markdown).grid(row=1, column=2, **pad)

        ttk.Label(frm_inputs, text="Datasheet (PDF, optional):").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frm_inputs, textvariable=self.pdf_path, width=60).grid(row=2, column=1, sticky="w", **pad)
        ttk.Button(frm_inputs, text="Browse...", command=self._browse_pdf).grid(row=2, column=2, **pad)

        ttk.Label(frm_inputs, text="Reference Schematic (Markdown, optional):").grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(frm_inputs, textvariable=self.reference_schematic_path, width=60).grid(row=3, column=1, sticky="w", **pad)
        ttk.Button(frm_inputs, text="Browse...", command=self._browse_reference_schematic).grid(row=3, column=2, **pad)

        ttk.Label(
            frm_inputs,
            text="Tip: a Markdown conversion of the datasheet gives far more reliable pin-table extraction\n"
                 "than the raw PDF. The PDF is used as a fallback if Markdown extraction finds nothing.\n"
                 "If a reference design schematic is provided, pins found on exactly one of its sheets are\n"
                 "grouped by that sheet's function instead of the datasheet table — this reflects how the\n"
                 "pins are actually used on a real board, not just their generic datasheet description.",
            foreground="#555",
        ).grid(row=4, column=0, columnspan=3, sticky="w", padx=8)

        frm_actions = ttk.Frame(self)
        frm_actions.pack(fill="x", **pad)
        self.btn_run = ttk.Button(frm_actions, text="2. Run Extraction", command=self._on_run)
        self.btn_run.pack(side="left", padx=8)
        self.btn_export = ttk.Button(frm_actions, text="3. Export JSON...", command=self._on_export, state="disabled")
        self.btn_export.pack(side="left", padx=8)
        self.btn_delphiscript = ttk.Button(
            frm_actions, text="4. Generate DelphiScript (.pas)...", command=self._on_generate_delphiscript, state="disabled"
        )
        self.btn_delphiscript.pack(side="left", padx=8)
        self.progress = ttk.Progressbar(frm_actions, mode="indeterminate", length=200)
        self.progress.pack(side="left", padx=16)

        frm_output = ttk.LabelFrame(self, text="Review Report")
        frm_output.pack(fill="both", expand=True, **pad)
        self.txt_output = scrolledtext.ScrolledText(frm_output, wrap="word", font=("Consolas", 9))
        self.txt_output.pack(fill="both", expand=True, padx=6, pady=6)
        self.txt_output.configure(state="disabled")

        status_bar = ttk.Label(self, textvariable=self.status_text, relief="sunken", anchor="w")
        status_bar.pack(fill="x", side="bottom")

    def _browse_markdown(self):
        path = filedialog.askopenfilename(
            title="Select datasheet Markdown file",
            filetypes=[("Markdown files", "*.md"), ("All files", "*.*")],
        )
        if path:
            self.markdown_path.set(path)
            if not self.part_number.get():
                self.part_number.set(Path(path).stem)

    def _browse_pdf(self):
        path = filedialog.askopenfilename(
            title="Select datasheet PDF file",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self.pdf_path.set(path)
            if not self.part_number.get():
                self.part_number.set(Path(path).stem)

    def _browse_reference_schematic(self):
        path = filedialog.askopenfilename(
            title="Select reference schematic Markdown file",
            filetypes=[("Markdown files", "*.md"), ("All files", "*.*")],
        )
        if path:
            self.reference_schematic_path.set(path)

    def _set_output_text(self, text: str):
        self.txt_output.configure(state="normal")
        self.txt_output.delete("1.0", tk.END)
        self.txt_output.insert(tk.END, text)
        self.txt_output.configure(state="disabled")

    def _on_run(self):
        part = self.part_number.get().strip()
        md = self.markdown_path.get().strip() or None
        pdf = self.pdf_path.get().strip() or None
        ref_schem = self.reference_schematic_path.get().strip() or None

        if not part:
            messagebox.showwarning(APP_TITLE, "Enter a part number first.")
            return
        if not md and not pdf:
            messagebox.showwarning(APP_TITLE, "Select a Markdown or PDF datasheet file first.")
            return

        self.btn_run.configure(state="disabled")
        self.btn_export.configure(state="disabled")
        self.btn_delphiscript.configure(state="disabled")
        self.progress.start(12)
        self.status_text.set("Running extraction...")
        self._set_output_text("Running extraction — this can take a few seconds on large datasheets...\n")

        thread = threading.Thread(target=self._run_extraction_thread, args=(part, md, pdf, ref_schem), daemon=True)
        thread.start()

    def _run_extraction_thread(self, part, md, pdf, ref_schem):
        try:
            component = run_pipeline(part, md, pdf, reference_schematic_path=ref_schem)
            data = dataclasses.asdict(component)
            # round-trip through json_default-compatible dict so enum
            # values match what build_report expects (string values)
            import json
            data = json.loads(json.dumps(data, default=json_default))
            report = build_report(data)
            self.after(0, self._on_run_success, component, report)
        except Exception as exc:
            tb = traceback.format_exc()
            self.after(0, self._on_run_error, str(exc), tb)

    def _on_run_success(self, component, report: str):
        self._component = component
        self.progress.stop()
        self.btn_run.configure(state="normal")
        self.btn_export.configure(state="normal")
        self.btn_delphiscript.configure(state="normal")
        self.status_text.set(f"Done — {len(component.pins)} pins extracted.")
        self._set_output_text(report)

    def _on_run_error(self, message: str, traceback_text: str):
        self.progress.stop()
        self.btn_run.configure(state="normal")
        self.status_text.set("Extraction failed.")
        self._set_output_text(f"EXTRACTION FAILED:\n\n{message}\n\n{traceback_text}")
        messagebox.showerror(APP_TITLE, f"Extraction failed:\n{message}")

    def _on_export(self):
        if not self._component:
            return
        default_name = f"{self._component.part_number}_component.json"
        path = filedialog.asksaveasfilename(
            title="Export component JSON",
            defaultextension=".json",
            initialfile=default_name,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            save_component_json(self._component, path)
            self.status_text.set(f"Exported to {path}")
            messagebox.showinfo(APP_TITLE, f"Exported:\n{path}")

    def _on_generate_delphiscript(self):
        if not self._component:
            return
        default_name = f"{self._component.part_number}_CreateComponent.pas"
        path = filedialog.asksaveasfilename(
            title="Save DelphiScript",
            defaultextension=".pas",
            initialfile=default_name,
            filetypes=[("DelphiScript files", "*.pas"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            import json
            data = json.loads(json.dumps(dataclasses.asdict(self._component), default=json_default))
            script = generate_delphiscript(data)
            Path(path).write_text(script, encoding="utf-8")
            self.status_text.set(f"DelphiScript written to {path}")
            messagebox.showinfo(
                APP_TITLE,
                f"DelphiScript written:\n{path}\n\n"
                "Next steps:\n"
                "1. In Altium: File > New > Library > Schematic Library\n"
                "   (or open an existing .SchLib)\n"
                "2. DXP > Run Script... > browse to this file > CreateComponent > Run\n"
                "3. Save the library (Ctrl+S)\n\n"
                "Check the top comment of the .pas file for verification notes\n"
                "before trusting the result.",
            )
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"DelphiScript generation failed:\n{exc}")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
