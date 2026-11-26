"""M3 (2026-11-24): the rule revisions absorption r4.4, distribution r1.6, elimination r1.2 and the shared rules s1.0.

The tests read the machine YAML and check file integrity, the one version source, constants, labels and fields, the order of the
formal decision and representative results against the code. Synthetic data only."""
import json
import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import conftest  # noqa: F401,E402
from research_pipeline import eda_absorption as ab  # noqa: E402
from research_pipeline import eda_distribution as dist  # noqa: E402
from research_pipeline import eda_elimination as el  # noqa: E402
import eda_common as COMMON  # noqa: E402

RULES = COMMON.RULES_DIR
MANIFEST = COMMON.rules_manifest()
SECTIONS = MANIFEST["sections"]
MODULES = {"absorption": ab, "distribution": dist, "elimination": el}
LOCKED = {"absorption": ("r4.3", "EDA_absorption_rules_r4.3_rules_only_20261105.md",
                         "d63ecc86b79f2a0b7ba3677bd83f5a8a0f2a6166d5678d1cc6633e82f4ed817e"),
          "distribution": ("r1.3", "EDA_distribution_rules_r1.3_rules_only_20261110.md",
                           "5cb7ae001125093caf8b4fe6fd0fccfe6b33049675b825de9f6be6dd5d4ab106"),
          "elimination": ("r1.1", "EDA_elimination_metabolism_rules_r1.1_rules_only_FINAL.md",
                          "3b5fa0a60c29da8b336f37bf21229c674471cb09a27825aa5243e146bf926714")}
CODE_TOKEN = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")


def _yaml(section):
    return yaml.safe_load((RULES / SECTIONS[section]["yaml"]).read_text(encoding="utf-8"))


SHARED = _yaml("shared")


# ---------------------------------------------------------------- file integrity and history

def test_manifest_binds_the_new_revisions_and_the_rules_folder_matches():
    assert COMMON.check_rules() == []
    assert {s: SECTIONS[s]["version"] for s in SECTIONS} == {"absorption": "r4.4", "distribution": "r1.6", "elimination": "r1.2", "shared": "s1.0"}
    for s in MODULES:
        assert SECTIONS[s]["shared"] == "s1.0" and SECTIONS[s]["supersedes"] == LOCKED[s][0]


def test_superseded_revisions_have_pinned_archives_and_original_hashes():
    hist = {(h["section"], h["version"]): h for h in MANIFEST["history"]}
    for section, (version, filename, digest) in LOCKED.items():
        entry = hist[(section, version)]
        assert entry["sha256"] == digest
        assert entry["archive"]["path"] == f"tools/eda/rules/{filename}"
    r15 = hist[("distribution", "r1.5")]
    assert r15["archive"]["verbatim_file"] == "EDA_distribution_rules_r1.5_rules_only_20261121.md"
    for entry in MANIFEST["history"]:
        archive = entry["archive"]
        assert entry["status"] == "superseded" and entry["file"] is None
        assert re.fullmatch(r"[0-9a-f]{40}", archive["commit"])
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
        assert not (RULES / Path(archive["path"]).name).exists()


def test_consolidated_editions_change_wording_only():
    """2026-11-25: each current Markdown is one consolidated text; version, YAML and output_version are those of 2026-11-24."""
    hist = {(h["section"], h["version"], h.get("kind")): h for h in MANIFEST["history"]}
    for section, entry in SECTIONS.items():
        text = (RULES / entry["file"]).read_text(encoding="utf-8")
        assert f"Version: {entry['version']} · Edition: consolidated, 2026-11-25 (wording only; no rule changed)" in text
        assert "<!-- verbatim begin" not in text and "## Part 2" not in text and "## Part 3" not in text
        old = hist[(section, entry["version"], "layered_edition")]
        assert old["archive"]["path"] == f"tools/eda/rules/{entry['layered_file']}"


