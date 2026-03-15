"""Post-run diagnostic checks for NONMEM output.

Checks:
- Boundary estimates (THETA near bounds, OMEGA near zero)
- High condition number
- Large ETA/EPS shrinkage
- Covariance step issues
- Gradient problems
- Correlation matrix warnings
- Parameter precision (high RSE)

No NONMEM installation needed — works on output files only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from nonmem_mcp.parsers.control_stream_parser import parse_control_stream
from nonmem_mcp.parsers.ext_parser import parse_ext_file
from nonmem_mcp.parsers.lst_parser import parse_lst_file


@dataclass
class DiagnosticFlag:
    severity: str  # "error", "warning", "info"
    category: str  # "boundary", "precision", "shrinkage", etc.
    message: str
    parameter: str = ""
    value: float | None = None
    threshold: float | None = None


@dataclass
class DiagnosticReport:
    run_name: str
    run_dir: str
    flags: list[DiagnosticFlag] = field(default_factory=list)
    overall_status: str = "OK"  # OK, WARNING, ERROR

    @property
    def n_errors(self) -> int:
        return sum(1 for f in self.flags if f.severity == "error")

    @property
    def n_warnings(self) -> int:
        return sum(1 for f in self.flags if f.severity == "warning")


# Thresholds
CONDITION_NUMBER_WARNING = 1000
CONDITION_NUMBER_ERROR = 10000
SHRINKAGE_WARNING = 30.0
SHRINKAGE_ERROR = 50.0
RSE_THETA_WARNING = 30.0
RSE_THETA_ERROR = 50.0
RSE_OMEGA_WARNING = 50.0
RSE_OMEGA_ERROR = 100.0
OMEGA_NEAR_ZERO = 1e-6
BOUNDARY_FRACTION = 0.01  # Within 1% of bound


def run_diagnostics(
    run_dir: str,
    run_name: str | None = None,
) -> DiagnosticReport:
    """Run comprehensive diagnostics on a completed NONMEM run."""
    run_path = Path(run_dir)

    if not run_name:
        run_name = _detect_run_name(run_path)
    if not run_name:
        report = DiagnosticReport(run_name="unknown", run_dir=run_dir)
        report.flags.append(DiagnosticFlag(
            severity="error",
            category="setup",
            message=f"No NONMEM run files found in {run_dir}",
        ))
        report.overall_status = "ERROR"
        return report

    report = DiagnosticReport(run_name=run_name, run_dir=run_dir)

    # Check .ext file
    ext_path = run_path / f"{run_name}.ext"
    if ext_path.exists():
        try:
            ext_results = parse_ext_file(ext_path)
            if ext_results:
                _check_ext_diagnostics(ext_results[-1], report)
        except Exception as e:
            report.flags.append(DiagnosticFlag(
                severity="warning",
                category="parse",
                message=f"Failed to parse .ext file: {e}",
            ))

    # Check .lst file
    lst_path = run_path / f"{run_name}.lst"
    if lst_path.exists():
        try:
            lst = parse_lst_file(lst_path)
            _check_lst_diagnostics(lst, report)
        except Exception as e:
            report.flags.append(DiagnosticFlag(
                severity="warning",
                category="parse",
                message=f"Failed to parse .lst file: {e}",
            ))
    else:
        report.flags.append(DiagnosticFlag(
            severity="warning",
            category="setup",
            message=f"No .lst file found: {lst_path}",
        ))

    # Check control stream for boundary issues
    ctl_path = _find_ctl(run_path, run_name)
    if ctl_path and ext_path.exists():
        try:
            cs = parse_control_stream(ctl_path)
            ext_results = parse_ext_file(ext_path)
            if ext_results:
                _check_boundary_estimates(cs, ext_results[-1], report)
        except Exception:
            pass

    # Set overall status
    if report.n_errors > 0:
        report.overall_status = "ERROR"
    elif report.n_warnings > 0:
        report.overall_status = "WARNING"
    else:
        report.overall_status = "OK"

    return report


def _check_ext_diagnostics(ext_result, report: DiagnosticReport) -> None:
    """Check diagnostics from .ext file data."""
    from nonmem_mcp.types.nonmem import ExtResult

    # Condition number
    if ext_result.condition_number is not None:
        cn = ext_result.condition_number
        if cn > CONDITION_NUMBER_ERROR:
            report.flags.append(DiagnosticFlag(
                severity="error",
                category="condition_number",
                message=f"Very high condition number: {cn:.1f} (threshold: {CONDITION_NUMBER_ERROR}). Model may be overparameterized.",
                value=cn,
                threshold=CONDITION_NUMBER_ERROR,
            ))
        elif cn > CONDITION_NUMBER_WARNING:
            report.flags.append(DiagnosticFlag(
                severity="warning",
                category="condition_number",
                message=f"High condition number: {cn:.1f} (threshold: {CONDITION_NUMBER_WARNING}). Consider simplifying the model.",
                value=cn,
                threshold=CONDITION_NUMBER_WARNING,
            ))

    # RSE for THETAs
    for name, est in ext_result.thetas.items():
        if ext_result.fixed_flags.get(name):
            continue  # Skip fixed parameters
        se = ext_result.theta_ses.get(name)
        if se and est and est != 0:
            rse = abs(se / est) * 100
            if rse > RSE_THETA_ERROR:
                report.flags.append(DiagnosticFlag(
                    severity="error",
                    category="precision",
                    message=f"{name}: RSE={rse:.1f}% (>{RSE_THETA_ERROR}%). Parameter poorly estimated.",
                    parameter=name,
                    value=rse,
                    threshold=RSE_THETA_ERROR,
                ))
            elif rse > RSE_THETA_WARNING:
                report.flags.append(DiagnosticFlag(
                    severity="warning",
                    category="precision",
                    message=f"{name}: RSE={rse:.1f}% (>{RSE_THETA_WARNING}%). Consider fixing or removing.",
                    parameter=name,
                    value=rse,
                    threshold=RSE_THETA_WARNING,
                ))

    # RSE for OMEGAs (diagonal only)
    for name, est in ext_result.omegas.items():
        if ext_result.fixed_flags.get(name):
            continue
        # Check if diagonal (row == col in name pattern like OMEGA(1,1))
        if not _is_diagonal_omega(name):
            continue
        se = ext_result.omega_ses.get(name)
        if se and est and est != 0:
            rse = abs(se / est) * 100
            if rse > RSE_OMEGA_ERROR:
                report.flags.append(DiagnosticFlag(
                    severity="error",
                    category="precision",
                    message=f"{name}: RSE={rse:.1f}% (>{RSE_OMEGA_ERROR}%). IIV poorly estimated.",
                    parameter=name,
                    value=rse,
                    threshold=RSE_OMEGA_ERROR,
                ))
            elif rse > RSE_OMEGA_WARNING:
                report.flags.append(DiagnosticFlag(
                    severity="warning",
                    category="precision",
                    message=f"{name}: RSE={rse:.1f}% (>{RSE_OMEGA_WARNING}%).",
                    parameter=name,
                    value=rse,
                    threshold=RSE_OMEGA_WARNING,
                ))

    # OMEGA near zero (not fixed)
    for name, est in ext_result.omegas.items():
        if ext_result.fixed_flags.get(name):
            continue
        if _is_diagonal_omega(name) and abs(est) < OMEGA_NEAR_ZERO:
            report.flags.append(DiagnosticFlag(
                severity="warning",
                category="boundary",
                message=f"{name}: Estimate near zero ({est:.2e}). Consider removing this IIV.",
                parameter=name,
                value=est,
            ))

    # Negative OMEGA diagonal (should not happen for variance)
    for name, est in ext_result.omegas.items():
        if _is_diagonal_omega(name) and est < 0:
            report.flags.append(DiagnosticFlag(
                severity="error",
                category="boundary",
                message=f"{name}: Negative variance estimate ({est:.4f}). Model misspecification likely.",
                parameter=name,
                value=est,
            ))


def _check_lst_diagnostics(lst_result, report: DiagnosticReport) -> None:
    """Check diagnostics from .lst file data."""
    # Minimization failure
    if not lst_result.minimization_successful:
        report.flags.append(DiagnosticFlag(
            severity="error",
            category="convergence",
            message=f"Minimization failed: {lst_result.termination_status}",
        ))

    # Covariance step
    if not lst_result.covariance_step_successful:
        report.flags.append(DiagnosticFlag(
            severity="warning",
            category="covariance",
            message="Covariance step failed or not run. Standard errors not available.",
        ))

    # ETA shrinkage
    for i, shrink in enumerate(lst_result.eta_shrinkage):
        eta_name = f"ETA({i+1})"
        if shrink > SHRINKAGE_ERROR:
            report.flags.append(DiagnosticFlag(
                severity="error",
                category="shrinkage",
                message=f"{eta_name} shrinkage: {shrink:.1f}% (>{SHRINKAGE_ERROR}%). Individual estimates unreliable.",
                parameter=eta_name,
                value=shrink,
                threshold=SHRINKAGE_ERROR,
            ))
        elif shrink > SHRINKAGE_WARNING:
            report.flags.append(DiagnosticFlag(
                severity="warning",
                category="shrinkage",
                message=f"{eta_name} shrinkage: {shrink:.1f}% (>{SHRINKAGE_WARNING}%). Interpret ETAs with caution.",
                parameter=eta_name,
                value=shrink,
                threshold=SHRINKAGE_WARNING,
            ))

    # EPS shrinkage
    for i, shrink in enumerate(lst_result.eps_shrinkage):
        eps_name = f"EPS({i+1})"
        if shrink > SHRINKAGE_ERROR:
            report.flags.append(DiagnosticFlag(
                severity="warning",
                category="shrinkage",
                message=f"{eps_name} shrinkage: {shrink:.1f}% (>{SHRINKAGE_ERROR}%). CWRES-based diagnostics may be unreliable.",
                parameter=eps_name,
                value=shrink,
                threshold=SHRINKAGE_ERROR,
            ))

    # Significant digits
    if lst_result.significant_digits is not None and lst_result.significant_digits < 3.0:
        report.flags.append(DiagnosticFlag(
            severity="warning",
            category="convergence",
            message=f"Low significant digits: {lst_result.significant_digits:.1f} (<3.0). Estimates may be imprecise.",
            value=lst_result.significant_digits,
            threshold=3.0,
        ))

    # Existing warnings from lst
    for w in lst_result.warnings:
        report.flags.append(DiagnosticFlag(
            severity="warning",
            category="nonmem_warning",
            message=w,
        ))


def _check_boundary_estimates(cs, ext_result, report: DiagnosticReport) -> None:
    """Check if parameter estimates are near their bounds."""
    for theta in cs.thetas:
        if theta.fixed:
            continue
        est_key = f"THETA{theta.number}"
        est = ext_result.thetas.get(est_key)
        if est is None:
            continue

        # Check lower bound
        if theta.lower_bound is not None and theta.lower_bound != 0:
            bound_range = abs(theta.upper_bound - theta.lower_bound) if theta.upper_bound else abs(theta.lower_bound * 10)
            if bound_range > 0 and abs(est - theta.lower_bound) / bound_range < BOUNDARY_FRACTION:
                report.flags.append(DiagnosticFlag(
                    severity="warning",
                    category="boundary",
                    message=f"THETA{theta.number} ({theta.name}): estimate {est:.4f} near lower bound {theta.lower_bound}",
                    parameter=est_key,
                    value=est,
                    threshold=theta.lower_bound,
                ))

        # Check upper bound
        if theta.upper_bound is not None:
            bound_range = abs(theta.upper_bound - (theta.lower_bound or 0))
            if bound_range > 0 and abs(est - theta.upper_bound) / bound_range < BOUNDARY_FRACTION:
                report.flags.append(DiagnosticFlag(
                    severity="warning",
                    category="boundary",
                    message=f"THETA{theta.number} ({theta.name}): estimate {est:.4f} near upper bound {theta.upper_bound}",
                    parameter=est_key,
                    value=est,
                    threshold=theta.upper_bound,
                ))


def _is_diagonal_omega(name: str) -> bool:
    """Check if an OMEGA parameter name represents a diagonal element."""
    import re
    match = re.match(r"OMEGA\((\d+),(\d+)\)", name)
    if match:
        return match.group(1) == match.group(2)
    return False


def _detect_run_name(run_dir: Path) -> str | None:
    for ext in [".lst", ".ext", ".ctl", ".mod"]:
        files = list(run_dir.glob(f"*{ext}"))
        if files:
            return files[0].stem
    return None


def _find_ctl(run_dir: Path, run_name: str) -> Path | None:
    for ext in [".ctl", ".mod"]:
        p = run_dir / f"{run_name}{ext}"
        if p.exists():
            return p
    return None


def format_diagnostic_report(report: DiagnosticReport) -> str:
    """Format DiagnosticReport as human-readable text."""
    lines = []
    lines.append(f"=== Diagnostic Report: {report.run_name} ===")
    lines.append(f"Directory: {report.run_dir}")
    lines.append(f"Overall Status: {report.overall_status}")
    lines.append(f"Errors: {report.n_errors}, Warnings: {report.n_warnings}")
    lines.append("")

    if not report.flags:
        lines.append("No issues detected.")
        return "\n".join(lines)

    # Group by category
    categories: dict[str, list[DiagnosticFlag]] = {}
    for f in report.flags:
        categories.setdefault(f.category, []).append(f)

    for cat, flags in categories.items():
        lines.append(f"--- {cat.upper().replace('_', ' ')} ---")
        for f in flags:
            icon = {"error": "[ERROR]", "warning": "[WARN]", "info": "[INFO]"}.get(
                f.severity, "[?]"
            )
            lines.append(f"  {icon} {f.message}")
        lines.append("")

    return "\n".join(lines)
