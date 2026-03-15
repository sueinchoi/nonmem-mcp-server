"""Minimal parser for NONMEM .lst files.

Only extracts high-value fields:
- Termination status
- Minimization successful (yes/no)
- Condition number
- Eta/Epsilon shrinkage
- Covariance step status
- Estimation time
- Key warnings
"""

from __future__ import annotations

import re
from pathlib import Path

from nonmem_mcp.types.nonmem import LstResult


# Patterns for termination messages
MINIMIZATION_SUCCESS_PATTERNS = [
    r"MINIMIZATION SUCCESSFUL",
    r"OPTIMIZATION WAS COMPLETED",
]

MINIMIZATION_FAIL_PATTERNS = [
    r"MINIMIZATION TERMINATED",
    r"OPTIMIZATION NOT COMPLETED",
    r"ROUNDING ERRORS",
    r"ERROR IN NCONTR",
    r"ZERO GRADIENT",
]

WARNING_PATTERNS = [
    r"PARAMETER ESTIMATE IS NEAR ITS BOUNDARY",
    r"EIGENVALUE.*IS.*CLOSE TO.*ZERO",
    r"MATRIX.*ALGORITHMICALLY.*SINGULAR",
    r"R MATRIX.*NOT POSITIVE",
    r"S MATRIX.*NOT POSITIVE",
    r"COVARIANCE MATRIX.*NOT POSITIVE",
    r"ESTIMATE OF OMEGA HAS.*EIGENVALUE",
    r"GRADIENT.*LARGE",
]


def parse_lst_file(file_path: str | Path) -> LstResult:
    """Parse a NONMEM .lst file for minimal key results."""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    text = file_path.read_text(errors="replace")
    result = LstResult()

    _parse_termination(text, result)
    _parse_covariance(text, result)
    _parse_shrinkage(text, result)
    _parse_condition_number(text, result)
    _parse_estimation_time(text, result)
    _parse_warnings(text, result)

    return result


def _parse_termination(text: str, result: LstResult) -> None:
    """Extract termination status."""
    for pattern in MINIMIZATION_SUCCESS_PATTERNS:
        match = re.search(pattern, text)
        if match:
            result.minimization_successful = True
            result.termination_status = match.group(0)
            return

    for pattern in MINIMIZATION_FAIL_PATTERNS:
        match = re.search(pattern, text)
        if match:
            result.minimization_successful = False
            result.termination_status = match.group(0)
            return

    result.termination_status = "UNKNOWN"


def _parse_covariance(text: str, result: LstResult) -> None:
    """Extract covariance step status."""
    if re.search(r"Elapsed covariance\s+time", text) or \
       re.search(r"STANDARD ERROR OF ESTIMATE", text):
        result.covariance_step_successful = True
    if re.search(r"COVARIANCE STEP ABORTED", text):
        result.covariance_step_successful = False


def _parse_shrinkage(text: str, result: LstResult) -> None:
    """Extract eta and epsilon shrinkage values."""
    # ETA shrinkage: "ETAshrink(%):  X.XXE+00  X.XXE+00 ..."
    eta_match = re.search(
        r"ETAshrink\(%\)\s*:\s*([\d\s.E+\-]+)",
        text,
    )
    if eta_match:
        result.eta_shrinkage = _parse_number_list(eta_match.group(1))

    # EPS shrinkage: "EPSshrink(%):  X.XXE+00 ..."
    eps_match = re.search(
        r"EPSshrink\(%\)\s*:\s*([\d\s.E+\-]+)",
        text,
    )
    if eps_match:
        result.eps_shrinkage = _parse_number_list(eps_match.group(1))

    # Also try alternate format: "ETASHRINKSD(%):"
    if not result.eta_shrinkage:
        eta_match = re.search(
            r"ETASHRINKSD\(%\)\s*:\s*([\d\s.E+\-]+)",
            text,
        )
        if eta_match:
            result.eta_shrinkage = _parse_number_list(eta_match.group(1))

    if not result.eps_shrinkage:
        eps_match = re.search(
            r"EPSSHRINKSD\(%\)\s*:\s*([\d\s.E+\-]+)",
            text,
        )
        if eps_match:
            result.eps_shrinkage = _parse_number_list(eps_match.group(1))


def _parse_condition_number(text: str, result: LstResult) -> None:
    """Extract condition number."""
    match = re.search(
        r"EIGENVALUES OF COR MATRIX OF ESTIMATE.*?\n([\s\S]*?)(?:\n\s*\n|\Z)",
        text,
    )
    if match:
        values = _parse_number_list(match.group(1))
        if values:
            max_ev = max(abs(v) for v in values)
            min_ev = min(abs(v) for v in values if v != 0)
            if min_ev > 0:
                result.condition_number = max_ev / min_ev

    # Direct condition number output (NM 7.5+)
    cn_match = re.search(r"CONDITION NUMBER.*?:\s*([\d.E+\-]+)", text)
    if cn_match:
        try:
            result.condition_number = float(cn_match.group(1))
        except ValueError:
            pass


def _parse_estimation_time(text: str, result: LstResult) -> None:
    """Extract estimation elapsed time."""
    match = re.search(
        r"Elapsed estimation\s+time.*?:\s*([\d.]+)\s*",
        text,
    )
    if match:
        try:
            result.estimation_time_seconds = float(match.group(1))
        except ValueError:
            pass


def _parse_warnings(text: str, result: LstResult) -> None:
    """Extract warnings from lst file."""
    for pattern in WARNING_PATTERNS:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for m in matches:
            warning = m.group(0).strip()
            if warning not in result.warnings:
                result.warnings.append(warning)

    # Significant digits
    sig_match = re.search(
        r"NO\. OF SIG\. DIGITS IN FINAL EST\..*?:\s*([\d.]+)",
        text,
    )
    if sig_match:
        try:
            result.significant_digits = float(sig_match.group(1))
        except ValueError:
            pass
    # Check for low sig digits
    if result.significant_digits is not None and result.significant_digits < 3.0:
        result.warnings.append(
            f"Low significant digits: {result.significant_digits:.1f}"
        )


def _parse_number_list(text: str) -> list[float]:
    """Parse a whitespace-separated list of numbers."""
    values = []
    for token in text.split():
        try:
            values.append(float(token))
        except ValueError:
            continue
    return values


def format_lst_result(result: LstResult) -> str:
    """Format LstResult as a human-readable string."""
    lines = []
    status_icon = "OK" if result.minimization_successful else "FAIL"
    lines.append(f"Termination: [{status_icon}] {result.termination_status}")

    cov_icon = "OK" if result.covariance_step_successful else "FAIL"
    lines.append(f"Covariance:  [{cov_icon}]")

    if result.significant_digits is not None:
        lines.append(f"Significant Digits: {result.significant_digits:.1f}")

    if result.condition_number is not None:
        lines.append(f"Condition Number: {result.condition_number:.2f}")

    if result.estimation_time_seconds is not None:
        lines.append(f"Estimation Time: {result.estimation_time_seconds:.1f}s")

    if result.eta_shrinkage:
        shrink_str = ", ".join(f"{s:.1f}%" for s in result.eta_shrinkage)
        lines.append(f"ETA Shrinkage: {shrink_str}")

    if result.eps_shrinkage:
        shrink_str = ", ".join(f"{s:.1f}%" for s in result.eps_shrinkage)
        lines.append(f"EPS Shrinkage: {shrink_str}")

    if result.warnings:
        lines.append("")
        lines.append("Warnings:")
        for w in result.warnings:
            lines.append(f"  - {w}")

    return "\n".join(lines)
