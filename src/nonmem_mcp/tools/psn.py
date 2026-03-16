"""PsN (Perl-speaks-NONMEM) integration tools.

Wraps PsN CLI commands for VPC, Bootstrap, and result parsing.
Works with async fire-and-poll pattern for long-running operations.

Supports:
- execute_psn_vpc: Run VPC via PsN
- execute_psn_bootstrap: Run bootstrap via PsN
- parse_psn_results: Parse existing PsN output directories
- psn_sumo: Quick summary of NONMEM output (no execution needed)
"""

from __future__ import annotations

import csv
import os
import platform
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"

# Reuse job registry pattern from execute module
_psn_jobs: dict[str, "PsnJob"] = {}


@dataclass
class PsnJob:
    job_id: str
    command: str
    tool_name: str  # vpc, bootstrap, etc.
    work_dir: str
    model_path: str
    pid: int | None = None
    status: str = "pending"
    started_at: float = 0.0
    finished_at: float = 0.0
    error_message: str = ""
    output_dir: str = ""
    n_samples: int = 0
    completed_samples: int = 0


# ---------------------------------------------------------------------------
# PsN detection
# ---------------------------------------------------------------------------

def _build_common_psn_paths() -> list[str]:
    """Build platform-specific list of common PsN installation paths."""
    if IS_WINDOWS:
        return [
            os.path.expanduser("~/PsN/bin"),
            "C:\\PsN\\bin",
            "C:\\strawberry\\perl\\bin",
            "C:\\Program Files\\PsN\\bin",
        ]
    return [
        "/usr/local/bin",
        "/opt/PsN/bin",
        os.path.expanduser("~/PsN/bin"),
        "/usr/bin",
    ]


COMMON_PSN_PATHS = _build_common_psn_paths()


def detect_psn() -> dict[str, str | None]:
    """Detect PsN installation and available tools."""
    tools = {}
    for cmd in ["vpc", "bootstrap", "execute", "sumo", "scm", "sse"]:
        path = shutil.which(cmd)
        if not path:
            for base in COMMON_PSN_PATHS:
                candidate = Path(base) / cmd
                if candidate.exists():
                    path = str(candidate)
                    break
        tools[cmd] = path
    return tools


def _psn_not_found_error(tool: str) -> dict:
    return {
        "error": f"PsN '{tool}' command not found.",
        "hint": "Install PsN: https://github.com/UUPharmacometrics/PsN",
        "install_steps": [
            "1. Install Perl 5.10+ (brew install perl on macOS)",
            "2. Install CPAN modules: cpanm Math::Random::Free Mouse YAML Archive::Zip",
            "3. Download PsN from GitHub releases",
            "4. Run: sudo perl setup.pl",
        ],
        "alternative": "Use parse_psn_results to analyze existing PsN output directories",
    }


# ---------------------------------------------------------------------------
# VPC
# ---------------------------------------------------------------------------

def execute_psn_vpc(
    model_path: str,
    samples: int = 200,
    options: dict | None = None,
    work_dir: str | None = None,
) -> dict:
    """Execute PsN VPC command."""
    psn_tools = detect_psn()
    vpc_path = psn_tools.get("vpc")
    if not vpc_path:
        return _psn_not_found_error("vpc")

    model = Path(model_path)
    if not model.exists():
        return {"error": f"Model file not found: {model_path}"}

    if not work_dir:
        work_dir = str(model.parent)

    # Build command
    cmd = [vpc_path, str(model), f"-samples={samples}"]

    opts = options or {}
    if opts.get("predcorr"):
        cmd.append("-predcorr")
    if opts.get("stratify_on"):
        cmd.append(f"-stratify_on={opts['stratify_on']}")
    if opts.get("idv"):
        cmd.append(f"-idv={opts['idv']}")
    if opts.get("lloq"):
        cmd.append(f"-lloq={opts['lloq']}")
    if opts.get("seed"):
        cmd.append(f"-seed={opts['seed']}")
    if opts.get("threads"):
        cmd.append(f"-threads={opts['threads']}")
    if opts.get("directory"):
        cmd.append(f"-directory={opts['directory']}")

    # Create job
    job = PsnJob(
        job_id=str(uuid.uuid4())[:8],
        command=" ".join(cmd),
        tool_name="vpc",
        work_dir=work_dir,
        model_path=str(model),
        n_samples=samples,
    )

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        job.pid = proc.pid
        job.status = "running"
        job.started_at = time.time()
        _psn_jobs[job.job_id] = job

        return {
            "job_id": job.job_id,
            "status": "running",
            "tool": "vpc",
            "pid": proc.pid,
            "samples": samples,
            "command": job.command,
        }
    except Exception as e:
        return {"error": f"Failed to start VPC: {e}"}


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def execute_psn_bootstrap(
    model_path: str,
    samples: int = 200,
    options: dict | None = None,
    work_dir: str | None = None,
) -> dict:
    """Execute PsN bootstrap command."""
    psn_tools = detect_psn()
    bs_path = psn_tools.get("bootstrap")
    if not bs_path:
        return _psn_not_found_error("bootstrap")

    model = Path(model_path)
    if not model.exists():
        return {"error": f"Model file not found: {model_path}"}

    if not work_dir:
        work_dir = str(model.parent)

    cmd = [bs_path, str(model), f"-samples={samples}"]

    opts = options or {}
    if opts.get("stratify_on"):
        cmd.append(f"-stratify_on={opts['stratify_on']}")
    if opts.get("seed"):
        cmd.append(f"-seed={opts['seed']}")
    if opts.get("threads"):
        cmd.append(f"-threads={opts['threads']}")
    if opts.get("directory"):
        cmd.append(f"-directory={opts['directory']}")
    if opts.get("bca"):
        cmd.append("-bca")

    job = PsnJob(
        job_id=str(uuid.uuid4())[:8],
        command=" ".join(cmd),
        tool_name="bootstrap",
        work_dir=work_dir,
        model_path=str(model),
        n_samples=samples,
    )

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        job.pid = proc.pid
        job.status = "running"
        job.started_at = time.time()
        _psn_jobs[job.job_id] = job

        return {
            "job_id": job.job_id,
            "status": "running",
            "tool": "bootstrap",
            "pid": proc.pid,
            "samples": samples,
            "command": job.command,
        }
    except Exception as e:
        return {"error": f"Failed to start bootstrap: {e}"}


