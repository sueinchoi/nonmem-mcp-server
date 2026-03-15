"""Parser for NONMEM .ext files.

The .ext file contains parameter estimates at each iteration.
Special ITERATION values:
  -1000000000: Final parameter estimates
  -1000000001: Standard errors
  -1000000002: Eigenvalues of correlation matrix
  -1000000003: Condition number
  -1000000004: Standard errors (alternate)
  -1000000005: Eigenvalues (alternate)
  -1000000006: Fixed parameter flags (1=fixed, 0=not fixed)
"""

from __future__ import annotations

import re
from pathlib import Path

from nonmem_mcp.types.nonmem import ExtResult


# Special iteration markers
FINAL_ESTIMATES = -1000000000
STANDARD_ERRORS = -1000000001
EIGENVALUES = -1000000002
CONDITION_NUM = -1000000003
SE_ALT = -1000000004
EIGEN_ALT = -1000000005
FIXED_FLAGS = -1000000006


def parse_ext_file(file_path: str | Path) -> list[ExtResult]:
    """Parse a NONMEM .ext file and return results for each estimation step."""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    text = file_path.read_text()
    tables = _split_tables(text)
    results = []

    for table_num, method, lines in tables:
        result = _parse_table(table_num, method, lines)
        results.append(result)

    return results


def _split_tables(text: str) -> list[tuple[int, str, list[str]]]:
    """Split .ext file into separate tables (one per estimation step)."""
    tables = []
    current_lines: list[str] = []
    current_table = 0
    current_method = ""

    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        match = re.match(r"TABLE NO\.\s+(\d+):\s*(.*)", line)
        if match:
            if current_lines:
                tables.append((current_table, current_method, current_lines))
            current_table = int(match.group(1))
            current_method = match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        tables.append((current_table, current_method, current_lines))

    return tables


def _parse_table(table_num: int, method: str, lines: list[str]) -> ExtResult:
    """Parse a single table from the .ext file."""
    result = ExtResult(table_number=table_num, method=method)

    if not lines:
        return result

    # First line is the header
    header = lines[0].split()
    if not header or header[0] != "ITERATION":
        return result

    col_names = header[1:]  # Skip ITERATION column

    # Classify columns
    theta_cols = [c for c in col_names if c.startswith("THETA")]
    omega_cols = [c for c in col_names if c.startswith("OMEGA")]
    sigma_cols = [c for c in col_names if c.startswith("SIGMA")]
    obj_col = "OBJ" if "OBJ" in col_names else None

    # Parse data lines
    for line in lines[1:]:
        values = line.split()
        if len(values) < 2:
            continue

        try:
            iteration = int(float(values[0]))
        except ValueError:
            continue

        val_dict = {}
        for i, col in enumerate(col_names):
            try:
                val_dict[col] = float(values[i + 1])
            except (IndexError, ValueError):
                pass

        if iteration == FINAL_ESTIMATES:
            for c in theta_cols:
                result.thetas[c] = val_dict.get(c, 0.0)
            for c in omega_cols:
                result.omegas[c] = val_dict.get(c, 0.0)
            for c in sigma_cols:
                result.sigmas[c] = val_dict.get(c, 0.0)
            if obj_col:
                result.ofv = val_dict.get(obj_col)

        elif iteration in (STANDARD_ERRORS, SE_ALT):
            for c in theta_cols:
                if c in val_dict:
                    result.theta_ses[c] = val_dict[c]
            for c in omega_cols:
                if c in val_dict:
                    result.omega_ses[c] = val_dict[c]
            for c in sigma_cols:
                if c in val_dict:
                    result.sigma_ses[c] = val_dict[c]

        elif iteration == FIXED_FLAGS:
            for c in col_names:
                if c in val_dict:
                    result.fixed_flags[c] = val_dict[c] == 1.0

        elif iteration in (EIGENVALUES, EIGEN_ALT):
            result.eigenvalues = [v for v in val_dict.values() if v != 0.0]
            if result.eigenvalues:
                max_ev = max(abs(v) for v in result.eigenvalues)
                min_ev = min(abs(v) for v in result.eigenvalues if v != 0.0)
                if min_ev > 0:
                    result.condition_number = max_ev / min_ev

        elif iteration >= 0:
            iter_data = {"iteration": iteration}
            iter_data.update(val_dict)
            result.iterations.append(iter_data)

    return result


def format_ext_result(result: ExtResult) -> str:
    """Format ExtResult as a human-readable string."""
    lines = []
    lines.append(f"=== Table {result.table_number}: {result.method} ===")
    lines.append(f"OFV: {result.ofv:.4f}" if result.ofv is not None else "OFV: N/A")
    lines.append(f"Iterations: {len(result.iterations)}")

    if result.condition_number:
        lines.append(f"Condition Number: {result.condition_number:.2f}")

    lines.append("")
    lines.append("--- THETA Estimates ---")
    header = f"{'Parameter':<15} {'Estimate':>12} {'SE':>12} {'RSE%':>8}"
    lines.append(header)
    lines.append("-" * len(header))
    for name, val in result.thetas.items():
        se = result.theta_ses.get(name)
        rse = (abs(se / val) * 100) if (se and val and val != 0) else None
        se_str = f"{se:>12.4f}" if se else f"{'N/A':>12}"
        rse_str = f"{rse:>7.1f}%" if rse else f"{'N/A':>8}"
        fixed = " (FIX)" if result.fixed_flags.get(name) else ""
        lines.append(f"{name:<15} {val:>12.4f} {se_str} {rse_str}{fixed}")

    if result.omegas:
        lines.append("")
        lines.append("--- OMEGA Estimates ---")
        for name, val in result.omegas.items():
            se = result.omega_ses.get(name)
            se_str = f"  SE={se:.4f}" if se else ""
            lines.append(f"  {name}: {val:.6f}{se_str}")

    if result.sigmas:
        lines.append("")
        lines.append("--- SIGMA Estimates ---")
        for name, val in result.sigmas.items():
            se = result.sigma_ses.get(name)
            se_str = f"  SE={se:.4f}" if se else ""
            lines.append(f"  {name}: {val:.6f}{se_str}")

    return "\n".join(lines)
