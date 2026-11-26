"""Render a collection-level statistical readout from the published native stage results."""
import argparse
import json
from html import escape
from pathlib import Path
from urllib.parse import quote
if __package__:
    from . import figure_notes as display
else:
    import figure_notes as display

fmt, interval, table = display.fmt, display.interval, display.table


STAGES = {"absorption": "吸收", "distribution": "分布", "elimination": "消除"}
NAMES = {"Grepafloxacin": "格帕沙星", "Cefdinir": "头孢地尼", "Doxycycline": "多西环素",
         "dog": "犬", "monkey": "猴", "rat": "大鼠", "rabbit": "兔", "mouse": "小鼠"}


def p_value(value, alpha=.05):
    return display.p_value(value, alpha, missing="未检验", underflow="极小（原始计算舍入为 0）")


def time_window(values):
    return display.time_window(values, empty="无交集", single="仅 {:g} h")


def tail_reading(tail):
    original = tail.get("test") or {}
    common = tail.get("common_tail") or {}
    shared = common.get("test") or {}
    if original.get("p") is None:
        return "可比较的尾段不足，未检验。"
    alpha = tail.get("alpha", .05)
    if shared.get("p") is None:
        direction = "较慢" if tail["ratio"] > 1 else "较快"
        original_text = f"各自选窗提示口服末段{direction}。" if original["p"] < alpha else "各自选窗未能区分两条斜率。"
        return original_text + "共同窗缺少可拟合的下降段，无法复核。"
    if shared["p"] < alpha:
        direction = "较慢" if common["ratio"] > 1 else "较快"
        return f"在共同窗内，口服末段下降{direction}。"
    if original["p"] < alpha:
        return "各自选窗提示斜率有差异。缩到共同窗后，证据不足。"
    return "两个窗口均未能区分斜率，下降速度是否相同仍未确定。"


def p_value_report(cases):
    parts = ['<section id="p-values" aria-labelledby="p-title"><h2 id="p-title">p 值解读与本次结果</h2>',
             "<p>先问检验假定了什么。以口服和静脉曲线为例，零假设是两条曲线在指定时间窗内有相同的下降斜率。"
             "如果这个假设和回归模型都成立，双侧 p 值就是得到至少像本次这样极端的检验统计量的概率，两个方向的偏离都算在内。"
             "差异的方向和大小要看半衰期比。吸收机制成立的概率无法从这个 p 值读出。"
             ' <a href="https://doi.org/10.1080/00031305.2016.1154108">美国统计学会对 p 值的说明</a></p>']
    # Choose by the change in the sampling window, independently of p or direction.
    examples = []
    for drug, modules in sorted(cases.items()):
        absorption = modules["absorption"]
        cards = {d["card"]["dataset_id"]: d["card"] for d in absorption.get("datasets", [])}
        for p in absorption.get("ev_iv", []):
            tail = p.get("tail") or {}
            orig = tail.get("test") or {}
            overlap = (tail.get("common_tail") or {}).get("test") or {}
            if (p.get("dose_ev") is None or p["dose_ev"] != p.get("dose_iv") or
                    orig.get("p") is None or overlap.get("p") is None):
                continue
            fewer = orig["n_ev"] + orig["n_iv"] - overlap["n_ev"] - overlap["n_iv"]
            examples.append((fewer, drug, cards.get(p["ev"], {}), p))
    if examples:
        _, drug, card, pair = max(examples, key=lambda row: row[0])
        species = card.get("species", "").lower()
        who = escape(NAMES.get(drug, drug) + NAMES.get(species, species))
        ev_route = "口服" if str(card.get("route_detail", "")).upper() in ("PO", "ORAL") else "血管外"
    else:
        pair = {}
    tail = pair.get("tail") or {}
    original = tail.get("test") or {}
    common = tail.get("common_tail") or {}
    shared = common.get("test") or {}
    if original.get("p") is not None and shared.get("p") is not None:
        parts.append(f"<h3>{who}的{ev_route}尾段更慢吗？</h3>")
        parts.append(table(["同一次实验", "用于拟合的时间", f"{ev_route} / 静脉时点数", "残差自由度", f"{ev_route} / 静脉半衰期比", "双侧名义 p"],
                           [["各自选窗", f"{ev_route} {time_window(tail['ev_window_h'])}\n静脉 {time_window(tail['iv_window_h'])}",
                             f"{original['n_ev']} / {original['n_iv']}", original["df"], fmt(tail["ratio"]), p_value(original["p"])],
                            ["共同窗口", time_window(common["window_h"]), f"{shared['n_ev']} / {shared['n_iv']}",
                             shared["df"], fmt(common["ratio"]), p_value(shared["p"])]]))
        parts.append(f"<p><strong>本次可汇报为</strong>　{who}{ev_route}和静脉均为 {fmt(pair['dose_ev'])} mg/kg。"
                     f"各自选窗的半衰期比为 {fmt(tail['ratio'])}（p = {p_value(original['p'])}），"
                     f"共同窗为 {fmt(common['ratio'])}（p = {p_value(shared['p'])}）。{tail_reading(tail).replace('口服', ev_route)}"
                     "判断持续吸收还需要可比的晚期个体曲线。</p>")
        parts.append(f"<p>按相同斜率的模型，把原窗口当作固定窗口，约 {fmt(original['p'] * 100)}% 的重复抽样会得到绝对值至少这么大的 t 统计量。"
                     "此例取自同剂量且两种窗口均可拟合的比较，按共同窗内减少的时点数选取。共同窗复用了两条曲线在重叠时段的观测。时点、斜率估计和估计精度随之改变，两次结果不能当作独立重复。</p>")
    parts.append("<p><strong>怎样读 0.05 和空白。</strong>本页用 0.05 作为名义显著性参考。"
                 "尾段检验的自由度来自拟合用的时点，组均值曲线不能给出动物间的变异。"
                 "名义 p 没有校正选窗和跨物种的多次比较。p 较大时，观测值仍可能容许有实际意义的差异。"
                 "要判断足够接近，应事先给出可接受范围并检查区间。表中“未检验”表示数据或设计不足。</p>")
    tails = [p.get("tail") or {} for modules in cases.values() for p in modules["absorption"]["ev_iv"]]
    n_original = sum((t.get("test") or {}).get("p") is not None for t in tails)
    n_common = sum(((t.get("common_tail") or {}).get("test") or {}).get("p") is not None for t in tails)
    parts.append(f"<p>本次有 {n_original} 个口服/静脉比较得到原窗口 p 值，其中 {n_common} 个也能在共同窗复算。各药的全部结果列在下方。</p>")
    parts.append('<nav aria-label="各模块检验"><a href="#absorption">吸收的逐项结果</a> · '
                 '<a href="#distribution">分布检验</a> · <a href="#elimination">消除检验</a></nav></section>')
    return "".join(parts)


