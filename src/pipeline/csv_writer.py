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


def steps_to_csv(steps: List[AssemblyStep]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=CSV_COLUMNS,
        extrasaction='ignore',
        lineterminator='\n',
    )
    writer.writeheader()
    for i, step in enumerate(steps, 1):
        row: dict = {"ID": i}
        for col, field in FIELD_MAP.items():
            row[col] = getattr(step, field, "")
        writer.writerow(row)
    return output.getvalue()
