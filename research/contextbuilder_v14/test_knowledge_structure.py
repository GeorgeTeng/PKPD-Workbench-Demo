import copy
import unittest

from knowledge_structure import normalize_card, validate_normalized


class KnowledgeStructureTests(unittest.TestCase):
    def setUp(self):
        self.card = {
            "id": "source_A:K01",
            "title": "Example title",
            "topics": ["animal_pk"],
            "claim": "A bounded claim.",
            "conditions": ["Condition A"],
            "required_inputs": ["Input A"],
            "limitations": ["Limitation A"],
            "downstream_use": "Review only.",
            "evidence_chunk_ids": ["SRC:001"],
            "source_ids": ["SRC"],
            "claim_support": [{"claim_id": "C1", "evidence_chunk_ids": ["SRC:001"]}],
            "required_branches": ["translation"],
            "method_keywords": ["clearance", "animal PK"],
            "unrecognized_field": {"must": "survive"},
        }

    def test_normalize_preserves_entire_card_and_hash_binding(self):
        normalized = normalize_card(self.card)
        self.assertEqual(normalized["canonical_card"], self.card)
        self.assertTrue(validate_normalized(normalized, self.card))
        self.assertEqual(normalized["source_binding"]["card_sha256"], normalized["card_sha256"])

    def test_views_are_exact_source_bound_purpose_views(self):
        normalized = normalize_card(self.card)
        paths = {v["source_pointer"] for v in normalized["purpose_views"]}
        self.assertIn("/title", paths)
        self.assertIn("/claim", paths)
        self.assertIn("/method_keywords/0", paths)
        for view in normalized["purpose_views"]:
            self.assertTrue(view["source_sha256"])
            self.assertEqual(view["status"], "EXACT_BOUND_RETRIEVAL_VIEW_NOT_APPLICABILITY_APPROVAL")
            self.assertIn("/conditions", view["constraint_pointers"])
            self.assertIn("/limitations", view["constraint_pointers"])

    def test_claim_evidence_links_are_declared_and_prose_semantics_unknown(self):
        normalized = normalize_card(self.card)
        self.assertEqual(normalized["declared_claim_support"][0]["claim_pointer"], "/claim_support/0")
        self.assertEqual(normalized["declared_claim_support"][0]["evidence_chunk_ids"], ["SRC:001"])
        self.assertEqual(normalized["semantic_dependency_status"], "UNKNOWN")
        self.assertEqual(normalized["evidence_units"][0]["kind"], "FULL_CARD_FALLBACK")
        self.assertEqual(normalized["evidence_units"][0]["source_pointers"], [""])

    def test_validation_rejects_changed_card_or_normalized_pointer_hash(self):
        normalized = normalize_card(self.card)
        changed = copy.deepcopy(self.card)
        changed["limitations"].append("New limitation")
        self.assertFalse(validate_normalized(normalized, changed))
        tampered = copy.deepcopy(normalized)
        tampered["purpose_views"][0]["source_sha256"] = "0" * 64
        self.assertFalse(validate_normalized(tampered, self.card))

    def test_card_is_not_mutated(self):
        original = copy.deepcopy(self.card)
        normalize_card(self.card)
        self.assertEqual(self.card, original)


if __name__ == "__main__":
    unittest.main()