def test_current_markdown_carries_the_revised_exclusion_and_shared_decisions():
    absorption = (RULES / SECTIONS["absorption"]["file"]).read_text(encoding="utf-8")
    assert "#### A0.3 Exclusion principle and evidence labels" in absorption
    assert "LOO_NOT_ASSESSABLE" in absorption and "replaces r4.3 A0.3" not in absorption
    shared = (RULES / SECTIONS["shared"]["file"]).read_text(encoding="utf-8")
    assert re.findall(r"^## (S\d+)\. ", shared, re.M) == [f"S{i}" for i in range(1, 14)]


def test_check_rules_verifies_current_yaml_and_legacy_local_history(tmp_path):
    folder = tmp_path / "rules"
    shutil.copytree(RULES, folder)
    assert COMMON.check_rules(folder) == []
    yml = folder / SECTIONS["distribution"]["yaml"]
    yml.chmod(0o600)
    yml.write_bytes(yml.read_bytes() + b"\n# edited\n")
    path = folder / "rules_manifest.json"
    manifest = json.loads(path.read_bytes())
    legacy = next(entry for entry in manifest["history"] if (entry["section"], entry["version"]) == ("elimination", "r1.1"))
    legacy["file"] = LOCKED["elimination"][1]
    path.chmod(0o600)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    (folder / legacy["file"]).write_bytes(b"changed copy of an older rule")
    problems = COMMON.check_rules(folder)
    assert any("distribution machine YAML" in p for p in problems)
    assert any("elimination r1.1 (superseded)" in p for p in problems)


def test_check_rules_needs_the_current_shared_entry(tmp_path):
    folder = tmp_path / "rules"
    shutil.copytree(RULES, folder)
    m = json.loads((folder / "rules_manifest.json").read_text(encoding="utf-8"))
    m["sections"]["absorption"]["shared"] = "s0.9"
    (folder / "rules_manifest.json").chmod(0o600)
    (folder / "rules_manifest.json").write_text(json.dumps(m), encoding="utf-8")
    assert any("absorption: shared rules s0.9" in p for p in COMMON.check_rules(folder))


# ---------------------------------------------------------------- one version source (L7)

@pytest.mark.parametrize("section", list(MODULES))
def test_one_version_source(section):
    mod, entry, y = MODULES[section], SECTIONS[section], _yaml(section)
    assert mod.VERSION == entry["output_version"]
    assert mod.RULES_VERSION == entry["version"] == y["meta"]["version"]
    assert mod.RULES["output_version"] == mod.VERSION and mod.RULES["sha256"] == entry["sha256"]
    assert y["meta"]["supersedes"] == entry["supersedes"] and y["meta"]["shared_rules"] == SHARED["meta"]["version"]
    assert SHARED["meta"]["applies_to"][section] == entry["version"]
    assert y["shared_rules"]["file"] == SECTIONS["shared"]["yaml"]


def test_absorption_result_carries_the_manifest_version(tmp_path, monkeypatch):
    from test_rule_decisions_20261124 import _group_table, _oral
    t = [0.25, 0.5, 1, 2, 4, 6, 8, 12, 16, 24]
    (tmp_path / "source_tables.json").write_text(json.dumps([_group_table("PO_10", t, _oral(t, 2.0, 0.3, 10), 10)]), encoding="utf8")
    monkeypatch.setenv("ABSORPTION_STABILITY", "0")
    monkeypatch.setattr(ab, "render_all", lambda out: None)
    res = ab.build(tmp_path)
    assert res["version"] == res["guide"]["version"] == SECTIONS["absorption"]["output_version"]
    assert res["rules"]["version"] == "r4.4" and res["rules"]["yaml_sha256"] == SECTIONS["absorption"]["yaml_sha256"]


# ---------------------------------------------------------------- constants

def test_absorption_constants_match_the_yaml():
    c = _yaml("absorption")["const"]
    assert c["tol_rel"] == ab.TOL and c["span_min_half_lives"] == ab.SPAN_MIN and c["adj_r2_tie"] == ab.ADJ_R2_TIE and c["adj_r2_min"] == ab.ADJ_R2_MIN
    assert tuple(c["half_life_ratio_cuts"]) == ab.HL_CUTS == tuple(SHARED["flip_flop"]["cuts"])
    assert c["tail_fraction_max"] == ab.TAIL_FLAG and c["t3p_time_dev"] == ab.T3P_TIME_DEV
    assert (c["share_min"], c["trend_ratio"], c["tail_alpha"]) == (ab.SHARE_MIN, ab.TREND_RATIO, ab.TAIL_ALPHA)
    assert c["cmax_screen"]["window_share_min"] == ab.CMAX_SCREEN_SHARE_MIN
    assert c["alpha"]["family_two_sided"] == SHARED["family"]["alpha"] == ab.T3P_ALPHA


