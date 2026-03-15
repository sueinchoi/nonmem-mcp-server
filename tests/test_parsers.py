"""Tests for NONMEM parsers."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

FIXTURES = Path(__file__).parent / "fixtures"


def test_ext_parser():
    from nonmem_mcp.parsers.ext_parser import parse_ext_file, format_ext_result

    results = parse_ext_file(FIXTURES / "sample.ext")
    assert len(results) == 1

    r = results[0]
    assert r.table_number == 1
    assert "THETA1" in r.thetas
    assert abs(r.thetas["THETA1"] - 4.985) < 0.001
    assert r.ofv is not None
    assert abs(r.ofv - 4228.91234) < 0.01
    assert len(r.iterations) == 5  # iterations 0, 5, 10, 15, 20

    # Check SEs parsed
    assert "THETA1" in r.theta_ses
    assert abs(r.theta_ses["THETA1"] - 0.215) < 0.001

    # Check fixed flags
    assert r.fixed_flags.get("SIGMA(1,1)") is True
    assert r.fixed_flags.get("THETA1") is False

    # Format test
    text = format_ext_result(r)
    assert "OFV" in text
    assert "THETA1" in text
    print("  ext_parser: OK")


def test_lst_parser():
    from nonmem_mcp.parsers.lst_parser import parse_lst_file, format_lst_result

    result = parse_lst_file(FIXTURES / "sample.lst")

    assert result.minimization_successful is True
    assert result.termination_status == "MINIMIZATION SUCCESSFUL"
    assert result.covariance_step_successful is True
    assert result.significant_digits == 3.5
    assert result.estimation_time_seconds == 12.5
    assert len(result.eta_shrinkage) == 3
    assert abs(result.eta_shrinkage[0] - 8.23) < 0.1
    assert len(result.eps_shrinkage) == 1

    # Condition number from eigenvalues
    assert result.condition_number is not None

    text = format_lst_result(result)
    assert "OK" in text
    print("  lst_parser: OK")


def test_control_stream_parser():
    from nonmem_mcp.parsers.control_stream_parser import (
        parse_control_stream,
        format_control_stream,
    )

    cs = parse_control_stream(FIXTURES / "sample.ctl")

    assert "2-Compartment" in cs.problem
    assert cs.data_file == "../data/pk_data.csv"
    assert "ADVAN4" in cs.subroutine
    assert "TRANS4" in cs.subroutine

    # Input columns
    assert "ID" in cs.input_columns
    assert "TIME" in cs.input_columns
    assert "WT" in cs.input_columns
    assert len(cs.input_columns) == 10

    # THETAs
    assert len(cs.thetas) == 7
    assert cs.thetas[0].name == "CL (L/h)"
    assert cs.thetas[0].initial == 5.0
    assert cs.thetas[0].lower_bound == 0.0
    assert cs.thetas[0].upper_bound == 50.0

    # OMEGAs: BLOCK(2) + diagonal(1) = 3 + 1 = 4 elements
    assert len(cs.omegas) >= 3  # At least the BLOCK(2) elements
    # BLOCK(2): (1,1), (2,1), (2,2) + diagonal: (3,3)
    diag_omegas = [o for o in cs.omegas if o.row == o.col]
    assert len(diag_omegas) >= 3  # 3 diagonal elements

    # SIGMAs
    assert len(cs.sigmas) == 1
    assert cs.sigmas[0].fixed is True

    # Estimation
    assert len(cs.estimation_methods) == 1
    assert cs.estimation_methods[0].method == "FOCE"
    assert cs.estimation_methods[0].interaction is True

    text = format_control_stream(cs)
    assert "ADVAN4" in text
    print("  control_stream_parser: OK")


def test_table_parser():
    """Test table parser with a small inline fixture."""
    from nonmem_mcp.parsers.table_parser import parse_table_file

    # Create a temp table file
    table_content = """TABLE NO.  1
 ID          TIME        DV          PRED        IPRED       CWRES       ETA1
  1.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00 -1.2300E-01
  1.0000E+00  1.0000E+00  5.2300E+00  4.8500E+00  5.1200E+00  3.5000E-01 -1.2300E-01
  1.0000E+00  2.0000E+00  8.1500E+00  7.9200E+00  8.0800E+00 -2.1000E-01 -1.2300E-01
  2.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00  0.0000E+00  2.5600E-01
  2.0000E+00  1.0000E+00  6.1200E+00  5.5200E+00  5.9800E+00  1.2000E+00  2.5600E-01
  2.0000E+00  2.0000E+00  9.8500E+00  8.9500E+00  9.5200E+00  8.5000E-01  2.5600E-01
"""
    tmp_path = FIXTURES / "tmp_sdtab.tab"
    tmp_path.write_text(table_content)

    try:
        summary = parse_table_file(tmp_path)
        assert summary.n_rows == 6
        assert "CWRES" in summary.columns
        assert "CWRES" in summary.statistics
        assert "ETA1" in summary.statistics
        assert summary.statistics["CWRES"]["n"] == 6
        print("  table_parser: OK")
    finally:
        tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    print("Running parser tests...")
    test_ext_parser()
    test_lst_parser()
    test_control_stream_parser()
    test_table_parser()
    print("\nAll tests passed!")
