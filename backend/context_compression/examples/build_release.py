"""Package local source, tests and demonstration; excludes virtualenv and caches."""
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
import hashlib
import json
import zipfile
import xml.etree.ElementTree as ET

from ctxcomp.engine import verify
from ctxcomp.io import write_json
from ctxcomp.schemas import SCHEMAS, CONTEXT, PIPELINE

PROJECT = Path(__file__).resolve().parents[1]
WORKSPACE = PROJECT.parent
RELEASE = WORKSPACE / "outputs" / "Context_Compression_Local_2026-09-16"
RUN = RELEASE / "demo_run"


def main():
    check = verify(RUN)
    tree = ET.parse(RELEASE / "test_results.xml")
    suites = list(tree.getroot().iter("testsuite"))
    totals = {key: sum(int(s.attrib.get(key, 0)) for s in suites)
              for key in ("tests", "failures", "errors", "skipped")}
    if totals["failures"] or totals["errors"]:
        raise RuntimeError("Do not package a release with failing tests")
    packages = {p: version(p) for p in ("research-context-compression", "jsonschema", "pytest", "pypdf", "python-docx")}
    write_json(RELEASE / "environment.json", {"recorded_at": datetime.now(timezone.utc).isoformat(), "packages": packages})
    # Portable direct runtime pins; transitive versions remain recorded by pip resolution.
    (PROJECT / "requirements-tested.txt").write_text(
        "# Direct dependencies used for the recorded local test run\n" +
        "\n".join(f"{p}=={v}" for p, v in packages.items() if p != "research-context-compression") + "\n", encoding="utf-8")
    for name, schema in SCHEMAS.items():
        write_json(PROJECT / "schemas" / f"{name}.response.schema.json", schema)
    write_json(PROJECT / "schemas" / "context.schema.json", CONTEXT)
    write_json(PROJECT / "schemas" / "pipeline.schema.json", PIPELINE)

    history = WORKSPACE / "outputs" / "context_compression_chat_complete.md"
    text = history.read_text(encoding="utf-8-sig")
    selected = [
        ("compact_keys", "`objective` | 整体研究目的"),
        ("sidecar_evidence", "下游仍然只接收原结构的 `context.json`。"),
        ("known_values", "原文未提供的信息，正确写成 `NOT_FOUND` 可以得分"),
        ("budget", "220 content words / 2,400 compact characters"),
        ("two_stages", "整个 B1 就分为两个模块：Context Compression 和 Scientific Pipeline Planning"),
        ("wrapper", "最终可以统一为一个 **`project_plan.json`**"),
        ("human_review", "Fail 必须填写理由"),
        ("lock_context", "读取锁定的 context，并回查原文")
    ]
    recovered = []
    for rule, quote in selected:
        start = text.find(quote)
        if start < 0:
            raise RuntimeError(f"Historical rule quote not found: {rule}")
        recovered.append({"rule": rule, "quote": quote, "line": text[:start].count("\n") + 1,
                          "start_char": start, "end_char": start + len(quote)})
    write_json(RELEASE / "recovered_rules.json", {
        "source": str(history), "source_sha256": hashlib.sha256(history.read_bytes()).hexdigest(),
        "basis": "Saved transcript, not recovered original code", "rules": recovered})
    summary = {"software_version": "3.8.0", "tests": totals, "run_integrity": check,
               "blocks": 10, "file_dependencies": 19,
               "live_literature_search": "PASS: 3 matching primary records",
               "live_model_generation": "NOT_RUN",
               "model_adapter_test": "Mocked subprocess and four-stage orchestration tests passed",
               "example_origin": "Assistant-authored responses replayed through installed program",
               "independent_semantic_accuracy": "NOT_ESTIMATED",
               "old_source_compatibility": "Top-level rules reconstructed from transcript; original subfield schema unavailable"}
    write_json(RELEASE / "validation_summary.json", summary)
    (RELEASE / "README.md").write_text(
        "# 本机 Context Compression 交付结果\n\n"
        "代码：`context_compression`；已安装环境：`.venv-context`。\n\n"
        "当前示例先提取 context，再规划动物 PK、精度/样本量、人体外推、条件性 PD 和后续验证。\n\n"
        f"程序测试：{totals['tests']} 项，通过；失败 {totals['failures']}；错误 {totals['errors']}；跳过 {totals['skipped']}。\n\n"
        "原顶层 JSON 字段、NOT_FOUND、独立来源审计、context 锁定和 Pass/Fail 人工审核规则已保留。"
        "旧 Mac 源码未找回；本版依据聊天记录重建，不能宣称旧子字段完全兼容。\n\n"
        "## 当前验证边界\n\n"
        "- 示例由本助手编写，经过四阶段保存响应回放。\n"
        "- Codex 自动生成适配层已实现并用替身测试；本轮未调用真实模型。\n"
        "- Europe PMC 真实查询返回 3 条指定文献。\n"
        "- 独立语义准确率未估计，F/R/A 分数保持 null。\n"
        "- 未执行研究数据清洗或 PK/PD 拟合；科研审核仍为 Pending。\n\n"
        "详见 `demo_run/REPORT.md`、`demo_run/project_plan.candidate.json` 和源码 README。\n", encoding="utf-8")
    zip_path = RELEASE / "Context_Compression_Windows_3.8.0.zip"
    manifest = []
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for base, prefix in ((PROJECT, "context_compression"), (RUN, "demo_run")):
            for file in sorted(base.rglob("*")):
                if not file.is_file() or any(p in {"__pycache__", ".pytest_cache", "runs", "build", "dist"} or p.endswith(".egg-info") for p in file.relative_to(base).parts):
                    continue
                relative = prefix + "/" + file.relative_to(base).as_posix()
                archive.write(file, relative)
                manifest.append({"path": relative, "sha256": hashlib.sha256(file.read_bytes()).hexdigest(), "bytes": file.stat().st_size})
        for name in ("README.md", "environment.json", "validation_summary.json", "recovered_rules.json", "test_results.xml", "literature_search_smoke.json"):
            archive.write(RELEASE / name, "validation/" + name)
    write_json(RELEASE / "package_manifest.json", {"archive": zip_path.name,
                                                   "archive_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(), "files": manifest})
    with zipfile.ZipFile(zip_path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Archive integrity check failed")
    print(json.dumps({"archive": str(zip_path), "source_and_example_files": len(manifest), "tests": totals}, indent=2))


if __name__ == "__main__":
    main()
