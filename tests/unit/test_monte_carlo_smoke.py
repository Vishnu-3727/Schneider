"""Smoke test for scripts/validation/monte_carlo_verify.py (SIMULATED data only).

Tiny N=3 run of the no_effect and production_shift scenarios, no database.
Must run in < 60 s.
"""

from scripts.validation.monte_carlo_verify import main

SUMMARY_KEYS = {"scenario", "n", "n_paired", "outcome_counts", "result_class_counts", "verified",
                "false_claim_rate", "false_claim_rate_paired", "detection_rate",
                "coverage", "coverage_paired", "n_comparable", "n_comparable_paired",
                "mean_true_kwh", "mean_reported_kwh", "mean_abs_error_kwh"}


def test_monte_carlo_smoke(tmp_path):
    res = main(n=3, seed0=1, scenarios=["no_effect", "production_shift"],
               out_csv=tmp_path / "mc.csv", out_md=tmp_path / "mc.md")
    for k in ("n", "seed0", "scenarios", "rows", "pre_equal_all", "runtime_s"):
        assert k in res
    assert res["n"] == 3 and res["pre_equal_all"] is True
    assert set(res["scenarios"]) == {"no_effect", "production_shift"}
    for name, summ in res["scenarios"].items():
        assert SUMMARY_KEYS <= set(summ)
        assert summ["n"] == 3 and len(res["rows"][name]) == 3
    shifted = res["rows"]["production_shift"]
    assert all(r["outcome"] != "VERIFIED" for r in shifted), shifted
    no_effect = res["rows"]["no_effect"]
    assert all(r["true_saving_kwh"] == 0.0 for r in no_effect), no_effect
    # Rebound-free scenarios stay paired: identical heat starts in both runs.
    for name in ("no_effect", "production_shift"):
        assert all(r["paired"] is True for r in res["rows"][name]), res["rows"][name]
    assert (tmp_path / "mc.csv").exists() and (tmp_path / "mc.md").exists()
