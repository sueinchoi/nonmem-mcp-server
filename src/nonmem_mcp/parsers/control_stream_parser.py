"""Structural parser for NONMEM control stream (.ctl/.mod) files.

Strategy: Split into $RECORD blocks, parse THETA/OMEGA/SIGMA numerics,
treat $PK/$ERROR/$DES as opaque text (Claude interprets these directly).
"""

from __future__ import annotations

import re
from pathlib import Path

from nonmem_mcp.types.nonmem import (
    ControlStream,
    EstimationMethod,
    OmegaEstimate,
    RecordBlock,
    SigmaEstimate,
    ThetaEstimate,
)

# Known NONMEM record keywords
RECORD_KEYWORDS = {
    "PROB", "PROBLEM",
    "INPUT", "INPT",
    "DATA",
    "SUBROUTINES", "SUBROUTINE", "SUB",
    "MODEL", "MOD",
    "PK",
    "PRED",
    "DES",
    "ERROR", "ERR",
    "THETA", "THET",
    "OMEGA", "OMEG",
    "SIGMA", "SIGM",
    "ESTIMATION", "EST",
    "COVARIANCE", "COV",
    "TABLE", "TABL",
    "SIMULATION", "SIM",
    "PRIOR",
    "SIZES",
    "ABBREVIATED", "ABBR",
    "ANNEAL",
    "SCATTER",
    "MSFI",
    "CONTR",
    "MIX",
    "NONPARAMETRIC", "NONP",
    "LEVEL",
    "ETAS",
    "PHIS",
    "THETAI",
    "THETAR",
    "THETAP", "THETAPV",
    "OMEGAP", "OMEGAPD",
    "SIGMAP", "SIGMAPD",
}


def parse_control_stream(file_path: str | Path) -> ControlStream:
    """Parse a NONMEM control stream into structured components."""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    text = file_path.read_text(errors="replace")
    cs = ControlStream(file_path=str(file_path))

    # Split into record blocks
    cs.records = _split_records(text)

    # Parse specific blocks
    for rec in cs.records:
        kw = _normalize_keyword(rec.keyword)
        if kw in ("PROB", "PROBLEM"):
            cs.problem = rec.content.strip()
        elif kw in ("INPUT", "INPT"):
            cs.input_columns = _parse_input(rec.content)
        elif kw == "DATA":
            cs.data_file = _parse_data_path(rec.content)
        elif kw in ("SUBROUTINES", "SUBROUTINE", "SUB"):
            cs.subroutine = _parse_subroutine(rec.content)
        elif kw in ("THETA", "THET"):
            cs.thetas.extend(_parse_theta_block(rec.content, len(cs.thetas)))
        elif kw in ("OMEGA", "OMEG"):
            cs.omegas.extend(_parse_omega_block(rec.content, cs.omegas))
        elif kw in ("SIGMA", "SIGM"):
            cs.sigmas.extend(_parse_sigma_block(rec.content, cs.sigmas))
        elif kw in ("ESTIMATION", "EST"):
            cs.estimation_methods.append(_parse_estimation(rec.content))

    return cs


def _split_records(text: str) -> list[RecordBlock]:
    """Split control stream text into $RECORD blocks."""
    records = []
    current_keyword = None
    current_lines: list[str] = []
    current_line_num = 0

    for line_num, line in enumerate(text.splitlines(), 1):
        # Skip pure comment lines (starting with ;)
        stripped = line.strip()
        if stripped.startswith(";") and current_keyword is None:
            continue

        # Check if line starts a new record
        match = re.match(r"^\$(\w+)(.*)", stripped)
        if match:
            keyword_candidate = match.group(1).upper()
            if keyword_candidate in RECORD_KEYWORDS:
                # Save previous record
                if current_keyword is not None:
                    content = "\n".join(current_lines)
                    records.append(RecordBlock(
                        keyword=current_keyword,
                        content=content,
                        line_number=current_line_num,
                    ))
                current_keyword = keyword_candidate
                current_lines = [match.group(2)]
                current_line_num = line_num
                continue

        if current_keyword is not None:
            current_lines.append(line)

    # Save last record
    if current_keyword is not None:
        content = "\n".join(current_lines)
        records.append(RecordBlock(
            keyword=current_keyword,
            content=content,
            line_number=current_line_num,
        ))

    return records


