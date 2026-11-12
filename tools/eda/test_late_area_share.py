"""Distribution rules r1.3, item 24 step 7: the late-area share is a value row, reported only when two phases are visible."""
import math

from research_pipeline import eda_distribution as dist
from research_pipeline import eda_absorption as ab


def test_iv_inventory_keeps_sparse_profiles_before_phase_eligibility():
    # No fitted result or expected report string is used to construct this oracle.
    profile = dict(dataset_id="local", sid="animal", route_class="IV", matrix_class="SERUM", occasion="REPEAT",
                   points=[dict(t=0, status="QUANTIFIED"), dict(t=4, status="BLQ"),
                           dict(t=4, status="BLQ"), dict(t=8, status="MISSING")])
    for source in ("local", "renamed"):
        series = [dict(profile, dataset_id=source), dict(profile, matrix_class="TISSUE"), dict(profile, route_class="EV")]
        observed, = dist.systemic_iv_coverage(series)
        assert (observed["dataset_id"], observed["occasion"], observed["reported_times"]) == (source, "REPEAT", 2)
    assert dist.systemic_iv_coverage([dict(profile, route_class="EV")]) == []


def _profile():
    times = [0.25, 0.5, 1, 2, 4, 6, 8, 12]
    return [{"t": t, "c": 10 * math.exp(-1.5 * t) + 2 * math.exp(-0.1 * t)} for t in times]


def test_share_uses_the_same_points_and_the_d06_rule():
    q = _profile()
    share = dist.late_area_share(q, "TWO_OR_MORE", 2)
    ts, cs = [p["t"] for p in q], [p["c"] for p in q]
    expected = 100 * ab.auc(ts[3:], cs[3:]) / ab.auc(ts, cs)
    assert math.isclose(share["percent"], expected)
    assert share["window_h"] == [0.25, 12] and share["cut_h"] == 2 and share["n_points"] == 8
    assert "no extrapolation" in share["method"]
    assert dist.late_area_share(q, "TWO_OR_MORE_TENTATIVE", 2)["percent"] == share["percent"]


def test_share_is_not_reported_without_two_phases_or_a_cut():
    q = _profile()
    assert dist.late_area_share(q, "ONE_APPARENT", 0.25) is None
    assert dist.late_area_share(q, "NOT_ASSESSABLE", 2) is None
    assert dist.late_area_share(q, "TWO_OR_MORE", "NOT_DETERMINED") is None
    assert dist.late_area_share(q, "TWO_OR_MORE", 12) is None  # one point after the cut has no area


def test_rules_version_comes_from_the_manifest():
    import eda_common
    assert dist.RULES_VERSION == eda_common.rules_entry("distribution")["version"] == "r1.3"
    assert dist.RULES["sha256"] and not eda_common.check_rules()
    assert any("late-area share" in row[2] for row in dist.READING_MAP if row[0] == "DIS-1b")