# ---------------------------------------------------------------------------
# Check PsN job status
# ---------------------------------------------------------------------------

def check_psn_status(job_id: str) -> dict:
    """Check status of a PsN job."""
    job = _psn_jobs.get(job_id)
    if not job:
        return {"error": f"PsN job not found: {job_id}"}

    result = {
        "job_id": job.job_id,
        "tool": job.tool_name,
        "status": job.status,
    }

    if job.status == "running" and job.pid:
        from nonmem_mcp.tools.execute import _is_process_alive
        if not _is_process_alive(job.pid):
            job.status = "completed"
            job.finished_at = time.time()

        # Check progress for bootstrap
        if job.tool_name == "bootstrap":
            raw_results = _find_file_in_subdirs(
                job.work_dir, "raw_results.csv"
            )
            if raw_results:
                try:
                    with open(raw_results, newline="") as f:
                        reader = csv.reader(f)
                        next(reader, None)  # skip header
                        job.completed_samples = sum(1 for _ in reader)
                except Exception:
                    pass
            result["completed_samples"] = job.completed_samples
            result["total_samples"] = job.n_samples
            if job.n_samples > 0:
                result["progress_pct"] = round(
                    job.completed_samples / job.n_samples * 100, 1
                )

        if job.started_at:
            result["elapsed_seconds"] = round(time.time() - job.started_at, 1)

    result["status"] = job.status
    if job.finished_at and job.started_at:
        result["total_seconds"] = round(job.finished_at - job.started_at, 1)

    return result


# ---------------------------------------------------------------------------
# Parse existing PsN results (no execution needed)
# ---------------------------------------------------------------------------

def parse_psn_results(results_dir: str) -> dict:
    """Parse results from an existing PsN output directory.

    Works with VPC, bootstrap, and other PsN tool outputs.
    No PsN or NONMEM installation needed.
    """
    rdir = Path(results_dir)
    if not rdir.exists():
        return {"error": f"Directory not found: {results_dir}"}

    result: dict = {"directory": str(rdir), "files_found": []}

    # Detect tool type from files present
    for f in rdir.rglob("*"):
        if f.is_file() and f.suffix in (".csv", ".json", ".txt", ".dta"):
            result["files_found"].append(str(f.relative_to(rdir)))

    # Parse bootstrap results
    bootstrap_csv = rdir / "bootstrap_results.csv"
    if not bootstrap_csv.exists():
        bootstrap_csv = _find_file_in_subdirs(str(rdir), "bootstrap_results.csv")
        if bootstrap_csv:
            bootstrap_csv = Path(bootstrap_csv)

    if bootstrap_csv and bootstrap_csv.exists():
        result["type"] = "bootstrap"
        result["bootstrap"] = _parse_bootstrap_results(bootstrap_csv)

    # Parse raw_results for bootstrap
    raw_csv = rdir / "raw_results.csv"
    if not raw_csv.exists():
        raw_csv_path = _find_file_in_subdirs(str(rdir), "raw_results.csv")
        if raw_csv_path:
            raw_csv = Path(raw_csv_path)

    if raw_csv and raw_csv.exists():
        result["raw_results_summary"] = _parse_raw_results(raw_csv)

    # Parse VPC results
    vpc_csv = rdir / "vpc_results.csv"
    if not vpc_csv.exists():
        vpc_path = _find_file_in_subdirs(str(rdir), "vpc_results.csv")
        if vpc_path:
            vpc_csv = Path(vpc_path)

    if vpc_csv and vpc_csv.exists():
        result["type"] = "vpc"
        result["vpc"] = _parse_vpc_results(vpc_csv)

    # Parse NPC results
    npc_csv = rdir / "npc_results.csv"
    if not npc_csv.exists():
        npc_path = _find_file_in_subdirs(str(rdir), "npc_results.csv")
        if npc_path:
            npc_csv = Path(npc_path)

    if npc_csv and npc_csv.exists():
        result["type"] = result.get("type", "npc")
        result["npc"] = _parse_vpc_results(npc_csv)  # Same format

    if "type" not in result:
        result["type"] = "unknown"
        result["hint"] = "Could not identify PsN output type. Expected bootstrap_results.csv or vpc_results.csv"

    return result


