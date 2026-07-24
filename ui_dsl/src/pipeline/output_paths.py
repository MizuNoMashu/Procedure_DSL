"""
Shared helpers for the per-CSV output folder layout.

Every CSV — whether hand-created in the editor or produced by the extractor —
lives in its own folder named after the CSV filename's stem, e.g.:

    output/
      Montaggio_Cubesat_procedure/
        Montaggio_Cubesat_procedure.csv
        Cubesat_external_DSL.yml
        Cubesat_internal_DSL.txt

DSL project names are user-chosen and may not match the CSV's stem, so DSL
files are located by searching one level under output/ (find_in_any_folder)
rather than by recomputing a folder name from the DSL filename.
"""

import re
from pathlib import Path


def output_root(src_dir: Path) -> Path:
    p = src_dir / "output"
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_stem(filename: str) -> str:
    """Sanitize a filename's stem for use as a folder name."""
    stem = re.sub(r'[^\w\-]', '_', Path(filename).stem.strip())
    if not stem:
        raise ValueError("Invalid filename")
    return stem[:80]


def csv_folder(src_dir: Path, csv_filename: str, create: bool = False) -> Path:
    """The per-CSV folder for csv_filename, derived from its stem."""
    folder = output_root(src_dir) / safe_stem(csv_filename)
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def resolve_in(folder: Path, filename: str) -> Path:
    """Resolve filename inside folder, guarding against path escape."""
    if not filename or '/' in filename or '\\' in filename:
        raise ValueError("Invalid filename")
    folder = folder.resolve()
    path = (folder / filename).resolve()
    if not str(path).startswith(str(folder)):
        raise ValueError("Invalid filename")
    return path


def find_in_any_folder(src_dir: Path, filename: str) -> Path | None:
    """Locate filename inside any per-CSV folder — used for DSL files, whose
    project name may not match any CSV's stem."""
    if not filename or '/' in filename or '\\' in filename:
        return None
    matches = sorted(output_root(src_dir).glob(f'*/{filename}'))
    return matches[0] if matches else None
