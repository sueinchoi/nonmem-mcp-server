# nonmem-mcp-server

MCP (Model Context Protocol) server for NONMEM pharmacometric modeling workflows. Gives Claude (and any MCP-compatible client) structured access to NONMEM models, results, and simulation tools.

Supports **Windows**, **macOS**, and **Linux**.

## Features

### Parsing & Analysis (no NONMEM needed)
- **`read_ext_file`** — Parse .ext files for parameter estimates, SEs, OFV, condition number
- **`read_lst_file`** — Extract termination status, shrinkage, covariance step results
- **`parse_control_stream`** — Structural parsing of .ctl/.mod files (THETAs, OMEGAs, $EST options)
- **`read_nm_dataset`** — Dataset summary: subjects, observations, missing values
- **`read_nm_tables`** — Parse SDTAB/PATAB with statistics for CWRES, ETAs, PRED
- **`compare_models`** — Multi-run OFV comparison with delta-OFV and AIC
- **`summarize_run`** — Combined .ctl + .ext + .lst summary
- **`list_runs`** — Scan project directories for NONMEM runs

### Execution & Diagnostics
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

### Simulation (no NONMEM needed)
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
- **NONMEM 7.3–7.6** — Required for `submit_run` (commercial license)
- **PsN** — Required for `execute_psn_vpc`, `execute_psn_bootstrap`
- **R** with `mrgsolve`, `vpc`, `dplyr`, `ggplot2` — Required for simulation and GOF tools

## Installation

### Using uv (recommended)

```bash
git clone https://github.com/sueinchoi/nonmem-mcp-server.git
cd nonmem-mcp-server
uv sync
```

### Using pip

```bash
pip install git+https://github.com/sueinchoi/nonmem-mcp-server.git
```

Or for development:

```bash
git clone https://github.com/sueinchoi/nonmem-mcp-server.git
cd nonmem-mcp-server
pip install -e .
```

## NONMEM Path Configuration

The server auto-detects NONMEM from common install locations. If auto-detection fails, set one of these environment variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `NONMEM_NMFE_PATH` | Full path to nmfe executable | `/opt/nm760/run/nmfe76` |
| `NONMEM_INSTALL_PATH` | NONMEM installation root | `/opt/nm760` |

### Auto-detected paths

**macOS / Linux:**
- `/opt/nm760/run/nmfe76`, `/opt/NONMEM/nm75/run/nmfe75`, etc.
- `/usr/local/NONMEM/nm76/run/nmfe76`
- `~/NONMEM/nm76/run/nmfe76`

**Windows:**
- `C:\nm760\run\nmfe76.bat`, `C:\NONMEM\nm76\run\nmfe76.bat`
- `C:\Program Files\NONMEM\nm76\run\nmfe76.bat`
- `D:\NONMEM\nm76\run\nmfe76.bat`

## Usage with Claude Code

### Basic (no NONMEM)

```bash
claude mcp add nonmem -- nonmem-mcp
```

### With uv (from source)

```bash
claude mcp add -s user nonmem -- \
  uv run --directory /path/to/nonmem-mcp-server python -m nonmem_mcp
```

### With NONMEM path

```bash
# macOS / Linux
claude mcp add -s user \
  -e NONMEM_NMFE_PATH=/opt/nm760/run/nmfe76 \
  nonmem -- \
  uv run --directory /path/to/nonmem-mcp-server python -m nonmem_mcp
```

```powershell
# Windows (PowerShell)
claude mcp add -s user `
  -e NONMEM_NMFE_PATH=C:\nm760\run\nmfe76.bat `
  nonmem -- `
  uv run --directory C:\path\to\nonmem-mcp-server python -m nonmem_mcp
```

### Verify

```bash
claude mcp list
# nonmem: ... - ✓ Connected
```

## Usage with Claude Desktop

Add to `claude_desktop_config.json`:

### macOS / Linux

```json
{
  "mcpServers": {
    "nonmem": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/nonmem-mcp-server", "python", "-m", "nonmem_mcp"],
      "env": {
        "NONMEM_NMFE_PATH": "/opt/nm760/run/nmfe76"
      }
    }
  }
}
```

### Windows

```json
{
  "mcpServers": {
    "nonmem": {
      "command": "uv",
      "args": ["run", "--directory", "C:\\path\\to\\nonmem-mcp-server", "python", "-m", "nonmem_mcp"],
      "env": {
        "NONMEM_NMFE_PATH": "C:\\nm760\\run\\nmfe76.bat"
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

# Systematic model development
"Develop a 2-compartment model with forward IIV addition"

# Translate to mrgsolve for simulation
"Convert my NONMEM model to mrgsolve and run a VPC"

# GOF plots
"Generate GOF plots for run015 with IPRED and CWRES"
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

## Included Examples

The `examples/theopp/` directory contains a complete model development workflow using the Theophylline dataset:

- **run001.ctl** — 1-compartment base model (ADVAN2, FO)
- **run002.ctl** — 2-compartment model (ADVAN4 TRANS4)
- **run003–005.ctl** — 2-comp base models with different initial estimates (no IIV)
- **run006–010.ctl** — Single IIV forward addition (CL, V2, Q, V3, KA)
- **run011–014.ctl** — Double IIV forward addition (V2+CL, V2+KA, V2+Q, V2+V3)
- **run015.ctl** — Final 1-comp model with FOCE+INTER, IPRED, CWRES
- **gof_plot_v2.R** — GOF plotting script (DV vs PRED/IPRED, CWRES, QQ plot)

## License

MIT