def _normalize_keyword(kw: str) -> str:
    """Return the keyword as-is (already uppercased in _split_records)."""
    return kw.upper()


def _parse_input(content: str) -> list[str]:
    """Parse $INPUT record to extract column names."""
    columns = []
    # Remove comments and continuation markers
    text = re.sub(r";.*", "", content)
    text = re.sub(r"&", "", text)
    for token in text.split():
        token = token.strip()
        if not token:
            continue
        # Handle DROP/SKIP: e.g., "DV=DROP" or "SKIP"
        if "=" in token:
            parts = token.split("=")
            columns.append(parts[0])
        else:
            columns.append(token)
    return columns


def _parse_data_path(content: str) -> str:
    """Extract the data file path from $DATA record."""
    text = re.sub(r";.*", "", content).strip()
    # First non-option token is the file path
    tokens = text.split()
    if tokens:
        path = tokens[0].strip("'\"")
        return path
    return ""


def _parse_subroutine(content: str) -> str:
    """Extract ADVAN/TRANS from $SUBROUTINES."""
    text = re.sub(r";.*", "", content)
    parts = []
    advan_match = re.search(r"ADVAN\d+", text, re.IGNORECASE)
    trans_match = re.search(r"TRANS\d+", text, re.IGNORECASE)
    tol_match = re.search(r"TOL\s*=\s*(\d+)", text, re.IGNORECASE)
    if advan_match:
        parts.append(advan_match.group(0).upper())
    if trans_match:
        parts.append(trans_match.group(0).upper())
    if tol_match:
        parts.append(f"TOL={tol_match.group(1)}")
    return " ".join(parts)


def _parse_theta_block(content: str, offset: int) -> list[ThetaEstimate]:
    """Parse $THETA block for initial estimates and bounds."""
    thetas = []
    # Remove comments but keep labels (after ;)
    lines = content.splitlines()
    theta_num = offset

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Extract comment/label
        label = ""
        if ";" in line:
            parts = line.split(";", 1)
            line = parts[0].strip()
            label = parts[1].strip()

        if not line:
            continue

        # Find all theta specs on this line
        # Pattern: (lower, init, upper) or just init or (lower, init) or init FIX
        specs = _extract_theta_specs(line)
        for spec in specs:
            theta_num += 1
            name = label if label else f"THETA{theta_num}"
            thetas.append(ThetaEstimate(
                number=theta_num,
                name=name,
                initial=spec.get("init"),
                lower_bound=spec.get("lower"),
                upper_bound=spec.get("upper"),
                fixed=spec.get("fixed", False),
            ))

    return thetas


def _extract_theta_specs(line: str) -> list[dict]:
    """Extract theta specifications from a line."""
    specs = []
    # Remove FIXED/FIX at end
    is_fixed = bool(re.search(r"\bFIX(ED)?\b", line, re.IGNORECASE))
    line = re.sub(r"\bFIX(ED)?\b", "", line, flags=re.IGNORECASE).strip()

    # Match (lower, init, upper) patterns
    paren_pattern = re.compile(
        r"\(\s*([^,)]+)\s*,\s*([^,)]+)\s*(?:,\s*([^,)]+)\s*)?\)"
    )

    last_end = 0
    for match in paren_pattern.finditer(line):
        # Check for bare numbers before this match
        before = line[last_end:match.start()].strip()
        if before:
            for num in _extract_bare_numbers(before):
                specs.append({"init": num, "fixed": is_fixed})

        lower_str = match.group(1).strip()
        init_str = match.group(2).strip()
        upper_str = match.group(3).strip() if match.group(3) else None

        lower = _parse_bound(lower_str)
        init = _safe_float(init_str)
        upper = _parse_bound(upper_str) if upper_str else None

        specs.append({
            "init": init,
            "lower": lower,
            "upper": upper,
            "fixed": is_fixed,
        })
        last_end = match.end()

    # Handle remaining bare numbers
    remaining = line[last_end:].strip()
    if remaining:
        for num in _extract_bare_numbers(remaining):
            specs.append({"init": num, "fixed": is_fixed})

    # If nothing was found, try the whole line as a single number
    if not specs:
        val = _safe_float(line)
        if val is not None:
            specs.append({"init": val, "fixed": is_fixed})

    return specs