def test_distribution_constants_match_the_yaml():
    c = _yaml("distribution")["const"]
    assert c["early_mix_h"] == dist.EARLY_MIX_H == SHARED["early_mixing"]["window_h"]
    assert dist.early_mixing(c["early_mix_h"]) and not dist.early_mixing(c["early_mix_h"] + 1e-4)   # bound included
    assert c["min_test_times"] == dist.MIN_TEST_TIMES and c["family_alpha"] == dist.FAMILY_ALPHA == SHARED["family"]["alpha"]
    assert (c["split"]["R"], c["split"]["z"], c["split"]["min_n"], c["split"]["borderline_z"]) == (dist.SPLIT_R, dist.SPLIT_Z, dist.MIN_SPLIT_POINTS, dist.BORDERLINE_Z)
    assert c["sigma_default"]["individual"] == dist.SIGMA_IND and c["sigma_default"]["group_no_sd"] == dist.SIGMA_GROUP_DEFAULT
    assert c["tol_rel"] == dist.TOL and c["lloq_prox"] == dist.LLOQ_PROX
    assert tuple(c["dose_band"]["default"]) == dist.BAND and tuple(c["dose_band"]["digitized"]) == dist.BAND_DIGITIZED


def test_shared_constants_match_the_code():
    p = SHARED["precision"]
    assert tuple(p["assay_cv_match"]) == COMMON.CV_MATCH_KEYS and tuple(p["digitized_reading_bases"]) == COMMON.READING_BASES
    assert p["default_reading_pct"] == COMMON.DEFAULT_READING_PCT and p["noise_tier"] == COMMON.NOISE_TIER_LABEL
    assert set(SHARED["limiting_flags"]) == set(COMMON.LIMITING_FLAGS)
    assert set(SHARED["sensitivity_record"]["moved_when_formal_is_CANNOT_ASSESS"]) == set(COMMON.SENSITIVITY_RECORD_FLAGS)
    assert SHARED["iv_window"]["name"] == COMMON.IV_WINDOW_NAME and SHARED["predose_zero"]["status"] == COMMON.PREDOSE_ZERO
    assert SHARED["question_ids"]["upstream_tests"] == COMMON.UPSTREAM_TESTS
    assert SHARED["rank"]["groups"] == list(ab.RANK_GROUPS) == list(dist.RANK_GROUPS)
    assert p["replicate_factor_examples"]["df_1"] == pytest.approx(ab.t_ppf(1 - 0.025 / 10, 1), abs=1e-3)
    assert p["replicate_factor_examples"]["known_sigma"] == pytest.approx(ab.t_ppf(1 - 0.025 / 10, 1000), abs=1e-3)   # code: df 1000


# ---------------------------------------------------------------- decision order and representative results

def test_decision_order_is_the_shared_table():
    assert [s["id"] for s in SHARED["decision_order"]] == ["premises", "interval_or_test_basis", "full_data", "removal",
                                                           "timing_and_widening", "exclusion"]
    for section in MODULES:
        y = _yaml(section)
        outcome = y["outcome"] if section == "absorption" else (y["tests"]["outcome"] if section == "distribution" else None)
        if outcome is None:
            continue
        steps = [o["step"] for o in outcome]
        assert steps == sorted(steps) and steps[0] == 1 and steps[-1] == 6
        assert outcome[-1]["then"] == "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
        flags = {o.get("flag") for o in outcome if o["step"] == 4}
        assert flags == {"SINGLE_POINT_SUPPORT", "LOO_NOT_ASSESSABLE"}
        assert [o.get("flag") for o in outcome if o["step"] == 5] == ["BORDERLINE"]


