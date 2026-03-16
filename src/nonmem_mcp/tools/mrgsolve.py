"""mrgsolve integration for NONMEM-free simulation.

Provides:
- translate_to_mrgsolve: Convert NONMEM control stream to mrgsolve model code
- simulate_mrgsolve: Run simulation using mrgsolve via Rscript
- generate_vpc_data: Generate VPC data using mrgsolve + vpc R package

Requirements: R with mrgsolve and vpc packages installed.
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from nonmem_mcp.parsers.control_stream_parser import parse_control_stream
from nonmem_mcp.types.nonmem import ControlStream


def _r_path(p: str | Path) -> str:
    """Convert a file path to R-compatible format (forward slashes)."""
    return str(p).replace("\\", "/")


# ---------------------------------------------------------------------------
# R/mrgsolve detection
# ---------------------------------------------------------------------------

def detect_r_setup() -> dict:
    """Check R and required packages."""
    rscript = shutil.which("Rscript")
    if not rscript:
        return {"installed": False, "error": "Rscript not found in PATH"}

    result = {"installed": True, "rscript": rscript, "packages": {}}
    try:
        proc = subprocess.run(
            [rscript, "-e",
             'pkgs <- c("mrgsolve","vpc","dplyr","ggplot2"); '
             'cat(paste(pkgs, pkgs %in% installed.packages()[,"Package"], sep="="), sep="\\n")'],
            capture_output=True, text=True, timeout=30,
        )
        for line in proc.stdout.strip().splitlines():
            if "=" in line:
                pkg, status = line.split("=")
                result["packages"][pkg] = status == "TRUE"
    except Exception as e:
        result["error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# NONMEM → mrgsolve translator
# ---------------------------------------------------------------------------

# ADVAN to mrgsolve compartment mapping
ADVAN_MAP = {
    "ADVAN1": {"type": "closed", "cmt": ["CENT"], "n_cmt": 1},
    "ADVAN2": {"type": "closed", "cmt": ["DEPOT", "CENT"], "n_cmt": 2},
    "ADVAN3": {"type": "closed", "cmt": ["CENT", "PERIPH"], "n_cmt": 2},
    "ADVAN4": {"type": "closed", "cmt": ["DEPOT", "CENT", "PERIPH"], "n_cmt": 3},
    "ADVAN11": {"type": "closed", "cmt": ["CENT", "PERIPH1", "PERIPH2"], "n_cmt": 3},
    "ADVAN12": {"type": "closed", "cmt": ["DEPOT", "CENT", "PERIPH1", "PERIPH2"], "n_cmt": 4},
    "ADVAN5": {"type": "ode", "cmt": "general", "n_cmt": None},
    "ADVAN6": {"type": "ode", "cmt": "general", "n_cmt": None},
    "ADVAN8": {"type": "ode", "cmt": "general", "n_cmt": None},
    "ADVAN9": {"type": "ode", "cmt": "general", "n_cmt": None},
    "ADVAN13": {"type": "ode", "cmt": "general", "n_cmt": None},
}


def translate_to_mrgsolve(
    ctl_path: str,
    output_path: str | None = None,
    parameter_values: dict | None = None,
) -> dict:
    """Translate a NONMEM control stream to mrgsolve model code.

    Args:
        ctl_path: Path to NONMEM .ctl/.mod file
        output_path: Where to save the .mod file (optional)
        parameter_values: Override parameter values from .ext file (optional)

    Returns:
        dict with 'model_code' (string) and metadata
    """
    cs = parse_control_stream(ctl_path)

    # Extract ADVAN info
    advan = ""
    trans = ""
    for part in cs.subroutine.split():
        if part.startswith("ADVAN"):
            advan = part
        elif part.startswith("TRANS"):
            trans = part

    advan_info = ADVAN_MAP.get(advan, {"type": "ode", "cmt": "general", "n_cmt": None})

    # Build mrgsolve model code
    sections = []

    # [PROB]
    sections.append(f"$PROB {cs.problem}")

    # [CMT] - compartments
    cmt_section = _build_cmt_section(cs, advan_info)
    sections.append(cmt_section)

    # [PARAM] - THETAs and covariates
    param_section = _build_param_section(cs, parameter_values)
    sections.append(param_section)

    # [OMEGA] - IIV
    omega_section = _build_omega_section(cs, parameter_values)
    sections.append(omega_section)

    # [SIGMA] - residual
    sigma_section = _build_sigma_section(cs, parameter_values)
    sections.append(sigma_section)

    # [MAIN] - equivalent to $PK
    main_section = _build_main_section(cs, advan_info, trans)
    sections.append(main_section)

    # [ODE] - if ADVAN13/5/6/8/9
    if advan_info["type"] == "ode":
        ode_section = _build_ode_section(cs)
        if ode_section:
            sections.append(ode_section)

    # [TABLE] - equivalent to $ERROR
    table_section = _build_table_section(cs)
    sections.append(table_section)

    # [CAPTURE] - output variables
    sections.append("$CAPTURE IPRED DV")

    model_code = "\n\n".join(sections)

    # Save if output path given
    if output_path:
        Path(output_path).write_text(model_code)

    return {
        "model_code": model_code,
        "source": str(ctl_path),
        "advan": advan,
        "trans": trans,
        "model_type": advan_info["type"],
        "n_theta": len(cs.thetas),
        "n_omega": len([o for o in cs.omegas if o.row == o.col]),
        "n_sigma": len([s for s in cs.sigmas if s.row == s.col]),
        "output_path": output_path,
        "warnings": _check_translation_warnings(cs, advan_info),
    }


def _build_cmt_section(cs: ControlStream, advan_info: dict) -> str:
    """Build $CMT section from NONMEM model structure."""
    # Try to get compartment names from $MODEL
    model_rec = next((r for r in cs.records if r.keyword in ("MODEL", "MOD")), None)
    if model_rec:
        cmt_names = re.findall(r"COMP\s*=\s*\(?\s*(\w+)", model_rec.content, re.IGNORECASE)
        if cmt_names:
            return "$CMT " + " ".join(cmt_names)

    # Use ADVAN defaults
    if advan_info["cmt"] != "general":
        return "$CMT " + " ".join(advan_info["cmt"])

    # Fallback: count from $DES DADT equations
    des_rec = next((r for r in cs.records if r.keyword == "DES"), None)
    if des_rec:
        n_cmt = len(re.findall(r"DADT\(\d+\)", des_rec.content))
        cmt_names = [f"CMT{i+1}" for i in range(n_cmt)]
        return "$CMT " + " ".join(cmt_names)

    return "$CMT CENT"


def _build_param_section(cs: ControlStream, param_values: dict | None) -> str:
    """Build $PARAM section from THETAs."""
    lines = ["$PARAM"]
    for t in cs.thetas:
        val = t.initial
        if param_values and f"THETA{t.number}" in param_values:
            val = param_values[f"THETA{t.number}"]
        name = _sanitize_param_name(t.name, t.number)
        lines.append(f"  {name} = {val}")
    return "\n".join(lines)


def _build_omega_section(cs: ControlStream, param_values: dict | None) -> str:
    """Build $OMEGA section."""
    # Find diagonal omegas
    diag_omegas = [o for o in cs.omegas if o.row == o.col]
    if not diag_omegas:
        return "$OMEGA 0"

    # Check for BLOCK structure
    blocks = _detect_omega_blocks(cs)

    lines = ["$OMEGA"]
    processed_rows = set()

    for block_rows, block_values in blocks:
        if len(block_rows) == 1:
            row = block_rows[0]
            if row in processed_rows:
                continue
            processed_rows.add(row)
            omega = next((o for o in cs.omegas if o.row == row and o.col == row), None)
            if omega:
                val = omega.initial or 0.0
                if param_values and f"OMEGA({row},{row})" in param_values:
                    val = param_values[f"OMEGA({row},{row})"]
                fix = " @fix" if omega.fixed else ""
                lines.append(f"  {val}{fix}")
        else:
            # BLOCK
            n = len(block_rows)
            lines.append(f"  @block")
            for vals_row in block_values:
                vals_str = " ".join(f"{v}" for v in vals_row)
                lines.append(f"  {vals_str}")
            processed_rows.update(block_rows)

    return "\n".join(lines)


def _detect_omega_blocks(cs: ControlStream) -> list[tuple[list[int], list[list[float]]]]:
    """Detect BLOCK structure in OMEGAs."""
    blocks = []
    omega_records = [r for r in cs.records if r.keyword in ("OMEGA", "OMEG")]

    for rec in omega_records:
        block_match = re.match(r"\s*BLOCK\s*\(\s*(\d+)\s*\)", rec.content, re.IGNORECASE)
        is_fixed = bool(re.search(r"\bFIX(ED)?\b", rec.content, re.IGNORECASE))

        if block_match:
            block_size = int(block_match.group(1))
            # Extract values
            remaining = rec.content[block_match.end():]
            remaining = re.sub(r"\bFIX(ED)?\b", "", remaining, flags=re.IGNORECASE)
            remaining = re.sub(r";.*", "", remaining)
            values = []
            for token in remaining.split():
                try:
                    values.append(float(token))
                except ValueError:
                    continue

            # Build block matrix rows
            rows = []
            idx = 0
            current_row = max((b[0][-1] for b in blocks), default=0) if blocks else 0
            block_rows = list(range(current_row + 1, current_row + 1 + block_size))
            for i in range(block_size):
                row_vals = []
                for j in range(i + 1):
                    row_vals.append(values[idx] if idx < len(values) else 0.0)
                    idx += 1
                rows.append(row_vals)
            blocks.append((block_rows, rows))
        else:
            # Diagonal
            text = re.sub(r"\bFIX(ED)?\b", "", rec.content, flags=re.IGNORECASE)
            text = re.sub(r";.*", "", text)
            values = []
            for token in text.split():
                try:
                    values.append(float(token))
                except ValueError:
                    continue
            current_row = max((b[0][-1] for b in blocks), default=0) if blocks else 0
            for i, v in enumerate(values):
                row = current_row + i + 1
                blocks.append(([row], [[v]]))

    return blocks


def _build_sigma_section(cs: ControlStream, param_values: dict | None) -> str:
    """Build $SIGMA section."""
    diag_sigmas = [s for s in cs.sigmas if s.row == s.col]
    if not diag_sigmas:
        return "$SIGMA 1"

    lines = ["$SIGMA"]
    for s in diag_sigmas:
        val = s.initial or 0.0
        if param_values and f"SIGMA({s.row},{s.col})" in param_values:
            val = param_values[f"SIGMA({s.row},{s.col})"]
        fix = " @fix" if s.fixed else ""
        lines.append(f"  {val}{fix}")
    return "\n".join(lines)


def _build_main_section(cs: ControlStream, advan_info: dict, trans: str) -> str:
    """Build $MAIN section from $PK block."""
    pk_rec = next((r for r in cs.records if r.keyword == "PK"), None)
    if not pk_rec:
        pred_rec = next((r for r in cs.records if r.keyword == "PRED"), None)
        if pred_rec:
            pk_code = pred_rec.content
        else:
            return "$MAIN\n  // No $PK block found"
    else:
        pk_code = pk_rec.content

    # Convert NONMEM syntax to mrgsolve C++ syntax
    code = _convert_nmtran_to_cpp(pk_code)

    # Replace THETA(n) with parameter names
    for t in _get_theta_list_from_code(code):
        num = t
        # Will be handled by param name mapping
        pass

    return f"$MAIN\n{code}"


def _build_ode_section(cs: ControlStream) -> str | None:
    """Build $ODE section from $DES block."""
    des_rec = next((r for r in cs.records if r.keyword == "DES"), None)
    if not des_rec:
        return None

    code = _convert_nmtran_to_cpp(des_rec.content)

    # Convert DADT(n) to dxdt_CMTn or dxdt_NAME
    model_rec = next((r for r in cs.records if r.keyword in ("MODEL", "MOD")), None)
    cmt_names = []
    if model_rec:
        cmt_names = re.findall(r"COMP\s*=\s*\(?\s*(\w+)", model_rec.content, re.IGNORECASE)

    def replace_dadt(m):
        n = int(m.group(1))
        if n <= len(cmt_names):
            return f"dxdt_{cmt_names[n-1]}"
        return f"dxdt_CMT{n}"

    code = re.sub(r"DADT\((\d+)\)", replace_dadt, code)

    # Convert A(n) to CMT name
    def replace_a(m):
        n = int(m.group(1))
        if n <= len(cmt_names):
            return cmt_names[n-1]
        return f"CMT{n}"

    code = re.sub(r"A\((\d+)\)", replace_a, code)

    return f"$ODE\n{code}"


def _build_table_section(cs: ControlStream) -> str:
    """Build $TABLE section from $ERROR block."""
    err_rec = next((r for r in cs.records if r.keyword in ("ERROR", "ERR")), None)
    if not err_rec:
        return "$TABLE\n  double DV = IPRED + EPS(1);"

    code = _convert_nmtran_to_cpp(err_rec.content)
    return f"$TABLE\n{code}"


def _convert_nmtran_to_cpp(code: str) -> str:
    """Convert NM-TRAN abbreviated code to mrgsolve C++-like syntax."""
    lines = []
    for line in code.splitlines():
        # Preserve comments
        comment = ""
        if ";" in line:
            parts = line.split(";", 1)
            line = parts[0]
            comment = f" // {parts[1].strip()}"

        stripped = line.strip()
        if not stripped:
            continue

        # Convert THETA(n) references
        stripped = re.sub(r"THETA\((\d+)\)", r"THETA\1", stripped)

        # Convert ETA(n) references
        stripped = re.sub(r"ETA\((\d+)\)", r"ETA(\1)", stripped)

        # Convert EPS(n) references
        stripped = re.sub(r"EPS\((\d+)\)", r"EPS(\1)", stripped)

        # Convert IF statements
        stripped = re.sub(r"IF\s*\((.+?)\)\s*THEN", r"if(\1) {", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"^\s*ELSE\s*$", "} else {", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"^\s*ENDIF\s*$", "}", stripped, flags=re.IGNORECASE)

        # Convert .EQ. .NE. .GT. .LT. .GE. .LE. .AND. .OR.
        stripped = re.sub(r"\.EQ\.", "==", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\.NE\.", "!=", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\.GT\.", ">", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\.LT\.", "<", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\.GE\.", ">=", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\.LE\.", "<=", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\.AND\.", "&&", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\.OR\.", "||", stripped, flags=re.IGNORECASE)

        # Convert EXP, LOG, SQRT (already valid in C++)
        # Convert ** to pow()
        stripped = re.sub(r"(\w+)\*\*(\w+[\(\)]*)", r"pow(\1, \2)", stripped)
        stripped = re.sub(r"(\w+\([^)]*\))\*\*(\w+)", r"pow(\1, \2)", stripped)

        # Add double declaration for new variables (simple heuristic)
        assign_match = re.match(r"^\s*(\w+)\s*=\s*(.+)", stripped)
        if assign_match and not stripped.startswith(("if", "}", "else", "double", "//")):
            var_name = assign_match.group(1)
            expr = assign_match.group(2)
            # Don't re-declare compartment variables or known variables
            stripped = f"  double {var_name} = {expr};"
        elif stripped.startswith(("if", "}", "else")):
            stripped = f"  {stripped}"

        lines.append(f"{stripped}{comment}")

    return "\n".join(lines)


def _sanitize_param_name(name: str, number: int) -> str:
    """Convert theta label to a valid parameter name."""
    if not name or name == f"THETA{number}":
        return f"THETA{number}"
    # Clean up: remove special chars, take first word
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    clean = re.sub(r"_+", "_", clean).strip("_")
    if clean and clean[0].isdigit():
        clean = f"T_{clean}"
    return clean or f"THETA{number}"


def _get_theta_list_from_code(code: str) -> list[int]:
    """Extract THETA numbers referenced in code."""
    return [int(m) for m in re.findall(r"THETA(\d+)", code)]


def _check_translation_warnings(cs: ControlStream, advan_info: dict) -> list[str]:
    """Check for potential translation issues."""
    warnings = []

    if advan_info["type"] == "ode":
        warnings.append("ODE model: Verify dxdt equations match NONMEM $DES exactly")

    # Check for NM-TRAN features not easily translated
    pk_rec = next((r for r in cs.records if r.keyword == "PK"), None)
    if pk_rec:
        if "CALLFL" in pk_rec.content.upper():
            warnings.append("CALLFL detected: mrgsolve handles this differently")
        if "COMRES" in pk_rec.content.upper():
            warnings.append("COMRES detected: may need manual translation")
        if "MIX" in pk_rec.content.upper():
            warnings.append("Mixture model detected: mrgsolve uses different syntax")

    err_rec = next((r for r in cs.records if r.keyword in ("ERROR", "ERR")), None)
    if err_rec and "CMT" in err_rec.content:
        warnings.append("CMT-dependent error model: verify conditional logic in $TABLE")

    if len(cs.thetas) > 15:
        warnings.append(f"Large model ({len(cs.thetas)} THETAs): review parameter mapping carefully")

    return warnings


# ---------------------------------------------------------------------------
# Simulation via mrgsolve
# ---------------------------------------------------------------------------

def simulate_mrgsolve(
    model_code: str | None = None,
    model_file: str | None = None,
    data_path: str | None = None,
    n_subjects: int = 100,
    end_time: float = 24,
    delta: float = 0.5,
    dose_amt: float | None = None,
    dose_cmt: int = 1,
    seed: int = 12345,
    output_path: str | None = None,
) -> dict:
    """Run a simulation using mrgsolve.

    Either model_code (inline) or model_file (.mod path) must be provided.
    If data_path is given, simulates from that dataset.
    Otherwise, generates a simple dosing regimen.
    """
    r_setup = detect_r_setup()
    if not r_setup.get("installed"):
        return {"error": "R/Rscript not found in PATH"}
    if not r_setup.get("packages", {}).get("mrgsolve"):
        return {"error": "mrgsolve R package not installed. Run: install.packages('mrgsolve')"}

    # Create temp directory for R script and model
    with tempfile.TemporaryDirectory(prefix="mrgsolve_") as tmpdir:
        # Write model file
        if model_code:
            model_path = Path(tmpdir) / "model.mod"
            model_path.write_text(model_code)
        elif model_file:
            model_path = Path(model_file)
            if not model_path.exists():
                return {"error": f"Model file not found: {model_file}"}
        else:
            return {"error": "Either model_code or model_file must be provided"}

        # Output path
        if not output_path:
            output_path = str(Path(tmpdir) / "sim_output.csv")

        # Build R script
        r_script = _build_sim_r_script(
            model_path=str(model_path),
            data_path=data_path,
            n_subjects=n_subjects,
            end_time=end_time,
            delta=delta,
            dose_amt=dose_amt,
            dose_cmt=dose_cmt,
            seed=seed,
            output_path=output_path,
        )

        r_script_path = Path(tmpdir) / "run_sim.R"
        r_script_path.write_text(r_script)

        # Execute R script
        try:
            proc = subprocess.run(
                ["Rscript", str(r_script_path)],
                capture_output=True, text=True,
                timeout=120,
                cwd=tmpdir,
            )
        except subprocess.TimeoutExpired:
            return {"error": "Simulation timed out (120s limit)"}
        except Exception as e:
            return {"error": f"Failed to run Rscript: {e}"}

        if proc.returncode != 0:
            return {
                "error": "R simulation failed",
                "stderr": proc.stderr[-500:] if proc.stderr else "",
                "stdout": proc.stdout[-500:] if proc.stdout else "",
            }

        # Read results
        result = {"status": "success", "output_path": output_path}

        if Path(output_path).exists():
            try:
                with open(output_path) as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                result["n_rows"] = len(rows)
                result["columns"] = list(rows[0].keys()) if rows else []
                result["preview"] = rows[:10]
            except Exception as e:
                result["parse_error"] = str(e)

        if proc.stdout:
            result["r_output"] = proc.stdout[-500:]

        return result


def _build_sim_r_script(
    model_path: str,
    data_path: str | None,
    n_subjects: int,
    end_time: float,
    delta: float,
    dose_amt: float | None,
    dose_cmt: int,
    seed: int,
    output_path: str,
) -> str:
    """Build R script for mrgsolve simulation."""
    lines = [
        "library(mrgsolve)",
        "library(dplyr)",
        f"set.seed({seed})",
        "",
        f'mod <- mread_cache("model", "{_r_path(Path(model_path).parent)}", "{Path(model_path).name}")',
        "",
    ]

    if data_path:
        lines.extend([
            f'data <- read.csv("{_r_path(data_path)}")',
            "out <- mod %>%",
            "  data_set(data) %>%",
            "  mrgsim()",
        ])
    elif dose_amt:
        lines.extend([
            f"ev <- ev(amt = {dose_amt}, cmt = {dose_cmt})",
            "out <- mod %>%",
            f"  ev(ev) %>%",
            f"  mrgsim(end = {end_time}, delta = {delta}, nid = {n_subjects})",
        ])
    else:
        lines.extend([
            "out <- mod %>%",
            f"  mrgsim(end = {end_time}, delta = {delta}, nid = {n_subjects})",
        ])

    lines.extend([
        "",
        "result <- as.data.frame(out)",
        f'write.csv(result, "{_r_path(output_path)}", row.names = FALSE)',
        'cat("Simulation complete.\\n")',
        f'cat("Rows:", nrow(result), "\\n")',
        f'cat("Columns:", paste(names(result), collapse=", "), "\\n")',
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# VPC data generation
# ---------------------------------------------------------------------------

def generate_vpc_data(
    model_code: str | None = None,
    model_file: str | None = None,
    observed_data_path: str | None = None,
    n_sim: int = 200,
    seed: int = 12345,
    pred_corr: bool = False,
    stratify_on: str | None = None,
    output_dir: str | None = None,
) -> dict:
    """Generate VPC data using mrgsolve simulation + vpc R package.

    This replaces PsN VPC when NONMEM is not available.
    Requires: R with mrgsolve and vpc packages.
    """
    r_setup = detect_r_setup()
    if not r_setup.get("installed"):
        return {"error": "R/Rscript not found"}
    if not r_setup.get("packages", {}).get("mrgsolve"):
        return {"error": "mrgsolve not installed"}
    if not r_setup.get("packages", {}).get("vpc"):
        return {"error": "vpc R package not installed. Run: install.packages('vpc')"}

    if not observed_data_path:
        return {"error": "observed_data_path is required for VPC"}

    if not Path(observed_data_path).exists():
        return {"error": f"Observed data not found: {observed_data_path}"}

    with tempfile.TemporaryDirectory(prefix="vpc_") as tmpdir:
        if not output_dir:
            output_dir = tmpdir

        # Write model if inline
        if model_code:
            model_path = Path(tmpdir) / "model.mod"
            model_path.write_text(model_code)
        elif model_file:
            model_path = Path(model_file)
        else:
            return {"error": "Either model_code or model_file required"}

        vpc_json_path = Path(output_dir) / "vpc_data.json"
        vpc_csv_path = Path(output_dir) / "vpc_sim.csv"

        r_script = _build_vpc_r_script(
            model_path=str(model_path),
            observed_data_path=observed_data_path,
            n_sim=n_sim,
            seed=seed,
            pred_corr=pred_corr,
            stratify_on=stratify_on,
            vpc_json_path=str(vpc_json_path),
            vpc_csv_path=str(vpc_csv_path),
        )

        r_script_path = Path(tmpdir) / "run_vpc.R"
        r_script_path.write_text(r_script)

        try:
            proc = subprocess.run(
                ["Rscript", str(r_script_path)],
                capture_output=True, text=True,
                timeout=600,
                cwd=tmpdir,
            )
        except subprocess.TimeoutExpired:
            return {"error": "VPC generation timed out (10min limit)"}

        if proc.returncode != 0:
            return {
                "error": "VPC generation failed",
                "stderr": proc.stderr[-1000:] if proc.stderr else "",
            }

        result = {"status": "success", "n_simulations": n_sim}

        if vpc_json_path.exists():
            try:
                result["vpc_stats"] = json.loads(vpc_json_path.read_text())
            except Exception:
                pass

        if vpc_csv_path.exists():
            result["sim_data_path"] = str(vpc_csv_path)
            try:
                with open(vpc_csv_path) as f:
                    n_rows = sum(1 for _ in f) - 1
                result["sim_n_rows"] = n_rows
            except Exception:
                pass

        if proc.stdout:
            result["r_output"] = proc.stdout[-500:]

        return result


def _build_vpc_r_script(
    model_path: str,
    observed_data_path: str,
    n_sim: int,
    seed: int,
    pred_corr: bool,
    stratify_on: str | None,
    vpc_json_path: str,
    vpc_csv_path: str,
) -> str:
    """Build R script for VPC data generation."""
    lines = [
        "library(mrgsolve)",
        "library(vpc)",
        "library(dplyr)",
        "library(jsonlite)",
        f"set.seed({seed})",
        "",
        f'mod <- mread_cache("model", "{_r_path(Path(model_path).parent)}", "{Path(model_path).name}")',
        f'obs <- read.csv("{_r_path(observed_data_path)}")',
        "",
        "# Run simulations",
        f"sim_all <- lapply(1:{n_sim}, function(i) {{",
        "  out <- mod %>%",
        "    data_set(obs) %>%",
        "    mrgsim() %>%",
        "    as.data.frame() %>%",
        "    mutate(sim = i)",
        "  return(out)",
        "})",
        "sim_data <- bind_rows(sim_all)",
        f'write.csv(sim_data, "{_r_path(vpc_csv_path)}", row.names = FALSE)',
        "",
        "# Generate VPC statistics",
        "tryCatch({",
    ]

    vpc_call = '  vpc_result <- vpc(sim = sim_data, obs = obs, obs_cols = list(dv = "DV", idv = "TIME")'
    if pred_corr:
        vpc_call += ", pred_corr = TRUE"
    if stratify_on:
        vpc_call += f', stratify = "{stratify_on}"'
    vpc_call += ", vpcdb = TRUE)"

    lines.extend([
        vpc_call,
        "  # Extract VPC statistics",
        "  vpc_stats <- list(",
        '    obs_percentiles = vpc_result$obs %>% select(any_of(c("bin_mid", "q5", "q50", "q95"))) %>% as.data.frame(),',
        '    sim_percentiles = vpc_result$sim %>% select(any_of(c("bin_mid", "q5.low", "q5.med", "q5.up", "q50.low", "q50.med", "q50.up", "q95.low", "q95.med", "q95.up"))) %>% as.data.frame(),',
        f"    n_sim = {n_sim},",
        f"    pred_corr = {'TRUE' if pred_corr else 'FALSE'}",
        "  )",
        f'  write(toJSON(vpc_stats, auto_unbox = TRUE), "{_r_path(vpc_json_path)}")',
        '  cat("VPC statistics generated successfully.\\n")',
        "}, error = function(e) {",
        '  cat("VPC stats error:", conditionMessage(e), "\\n")',
        '  cat("Simulation data saved, but VPC stats could not be computed.\\n")',
        "})",
    ])

    return "\n".join(lines)