def _extract_bare_numbers(text: str) -> list[float]:
    """Extract standalone numbers from text."""
    nums = []
    for token in text.split():
        val = _safe_float(token)
        if val is not None:
            nums.append(val)
    return nums


def _parse_bound(s: str) -> float | None:
    """Parse a bound value, handling -INF and INF."""
    s = s.strip().upper()
    if s in ("-INF", "-1000000", "-99999"):
        return None  # No lower bound
    if s in ("INF", "1000000", "99999"):
        return None  # No upper bound
    return _safe_float(s)


def _safe_float(s: str) -> float | None:
    """Safely convert string to float."""
    try:
        return float(s.strip())
    except (ValueError, AttributeError):
        return None


def _parse_omega_block(content: str, existing: list[OmegaEstimate]) -> list[OmegaEstimate]:
    """Parse $OMEGA block."""
    omegas = []
    text = re.sub(r";.*", "", content)

    # Determine starting position
    max_row = max((o.row for o in existing), default=0)
    current_row = max_row

    # Check for BLOCK(n) syntax
    block_match = re.match(r"\s*BLOCK\s*\(\s*(\d+)\s*\)", text, re.IGNORECASE)
    is_same = bool(re.search(r"\bSAME\b", text, re.IGNORECASE))
    is_fixed = bool(re.search(r"\bFIX(ED)?\b", text, re.IGNORECASE))

    if is_same:
        # SAME repeats the previous block structure
        return omegas

    if block_match:
        block_size = int(block_match.group(1))
        # Extract values after the BLOCK(n) keyword
        remaining = text[block_match.end():]
        remaining = re.sub(r"\bFIX(ED)?\b", "", remaining, flags=re.IGNORECASE)
        values = _extract_bare_numbers(remaining)

        idx = 0
        for i in range(block_size):
            for j in range(i + 1):
                row = current_row + i + 1
                col = current_row + j + 1
                val = values[idx] if idx < len(values) else 0.0
                omegas.append(OmegaEstimate(
                    row=row, col=col,
                    initial=val, fixed=is_fixed,
                ))
                idx += 1
    else:
        # Diagonal elements
        text_clean = re.sub(r"\bFIX(ED)?\b", "", text, flags=re.IGNORECASE)
        values = _extract_bare_numbers(text_clean)
        for val in values:
            current_row += 1
            omegas.append(OmegaEstimate(
                row=current_row, col=current_row,
                initial=val, fixed=is_fixed,
            ))

    return omegas


def _parse_sigma_block(content: str, existing: list[SigmaEstimate]) -> list[SigmaEstimate]:
    """Parse $SIGMA block (same structure as OMEGA)."""
    sigmas = []
    text = re.sub(r";.*", "", content)

    max_row = max((s.row for s in existing), default=0)
    current_row = max_row

    is_fixed = bool(re.search(r"\bFIX(ED)?\b", text, re.IGNORECASE))
    text_clean = re.sub(r"\bFIX(ED)?\b", "", text, flags=re.IGNORECASE)

    block_match = re.match(r"\s*BLOCK\s*\(\s*(\d+)\s*\)", text_clean, re.IGNORECASE)
    if block_match:
        block_size = int(block_match.group(1))
        remaining = text_clean[block_match.end():]
        values = _extract_bare_numbers(remaining)
        idx = 0
        for i in range(block_size):
            for j in range(i + 1):
                row = current_row + i + 1
                col = current_row + j + 1
                val = values[idx] if idx < len(values) else 0.0
                sigmas.append(SigmaEstimate(
                    row=row, col=col, initial=val, fixed=is_fixed,
                ))
                idx += 1
    else:
        values = _extract_bare_numbers(text_clean)
        for val in values:
            current_row += 1
            sigmas.append(SigmaEstimate(
                row=current_row, col=current_row,
                initial=val, fixed=is_fixed,
            ))

    return sigmas


