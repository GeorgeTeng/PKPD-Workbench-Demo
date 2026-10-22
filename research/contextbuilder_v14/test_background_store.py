import json
import tempfile
import unittest
from pathlib import Path

import background_info
import background_store

TEST_TMP = Path(__file__).resolve().parent / "test_tmp"
TEST_TMP.mkdir(exist_ok=True)


def valid_registry():
    source = {"text": "source", "locator": "p. 1"}
    card = {"id": "m", "evidence_chunk_ids": ["e"], "source_ids": ["s"],
            "conditions": ["when"], "limitations": ["limit"], "required_inputs": ["x"]}
    root = "/0/packet/context/general_methods/0"
    prefix = "/0/packet/context"
    nodes = [root, *(root + "/" + key for key in card),
             prefix + "/applicability_and_examples/evidence/0",
             prefix + "/applicability_and_examples/cited_originals/s"]
    row = {"unit_id": "u", "need_id": "need", "root": root, "card": card,
           "evidence": [{"id": "e", "text": "exact", "locator": "p. 1", "source_id": "s"}],
           "sources": {"s": source}, "applicability": {}, "problems": [],
           "closure": {"nodes": nodes, "missing": [], "cycles": []},
           "evidence_pointer_hashes": {prefix + "/applicability_and_examples/evidence/0":
                                       background_info.sha256({"id": "e", "text": "exact",
                                                               "locator": "p. 1", "source_id": "s"})}}
    return background_info.build_registry([row], {"s": background_info.sha256(source)})


class BackgroundStoreTests(unittest.TestCase):
    def test_save_load_is_hash_pinned_and_append_only(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as tmp:
            root = Path(tmp) / "case"; root.mkdir()
            registry = valid_registry()
            ref = background_store.save_registry(root, registry)
            self.assertEqual(ref["relative_path"], "background_info.json")
            self.assertEqual(background_store.load_registry(root, ref["sha256"]), registry)
            with self.assertRaises(FileExistsError): background_store.save_registry(root, registry)
            path = root / "background_info.json"
            value = json.loads(path.read_text(encoding="utf-8")); value["units"]["u"]["need_id"] = "changed"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                background_store.load_registry(root, ref["sha256"])

    def test_requires_existing_root_and_expected_hash(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as tmp:
            root = Path(tmp) / "case"; root.mkdir()
            ref = background_store.save_registry(root, valid_registry())
            for bad in (None, "0" * 63):
                with self.assertRaises(ValueError): background_store.load_registry(root, bad)
            with self.assertRaises(FileNotFoundError): background_store.load_registry(Path(tmp), ref["sha256"])

    def test_symlinked_store_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as tmp:
            root = Path(tmp) / "case"; root.mkdir()
            outside = Path(tmp) / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            try:
                (root / "background_info.json").symlink_to(outside)
            except OSError as exc:
                self.skipTest("This Windows account cannot create symlinks: " + str(exc))
            with self.assertRaisesRegex(ValueError, "symlink"):
                background_store.load_registry(root, background_info.sha256({}))


if __name__ == "__main__":
    unittest.main()
