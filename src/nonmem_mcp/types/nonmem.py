"""NONMEM data types for structured parsing results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ThetaEstimate:
    number: int
    name: str  # from comment or THETAn
    initial: float | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    fixed: bool = False
    estimate: float | None = None
    se: float | None = None
    rse_percent: float | None = None


@dataclass
class OmegaEstimate:
    row: int
    col: int
    initial: float | None = None
    fixed: bool = False
    estimate: float | None = None
    se: float | None = None
    block_number: int | None = None


@dataclass
class SigmaEstimate:
    row: int
    col: int
    initial: float | None = None
    fixed: bool = False
    estimate: float | None = None
    se: float | None = None


@dataclass
class EstimationMethod:
    method: str  # FOCE, SAEM, BAYES, IMP, etc.
    interaction: bool = False
    maxeval: int | None = None
    sigdigits: int | None = None
    options: dict[str, str] = field(default_factory=dict)


@dataclass
class RecordBlock:
    """A single $RECORD block from a control stream."""
    keyword: str  # PROBLEM, INPUT, DATA, SUBROUTINES, etc.
    content: str  # Raw text content of the block
    line_number: int = 0


@dataclass
class ControlStream:
    """Structurally parsed NONMEM control stream."""
    file_path: str
    records: list[RecordBlock] = field(default_factory=list)
    thetas: list[ThetaEstimate] = field(default_factory=list)
    omegas: list[OmegaEstimate] = field(default_factory=list)
    sigmas: list[SigmaEstimate] = field(default_factory=list)
    estimation_methods: list[EstimationMethod] = field(default_factory=list)
    problem: str = ""
    data_file: str = ""
    input_columns: list[str] = field(default_factory=list)
    subroutine: str = ""  # ADVAN/TRANS


@dataclass
class ExtResult:
    """Parsed .ext file results for one estimation step."""
    table_number: int
    method: str
    thetas: dict[str, float] = field(default_factory=dict)
    omegas: dict[str, float] = field(default_factory=dict)
    sigmas: dict[str, float] = field(default_factory=dict)
    ofv: float | None = None
    theta_ses: dict[str, float] = field(default_factory=dict)
    omega_ses: dict[str, float] = field(default_factory=dict)
    sigma_ses: dict[str, float] = field(default_factory=dict)
    fixed_flags: dict[str, bool] = field(default_factory=dict)
    eigenvalues: list[float] = field(default_factory=list)
    condition_number: float | None = None
    iterations: list[dict[str, float]] = field(default_factory=list)


@dataclass
class LstResult:
    """Minimal parsed .lst file results."""
    termination_status: str = ""
    minimization_successful: bool = False
    significant_digits: float | None = None
    condition_number: float | None = None
    eta_shrinkage: list[float] = field(default_factory=list)
    eps_shrinkage: list[float] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    estimation_time_seconds: float | None = None
    covariance_step_successful: bool = False


@dataclass
class RunSummary:
    """Combined summary of a NONMEM run."""
    run_name: str
    run_dir: str
    problem: str = ""
    data_file: str = ""
    subroutine: str = ""
    estimation_methods: list[str] = field(default_factory=list)
    n_thetas: int = 0
    n_etas: int = 0
    n_eps: int = 0
    ofv: float | None = None
    minimization_successful: bool = False
    covariance_successful: bool = False
    condition_number: float | None = None
    eta_shrinkage: list[float] = field(default_factory=list)
    eps_shrinkage: list[float] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    thetas: dict[str, float] = field(default_factory=dict)
    theta_ses: dict[str, float] = field(default_factory=dict)


@dataclass
class DatasetSummary:
    """Summary of a NONMEM dataset."""
    file_path: str
    n_subjects: int = 0
    n_observations: int = 0
    n_records: int = 0
    n_dose_records: int = 0
    columns: list[str] = field(default_factory=list)
    missing_counts: dict[str, int] = field(default_factory=dict)
    id_column: str = "ID"
    mdv_column: str = "MDV"
    evid_column: str = "EVID"


@dataclass
class TableFileSummary:
    """Summary statistics from NONMEM table output files."""
    file_path: str
    n_rows: int = 0
    columns: list[str] = field(default_factory=list)
    statistics: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class ModelComparison:
    """Comparison between multiple NONMEM runs."""
    models: list[dict] = field(default_factory=list)  # [{name, ofv, n_params, aic, bic}]
    pairwise: list[dict] = field(default_factory=list)  # [{base, test, delta_ofv, df, p_value}]
