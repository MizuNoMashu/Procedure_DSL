"""
Convert validated AssemblyStep list to CSV.
Column mapping is defined here; update FIELD_MAP to change the output schema.
"""

import csv
import io
from typing import List

from pipeline.schema import AssemblyStep

CSV_COLUMNS = [
    "ID", "COMPONENT", "COMPONENT DETAIL", "ORIENTATION",
    "ACTION", "APPLIED TO", "TOOL", "TOOL DETAIL", "ASSEMBLY DETAIL",
]

# Maps CSV column name → AssemblyStep field name
FIELD_MAP = {
    "COMPONENT":        "component",
    "COMPONENT DETAIL": "component_detail",
    "ORIENTATION":      "orientation",
    "ACTION":           "action",
    "APPLIED TO":       "applied_to",
    "TOOL":             "tool",
    "TOOL DETAIL":      "tool_detail",
    "ASSEMBLY DETAIL":  "assembly_detail",
}


def _write_rows(steps: List[AssemblyStep], fieldnames: list) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output, fieldnames=fieldnames, extrasaction='ignore', lineterminator='\n'
    )
    writer.writeheader()
    for i, step in enumerate(steps, 1):
        row: dict = {"ID": i}
        for col, field in FIELD_MAP.items():
            row[col] = getattr(step, field, "")
        writer.writerow(row)
    return output.getvalue()


def steps_to_csv(steps: List[AssemblyStep]) -> str:
    """Standard 9-column CSV (no confidence). Use for final/clean output."""
    return _write_rows(steps, CSV_COLUMNS)


def steps_to_csv_with_confidence(steps: List[AssemblyStep]) -> str:
    """10-column CSV: standard 9 columns + CONFIDENCE at the end.
    Intended for the editor view so users can prioritise which steps need review.
    The confidence column is stripped automatically when the editor saves the file."""
    output = io.StringIO()
    fieldnames = CSV_COLUMNS + ["CONFIDENCE"]
    writer = csv.DictWriter(
        output, fieldnames=fieldnames, extrasaction='ignore', lineterminator='\n'
    )
    writer.writeheader()
    for i, step in enumerate(steps, 1):
        row: dict = {"ID": i, "CONFIDENCE": f"{step.confidence:.2f}"}
        for col, field in FIELD_MAP.items():
            row[col] = getattr(step, field, "")
        writer.writerow(row)
    return output.getvalue()
