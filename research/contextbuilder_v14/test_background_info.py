import unittest
import background_info as bg
from rag_vnext import delivery_codec


def fixture(unit="/root/a", need="n1", sid="s1", title="Method A"):
    source = {"title": "Source", "locator": "p. 2", "text": "source material"}
    root = "/0/packet/context/general_methods/0"
    card = {"id": title, "title": title, "evidence_chunk_ids": ["e1"],
                    "source_ids": [sid], "conditions": ["when applicable"],
                    "limitations": ["limited scope"], "required_inputs": ["dose"],
                    "method_recipe": {"step": 1}}
    prefix = "/0/packet/context"
    nodes = [root, *(root + "/" + k.replace("~", "~0").replace("/", "~1") for k in card),
             prefix + "/applicability_and_examples/evidence/0",
             prefix + "/applicability_and_examples/cited_originals/" + sid]
    row = {"unit_id": unit, "need_id": need, "root": root,
           "card": card,
           "evidence": [{"id": "e1", "text": "exact evidence", "locator": "p. 2", "source_id": sid}],
           "sources": {sid: source}, "applicability": {"scope": "adult"},
           "problems": [], "closure": {"nodes": nodes, "missing": [], "cycles": []},
           "evidence_pointer_hashes": {prefix + "/applicability_and_examples/evidence/0":
                                       bg.sha256({"id": "e1", "text": "exact evidence",
                                                  "locator": "p. 2", "source_id": sid})}}
    return row, {sid: bg.sha256(source)}


def registry(rows):
    hashes = {sid: bg.sha256(source) for row in rows for sid, source in row["sources"].items()}
    return bg.build_registry(rows, hashes), hashes


def read(reg, hashes, unit="/root/a", need="n1", **kw):
    return bg.fulfill_read(reg, {"unit_id": unit, "need_id": need},
                           authorized_unit_ids=[unit], allowed_source_ids=hashes.keys(),
                           allowed_branches=[], current_request_bytes=1200,
                           current_raw_context_chars=2000,
                           current_source_manifest_hashes=hashes, **kw)


