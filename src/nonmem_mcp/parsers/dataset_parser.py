"""Parser for NONMEM datasets.

Reads the data file referenced in a control stream and provides
summary statistics: subject count, observation count, dosing records,
missing values, column overview.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from nonmem_mcp.types.nonmem import DatasetSummary


def parse_dataset(
    data_path: str | Path,
    input_columns: list[str] | None = None,
) -> DatasetSummary:
    """Parse a NONMEM dataset file and return summary statistics."""
    data_path = Path(data_path)
    if not data_path.exists():
        raise FileNotFoundError(f"Dataset not found: {data_path}")

    summary = DatasetSummary(file_path=str(data_path))

    # Detect delimiter
    first_line = data_path.open().readline()
    if "," in first_line:
        delimiter = ","
    else:
        delimiter = None  # whitespace

    # Read data
    rows: list[dict[str, str]] = []
    with open(data_path) as f:
        # Check if first line is a header
        first_line = f.readline().strip()
        f.seek(0)

        has_header = not _is_numeric_line(first_line, delimiter)

        if has_header:
            if delimiter:
                reader = csv.DictReader(f, delimiter=delimiter)
            else:
                # Whitespace-delimited with header
                header_line = f.readline().strip()
                columns = header_line.split()
                for line in f:
                    line = line.strip()
                    if not line or line.startswith(";"):
                        continue
                    values = line.split()
                    if len(values) >= len(columns):
                        rows.append(dict(zip(columns, values[:len(columns)])))
                summary.columns = columns
        else:
            # No header - use input_columns if provided
            columns = input_columns or [f"COL{i+1}" for i in range(len(first_line.split()))]
            for line in f:
                line = line.strip()
                if not line or line.startswith(";"):
                    continue
                values = line.split() if not delimiter else line.split(delimiter)
                if len(values) >= len(columns):
                    rows.append(dict(zip(columns, values[:len(columns)])))
            summary.columns = columns

        if has_header and not rows:
            # csv.DictReader case
            f.seek(0)
            if delimiter:
                reader = csv.DictReader(f, delimiter=delimiter)
            else:
                reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)
            if rows:
                summary.columns = list(rows[0].keys())

    if not rows:
        return summary

    if not summary.columns:
        summary.columns = list(rows[0].keys())

    summary.n_records = len(rows)

    # Find ID column
    id_col = _find_column(summary.columns, ["ID", "SUBJ", "SUBJECT"])
    summary.id_column = id_col or "ID"

    # Count unique subjects
    if id_col:
        ids = {row.get(id_col, "") for row in rows}
        ids.discard("")
        ids.discard(".")
        summary.n_subjects = len(ids)

    # Find MDV and EVID columns
    mdv_col = _find_column(summary.columns, ["MDV"])
    evid_col = _find_column(summary.columns, ["EVID"])
    summary.mdv_column = mdv_col or "MDV"
    summary.evid_column = evid_col or "EVID"

    # Count observations (MDV=0 or EVID=0)
    obs_count = 0
    dose_count = 0
    for row in rows:
        evid = _safe_int(row.get(evid_col, "0")) if evid_col else None
        mdv = _safe_int(row.get(mdv_col, "0")) if mdv_col else None

        if evid is not None:
            if evid == 0:
                obs_count += 1
            elif evid == 1:
                dose_count += 1
        elif mdv is not None:
            if mdv == 0:
                obs_count += 1

    summary.n_observations = obs_count
    summary.n_dose_records = dose_count

    # Count missing values per column
    for col in summary.columns:
        missing = sum(
            1 for row in rows
            if row.get(col, ".") in (".", "", "NA", "na", "-99", "-999")
        )
        if missing > 0:
            summary.missing_counts[col] = missing

    return summary


def _find_column(columns: list[str], candidates: list[str]) -> str | None:
    """Find a column name matching one of the candidates (case-insensitive)."""
    upper_cols = {c.upper(): c for c in columns}
    for cand in candidates:
        if cand.upper() in upper_cols:
            return upper_cols[cand.upper()]
    return None


def _is_numeric_line(line: str, delimiter: str | None = None) -> bool:
    """Check if a line contains only numeric values."""
    if delimiter:
        tokens = line.split(delimiter)
    else:
        tokens = line.split()
    if not tokens:
        return False
    for token in tokens[:5]:  # Check first 5 tokens
        token = token.strip()
        if not token:
            continue
        try:
            float(token)
        except ValueError:
            return False
    return True


def _safe_int(s: str) -> int | None:
    """Safely convert string to int."""
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def format_dataset_summary(summary: DatasetSummary) -> str:
    """Format DatasetSummary as a human-readable string."""
    lines = []
    lines.append(f"Dataset: {summary.file_path}")
    lines.append(f"Records: {summary.n_records}")
    lines.append(f"Subjects: {summary.n_subjects}")
    lines.append(f"Observations: {summary.n_observations}")
    lines.append(f"Dose Records: {summary.n_dose_records}")
    lines.append(f"Columns ({len(summary.columns)}): {', '.join(summary.columns)}")

    if summary.missing_counts:
        lines.append("")
        lines.append("Missing Values:")
        for col, count in summary.missing_counts.items():
            pct = (count / summary.n_records * 100) if summary.n_records > 0 else 0
            lines.append(f"  {col}: {count} ({pct:.1f}%)")

    return "\n".join(lines)