def psn_sumo(lst_path: str) -> dict:
    """Quick summary using PsN's sumo (or fallback to internal parser).

    sumo only reads existing output — no NONMEM execution needed.
    If PsN is not installed, falls back to internal lst parser.
    """
    lst = Path(lst_path)
    if not lst.exists():
        return {"error": f"File not found: {lst_path}"}

    # Try PsN sumo first
    psn_tools = detect_psn()
    sumo_path = psn_tools.get("sumo")

    if sumo_path:
        try:
            proc = subprocess.run(
                [sumo_path, str(lst)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode == 0:
                return {
                    "source": "psn_sumo",
                    "output": proc.stdout,
                }
        except Exception:
            pass

    # Fallback to internal parser
    from nonmem_mcp.parsers.lst_parser import format_lst_result, parse_lst_file

    result = parse_lst_file(lst_path)
    return {
        "source": "internal_parser",
        "output": format_lst_result(result),
    }


# ---------------------------------------------------------------------------
# Result parsing helpers
# ---------------------------------------------------------------------------

def _parse_bootstrap_results(csv_path: Path) -> dict:
    """Parse PsN bootstrap_results.csv."""
    result: dict = {"file": str(csv_path), "parameters": {}}
    try:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                param = row.get("parameter", row.get("", ""))
                if not param:
                    continue
                entry = {}
                for key in ["mean", "median", "se", "bias", "2.5th", "97.5th",
                            "percentile_2.5", "percentile_97.5"]:
                    if key in row and row[key]:
                        try:
                            entry[key] = float(row[key])
                        except ValueError:
                            entry[key] = row[key]
                if entry:
                    result["parameters"][param] = entry
    except Exception as e:
        result["error"] = str(e)
    return result


def _parse_raw_results(csv_path: Path) -> dict:
    """Parse PsN raw_results.csv for bootstrap summary."""
    result: dict = {"file": str(csv_path)}
    try:
        rows = []
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            for row in reader:
                rows.append(row)

        result["n_samples"] = len(rows)
        result["columns"] = headers

        # Count successful runs
        ofv_col = None
        for h in headers:
            if "ofv" in h.lower() or "obj" in h.lower():
                ofv_col = h
                break

        if ofv_col:
            successful = sum(
                1 for r in rows
                if r.get(ofv_col) and r[ofv_col] not in ("", "NA", ".")
            )
            result["successful_runs"] = successful
            result["success_rate"] = f"{successful/len(rows)*100:.1f}%" if rows else "0%"

    except Exception as e:
        result["error"] = str(e)
    return result


def _parse_vpc_results(csv_path: Path) -> dict:
    """Parse PsN vpc_results.csv."""
    result: dict = {"file": str(csv_path)}
    try:
        rows = []
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            for row in reader:
                rows.append(row)

        result["n_bins"] = len(rows)
        result["columns"] = headers
        result["data_preview"] = rows[:5] if rows else []

    except Exception as e:
        result["error"] = str(e)
    return result


def _find_file_in_subdirs(base_dir: str, filename: str) -> str | None:
    """Find a file in base_dir or its immediate subdirectories."""
    base = Path(base_dir)
    # Direct match
    candidate = base / filename
    if candidate.exists():
        return str(candidate)
    # One level deep
    for subdir in base.iterdir():
        if subdir.is_dir():
            candidate = subdir / filename
            if candidate.exists():
                return str(candidate)
    return None
