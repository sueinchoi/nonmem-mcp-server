"""NONMEM MCP Server - Main server definition with all tools and prompts."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import (
    GetPromptResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    TextContent,
    Tool,
)

from nonmem_mcp.parsers.control_stream_parser import (
    format_control_stream,
    parse_control_stream,
)
from nonmem_mcp.parsers.dataset_parser import format_dataset_summary, parse_dataset
from nonmem_mcp.parsers.ext_parser import format_ext_result, parse_ext_file
from nonmem_mcp.parsers.lst_parser import format_lst_result, parse_lst_file
from nonmem_mcp.parsers.table_parser import format_table_summary, parse_table_file
from nonmem_mcp.tools.diagnostics import format_diagnostic_report, run_diagnostics
from nonmem_mcp.tools.execute import (
    cancel_run,
    check_run_status,
    detect_nmfe,
    get_run_results,
    list_jobs,
    submit_run,
)
from nonmem_mcp.tools.psn import (
    check_psn_status,
    detect_psn,
    execute_psn_bootstrap,
    execute_psn_vpc,
    parse_psn_results,
    psn_sumo,
)
from nonmem_mcp.tools.mrgsolve import (
    detect_r_setup,
    generate_vpc_data,
    simulate_mrgsolve,
    translate_to_mrgsolve,
)

server = Server("nonmem-mcp-server")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="read_ext_file",
            description="Parse a NONMEM .ext file to extract parameter estimates, standard errors, OFV, eigenvalues, and condition number.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the .ext file",
                    },
                },
                "required": ["file_path"],
            },
        ),
        Tool(
            name="read_lst_file",
            description="Parse a NONMEM .lst file for termination status, minimization success, shrinkage, condition number, and warnings.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the .lst file",
                    },
                },
                "required": ["file_path"],
            },
        ),
        Tool(
            name="parse_control_stream",
            description="Parse a NONMEM control stream (.ctl/.mod) into structured components: $THETA, $OMEGA, $SIGMA, $EST options, input columns, data file, and ADVAN/TRANS.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the .ctl or .mod file",
                    },
                },
                "required": ["file_path"],
            },
        ),
        Tool(
            name="read_nm_dataset",
            description="Read and summarize a NONMEM dataset: subject count, observation count, dose records, missing values, and column overview.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the dataset file",
                    },
                    "input_columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Column names from $INPUT (optional, auto-detected if file has header)",
                    },
                },
                "required": ["file_path"],
            },
        ),
        Tool(
            name="read_nm_tables",
            description="Parse NONMEM table output files (SDTAB, PATAB, etc.) and compute summary statistics for key columns (CWRES, PRED, IPRED, ETAs).",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the table output file",
                    },
                },
                "required": ["file_path"],
            },
        ),
        Tool(
            name="compare_models",
            description="Compare multiple NONMEM runs by OFV, delta-OFV, parameter counts, and AIC. Accepts a list of run directories or .ext file paths.",
            inputSchema={
                "type": "object",
                "properties": {
                    "models": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Model name/label"},
                                "ext_path": {"type": "string", "description": "Path to .ext file"},
                            },
                            "required": ["name", "ext_path"],
                        },
                        "description": "List of models to compare",
                    },
                },
                "required": ["models"],
            },
        ),
        Tool(
            name="summarize_run",
            description="Generate a comprehensive summary of a NONMEM run by combining control stream, .ext, and .lst results.",
            inputSchema={
                "type": "object",
                "properties": {
                    "run_dir": {
                        "type": "string",
                        "description": "Path to the run directory",
                    },
                    "run_name": {
                        "type": "string",
                        "description": "Base name of the run files (e.g., 'run001'). If omitted, auto-detected from directory.",
                    },
                },
                "required": ["run_dir"],
            },
        ),
        Tool(
            name="list_runs",
            description="Scan a project directory for NONMEM run files and list their status (completed/failed/running).",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_dir": {
                        "type": "string",
                        "description": "Path to the project directory to scan",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "Search subdirectories recursively (default: true)",
                        "default": True,
                    },
                },
                "required": ["project_dir"],
            },
        ),
        # --- Phase 2: Execution Tools ---
        Tool(
            name="submit_run",
            description="Submit a NONMEM run (async). Returns a job ID for polling. Requires NONMEM installation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ctl_path": {"type": "string", "description": "Path to the control stream file"},
                    "work_dir": {"type": "string", "description": "Working directory (default: same as ctl file)"},
                    "nmfe_path": {"type": "string", "description": "Path to nmfe executable (auto-detected if omitted)"},
                    "run_name": {"type": "string", "description": "Run name (default: ctl filename stem)"},
                },
                "required": ["ctl_path"],
            },
        ),
        Tool(
            name="check_run_status",
            description="Check the status and progress of a submitted NONMEM run by job ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID from submit_run"},
                },
                "required": ["job_id"],
            },
        ),
        Tool(
            name="get_run_results",
            description="Get full parsed results of a completed NONMEM run by job ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID from submit_run"},
                },
                "required": ["job_id"],
            },
        ),
        Tool(
            name="cancel_run",
            description="Cancel a running NONMEM job.",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID to cancel"},
                },
                "required": ["job_id"],
            },
        ),
        Tool(
            name="run_diagnostics",
            description="Run comprehensive post-run diagnostics: boundary checks, condition number, shrinkage, precision (RSE), convergence warnings. No NONMEM needed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "run_dir": {"type": "string", "description": "Path to the run directory"},
                    "run_name": {"type": "string", "description": "Run name (auto-detected if omitted)"},
                },
                "required": ["run_dir"],
            },
        ),
        # --- Phase 2: PsN Integration ---
        Tool(
            name="execute_psn_vpc",
            description="Run VPC using PsN (async). Returns job ID for polling. Requires PsN + NONMEM.",
            inputSchema={
                "type": "object",
                "properties": {
                    "model_path": {"type": "string", "description": "Path to the model file"},
                    "samples": {"type": "integer", "description": "Number of simulations (default: 200)", "default": 200},
                    "options": {
                        "type": "object",
                        "description": "Additional PsN VPC options",
                        "properties": {
                            "predcorr": {"type": "boolean", "description": "Prediction-corrected VPC"},
                            "stratify_on": {"type": "string", "description": "Stratification variable"},
                            "idv": {"type": "string", "description": "Independent variable (default: TIME)"},
                            "lloq": {"type": "number", "description": "Lower limit of quantification"},
                            "seed": {"type": "integer", "description": "Random seed"},
                            "threads": {"type": "integer", "description": "Number of parallel threads"},
                        },
                    },
                },
                "required": ["model_path"],
            },
        ),
        Tool(
            name="execute_psn_bootstrap",
            description="Run bootstrap using PsN (async). Returns job ID for polling. Requires PsN + NONMEM.",
            inputSchema={
                "type": "object",
                "properties": {
                    "model_path": {"type": "string", "description": "Path to the model file"},
                    "samples": {"type": "integer", "description": "Number of bootstrap samples (default: 200)", "default": 200},
                    "options": {
                        "type": "object",
                        "description": "Additional PsN bootstrap options",
                        "properties": {
                            "stratify_on": {"type": "string", "description": "Stratification variable"},
                            "seed": {"type": "integer", "description": "Random seed"},
                            "threads": {"type": "integer", "description": "Number of parallel threads"},
                            "bca": {"type": "boolean", "description": "BCa confidence intervals"},
                        },
                    },
                },
                "required": ["model_path"],
            },
        ),
        Tool(
            name="check_psn_status",
            description="Check status and progress of a PsN VPC or bootstrap job.",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "PsN job ID"},
                },
                "required": ["job_id"],
            },
        ),
        Tool(
            name="parse_psn_results",
            description="Parse results from an existing PsN output directory (VPC or bootstrap). No PsN/NONMEM installation needed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "results_dir": {"type": "string", "description": "Path to PsN output directory"},
                },
                "required": ["results_dir"],
            },
        ),
        Tool(
            name="check_nonmem_setup",
            description="Check NONMEM, PsN, R, and mrgsolve installation status and paths.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        # --- Phase 3: mrgsolve Simulation ---
        Tool(
            name="translate_to_mrgsolve",
            description="Translate a NONMEM control stream (.ctl/.mod) to mrgsolve model code. Handles ADVAN1-13, THETAs, OMEGAs, $PK, $DES, $ERROR.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ctl_path": {"type": "string", "description": "Path to NONMEM control stream"},
                    "output_path": {"type": "string", "description": "Where to save the mrgsolve .mod file (optional)"},
                    "parameter_values": {
                        "type": "object",
                        "description": "Override parameter values (e.g., from .ext final estimates)",
                    },
                },
                "required": ["ctl_path"],
            },
        ),
        Tool(
            name="simulate_mrgsolve",
            description="Run a simulation using mrgsolve (R). No NONMEM needed. Provide model code or model file path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "model_code": {"type": "string", "description": "Inline mrgsolve model code"},
                    "model_file": {"type": "string", "description": "Path to mrgsolve .mod file"},
                    "data_path": {"type": "string", "description": "Path to dataset for simulation (optional)"},
                    "n_subjects": {"type": "integer", "description": "Number of subjects (default: 100)", "default": 100},
                    "end_time": {"type": "number", "description": "End time for simulation (default: 24)", "default": 24},
                    "delta": {"type": "number", "description": "Time step (default: 0.5)", "default": 0.5},
                    "dose_amt": {"type": "number", "description": "Dose amount (for simple dosing regimen)"},
                    "dose_cmt": {"type": "integer", "description": "Dosing compartment (default: 1)", "default": 1},
                    "seed": {"type": "integer", "description": "Random seed (default: 12345)", "default": 12345},
                    "output_path": {"type": "string", "description": "Path to save output CSV"},
                },
            },
        ),
        Tool(
            name="generate_vpc_data",
            description="Generate VPC data using mrgsolve + vpc R package. No NONMEM needed. Requires observed data and model.",
            inputSchema={
                "type": "object",
                "properties": {
                    "model_code": {"type": "string", "description": "Inline mrgsolve model code"},
                    "model_file": {"type": "string", "description": "Path to mrgsolve .mod file"},
                    "observed_data_path": {"type": "string", "description": "Path to observed dataset (required)"},
                    "n_sim": {"type": "integer", "description": "Number of simulations (default: 200)", "default": 200},
                    "seed": {"type": "integer", "description": "Random seed", "default": 12345},
                    "pred_corr": {"type": "boolean", "description": "Prediction-corrected VPC", "default": False},
                    "stratify_on": {"type": "string", "description": "Stratification variable"},
                    "output_dir": {"type": "string", "description": "Directory for output files"},
                },
                "required": ["observed_data_path"],
            },
        ),
        Tool(
            name="check_r_setup",
            description="Check R installation and required packages (mrgsolve, vpc, dplyr, ggplot2).",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        if name == "read_ext_file":
            return _handle_read_ext(arguments)
        elif name == "read_lst_file":
            return _handle_read_lst(arguments)
        elif name == "parse_control_stream":
            return _handle_parse_ctl(arguments)
        elif name == "read_nm_dataset":
            return _handle_read_dataset(arguments)
        elif name == "read_nm_tables":
            return _handle_read_tables(arguments)
        elif name == "compare_models":
            return _handle_compare(arguments)
        elif name == "summarize_run":
            return _handle_summarize(arguments)
        elif name == "list_runs":
            return _handle_list_runs(arguments)
        # Phase 2: Execution
        elif name == "submit_run":
            result = submit_run(
                arguments["ctl_path"],
                arguments.get("work_dir"),
                arguments.get("nmfe_path"),
                arguments.get("run_name"),
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        elif name == "check_run_status":
            result = check_run_status(arguments["job_id"])
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        elif name == "get_run_results":
            result = get_run_results(arguments["job_id"])
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
        elif name == "cancel_run":
            result = cancel_run(arguments["job_id"])
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        elif name == "run_diagnostics":
            report = run_diagnostics(arguments["run_dir"], arguments.get("run_name"))
            return [TextContent(type="text", text=format_diagnostic_report(report))]
        # Phase 2: PsN
        elif name == "execute_psn_vpc":
            result = execute_psn_vpc(
                arguments["model_path"],
                arguments.get("samples", 200),
                arguments.get("options"),
                arguments.get("work_dir"),
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        elif name == "execute_psn_bootstrap":
            result = execute_psn_bootstrap(
                arguments["model_path"],
                arguments.get("samples", 200),
                arguments.get("options"),
                arguments.get("work_dir"),
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        elif name == "check_psn_status":
            result = check_psn_status(arguments["job_id"])
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        elif name == "parse_psn_results":
            result = parse_psn_results(arguments["results_dir"])
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
        elif name == "check_nonmem_setup":
            nmfe = detect_nmfe()
            psn_tools = detect_psn()
            r_setup = detect_r_setup()
            setup = {
                "nonmem": {"nmfe_path": nmfe, "installed": nmfe is not None},
                "psn": {tool: {"path": path, "installed": path is not None} for tool, path in psn_tools.items()},
                "r": r_setup,
            }
            return [TextContent(type="text", text=json.dumps(setup, indent=2))]
        # Phase 3: mrgsolve
        elif name == "translate_to_mrgsolve":
            result = translate_to_mrgsolve(
                arguments["ctl_path"],
                arguments.get("output_path"),
                arguments.get("parameter_values"),
            )
            text = result.get("model_code", "")
            meta = {k: v for k, v in result.items() if k != "model_code"}
            return [TextContent(type="text", text=f"--- mrgsolve Model Code ---\n{text}\n\n--- Metadata ---\n{json.dumps(meta, indent=2)}")]
        elif name == "simulate_mrgsolve":
            result = simulate_mrgsolve(
                model_code=arguments.get("model_code"),
                model_file=arguments.get("model_file"),
                data_path=arguments.get("data_path"),
                n_subjects=arguments.get("n_subjects", 100),
                end_time=arguments.get("end_time", 24),
                delta=arguments.get("delta", 0.5),
                dose_amt=arguments.get("dose_amt"),
                dose_cmt=arguments.get("dose_cmt", 1),
                seed=arguments.get("seed", 12345),
                output_path=arguments.get("output_path"),
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
        elif name == "generate_vpc_data":
            result = generate_vpc_data(
                model_code=arguments.get("model_code"),
                model_file=arguments.get("model_file"),
                observed_data_path=arguments.get("observed_data_path"),
                n_sim=arguments.get("n_sim", 200),
                seed=arguments.get("seed", 12345),
                pred_corr=arguments.get("pred_corr", False),
                stratify_on=arguments.get("stratify_on"),
                output_dir=arguments.get("output_dir"),
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
        elif name == "check_r_setup":
            result = detect_r_setup()
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")]


def _handle_read_ext(args: dict) -> list[TextContent]:
    results = parse_ext_file(args["file_path"])
    output_parts = []
    for r in results:
        output_parts.append(format_ext_result(r))
    # Also include JSON for structured access
    json_data = [asdict(r) for r in results]
    text = "\n\n".join(output_parts)
    text += "\n\n--- JSON ---\n" + json.dumps(json_data, indent=2, default=str)
    return [TextContent(type="text", text=text)]


def _handle_read_lst(args: dict) -> list[TextContent]:
    result = parse_lst_file(args["file_path"])
    text = format_lst_result(result)
    text += "\n\n--- JSON ---\n" + json.dumps(asdict(result), indent=2, default=str)
    return [TextContent(type="text", text=text)]


def _handle_parse_ctl(args: dict) -> list[TextContent]:
    cs = parse_control_stream(args["file_path"])
    text = format_control_stream(cs)
    # Include raw block content for Claude to interpret
    text += "\n\n--- Raw Code Blocks ---"
    for rec in cs.records:
        if rec.keyword in ("PK", "PRED", "ERROR", "ERR", "DES", "MODEL", "MOD"):
            text += f"\n\n${rec.keyword}:\n{rec.content}"
    return [TextContent(type="text", text=text)]


def _handle_read_dataset(args: dict) -> list[TextContent]:
    input_cols = args.get("input_columns")
    summary = parse_dataset(args["file_path"], input_cols)
    text = format_dataset_summary(summary)
    return [TextContent(type="text", text=text)]


def _handle_read_tables(args: dict) -> list[TextContent]:
    summary = parse_table_file(args["file_path"])
    text = format_table_summary(summary)
    return [TextContent(type="text", text=text)]


def _handle_compare(args: dict) -> list[TextContent]:
    models = args["models"]
    results = []
    for model in models:
        ext_results = parse_ext_file(model["ext_path"])
        if ext_results:
            last = ext_results[-1]  # Use last estimation step
            # Count non-fixed parameters
            n_free = 0
            for key in list(last.thetas) + list(last.omegas) + list(last.sigmas):
                if not last.fixed_flags.get(key, False):
                    n_free += 1

            ofv = last.ofv or 0.0
            aic = ofv + 2 * n_free
            results.append({
                "name": model["name"],
                "ofv": ofv,
                "n_params": n_free,
                "aic": aic,
                "condition_number": last.condition_number,
            })

    # Sort by OFV
    results.sort(key=lambda x: x["ofv"])

    lines = []
    header = f"{'Model':<20} {'OFV':>12} {'nPar':>6} {'AIC':>12} {'Cond#':>10}"
    lines.append(header)
    lines.append("-" * len(header))
    for r in results:
        cn = f"{r['condition_number']:.1f}" if r["condition_number"] else "N/A"
        lines.append(
            f"{r['name']:<20} {r['ofv']:>12.4f} {r['n_params']:>6} "
            f"{r['aic']:>12.4f} {cn:>10}"
        )

    # Pairwise comparison (first model as base)
    if len(results) >= 2:
        lines.append("")
        lines.append("--- Pairwise Comparison (vs best OFV) ---")
        base = results[0]
        for r in results[1:]:
            delta = r["ofv"] - base["ofv"]
            df = abs(r["n_params"] - base["n_params"])
            lines.append(
                f"  {r['name']} vs {base['name']}: "
                f"dOFV={delta:+.4f}, df={df}"
            )

    text = "\n".join(lines)
    text += "\n\n--- JSON ---\n" + json.dumps(results, indent=2, default=str)
    return [TextContent(type="text", text=text)]


def _handle_summarize(args: dict) -> list[TextContent]:
    run_dir = Path(args["run_dir"])
    run_name = args.get("run_name")

    if not run_dir.exists():
        return [TextContent(type="text", text=f"Directory not found: {run_dir}")]

    # Auto-detect run name
    if not run_name:
        run_name = _detect_run_name(run_dir)

    if not run_name:
        return [TextContent(type="text", text=f"Could not detect run files in {run_dir}")]

    lines = [f"=== Run Summary: {run_name} ===", f"Directory: {run_dir}", ""]

    # Parse control stream
    ctl_path = _find_file(run_dir, run_name, [".ctl", ".mod"])
    if ctl_path:
        cs = parse_control_stream(ctl_path)
        lines.append(f"Problem: {cs.problem}")
        lines.append(f"Data: {cs.data_file}")
        lines.append(f"Subroutine: {cs.subroutine}")
        lines.append(f"THETAs: {len(cs.thetas)}, OMEGAs: {len(cs.omegas)}, SIGMAs: {len(cs.sigmas)}")
        methods = [e.method + (" INTER" if e.interaction else "") for e in cs.estimation_methods]
        lines.append(f"Estimation: {', '.join(methods)}")
        lines.append("")

    # Parse .ext
    ext_path = _find_file(run_dir, run_name, [".ext"])
    if ext_path:
        ext_results = parse_ext_file(ext_path)
        if ext_results:
            last = ext_results[-1]
            lines.append(f"OFV: {last.ofv:.4f}" if last.ofv else "OFV: N/A")
            if last.condition_number:
                lines.append(f"Condition Number: {last.condition_number:.2f}")
            lines.append("")
            lines.append(format_ext_result(last))
            lines.append("")

    # Parse .lst
    lst_path = _find_file(run_dir, run_name, [".lst"])
    if lst_path:
        lst_result = parse_lst_file(lst_path)
        lines.append(format_lst_result(lst_result))

    return [TextContent(type="text", text="\n".join(lines))]


def _handle_list_runs(args: dict) -> list[TextContent]:
    project_dir = Path(args["project_dir"])
    recursive = args.get("recursive", True)

    if not project_dir.exists():
        return [TextContent(type="text", text=f"Directory not found: {project_dir}")]

    # Find all .ext files (indicator of a NONMEM run)
    if recursive:
        ext_files = list(project_dir.rglob("*.ext"))
    else:
        ext_files = list(project_dir.glob("*.ext"))

    if not ext_files:
        return [TextContent(type="text", text=f"No NONMEM runs found in {project_dir}")]

    lines = [f"NONMEM Runs in {project_dir}", ""]
    header = f"{'Run':<30} {'Dir':<40} {'OFV':>12} {'Status':<15}"
    lines.append(header)
    lines.append("-" * len(header))

    for ext_path in sorted(ext_files):
        run_name = ext_path.stem
        run_dir = ext_path.parent

        # Quick status check
        status = "completed"
        ofv_str = "N/A"

        lst_path = run_dir / f"{run_name}.lst"
        if lst_path.exists():
            try:
                lst = parse_lst_file(lst_path)
                if lst.minimization_successful:
                    status = "OK"
                else:
                    status = f"FAIL: {lst.termination_status[:20]}"
            except Exception:
                status = "parse_error"

        try:
            ext_results = parse_ext_file(ext_path)
            if ext_results and ext_results[-1].ofv is not None:
                ofv_str = f"{ext_results[-1].ofv:.4f}"
        except Exception:
            pass

        rel_dir = str(run_dir.relative_to(project_dir)) if run_dir != project_dir else "."
        lines.append(f"{run_name:<30} {rel_dir:<40} {ofv_str:>12} {status:<15}")

    return [TextContent(type="text", text="\n".join(lines))]


def _detect_run_name(run_dir: Path) -> str | None:
    """Auto-detect the run name from files in the directory."""
    for ext in [".ctl", ".mod"]:
        files = list(run_dir.glob(f"*{ext}"))
        if files:
            return files[0].stem
    for ext in [".ext"]:
        files = list(run_dir.glob(f"*{ext}"))
        if files:
            return files[0].stem
    return None


def _find_file(run_dir: Path, run_name: str, extensions: list[str]) -> Path | None:
    """Find a file with the given run name and one of the extensions."""
    for ext in extensions:
        path = run_dir / f"{run_name}{ext}"
        if path.exists():
            return path
    return None


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

@server.list_prompts()
async def list_prompts() -> list[Prompt]:
    return [
        Prompt(
            name="review_model",
            description="Review a NONMEM model for errors, best practices, and improvement suggestions",
            arguments=[
                PromptArgument(
                    name="file_path",
                    description="Path to the control stream file",
                    required=True,
                ),
            ],
        ),
        Prompt(
            name="interpret_results",
            description="Interpret NONMEM run results in pharmacological context",
            arguments=[
                PromptArgument(
                    name="run_dir",
                    description="Path to the run directory",
                    required=True,
                ),
            ],
        ),
        Prompt(
            name="troubleshoot_run",
            description="Diagnose why a NONMEM run failed or produced warnings",
            arguments=[
                PromptArgument(
                    name="file_path",
                    description="Path to the .lst file",
                    required=True,
                ),
            ],
        ),
        Prompt(
            name="suggest_next_model",
            description="Suggest what to try next in model development based on current results",
            arguments=[
                PromptArgument(
                    name="run_dir",
                    description="Path to the current best model run directory",
                    required=True,
                ),
            ],
        ),
        Prompt(
            name="write_methods_section",
            description="Draft a Methods section for a publication based on the final model",
            arguments=[
                PromptArgument(
                    name="run_dir",
                    description="Path to the final model run directory",
                    required=True,
                ),
            ],
        ),
    ]


@server.get_prompt()
async def get_prompt(name: str, arguments: dict[str, str] | None) -> GetPromptResult:
    arguments = arguments or {}

    if name == "review_model":
        return _prompt_review_model(arguments)
    elif name == "interpret_results":
        return _prompt_interpret_results(arguments)
    elif name == "troubleshoot_run":
        return _prompt_troubleshoot(arguments)
    elif name == "suggest_next_model":
        return _prompt_suggest_next(arguments)
    elif name == "write_methods_section":
        return _prompt_write_methods(arguments)
    else:
        raise ValueError(f"Unknown prompt: {name}")


def _prompt_review_model(args: dict) -> GetPromptResult:
    file_path = args.get("file_path", "")
    return GetPromptResult(
        description="Review NONMEM model",
        messages=[
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"""Please review the NONMEM control stream at: {file_path}