def test_removal_step_gives_the_shared_outcomes():
    step = next(s for s in SHARED["decision_order"] if s["id"] == "removal")
    lost = step["contradiction_lost_in_valid_rerun"]
    nope = step["no_removable_unit_or_rerun_not_assessable"]
    ex = "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
    assert ab._removal_outcome(ex, [("a", ex), ("b", ex)], "point")[:2] == (ex, [])
    assert ab._removal_outcome(ex, [("a", ex), ("b", "NOT_EXCLUDED")], "point")[:2] == (lost["label"], [lost["flag"]])
    assert ab._removal_outcome(ex, [("a", None)], "point")[:2] == (nope["label"], [nope["flag"]])
    assert ab._removal_outcome(ex, [], "point")[:2] == (nope["label"], [nope["flag"]])
    label, flags, _ = ab._removal_outcome(ex, [("a", None), ("b", "NOT_EXCLUDED")], "point")
    assert label == "NOT_EXCLUDED" and set(flags) == {lost["flag"], nope["flag"]}      # both recorded
    assert ab._removal_outcome("NOT_EXCLUDED", [], "point")[:2] == ("NOT_EXCLUDED", [])   # only a contradiction is rerun


def test_basis_step_keeps_only_its_own_reason_in_the_formal_record():
    moved = SHARED["sensitivity_record"]["moved_when_formal_is_CANNOT_ASSESS"]
    rec = {"t7_label": "CANNOT_ASSESS", "t7_flags": ["SENSITIVITY_ONLY"] + moved}
    COMMON.separate_sensitivity_flags(rec)
    assert rec["t7_flags"] == ["SENSITIVITY_ONLY"] and rec["t7_sensitivity_flags"] == moved
    assert COMMON.test_flags(rec, "t7") == ["SENSITIVITY_ONLY"] + moved     # the consumer rule reads both keys


@pytest.mark.parametrize("ratio,grade", [(0.79, "STEEPER"), (0.80, "APPROXIMATELY_PARALLEL"), (1.2499, "APPROXIMATELY_PARALLEL"),
                                         (1.25, "MODERATELY_SHALLOWER"), (1.99, "MODERATELY_SHALLOWER"), (2.0, "MARKEDLY_SHALLOWER")])
def test_flip_flop_grades_follow_the_yaml_cuts(ratio, grade):
    ff = SHARED["flip_flop"]
    assert ff["lower_bound_inclusive"] is True
    assert ab.hl_grade(ratio) == grade and ab.FF_READING[grade] == ff["readings"][grade]
    assert set(ff["not_evidence_against_flip_flop"]) == set(ab.FF_NOT_AGAINST)


def test_flip_flop_reading_is_unresolved_only_when_qualified_pairs_disagree():
    def met(th):
        return {"terminal_windows": [{"thalf": x, "start": 4.0, "end": 24.0, "n": 5, "adj_r2": 0.99, "span": 3.0, "qualified": True}
                                     for x in th]}
    one = ab.flip_flop_reading(met([5.0, 5.2]), met([2.0]))
    assert one["flip_flop_reading"] == "ABSORPTION_INFLUENCED_CANDIDATE" and one["n_window_pairs"] == 2
    two = ab.flip_flop_reading(met([2.4, 2.6]), met([2.0]))
    assert two["flip_flop_reading"] == "UNRESOLVED"
    none = ab.flip_flop_reading(met([]), met([2.0]))
    assert none["flip_flop_reading"] == "NOT_ASSESSABLE" and none["missing_side"]


def test_answer_status_codes_and_display_labels():
    rows = {r["code"]: r for r in SHARED["answer_status"]}
    assert {code: label for label, code in ab.ST_CODE.items()} == {c: r["en"] for c, r in rows.items()}
    disp = _yaml("absorption")["labels"]["answer_display"]
    assert disp == {c: r["en"] for c, r in rows.items()}


# ---------------------------------------------------------------- labels and fields

def _module_code(section):
    return Path(MODULES[section].__file__).read_text(encoding="utf-8") + Path(COMMON.__file__).read_text(encoding="utf-8")


