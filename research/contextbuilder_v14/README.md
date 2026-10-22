# ContextBuilder revision14 — inactive research reference

Standalone deterministic components from the locally verified revision14 candidate: demand/closure assembly, whole-card allocation, conservative selection, reversible transport encoding and hash-bound background storage/read fulfillment. This publication does not select this candidate as the production builder or introduce a retrieval/model loop.

`background_info.py` and `background_store.py` match the final `background_code_freeze006` hashes. The `rag_vnext/` folder contains only the codec and its local contract dependency, **not** the experimental retriever/reranker runtime. The source is preserved unchanged.

From this folder:

```text
python -B -m unittest test_assembly_v14 test_conservative_selection test_background_info test_background_store test_delivery_codec_v14 test_knowledge_structure -v
```

These tests use synthetic fixtures. A Windows account without symlink privileges skips the symlink-specific test. The original real-input verification found 54/54 bound arms preserved, but evidence-use improvement was not established and no scientific or production approval was granted. Original source passages, model calls and evaluation packets remain local.
