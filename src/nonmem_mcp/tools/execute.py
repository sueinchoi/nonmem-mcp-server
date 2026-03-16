"""NONMEM execution tools with async fire-and-poll pattern.

Supports:
- submit_run: Start a NONMEM run, return job ID
- check_run_status: Poll .ext file for iteration progress
- get_run_results: Return parsed results when complete
- cancel_run: Kill a running NONMEM process

All tools work without NONMEM installed (returns helpful error).
When NONMEM is available, auto-detects nmfe path from common locations.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from nonmem_mcp.parsers.ext_parser import format_ext_result, parse_ext_file
from nonmem_mcp.parsers.lst_parser import format_lst_result, parse_lst_file

# In-memory job registry (persists within server process lifetime)
_jobs: dict[str, "NmJob"] = {}


@dataclass
class NmJob:
    job_id: str
    run_name: str
    work_dir: str
    ctl_path: str
    nmfe_path: str
    pid: int | None = None
    status: str = "pending"  # pending, running, completed, failed, cancelled
    started_at: float = 0.0
    finished_at: float = 0.0
    error_message: str = ""
    current_iteration: int = 0
    current_ofv: float | None = None


# ---------------------------------------------------------------------------
# NONMEM path detection
# ---------------------------------------------------------------------------

COMMON_NMFE_PATHS = [
    "/opt/nm760/run/nmfe76",
    "/opt/NONMEM/nm760/run/nmfe76",
    "/opt/NONMEM/nm76/run/nmfe76",
    "/opt/NONMEM/nm75/run/nmfe75",
    "/opt/NONMEM/nm74/run/nmfe74",
    "/opt/NONMEM/nm75gf/run/nmfe75",
    "/opt/nm76/run/nmfe76",
    "/opt/nm75/run/nmfe75",
    "/opt/nm74/run/nmfe74",
    "/usr/local/NONMEM/nm76/run/nmfe76",
    "/usr/local/NONMEM/nm75/run/nmfe75",
    "/usr/local/NONMEM/nm74/run/nmfe74",
    os.path.expanduser("~/NONMEM/nm76/run/nmfe76"),
    os.path.expanduser("~/NONMEM/nm75/run/nmfe75"),
    os.path.expanduser("~/NONMEM/nm74/run/nmfe74"),
]


def detect_nmfe() -> str | None:
    """Auto-detect nmfe executable path."""
    # Check environment variable first
    env_path = os.environ.get("NONMEM_NMFE_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    env_install = os.environ.get("NONMEM_INSTALL_PATH")
    if env_install:
        for version in ["76", "75", "74", "73"]:
            candidate = Path(env_install) / f"run/nmfe{version}"
            if candidate.exists():
                return str(candidate)

    # Check PATH
    for version in ["76", "75", "74", "73"]:
        path = shutil.which(f"nmfe{version}")
        if path:
            return path

    # Check common install locations
    for path in COMMON_NMFE_PATHS:
        if Path(path).exists():
            return path

    return None


# ---------------------------------------------------------------------------
# Job management
# ---------------------------------------------------------------------------

def submit_run(
    ctl_path: str,
    work_dir: str | None = None,
    nmfe_path: str | None = None,
    run_name: str | None = None,
) -> dict:
    """Submit a NONMEM run. Returns job info dict."""
    ctl = Path(ctl_path)
    if not ctl.exists():
        return {"error": f"Control stream not found: {ctl_path}"}

    # Resolve nmfe
    nmfe = nmfe_path or detect_nmfe()
    if not nmfe:
        return {
            "error": "NONMEM not found. Set NONMEM_NMFE_PATH or NONMEM_INSTALL_PATH environment variable.",
            "hint": "Common install paths checked: " + ", ".join(COMMON_NMFE_PATHS[:3]),
            "searched_env_vars": ["NONMEM_NMFE_PATH", "NONMEM_INSTALL_PATH"],
        }

    # Setup work directory
    if not work_dir:
        work_dir = str(ctl.parent)
    work_path = Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)

    # Run name
    if not run_name:
        run_name = ctl.stem

    lst_path = work_path / f"{run_name}.lst"

    # Create job
    job = NmJob(
        job_id=str(uuid.uuid4())[:8],
        run_name=run_name,
        work_dir=str(work_path),
        ctl_path=str(ctl),
        nmfe_path=nmfe,
    )

    # Launch nmfe as subprocess
    cmd = [nmfe, str(ctl), str(lst_path)]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(work_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        job.pid = proc.pid
        job.status = "running"
        job.started_at = time.time()
        _jobs[job.job_id] = job

        return {
            "job_id": job.job_id,
            "status": "running",
            "pid": proc.pid,
            "run_name": run_name,
            "work_dir": str(work_path),
            "command": " ".join(cmd),
        }
    except FileNotFoundError:
        return {"error": f"nmfe executable not found at: {nmfe}"}
    except PermissionError:
        return {"error": f"Permission denied for nmfe at: {nmfe}. Try: chmod +x {nmfe}"}
    except Exception as e:
        return {"error": f"Failed to start NONMEM: {type(e).__name__}: {e}"}


def check_run_status(job_id: str) -> dict:
    """Check the status of a running NONMEM job."""
    job = _jobs.get(job_id)
    if not job:
        return {"error": f"Job not found: {job_id}", "known_jobs": list(_jobs.keys())}

    result = {
        "job_id": job.job_id,
        "run_name": job.run_name,
        "status": job.status,
    }

    if job.status == "running":
        # Check if process is still alive
        if job.pid:
            try:
                os.kill(job.pid, 0)  # Signal 0 = check existence
            except ProcessLookupError:
                # Process finished
                job.status = "completed"
                job.finished_at = time.time()
            except PermissionError:
                pass  # Process exists but we can't signal it

        # Check .ext file for progress
        ext_path = Path(job.work_dir) / f"{job.run_name}.ext"
        if ext_path.exists():
            try:
                ext_results = parse_ext_file(ext_path)
                if ext_results:
                    last = ext_results[-1]
                    if last.iterations:
                        latest = last.iterations[-1]
                        job.current_iteration = int(latest.get("iteration", 0))
                        job.current_ofv = latest.get("OBJ")
                    if last.ofv is not None:
                        # Final estimates exist → run completed
                        job.status = "completed"
                        job.finished_at = time.time()
            except Exception:
                pass

        # Check .lst for failure
        lst_path = Path(job.work_dir) / f"{job.run_name}.lst"
        if lst_path.exists() and job.status == "completed":
            try:
                lst = parse_lst_file(lst_path)
                if not lst.minimization_successful:
                    job.status = "completed"  # Still completed, just with failure
                    job.error_message = lst.termination_status
            except Exception:
                pass

        result["current_iteration"] = job.current_iteration
        if job.current_ofv is not None:
            result["current_ofv"] = job.current_ofv
        if job.started_at:
            result["elapsed_seconds"] = round(time.time() - job.started_at, 1)

    result["status"] = job.status
    if job.error_message:
        result["message"] = job.error_message
    if job.finished_at and job.started_at:
        result["total_seconds"] = round(job.finished_at - job.started_at, 1)

    return result


def get_run_results(job_id: str) -> dict:
    """Get full results of a completed NONMEM job."""
    job = _jobs.get(job_id)
    if not job:
        return {"error": f"Job not found: {job_id}"}

    # Force status check
    if job.status == "running":
        check_run_status(job_id)

    result = {
        "job_id": job.job_id,
        "run_name": job.run_name,
        "status": job.status,
        "work_dir": job.work_dir,
    }

    # Parse results
    ext_path = Path(job.work_dir) / f"{job.run_name}.ext"
    lst_path = Path(job.work_dir) / f"{job.run_name}.lst"

    if ext_path.exists():
        try:
            ext_results = parse_ext_file(ext_path)
            if ext_results:
                result["ext_summary"] = format_ext_result(ext_results[-1])
                result["ofv"] = ext_results[-1].ofv
                result["ext_data"] = asdict(ext_results[-1])
        except Exception as e:
            result["ext_error"] = str(e)

    if lst_path.exists():
        try:
            lst = parse_lst_file(lst_path)
            result["lst_summary"] = format_lst_result(lst)
            result["minimization_successful"] = lst.minimization_successful
            result["lst_data"] = asdict(lst)
        except Exception as e:
            result["lst_error"] = str(e)

    return result


def cancel_run(job_id: str) -> dict:
    """Cancel a running NONMEM job."""
    job = _jobs.get(job_id)
    if not job:
        return {"error": f"Job not found: {job_id}"}

    if job.status != "running":
        return {"message": f"Job is not running (status: {job.status})"}

    if job.pid:
        try:
            os.kill(job.pid, signal.SIGTERM)
            time.sleep(1)
            try:
                os.kill(job.pid, 0)
                os.kill(job.pid, signal.SIGKILL)  # Force kill if still alive
            except ProcessLookupError:
                pass
            job.status = "cancelled"
            job.finished_at = time.time()
            return {"message": f"Job {job_id} cancelled", "pid": job.pid}
        except ProcessLookupError:
            job.status = "completed"
            return {"message": f"Process already finished"}
        except Exception as e:
            return {"error": f"Failed to cancel: {e}"}

    return {"error": "No PID associated with job"}


def list_jobs() -> list[dict]:
    """List all known jobs."""
    return [
        {
            "job_id": j.job_id,
            "run_name": j.run_name,
            "status": j.status,
            "work_dir": j.work_dir,
        }
        for j in _jobs.values()
    ]