Use the parse_control_stream tool to read it, then check for:

1. **Structural issues**: Correct ADVAN/TRANS for the model type, appropriate compartment setup
2. **Parameter initialization**: Reasonable initial estimates, appropriate bounds for THETAs, OMEGA/SIGMA structure
3. **Estimation settings**: Appropriate METHOD, MAXEVAL, SIGDIGITS, INTERACTION usage
4. **Numerical stability**: Potential for boundary issues, poorly conditioned OMEGA blocks
5. **Best practices**:
   - Are initial estimates reasonable for the drug class?
   - Is the error model appropriate?
   - Are $TABLE outputs sufficient for diagnostics?
   - Any missing $COV step?
6. **Common errors**: Mismatched $INPUT columns vs data, wrong ADVAN for the number of compartments

Provide specific recommendations with corrected code where applicable.""",
                ),
            ),
        ],
    )


def _prompt_interpret_results(args: dict) -> GetPromptResult:
    run_dir = args.get("run_dir", "")
    return GetPromptResult(
        description="Interpret NONMEM results",
        messages=[
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"""Please interpret the NONMEM run results in: {run_dir}

Use summarize_run to get the full picture, then provide:

1. **Model adequacy**: Did the model converge successfully? Is the condition number acceptable (<1000)?
2. **Parameter estimates**: Are estimates pharmacologically reasonable? Flag any unusual values.
3. **Precision**: Are RSE% values acceptable? (THETAs <30-50%, OMEGAs <50%)
4. **Shrinkage**: Are ETA shrinkage values acceptable? (<30% is good, >40% is concerning)
5. **Interindividual variability**: Interpret OMEGA values as %CV
6. **Residual variability**: Interpret SIGMA in context of the error model
7. **Warnings**: Explain any warnings and their clinical significance
8. **Overall assessment**: Is this model adequate for its intended purpose?""",
                ),
            ),
        ],
    )


def _prompt_troubleshoot(args: dict) -> GetPromptResult:
    file_path = args.get("file_path", "")
    return GetPromptResult(
        description="Troubleshoot NONMEM run",
        messages=[
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"""Please diagnose problems with the NONMEM run. The .lst file is at: {file_path}