ALL_CODE = "".join(_module_code(s) for s in MODULES) + (Path(COMMON.__file__).parent / "modeling_handoff.py").read_text(encoding="utf-8")
# tokens that name keys or mappings rather than codes the module emits
NOT_LABELS = {"absorption": set(), "distribution": {"T6_T7"}, "elimination": {"T5_T9", "T3_T3P"}, "shared": {"TIMING_SENSITIVE"}}


@pytest.mark.parametrize("section", list(MODULES) + ["shared"])
def test_every_code_in_the_yaml_is_emitted_or_listed_as_not_implemented(section):
    text = (RULES / SECTIONS[section]["yaml"]).read_text(encoding="utf-8")
    y = yaml.safe_load(text)
    labels = y.get("labels") or {}
    exempt = set((labels.get("not_implemented") or {}).keys()) | NOT_LABELS[section] | set((labels.get("baseline_status_r43") or {}).keys())
    absent = [t for t in sorted(set(CODE_TOKEN.findall(text))) if t not in exempt and t not in ALL_CODE]
    assert absent == []
    for t in (labels.get("not_implemented") or {}):
        assert t not in _module_code(section), f"{t} is emitted now; move it back to the labels"


def test_retired_labels_left_the_current_yaml():
    elim = (RULES / SECTIONS["elimination"]["yaml"]).read_text(encoding="utf-8")
    assert "RECOVERY_REFERENCE_HUMAN" not in elim
    dist_y = (RULES / SECTIONS["distribution"]["yaml"]).read_text(encoding="utf-8")
    assert "vc_flags" not in dist_y and "SIMILAR" not in dist_y
    labels = _yaml("absorption")["labels"]
    assert "no_same_study_iv" not in labels["flip_flop_reading"]
    assert set(labels["f_status"]) == {"WINDOW_BASED_ESTIMATE", "OBSERVED_WINDOW_RATIO", "SOURCE_REPORTED", "NOT_ESTIMABLE"}


def test_question_maps_match_the_code():
    for section in ("distribution", "elimination"):
        rows = _yaml(section)["questions"]["rows"]
        for engine_q, spec in rows.items():
            f = COMMON.guide_fields(section, engine_q)
            assert f["qid"] == spec["qid"]
            assert f["guide_q"] == ([spec["guide_q"]] if spec.get("guide_q") else [])
            assert f["also_guide_q"] == spec.get("also_guide_q", [])
            if not spec.get("guide_q"):
                assert f["display_ref"] == spec["display_ref"]
        order = sorted(rows, key=lambda q: COMMON.guide_order(section, q))
        assert order == _yaml(section)["questions"]["page_order"]
    assert set(SHARED["question_ids"]["row_fields"]) <= set(COMMON.guide_fields("absorption", 1)) | {"legacy_q"}


def test_absorption_r43_field_map_names_real_keys():
    # the per-curve calculations moved to eda_common.py on 2026-11-26, so the keys may be written in either file
    src = Path(ab.__file__).read_text(encoding="utf-8") + Path(COMMON.__file__).read_text(encoding="utf-8")
    fmap = _yaml("absorption")["fields_r43"]
    assert sorted(fmap) == list(range(16, 24))
    for item, names in fmap.items():
        for name, key in names.items():
            if key == "-":
                continue
            for k in key.split(", "):
                assert re.search(r"[\"']%s[\"']" % re.escape(k), src), (item, name, k)


def test_distribution_item25_fields_are_written():
    import test_distribution_r15 as T
    s = T._series([0.1, 0.25, 0.5, 1, 2], [5.0, 20.0, 12.0, 6.0, 3.0], noise={})
    s.update(species="dog", matrix_class="PLASMA", dose=10.0)
    r = dist.item25_bound(s, None, {})
    wanted = set(_yaml("distribution")["fields"]["item25"]) - {"data_check_reason", "reference_volumes"}
    assert wanted <= set(r) | {"reference_volumes"}
    assert r["modeling_constraint"]["status"] in _yaml("distribution")["labels"]["vc_constraint_status"]
    assert set(r["caveats"]) <= set(_yaml("distribution")["labels"]["vc_caveats"])