def _parse_estimation(content: str) -> EstimationMethod:
    """Parse $ESTIMATION options."""
    text = re.sub(r";.*", "", content)
    est = EstimationMethod(method="FOCE")

    method_match = re.search(r"METHOD\s*=\s*(\S+)", text, re.IGNORECASE)
    if method_match:
        method_val = method_match.group(1).upper()
        method_map = {
            "0": "FO", "1": "FOCE", "COND": "FOCE", "CONDITIONAL": "FOCE",
            "SAEM": "SAEM", "IMP": "IMP", "IMPMAP": "IMPMAP",
            "BAYES": "BAYES", "CHAIN": "CHAIN", "ITS": "ITS",
        }
        est.method = method_map.get(method_val, method_val)

    est.interaction = bool(re.search(r"\bINTER(ACTION)?\b", text, re.IGNORECASE))

    maxeval_match = re.search(r"MAX(?:EVAL)?\s*=\s*(\d+)", text, re.IGNORECASE)
    if maxeval_match:
        est.maxeval = int(maxeval_match.group(1))

    sig_match = re.search(r"SIG(?:DIGITS)?\s*=\s*(\d+)", text, re.IGNORECASE)
    if sig_match:
        est.sigdigits = int(sig_match.group(1))

    # Capture all key=value options
    for match in re.finditer(r"(\w+)\s*=\s*(\S+)", text):
        key = match.group(1).upper()
        val = match.group(2)
        if key not in ("METHOD",):
            est.options[key] = val

    return est


def format_control_stream(cs: ControlStream) -> str:
    """Format ControlStream as a human-readable summary."""
    lines = []
    lines.append(f"File: {cs.file_path}")
    lines.append(f"Problem: {cs.problem}")
    lines.append(f"Data: {cs.data_file}")
    lines.append(f"Subroutine: {cs.subroutine}")
    lines.append(f"Input Columns: {', '.join(cs.input_columns)}")
    lines.append("")

    lines.append(f"--- {len(cs.thetas)} THETAs ---")
    for t in cs.thetas:
        bounds = ""
        if t.lower_bound is not None or t.upper_bound is not None:
            lb = f"{t.lower_bound}" if t.lower_bound is not None else "-INF"
            ub = f"{t.upper_bound}" if t.upper_bound is not None else "INF"
            bounds = f" [{lb}, {ub}]"
        fix = " FIX" if t.fixed else ""
        lines.append(f"  THETA{t.number}: {t.initial}{bounds}{fix}  ; {t.name}")

    lines.append(f"\n--- {len(cs.omegas)} OMEGA elements ---")
    for o in cs.omegas:
        fix = " FIX" if o.fixed else ""
        lines.append(f"  OMEGA({o.row},{o.col}): {o.initial}{fix}")

    lines.append(f"\n--- {len(cs.sigmas)} SIGMA elements ---")
    for s in cs.sigmas:
        fix = " FIX" if s.fixed else ""
        lines.append(f"  SIGMA({s.row},{s.col}): {s.initial}{fix}")

    lines.append(f"\n--- {len(cs.estimation_methods)} Estimation Method(s) ---")
    for e in cs.estimation_methods:
        inter = " INTERACTION" if e.interaction else ""
        lines.append(f"  {e.method}{inter}")
        if e.maxeval:
            lines.append(f"    MAXEVAL={e.maxeval}")

    lines.append(f"\n--- {len(cs.records)} Total Record Blocks ---")
    for rec in cs.records:
        preview = rec.content[:60].replace("\n", " ").strip()
        lines.append(f"  ${rec.keyword} (line {rec.line_number}): {preview}...")

    return "\n".join(lines)