def build(collection):
    cases = {}
    for case in sorted(collection.iterdir()):
        if (case / "portal_publication.json").is_file():
            cases[case.name] = {s: json.loads((case / s / (s + ".json")).read_text(encoding="utf8")) for s in STAGES}
    if not cases:
        raise ValueError(f"No published EDA cases found under {collection}")
    parts = ['<nav><a href="index.html">返回 EDA 首页</a> · <a href="#p-values">p 值解读与汇报</a></nav>',
             "<h1>吸收、分布、消除的统计检验</h1>", p_value_report(cases)]
    if (collection / "statistical_review_20261111.html").is_file():
        parts.append('<p><a href="statistical_review_20261111.html">首次审查与原文核对</a></p>')
    for stage, title in STAGES.items():
        parts.append(f"<h2 id='{stage}'>{title}</h2>")
        if stage == "absorption":
            parts.append("<p>口服与静脉的共同窗比较仅使用原选窗交集内的实测点，每条曲线至少三个。"
                         "两种选窗都用双侧 t 检验比较对数浓度的下降斜率。半衰期比大于 1 表示口服下降较慢，小于 1 表示口服下降较快。</p>")
        elif stage == "distribution":
            parts.append("<p>预设组织检验的零假设是早、晚两个时点的组织/血浆比相同。每只动物贡献配对的组织与血浆观测。"
                         "有多项预设比较时，用 Bonferroni 校正后的 p 判断证据。假设协方差为零所得的区间单列展示。</p>")
        elif stage == "elimination":
            parts.append("<p>剂量或场次比较检验两臂真实静脉清除率的几何均值比是否为 1，p 为单个预设比较的名义值。"
                         "肾滤过比较的零假设是逐动物肾清除率除以滤过参照后的总体中位数为 1，双侧符号检验计算比值落在 1 两侧的动物数。</p>")
        for name, modules in cases.items():
            result = modules[stage]
            parts.append(f'<h3>{escape(NAMES.get(name, name))} · <a href="{quote(name)}/{stage}/index.html">原生报告</a></h3>')
            if stage == "absorption":
                cards = {d["card"]["dataset_id"]: d["card"] for d in result["datasets"]}
                for series in result["dose_series"]:
                    stat = series.get("t3_power")
                    if stat:
                        dose_species = {cards[i]["species"].lower() for i in series.get("dataset_ids", []) if i in cards}
                        who = "、".join(escape(NAMES.get(s, s)) for s in sorted(dose_species))
                        doses = "、".join(fmt(x) for x in series["doses"])
                        reading = ("组均值的暴露趋势偏离剂量比例，偏离的机制仍待核查。" if stat["p"] < .05 else
                                   "这几组均值不足以判定暴露偏离剂量比例，也不足以确认成比例。")
                        parts.append(f"<p><strong>{who}的剂量与暴露。</strong> {doses} mg/kg 各剂量组各贡献一个平均曲线 AUC。"
                                     f"若剂量翻倍、暴露也翻倍，双对数回归斜率应为 1。估计斜率为 {fmt(stat['beta'])}，名义 95% 区间 "
                                     f"{interval(stat['ci'])}，双侧 p = {p_value(stat['p'])}，残差自由度 {stat['df']}。{reading}</p>")
                individual = [s["animal_auc"] for s in result["dose_series"] if s.get("animal_auc")]
                individual.extend(r["analysis"]["animal_auc"] for r in result.get("reported_parameters", [])
                                  if (r.get("analysis") or {}).get("animal_auc"))
                for test in individual:
                    if test["status"] == "ASSESSED":
                        eq = test["equivalence"]
                        if eq["status"] in ("WITHIN_PREDECLARED_MARGIN", "NOT_ESTABLISHED"):
                            decision = "在" if eq["status"] == "WITHIN_PREDECLARED_MARGIN" else "未完全落在"
                            equivalence = f"90% 区间 {interval(eq['ci90'])} {decision}预设范围 {interval(eq['margin'])} 内。"
                        else:
                            equivalence = "本次未判断等效性。"
                        method = "配对 t 检验" if test.get("design") == "PAIRED" else "独立动物组的 Welch t 检验"
                        reading = "观察到两剂量间的差异。" if test["p"] < .05 else "两剂量的差异证据不足。"
                        parts.append(f"<p>逐动物剂量归一化 AUC 的高/低剂量比为 {fmt(test['R'])}，95% 区间 {interval(test['ci'])}。"
                                     f"{method}检验总体几何均值比等于 1，p = {p_value(test['p'])}。{reading}{equivalence}</p>")
                    else:
                        parts.append("<p>逐动物剂量比较未执行。"+escape(test.get("reason", ""))+"</p>")
                rows = []
                for pair in result["ev_iv"]:
                    tail = pair.get("tail") or {}
                    common = tail.get("common_tail") or {}
                    animal = cards[pair["ev"]]["species"].lower()
                    original, shared = tail.get("test") or {}, common.get("test") or {}
                    first = second = "未检验"
                    if original.get("p") is not None:
                        first = (f"口服 {time_window(tail['ev_window_h'])}，静脉 {time_window(tail['iv_window_h'])}\n"
                                 f"比值 {fmt(tail['ratio'])}，p = {p_value(original['p'])}\n"
                                 f"{original['n_ev']} / {original['n_iv']} 个时点，df = {original['df']}")
                    if common:
                        refit = (f"比值 {fmt(common['ratio'])}，p = {p_value(shared['p'])}，df = {shared['df']}"
                                 if shared.get("p") is not None else "未检验")
                        second = f"{time_window(common['window_h'])}，{common['n_ev']} / {common['n_iv']} 个时点\n{refit}"
                    reading = tail_reading(tail)
                    if pair["dose_ev"] != pair["dose_iv"] and original.get("p") is not None:
                        reading += "两途径剂量不同。"
                    rows.append([f"{NAMES.get(animal, animal)}\n{fmt(pair['dose_ev'])} / {fmt(pair['dose_iv'])} mg/kg",
                                 first, second, reading])
                if rows:
                    parts.append(table(["物种及剂量（口服 / 静脉）", "各自选窗", "共同窗口", "本次可得结论"], rows))
                else:
                    parts.append("<p>本次没有可比的口服/静脉尾段。</p>")
            elif stage == "distribution":
                pairs = [p for b in result["boards"] for p in b.get("tissue_pairs", [])]
                conditional = [p for p in pairs if (p.get("dis4b") or {}).get("fold_ci_kind") == "CONDITIONAL_ZERO_COVARIANCE_INTERVAL"]
                parts.append(f"<p>组织或体液与血浆对照共 {len(pairs)} 组，其中 {len(conditional)} 组可在假设协方差为零时计算早晚变化区间。</p>")
                tests = result.get("prespecified_ratio_tests") or []
                if tests:
                    parts.append(table(["预设组织", "结果或缺失条件", "晚/早倍数", "校正区间", "原始 p", "校正 p"],
                                       [[t.get("organ", ""), ("校正后支持早晚比值改变" if t["p_adjusted"] < t["alpha_family"]
                                          else "校正后差异证据不足") if t["status"] == "ASSESSED" else ", ".join(t["exclusion_reasons"]),
                                         fmt(t.get("fold_change")), interval(t.get("ci_fold")), p_value(t.get("p_raw")),
                                         p_value(t.get("p_adjusted"), t.get("alpha_family", .05))] for t in tests]))
                else:
                    parts.append("<p>没有符合设计的预设逐动物组织比较，本次没有组织比变化的 p 值。</p>")
            else:
                tests = [c for b in result["boards"] for item in ("item30", "item31") for c in b[item].get("clearance_contrasts", [])]
                if tests:
                    # R7 item 2: recomparison of source-reported individual IV CL; the p is recomputed here and Holm-adjusted per board and kind
                    parts.append(table(["来源报告个体 IV CL 的重新比较", "结果或缺失条件", "清除率比", "95% 区间", "重算 p", "族校正 p (Holm)"],
                                       [[t["id"], ("校正后两臂清除率有差异" if t["reading"] == "DIFFERENCE_DETECTED" else "校正后两臂清除率差异证据不足")
                                         if t["status"] == "ASSESSED" else ", ".join(t["reasons"]),
                                         fmt(t.get("ratio_b_over_a")), interval(t.get("ci95")), p_value(t.get("p")),
                                         p_value(t.get("p_holm"))] for t in tests]))
                else:
                    parts.append("<p>输入未指定有逐动物 IV 清除率的剂量或场次比较。</p>")
                renal = [b["renal_filtration_comparison"] for b in result["boards"]]
                measured = [r for r in renal if r["status"] == "DESCRIBED"]
                for r in measured:
                    # R7 item 1: numbers as observed; the sign test p is audit detail only, with no direction drawn from it
                    a = r["audit"]
                    parts.append(f"<p>在 {interval(r['interval_h'])} h 的预设窗口，{r['n_animals']} 只动物的肾清除率/滤过参照中位数为 "
                                 f"{fmt(r['median_ratio'])}（范围 {fmt(r['range'][0])}–{fmt(r['range'][1])}），"
                                 f"高于、低于、等于 1 的动物各有 {r['above']}、{r['below']}、{r['ties']} 只。正式的滤过判断由 T10 给出。</p>"
                                 f"<details><summary>审计明细</summary><p>双侧符号检验 p = {p_value(a['sign_test_p'])}（不是登记的检查）。"
                                 "这个 p 只反映动物落在 1 同一侧的一致程度，无法校正共同的 GFR 偏差。</p></details>")
                if not measured:
                    parts.append("<p>肾清除率与滤过参照的动物层比较未执行。</p>")
                reasons = dict.fromkeys(r["reason"] for r in renal if r.get("reason"))
                if reasons:
                    parts.append("<details><summary>查看缺失条件</summary><ul>" +
                                 "".join("<li>"+escape(reason)+"</li>" for reason in reasons) + "</ul></details>")
    if (collection / "validation/statistical_implementation.json").is_file():
        parts.append('<p><a href="validation/statistical_implementation.json">本次运行记录与共同窗明细</a> · '
                     '<a href="verification.json">交付核验</a></p>')
    style = ("body{max-width:1060px;margin:36px auto;padding:0 20px 40px;color:#193239;"
             "font:16px/1.65 'Microsoft YaHei',sans-serif}h2{border-top:1px solid #bbc9c4;padding-top:16px}"
             "a{color:#075b64}.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse}"
             "th,td{border-bottom:1px solid #d1ded9;text-align:left;vertical-align:top;padding:7px 10px}th{background:#e9f0ed}"
             "td{white-space:pre-line}#p-values{background:#f3f8f6;padding:1px 18px 16px;border-left:3px solid #528278}"
             "#p-values h2{border:0;margin-top:8px}nav a{white-space:nowrap}@media(max-width:650px){body{padding:0 12px}.scroll table{min-width:640px}}")
    html = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>三模块统计检验</title><style>{style}</style><body>{''.join(parts)}</body></html>")
    (collection / "statistical_tests.html").write_text(html, encoding="utf8")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("collection", type=Path)
    build(cli.parse_args().collection.resolve())
