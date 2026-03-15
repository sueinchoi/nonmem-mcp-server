# nonmem-mcp-server

MCP (Model Context Protocol) server for NONMEM pharmacometric modeling workflows. Gives Claude (and any MCP-compatible client) structured access to NONMEM models, results, and simulation tools.

## Features

### Phase 1: Parsing & Analysis (no NONMEM needed)
- **`read_ext_file`** — Parse .ext files for parameter estimates, SEs, OFV, condition number
- **`read_lst_file`** — Extract termination status, shrinkage, covariance step results
- **`parse_control_stream`** — Structural parsing of .ctl/.mod files (THETAs, OMEGAs, $EST options)
- **`read_nm_dataset`** — Dataset summary: subjects, observations, missing values
- **`read_nm_tables`** — Parse SDTAB/PATAB with statistics for CWRES, ETAs, PRED
- **`compare_models`** — Multi-run OFV comparison with delta-OFV and AIC
- **`summarize_run`** — Combined .ctl + .ext + .lst summary
- **`list_runs`** — Scan project directories for NONMEM runs

### Phase 2: Execution & Diagnostics
- **`submit_run`** — Start NONMEM runs (async, fire-and-poll pattern)
- **`check_run_status`** — Monitor iteration progress via .ext file
- **`get_run_results`** — Retrieve parsed results when complete
- **`cancel_run`** — Kill running NONMEM jobs
- **`run_diagnostics`** — Automated checks: boundary, condition number, shrinkage, RSE
- **`execute_psn_vpc`** — Run VPC via PsN (predcorr, stratify, lloq options)
- **`execute_psn_bootstrap`** — Run bootstrap via PsN (BCa, stratify)
- **`check_psn_status`** — Monitor PsN job progress
- **`parse_psn_results`** — Parse existing PsN output directories (no installation needed)
- **`check_nonmem_setup`** — Detect NONMEM, PsN, R installation status

### Phase 3: Simulation (no NONMEM needed)
- **`translate_to_mrgsolve`** — Convert NONMEM .ctl/.mod to mrgsolve model code
- **`simulate_mrgsolve`** — Run PK simulations via mrgsolve (R)
- **`generate_vpc_data`** — Generate VPC data using mrgsolve + vpc R package
- **`check_r_setup`** — Check R and package availability

### Prompts
- **`review_model`** — Model review checklist
- **`interpret_results`** — Pharmacological interpretation
- **`troubleshoot_run`** — Diagnose run failures
- **`suggest_next_model`** — Suggest next modeling steps
- **`write_methods_section`** — Draft publication Methods text

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Optional
- **NONMEM** — Required for `submit_run` (commercial license)
- **PsN** — Required for `execute_psn_vpc`, `execute_psn_bootstrap`
- **R** with `mrgsolve`, `vpc`, `dplyr` — Required for simulation tools

## Installation

```bash
git clone https://github.com/sueinchoi/nonmem-mcp-server.git
cd nonmem-mcp-server
uv sync
```

## Usage with Claude Code

```bash
claude mcp add -s user nonmem -- \
  uv run --directory /path/to/nonmem-mcp-server python -m nonmem_mcp
```

With NONMEM installed:
```bash
claude mcp add -s user \
  -e NONMEM_NMFE_PATH=/opt/NONMEM/nm75/run/nmfe75 \
  nonmem -- \
  uv run --directory /path/to/nonmem-mcp-server python -m nonmem_mcp
```

Verify:
```bash
claude mcp list
# nonmem: ... - ✓ Connected
```

## Usage with Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "nonmem": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/nonmem-mcp-server", "python", "-m", "nonmem_mcp"],
      "env": {
        "NONMEM_NMFE_PATH": "/opt/NONMEM/nm75/run/nmfe75"
      }
    }
  }
}
```

## Examples

```
# Summarize a NONMEM run
"Summarize the run in /path/to/run001/"

# Compare covariate models
"Compare OFV across all models in the covariate analysis directory"

# Diagnose a failed run
"Why did this run fail? Check /path/to/run.lst"

# Translate to mrgsolve for simulation
"Convert my NONMEM model to mrgsolve and run a VPC"
```

## Capability Matrix

| Feature | No NONMEM | + NONMEM | + PsN |
|---------|:---------:|:--------:|:-----:|
| Parse .ext/.lst/.ctl | ✓ | ✓ | ✓ |
| Model comparison | ✓ | ✓ | ✓ |
| Diagnostics | ✓ | ✓ | ✓ |
| mrgsolve simulation | ✓ | ✓ | ✓ |
| mrgsolve VPC | ✓ | ✓ | ✓ |
| NONMEM execution | ✗ | ✓ | ✓ |
| PsN VPC | ✗ | ✗ | ✓ |
| PsN Bootstrap | ✗ | ✗ | ✓ |
| Parse PsN results | ✓ | ✓ | ✓ |

## License

MIT
