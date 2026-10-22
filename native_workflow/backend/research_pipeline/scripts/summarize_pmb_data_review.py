"""Verify a completed PMB B2 run and attach a human-readable review report."""

import argparse
from collections import Counter
from pathlib import Path
import sys

from research_pipeline.common import read_json, write_json, sha256, utcnow
from research_pipeline.data_preparation import digest


def require(condition, message):
    if not condition:
        raise ValueError(message)


def reference(path):
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def main(run):
    run = run.resolve()
    entry = read_json(run / "main.json")
    execution = read_json(run / "execution.json")
    require(execution["status"] == "B2_COMPLETE_PENDING_HUMAN_REVIEW", "B2 is not complete")
    for key, item in entry.items():
        if isinstance(item, dict) and "path" in item and "sha256" in item:
            require(sha256(item["path"]) == item["sha256"], f"Changed handoff reference: {key}")
    b1 = read_json(entry["upstream_main"]["path"])
    checked_inputs = []
    for item in b1["data"]["files"]:
        require(sha256(item["path"]) == item["sha256"], f"Changed original attachment: {item['id']}")
        checked_inputs.append({"id": item["id"], "sha256": item["sha256"], "unchanged": True})
    source_path = Path(execution["source_preparation"]["path"])
    require(sha256(source_path) == execution["source_preparation"]["sha256"], "Source preparation changed")
    source = read_json(source_path)
    originals = {}
    source_table = {}
    for item in source["tables"]:
        path = source_path.parent / item["records_path"]
        require(sha256(path) == item["sha256"], f"Changed table: {item['id']}")
        for row in read_json(path)["records"]:
            require(row["record_id"] not in originals, "Duplicate source record identity")
            originals[row["record_id"]] = row
            source_table[row["record_id"]] = item["id"]
    manifest = read_json(entry["normalization_manifest"]["path"])
    represented = Counter()
    normalized = {}
    for item in manifest["datasets"]:
        for kind in ("json", "csv"):
            require(sha256(item[kind]["path"]) == item[kind]["sha256"], f"Changed normalized file: {item['id']}")
        payload = read_json(item["json"]["path"])
        require(payload["fit_ready"] is False, "Unexpected model release")
        normalized[item["id"]] = payload["records"]
        require(len(payload["records"]) == item["record_count"], "Normalized row count mismatch")
        for row in payload["records"]:
            rid = row["record_id"]
            require(rid in originals, f"New unexplained source record: {rid}")
            represented[rid] += 1
            for field in ("source_file_id", "source_sha256", "source_sheet", "source_row", "source_cell", "source_cells"):
                if field in originals[rid]:
                    require(row.get(field) == originals[rid][field], f"Changed provenance: {rid}/{field}")
    require(set(represented) == set(originals), "Source records lost during normalization")
    require(all(n == (2 if source_table[rid] == "T0004" else 1) for rid, n in represented.items()),
            "Unexpected duplication; only T0004 serum/lung splitting is allowed")
    require(sum(represented.values()) == manifest["normalized_records"], "Total row mismatch")
    quarantine = read_json(entry["missingness"]["path"])["records"]
    time_kill_counts = {}
    for strain in ("BAA1705", "KP619"):
        rows = normalized[f"kp_{strain}_time_kill"]
        time_kill_counts[strain] = dict(Counter(r["status"] for r in rows))
        for row in rows:
            original = originals[row["record_id"]]
            require(row["Y_raw"] == original["c005_y"] and row["CENS"] == original["c006_cens"], "Time-kill raw value or CENS changed")
            event = originals[row["exposure_event_record_id"]]
            require(source_table[event["record_id"]] == source_table[row["record_id"]] and event["c001_id"] == original["c001_id"], "Exposure joined across source groups")
            require(row["nominal_concentration_mg_L"] == event["c002_amt"], "Exposure value changed")
            if row["status"].startswith("MISSING_"):
                require(row["log10_CFU_mL"] is None and row["fit_ready"] is False, "Missing value incorrectly used as numeric data")
            else:
                require(row["log10_CFU_mL"] == original["c005_y"], "Numeric observation changed")
            if row["status"] != "QUANTIFIED":
                require(any(q["record_id"] == row["record_id"] and q["status"] == row["status"] for q in quarantine), "Non-exact observation omitted from quarantine manifest")
    require(time_kill_counts["BAA1705"] == {"QUANTIFIED": 33, "CENSORED": 3, "MISSING_OBSERVATION": 1}, "Unexpected BAA1705 regression counts")
    require(time_kill_counts["KP619"] == {"QUANTIFIED": 28}, "Unexpected KP619 counts")
    native = read_json(entry["native_data_report"]["path"])
    assessment = {k: v for k, v in native.items() if k not in {"assessment_sha256", "review", "released_datasets"}}
    assessment["rule_status"] = "PROPOSED_PENDING_HUMAN_CONFIRMATION"
    require(digest(assessment) == native["assessment_sha256"], "Native assessment fingerprint invalid")
    gate = read_json(entry["human_review_gate"]["path"])
    review = read_json(gate["review_submission"]["path"])
    require(gate["assessment_sha256"] == review["assessment_sha256"] == native["assessment_sha256"], "Review fingerprint mismatch")
    require(review["decision"] == "PENDING" and not gate["model_execution_allowed"], "Unexpected human approval")
    require(not native["released_datasets"] and not entry["released_datasets"], "Unexpected released datasets")
    request = read_json(run / "request.json")
    require([s["module"] for s in request["steps"]] == ["data_preparation"], "Unexpected modeling step")
    require(sha256(run / "audit/run_pmb_data_review.py") == execution["script_sha256"], "Adapter snapshot mismatch")
    require(sha256(run / "audit/time_kill_preparation.py") == execution["time_kill_processor_sha256"], "Time-kill processor snapshot mismatch")
    previous = source_path.parent.parent
    previous_execution = read_json(previous / "execution.json")
    require(previous_execution["status"] == "STOPPED_ON_ERROR", "Previous failure record changed")
    require(sha256(previous / "run_pmb_data_review.py") == previous_execution["script_sha256"], "Previous failed adapter changed")

    severity = dict(Counter(i["severity"] for i in native["issues"]))
    codes = Counter(i["code"] for i in native["issues"])
    verification = {
        "status": "PASS", "verified_at": utcnow(), "verifier": reference(Path(__file__)),
        "input_attachments": checked_inputs, "source_tables": len(source["tables"]),
        "source_records": len(originals), "normalized_datasets": len(manifest["datasets"]),
        "normalized_records": sum(represented.values()), "all_source_records_preserved": True,
        "extra_rows_explained_by_serum_lung_split": True, "time_kill_status_counts": time_kill_counts,
        "missing_y_preserved_and_quarantined": True, "source_provenance_preserved": True,
        "native_assessment_fingerprint_verified": True, "previous_failed_run_preserved": True,
        "code_snapshots_verified": True, "human_approval": "PENDING", "model_execution": "NOT_RUN",
        "limit": "File and transformation integrity verification; not independent source-paper validation or proof of statistical adequacy."
    }
    verify_path = run / "report_verification.json"
    write_json(verify_path, verification)
    cards = read_json(entry["table_assessments"]["path"])["tables"]
    issues = read_json(entry["scientific_issues"]["path"])["issues"]
    lines = [
        "# PMB B2 数据整理与人工审核报告", "",
        f"运行：`{request['request_id']}`。完整整理已完成；原生 QC 为 **{entry['native_qc_status']}**，人工决定仍为 **PENDING**。", "",
        "## 1. 本次修复与执行证据", "",
        "- T0012_R161 / E161 的原值 `.` 保留为 Y_raw；数值字段为 null，状态 MISSING_OBSERVATION，CENS=0 不变，已隔离。",
        "- 结构性不适用、缺失观测、删失观测、精确定量观测分别标记；数值 0 保持数值。",
        f"- {len(source['tables'])} 张来源表、{len(originals)} 条来源记录 → {len(manifest['datasets'])} 个标准化 JSON/CSV 数据集、{sum(represented.values())} 行；增加的 3 行来自 T0004 的 serum/lung 拆分。",
        "- 5 个原附件哈希一致；上一轮失败代码与记录保留。本次脚本、处理模块快照及哈希见 audit/ 与 execution.json。",
        "- 复用了已校验的 B1 交接和来源表；未重新调用压缩模型。未执行 R 拟合、人体预测、PTA/CFR。", "",
        "## 2. 数据合理性与充分性结论", "",
        "| 数据 | 已有支持 | 当前阻断/限制 |", "|---|---|---|",
        "| 大鼠 IV plasma | 11 个来源支持的 serial 标签，102 个定量点；8 条隔离 | total/free 未注明；制剂/参数定义需确认，BLQ 限值和排除影响需审核。102 点不等于 102 只动物。 |",
        "| 小鼠 plasma / ELF | 数值及来源已保留 | 跨时间个体身份未证实；现有 PK 模块仅支持 IV，源数据为 IP/SC；ELF 有空槽位及重复数差异。 |",
        "| 兔 PK / 药效 | 参数汇总及终点可供背景核对 | 缺少 serial PK；PK 与药效方案不同；不能生成伪个体曲线或直接配对。 |",
        "| K. pneumoniae 静态 time-kill | BAA1705：33 定量 + 3 删失 + 1 缺失；KP619：28 定量；每株 6 暴露事件 | 名义暴露，生物重复与删失限值未明确；是 time-kill 候选，不是已满足动物 index 比较的数据。 |",
        "| 动物 PK/PD index | 终末肺菌量数据已整理 | 缺匹配的多方案暴露，不能据此比较三个 index 的 R²/AIC。 |",
        "| 所需样本量 | NOT_CALCULABLE | 缺目标参数个体间变异、预设 CI 精度、置信度及 assurance。 |",
        "| 人体外推 | NOT_ESTABLISHED | 需明确可比参数、体重、外推方法和目标；无人体独立验证。 |", "",
        "以上为当前附件和既有规则下的可用性审核；未独立重审来源论文，也未进行可辨识性或预测性能验证。", "",
        "## 3. 原生 QC 结果及覆盖范围", "",
        f"原生 PK/index QC 输入为 {len(read_json(run/'preparation.plan.json')['datasets'])} 个数据集，按身份/途径拆成 {len(native['datasets'])} 组。其余 time-kill、汇总和背景表由适配器分型及来源检查，不冒充原生 PK/index 数据。", "",
        f"共 {len(native['issues'])} 条 QC 发现：ERROR={severity.get('ERROR',0)}，REVIEW={severity.get('REVIEW',0)}。这些是逐行/逐组规则发现，可重复出现；不表示发生了同等数量的程序崩溃。", "",
        "当前所有原生数据组均 BLOCKED。species_count=0 表示目标定义不全时没有通过可比性筛选的物种，不表示附件没有动物数据。", "",
        "原生 QC 对 ELF 的 7 个 EMPTY_SLOT 输出 UNKNOWN_STATUS，反映现有处理器不支持该状态；来源空槽位已保留隔离，不能算成动物或自动补值。终点基线/对照与 PMB 组按途径拆开，baseline 0 h 和 vehicle 24 h 的混合也被明确阻断，尚不能直接用于 Emax。", "",
        "| QC code | 条数 |", "|---|---:|",
    ]
    lines += [f"| {code} | {count} |" for code, count in codes.items()]
    lines += ["", "## 4. 逐表整理状态", "", "| 表 | 来源 | 来源记录 | 用途/限制 |", "|---|---|---:|---|"]
    lines += [f"| {c['table_id']} | {c['title']} | {c['source_record_count']} | {c['mathematical_fit_assessment']} |" for c in cards]
    lines += ["", "## 5. 人工审核事项", ""]
    for issue in issues:
        lines += [f"### {issue['id']} — {issue['code']}", "", f"涉及：{', '.join(issue['source_tables'])}。{issue['message']}", "", f"需确认/补充：{issue['human_action']}", ""]
    lines += [
        "## 6. JSON 交接与 gate", "",
        "- `main.json` 是下游单一入口，引用标准化清单、逐表评估、QC、隔离清单和人工 gate。候选文件不等于已获准拟合。",
        "- `human_review_submission.template.json` 已绑定本轮 assessment_sha256，默认 PENDING，不能原样提交来放行。",
        "- 本轮无可 APPROVE 放行的数据组。人工可提出 REQUEST_CHANGES/REJECT；补齐来源/修正计划后重新评估，生成新指纹与新模板。",
        "- 已有接口 `POST /v1/data-reviews` 接收实际人工决定；本次没有提交或代填决定。服务需要指向本次 state 目录。",
        "- `execution.json` 可核对实际命令、PID、时间和代码哈希；`report_verification.json` 为完整性校验结果。", "",
        f"assessment_sha256：`{native['assessment_sha256']}`", "",
    ]
    report = run / "HUMAN_REVIEW_REPORT.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    entry.update(human_review_report=reference(report), verification=reference(verify_path),
                 execution=reference(run / "execution.json"))
    write_json(run / "main.json", entry)
    print({"verification": "PASS", "report": str(report), "qc_status": entry["native_qc_status"], "severity": severity})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    main(parser.parse_args().run)