Use read_lst_file to check the status, then investigate:

1. **Termination status**: What exactly went wrong?
2. **Common causes**:
   - ROUNDING ERRORS: Initial estimates too far from solution, overparameterized model
   - ZERO GRADIENT: Parameter at boundary, redundant parameters
   - MAX EVALUATIONS: Increase MAXEVAL or simplify model
   - SINGULAR MATRIX: Overparameterized, correlated parameters
   - NOT POSITIVE DEFINITE: OMEGA structure issues
3. **Specific recommendations**: What to change in the control stream to fix the issue
4. **Stepwise approach**: Suggest changes in order of likelihood of fixing the problem

Also check the corresponding .ext file for the iteration history - was the model converging before failure?""",
                ),
            ),
        ],
    )


def _prompt_suggest_next(args: dict) -> GetPromptResult:
    run_dir = args.get("run_dir", "")
    return GetPromptResult(
        description="Suggest next model",
        messages=[
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"""Based on the current model in: {run_dir}

Use summarize_run and read_nm_tables to understand the current model, then suggest:

1. **Structural model**: Should compartments be added/removed? Transit absorption? Non-linear elimination?
2. **IIV structure**: Which parameters need IIV? Should any OMEGAs be correlated (BLOCK)?
3. **Residual error**: Is the current error model adequate? Combined vs proportional vs additive?
4. **Covariate analysis**: Based on ETA distributions and available covariates, suggest candidates
5. **Priority**: Rank suggestions by expected impact on model fit
6. **Implementation**: Provide specific control stream modifications for the top 3 suggestions

Consider pharmacometric best practices and parsimony.""",
                ),
            ),
        ],
    )


def _prompt_write_methods(args: dict) -> GetPromptResult:
    run_dir = args.get("run_dir", "")
    return GetPromptResult(
        description="Write Methods section",
        messages=[
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=f"""Draft a Methods section for a pharmacometrics publication based on the final model in: {run_dir}

Use summarize_run to get all model details, then write:

1. **Software**: NONMEM version, estimation method, computing environment
2. **Structural model**: Compartmental structure, absorption model, elimination
3. **Statistical model**: IIV (log-normal, etc.), residual error model type
4. **Parameter estimation**: Method (FOCE-I, SAEM, etc.), convergence criteria
5. **Model evaluation**: GOF, VPC, bootstrap (if available), condition number
6. **Covariate analysis**: Strategy (if covariates present)

Write in standard pharmacometrics journal style (CPT:PSP, PAGE, JPP format).
Include a parameter table template.""",
                ),
            ),
        ],
    )