class BackgroundInfoTests(unittest.TestCase):
    def test_delivers_exact_complete_unit_without_granting_authority(self):
        row, hashes = fixture(); reg = bg.build_registry([row], hashes)
        out = read(reg, hashes)
        self.assertEqual(out["status"], "DELIVERED")
        for key in ("card", "evidence", "sources", "applicability", "closure"):
            self.assertEqual(out["payload"]["content"][key],
                             {"card": row["card"], "evidence": row["evidence"], "sources": row["sources"],
                              "applicability": row["applicability"], "closure": row["closure"]}[key])
        self.assertFalse(out["payload"]["authority_granted"])
        self.assertEqual(out["payload"]["semantic_status"], "DELIVERED_NOT_SEMANTICALLY_VERIFIED")

    def test_invalid_or_unknown_closure_and_missing_evidence_are_rejected(self):
        row, hashes = fixture(); row["closure"]["missing"] = ["unknown"]
        with self.assertRaises(ValueError): bg.build_registry([row], hashes)
        row, hashes = fixture(); row["problems"] = ["UNKNOWN_DEPENDENCY"]
        with self.assertRaises(ValueError): bg.build_registry([row], hashes)
        row, hashes = fixture(); row["evidence"] = []
        with self.assertRaises(ValueError): bg.build_registry([row], hashes)
        row, hashes = fixture(); row["closure"]["nodes"] = [row["root"]]
        with self.assertRaises(ValueError): bg.build_registry([row], hashes)

    def test_duplicate_evidence_pointer_cannot_replace_required_pointer(self):
        row, _ = fixture()
        row["card"]["evidence_chunk_ids"] = ["e1", "e2"]
        second = {"id": "e2", "text": "second evidence", "locator": "p. 3", "source_id": "s1"}
        row["evidence"].append(second)
        evidence0 = "/0/packet/context/applicability_and_examples/evidence/0"
        evidence1 = "/0/packet/context/applicability_and_examples/evidence/1"
        row["closure"]["nodes"] = [n for n in row["closure"]["nodes"] if n != evidence0]
        row["closure"]["nodes"].extend([evidence0, evidence0])
        row["evidence_pointer_hashes"][evidence1] = bg.sha256(second)
        self.assertNotIn(evidence1, row["closure"]["nodes"])
        hashes = {"s1": bg.sha256(row["sources"]["s1"])}
        with self.assertRaises(ValueError):
            bg.build_registry([row], hashes)

    def test_source_mismatch_and_stale_manifest_are_rejected(self):
        row, hashes = fixture(); reg = bg.build_registry([row], hashes)
        self.assertEqual(read(reg, dict(hashes, s1="0" * 64))["reason"], "STALE_SOURCE_BINDING")
        with self.assertRaises(ValueError): bg.build_registry([row], {"s1": "0" * 64})

    def test_scope_path_like_unknown_wrong_need_and_source_are_restricted(self):
        row, hashes = fixture(); reg = bg.build_registry([row], hashes)
        out = bg.fulfill_read(reg, {"unit_id": "../../secret", "need_id": "n1"},
                              authorized_unit_ids=["../../secret"], allowed_source_ids=["s1"],
                              allowed_branches=[], current_request_bytes=1,
                              current_raw_context_chars=1, current_source_manifest_hashes=hashes)
        self.assertEqual(out["reason"], "UNKNOWN_UNIT")
        self.assertEqual(read(reg, hashes, need="other")["reason"], "NEED_SCOPE_MISMATCH")
        self.assertEqual(bg.fulfill_read(reg, {"unit_id": "/root/a", "need_id": "n1"},
                         authorized_unit_ids=["/root/a"], allowed_source_ids=[], allowed_branches=[],
                         current_request_bytes=1, current_raw_context_chars=1,
                         current_source_manifest_hashes=hashes)["reason"], "SOURCE_OUTSIDE_AUTHORIZED_SCOPE")
        row["card"]["required_branches"] = ["branch-a"]
        row["closure"]["nodes"].append(row["root"] + "/required_branches")
        reg = bg.build_registry([row], hashes)
        self.assertEqual(bg.fulfill_read(reg, {"unit_id": "/root/a", "need_id": "n1"},
                         authorized_unit_ids=["/root/a"], allowed_source_ids=["s1"], allowed_branches=[],
                         current_request_bytes=1, current_raw_context_chars=1,
                         current_source_manifest_hashes=hashes)["reason"], "BRANCH_OUTSIDE_AUTHORIZED_SCOPE")

    def test_budget_types_limits_duplicate_reads_and_prior_state_are_checked(self):
        row, hashes = fixture()
        for limits in ({"max_reads": -1}, {"max_cumulative_bytes": -1}):
            with self.assertRaises(ValueError): bg.build_registry([row], hashes, **limits)
        reg = bg.build_registry([row], hashes, max_reads=1)
        first = read(reg, hashes)
        self.assertEqual(read(reg, hashes, prior_state=first["state"])["reason"], "DUPLICATE_READ")
        for state in ({"read_count": -1, "cumulative_bytes": 0, "read_ids": []},
                      {"read_count": 1, "cumulative_bytes": 0, "read_ids": []},
                      {"read_count": 0, "cumulative_bytes": -1, "read_ids": []}):
            self.assertEqual(read(reg, hashes, prior_state=state)["reason"], "INVALID_SESSION_STATE")
        no_reads = bg.build_registry([row], hashes, max_reads=0)
        self.assertEqual(read(no_reads, hashes)["reason"], "READ_COUNT_BUDGET_EXCEEDED")

    def test_utf8_request_bytes_raw_chars_and_cumulative_budget(self):
        row, hashes = fixture(); reg = bg.build_registry([row], hashes, max_cumulative_bytes=1)
        self.assertEqual(read(reg, hashes)["reason"], "CUMULATIVE_BYTE_BUDGET_EXCEEDED")
        common = dict(authorized_unit_ids=["/root/a"], allowed_source_ids=["s1"], allowed_branches=[],
                      current_source_manifest_hashes=hashes)
        self.assertEqual(bg.fulfill_read(reg, {"unit_id": "/root/a"}, current_request_bytes=-1,
                         current_raw_context_chars=1, **common)["reason"], "INVALID_CURRENT_REQUEST_SIZING")
        self.assertEqual(bg.fulfill_read(reg, {"unit_id": "/root/a"}, current_request_bytes=60001,
                         current_raw_context_chars=1, **common)["reason"], "EXISTING_REQUEST_LIMIT_EXCEEDED")
        self.assertEqual(bg.fulfill_read(reg, {"unit_id": "/root/a"}, current_request_bytes=1,
                         current_raw_context_chars=64001, **common)["reason"], "RAW_CONTEXT_LIMIT_EXCEEDED")

    def test_index_is_lightweight_scoped_and_integrity_checked(self):
        row, hashes = fixture(); reg = bg.build_registry([row], hashes)
        args = dict(allowed_source_ids=["s1"], allowed_branches=[])
        idx = bg.lightweight_index(reg, ["/root/a"], **args)
        self.assertEqual(idx["units"][0]["delivery"], "AVAILABLE_NOT_READ")
        self.assertNotIn("evidence", idx["units"][0])
        self.assertFalse(idx["authority_granted"])
        self.assertEqual(len(bg.lightweight_index(reg, ["/root/a", "outside"], **args)["units"]), 1)
        reg["units"]["/root/a"]["content"]["card"]["conditions"].append("tampered")
        with self.assertRaises(ValueError): bg.lightweight_index(reg, ["/root/a"], **args)
        reg, hashes = registry([row])
        reg["units"]["/root/a"]["content"]["sources"]["s1"]["text"] = "tampered"
        with self.assertRaises(ValueError): read(reg, hashes)

    def test_required_inline_evidence_is_not_evicted(self):
        row, hashes = fixture(); reg = bg.build_registry([row], hashes)
        common = dict(authorized_unit_ids=["/root/a"], allowed_source_ids=["s1"], allowed_branches=[],
                      current_source_manifest_hashes=hashes, current_context={"inline": {"id": "required-1"}})
        def evict(context, unit):
            return {"request": {"support": {"background": unit}}, "raw_context": {"background": unit}}
        with self.assertRaises(ValueError):
            bg.fulfill_read_from_context(reg, {"unit_id": "/root/a", "need_id": "n1"},
                                         append_whole_unit=evict, **common)

    def test_real_request_helper_measures_utf8_and_complete_candidate(self):
        row, hashes = fixture(); reg = bg.build_registry([row], hashes)
        common = dict(authorized_unit_ids=["/root/a"], allowed_source_ids=["s1"], allowed_branches=[],
                      current_source_manifest_hashes=hashes, current_context={"inline": {"id": "required-1"}})
        def append(context, unit):
            self.assertIn("conditions", unit["card"])
            raw = {"inline": context["inline"], "background": [unit]}
            projected = delivery_codec.project(raw)
            request = {"messages": [{"content": __import__("json").dumps(
                {"context_support": projected}, ensure_ascii=False)}]}
            return {"request": request, "raw_context": raw}
        out = bg.fulfill_read_from_context(reg, {"unit_id": "/root/a", "need_id": "n1"},
                                          append_whole_unit=append, **common)
        self.assertEqual(out["status"], "DELIVERED")
        self.assertEqual(out["prospective_request"], append(common["current_context"],
                                                            reg["units"]["/root/a"]["content"])["request"])
        self.assertEqual(out["prospective_raw_context"]["inline"], common["current_context"]["inline"])
        self.assertIn(reg["units"]["/root/a"]["content"], out["prospective_raw_context"]["background"])

    def test_model_visible_messages_required_not_audit_metadata(self):
        row, hashes = fixture(); reg = bg.build_registry([row], hashes)
        common = dict(authorized_unit_ids=["/root/a"], allowed_source_ids=["s1"], allowed_branches=[],
                      current_source_manifest_hashes=hashes, current_context={"inline": {"id": "keep"}})
        def append(context, unit):
            raw = {"inline": context["inline"], "background": [unit]}
            return {"raw_context": raw,
                    "request": {"messages": [{"role": "user", "content": "no evidence"}], "audit": raw}}
        with self.assertRaisesRegex(ValueError, "Model-visible"):
            bg.fulfill_read_from_context(reg, {"unit_id": "/root/a", "need_id": "n1"},
                                         append_whole_unit=append, **common)

    def test_scope_is_checked_before_append_callback(self):
        row, hashes = fixture(); reg = bg.build_registry([row], hashes)
        called = []
        def append(context, unit):
            called.append(True)
            raise AssertionError("must not append out-of-scope unit")
        out = bg.fulfill_read_from_context(
            reg, {"unit_id": "/root/a", "need_id": "n1"},
            authorized_unit_ids=["/root/a"], allowed_source_ids=[], allowed_branches=[],
            current_source_manifest_hashes=hashes, current_context={"inline": {"id": "keep"}},
            append_whole_unit=append)
        self.assertEqual(out["reason"], "SOURCE_OUTSIDE_AUTHORIZED_SCOPE")
        self.assertEqual(called, [])

    def test_independent_units_remain_separately_scoped(self):
        a, _ = fixture("/root/a", "n1", "s1", "A")
        b, _ = fixture("/root/b", "n2", "s2", "B")
        reg, hashes = registry([a, b])
        index = bg.lightweight_index(reg, ["/root/a"], allowed_source_ids=["s1", "s2"], allowed_branches=[])
        self.assertEqual([x["unit_id"] for x in index["units"]], ["/root/a"])
        self.assertEqual(read(reg, hashes, "/root/b", "n2")["status"], "DELIVERED")
        self.assertEqual(read(reg, hashes, "/root/b", "n1")["reason"], "NEED_SCOPE_MISMATCH")


if __name__ == "__main__":
    unittest.main()
