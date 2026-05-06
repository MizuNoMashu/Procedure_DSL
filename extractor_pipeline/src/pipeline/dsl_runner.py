"""
Run the parser_dsl pipeline from a CSV file as a subprocess.
Using a subprocess avoids import conflicts between parser_dsl's 'models.*'
package and the Flask app's own src/models/ directory.
"""

import re
import sys
import subprocess
from pathlib import Path

_PARSER_DSL_DIR = Path(__file__).parent.parent / "parser_dsl"


def _sanitize_name(name: str) -> str:
    """Allow only alphanumeric, underscores, hyphens — safe as a filename and CLI arg."""
    return re.sub(r'[^\w\-]', '_', name.strip())[:64]


def run_dsl_from_csv(csv_path: str, project_name: str, output_dir: Path) -> tuple:
    """
    Run parser_dsl/main.py as a subprocess (cwd=parser_dsl/) so its relative
    imports work unchanged, then move the generated files into output_dir.

    Returns:
        (external_dsl_path, internal_dsl_path) as Path objects.

    Raises:
        ValueError  — invalid project name
        RuntimeError — subprocess failed or expected output files missing
    """
    project_name = _sanitize_name(project_name)
    if not project_name:
        raise ValueError("Invalid project name — use alphanumeric characters")

    result = subprocess.run(
        [sys.executable, "main.py", "-csv", str(Path(csv_path).resolve()), project_name],
        cwd=str(_PARSER_DSL_DIR),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "DSL generation failed (unknown error)")

    external_src = _PARSER_DSL_DIR / f"{project_name}_external_DSL.yml"
    internal_src = _PARSER_DSL_DIR / f"{project_name}_internal_DSL.txt"

    for f in (external_src, internal_src):
        if not f.exists():
            raise RuntimeError(f"Expected output file not found: {f.name}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    external_dst = output_dir / external_src.name
    internal_dst = output_dir / internal_src.name
    external_src.replace(external_dst)
    internal_src.replace(internal_dst)

    return external_dst, internal_dst
