"""Parser for NONMEM table output files (SDTAB, PATAB, CATAB, COTAB, etc.).

Provides basic summary statistics for key columns like CWRES, PRED, IPRED, ETAs.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from nonmem_mcp.types.nonmem import TableFileSummary


def parse_table_file(file_path: str | Path) -> TableFileSummary:
    """Parse a NONMEM table output file."""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Table file not found: {file_path}")

    summary = TableFileSummary(file_path=str(file_path))

    # Read file, skipping NONMEM header lines (start with "TABLE NO.")
    lines = file_path.read_text().splitlines()
    data_lines = []
    header = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("TABLE NO."):
            continue
        if header is None:
            # First non-TABLE line is the header
            header = stripped.split()
            continue
        data_lines.append(stripped)

    if not header:
        return summary

    summary.columns = header

    # Parse data into columns
    col_data: dict[str, list[float]] = {col: [] for col in header}

    for line in data_lines:
        values = line.split()
        if len(values) < len(header):
            continue
        for i, col in enumerate(header):
            try:
                val = float(values[i])
                if not (math.isnan(val) or math.isinf(val)):
                    col_data[col].append(val)
            except (ValueError, IndexError):
                pass

    summary.n_rows = len(data_lines)

    # Compute statistics for key columns
    stat_columns = _identify_stat_columns(header)
    for col in stat_columns:
        values = col_data.get(col, [])
        if values:
            summary.statistics[col] = _compute_stats(values)

    return summary


def _identify_stat_columns(columns: list[str]) -> list[str]:
    """Identify columns worth computing statistics for."""
    # Always compute stats for these patterns
    patterns = [
        r"^CWRES$", r"^WRES$", r"^RES$", r"^IRES$", r"^IWRES$",
        r"^PRED$", r"^IPRED$", r"^DV$",
        r"^ETA\d+$", r"^ET\d+$",
        r"^CL$", r"^V\d?$", r"^KA$", r"^Q\d?$",
        r"^NPDE$", r"^EWRES$",
    ]
    result = []
    for col in columns:
        for pattern in patterns:
            if re.match(pattern, col, re.IGNORECASE):
                result.append(col)
                break
    return result


def _compute_stats(values: list[float]) -> dict[str, float]:
    """Compute basic statistics for a list of values."""
    n = len(values)
    if n == 0:
        return {}

    sorted_vals = sorted(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n if n > 1 else 0
    sd = variance ** 0.5

    return {
        "n": n,
        "mean": round(mean, 4),
        "sd": round(sd, 4),
        "median": round(_percentile(sorted_vals, 50), 4),
        "min": round(sorted_vals[0], 4),
        "max": round(sorted_vals[-1], 4),
        "p5": round(_percentile(sorted_vals, 5), 4),
        "p95": round(_percentile(sorted_vals, 95), 4),
    }


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Compute percentile from sorted values."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    k = (n - 1) * pct / 100.0
    f = int(k)
    c = f + 1
    if c >= n:
        return sorted_vals[-1]
    return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])


def format_table_summary(summary: TableFileSummary) -> str:
    """Format TableFileSummary as a human-readable string."""
    lines = []
    lines.append(f"Table File: {summary.file_path}")
    lines.append(f"Rows: {summary.n_rows}")
    lines.append(f"Columns: {', '.join(summary.columns)}")

    if summary.statistics:
        lines.append("")
        header = f"{'Column':<10} {'N':>6} {'Mean':>10} {'SD':>10} {'Median':>10} {'Min':>10} {'Max':>10}"
        lines.append(header)
        lines.append("-" * len(header))
        for col, stats in summary.statistics.items():
            lines.append(
                f"{col:<10} {stats.get('n', 0):>6.0f} "
                f"{stats.get('mean', 0):>10.4f} {stats.get('sd', 0):>10.4f} "
                f"{stats.get('median', 0):>10.4f} {stats.get('min', 0):>10.4f} "
                f"{stats.get('max', 0):>10.4f}"
            )

    return "\n".join(lines)
