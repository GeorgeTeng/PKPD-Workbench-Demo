"""A concise, deterministic view of an existing modeling DR; no model calls."""
import argparse
import html
import json
from pathlib import Path

from .adequacy import file_ref, check_ref
from .common import read_json, write_json


LABELS = {'NCA': 'Animal PK · NCA', 'MODEL_BASED': 'Animal PK · Model-based', 'PD_INDEX': 'PD index',
          'PD_TARGET': 'PD target', 'PTA': 'PTA · 非人类输入'}
STATUS = {'INPUT_CANDIDATE': '可尝试', 'PARTIAL': '需补充部分信息', 'BLOCKED': '缺少关键输入',
          'NOT_APPLICABLE': '不适用', 'DEFERRED': '后续再做'}


def build_view(requirements, payload):
    """Render model statements verbatim; never promote their scientific status."""
    names = {}
    for p in payload['data_profiles']:
        item = p['item_id']
        try:
            descriptor = json.loads(payload['source_units'][item])
        except (ValueError, TypeError, KeyError):
            descriptor = {}
        names[item] = ' · '.join(str(x) for x in [descriptor.get('sheet'), descriptor.get('title', item)] if x)
    result = {'objective': payload['context_sources']['main:/objective'],
              'scope': 'Animal PK: NCA and model-based methods; PD index.',
              'analyses': {a: [] for a in LABELS}}
    for task in requirements['method_feasibility']:
        for a in task['approaches']:
            result['analyses'][a['analysis']].append({
                'analysis': a['name'], 'data': [names[i] for i in a['dataset_ids']],
                'status': a['status'], 'what_it_supports': a['reason'],
                'available': a['available_inputs'], 'key_gaps': a['missing_inputs'],
                'conditions': a['applicability_conditions'], 'next_step': a['next_step']})
    checks = requirements.get('input_checks', {})
    if checks:
        panels = checks['PD_target_estimation']['panel_statistics']
        for key, name, level in [('stasis', 'Stasis target', 0), ('one_log_kill', '1-log kill target', -1), ('two_log_kill', '2-log kill target', -2)]:
            within = all(p['targets'][key]['within_observed_response_range'] for p in panels)
            result['analyses']['PD_TARGET'].append({
                'analysis': name, 'data': ['K. pneumoniae 104 · 0–24 h · 三个独立 index-response 面板'],
                'status': 'INPUT_CANDIDATE' if within else 'PARTIAL',
                'what_it_supports': '现有点支持逐面板探索目标；还没有计算或验证目标值。' if within else '当前有效点未达到 2-log kill；不能把外推当作已有观测支持。',
                'available': [f'三个面板有效点数：{", ".join(str(p["eligible_digitized_rows"]) for p in panels)}。',
                              f'观测 Δlog10 CFU 范围均为 −1.632 到 3.0；本目标响应水平为 {level}。',
                              '暴露坐标已应用 fu；参考为治疗前到 24 h 的变化。'],
                'key_gaps': [] if within else ['现有数字化点没有覆盖 −2 的响应水平。'],
                'conditions': ['范围覆盖不等于可识别或已估得目标；拟合后检查不确定性。',
                               '跨 index 公平比较仍需共同记录；各 panel 内的探索拟合不要求先完成这一配对。'],
                'next_step': '分别尝试 Emax / sigmoid Emax，检查目标与不确定性。' if within else '先补查现有原文/原记录，再判断模型外推是否有依据；需要经验验证但仍无覆盖时，才考虑补充数据。'})
        pta = checks['PTA_nonhuman']
        result['analyses']['PTA'] = [
            {'analysis': '固定 MIC 的 PTA', 'data': ['PD target + 后续 PK 模型 + 给药方案'], 'status': 'PARTIAL',
             'what_it_supports': '可以明确计算所需输入；这里不计算 PTA，也不检查人类数据。',
             'available': ['不依赖群体 MIC 分布。'], 'key_gaps': [],
             'conditions': ['模型参数和合格的 PD target 属于后续产物，不是必须新做实验才能获得的原始数据。'],
             'next_step': '接收后续模型/target 输出，并明确模拟方案、窗口及 free/total 基础。'},
            {'analysis': 'MIC 加权达标率', 'data': ['现有 652 株 surveillance MIC 分布'], 'status': 'PARTIAL',
             'what_it_supports': '已有一个来源明确的候选分布；与固定 MIC 的 PTA 分开报告。',
             'available': ['原百分比与本地复算合计 99.57%。'],
             'key_gaps': ['补查未覆盖的 0.43 个百分点、原始计数/分母及该分布对目标场景的代表性。'],
             'conditions': ['不静默归一；少量独立菌株 MIC 不能替代群体权重。'],
             'next_step': '优先补现有来源说明；尚不能据此断言必须新增采样。'},
            {'analysis': 'PK / target 的变异与不确定性', 'data': ['后续拟合产物和当前数据层级'], 'status': 'PARTIAL',
             'what_it_supports': '区分后续模型产物、定义选择和真正缺少的观测。',
             'available': pta['planned_model_output'], 'key_gaps': [],
             'conditions': ['均值曲线误差或参数标准误不能替代个体间变异。'],
             'next_step': '模型拟合后核对可支持的变异；不足时明确敏感性情景，届时再决定是否需要新数据。'}]
    return result


def html_view(view):
    esc = lambda value: html.escape(str(value), quote=True)
    def items(values):
        return '<ul>' + ''.join('<li>' + esc(x) + '</li>' for x in values) + '</ul>' if values else '<span class="muted">无列出的缺口</span>'
    sections = []
    buttons = []
    for index, (key, label) in enumerate(LABELS.items()):
        buttons.append(f'<button data-target="{key}" class="{"selected" if index == 0 else ""}">{esc(label)} <b>{len(view["analyses"][key])}</b></button>')
        cards = []
        for row in view['analyses'][key]:
            cards.append('<article><div class="row"><h2>' + esc(row['analysis']) + '</h2><span class="status">'
                + esc(STATUS[row['status']]) + '</span></div><div class="data">' + esc(' / '.join(row['data']))
                + '</div><p>' + esc(row['what_it_supports']) + '</p><div class="columns"><div><h3>现有信息</h3>'
                + items(row['available']) + '</div><div><h3>关键缺口</h3>' + items(row['key_gaps'])
                + '</div></div><div class="next"><b>下一步</b> ' + esc(row['next_step'])
                + '</div><details><summary>适用条件</summary>' + items(row['conditions']) + '</details></article>')
        sections.append(f'<section id="{key}" {"hidden" if index else ""}>' + ''.join(cards) + '</section>')
    return ('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Data requirement · 现有数据能做什么</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f5f8;color:#172a3b;font:15px/1.55 system-ui,sans-serif}
main{max-width:1120px;margin:36px auto;padding:0 24px}h1{font-size:28px;margin:0 0 6px}h2{font-size:19px;margin:0}
.intro{color:#556477;margin:8px 0 22px}.objective{background:#e8eef4;border-left:4px solid #36798b;padding:14px 18px}
nav{display:flex;gap:10px;margin:24px 0;flex-wrap:wrap}button{cursor:pointer;border:1px solid #bfcbd6;border-radius:8px;background:white;padding:12px 16px;font:inherit;color:inherit}
button.selected{background:#174d60;color:white;border-color:#174d60}button b{margin-left:10px;opacity:.7}
article{background:white;border:1px solid #dce2e8;border-radius:12px;padding:22px;margin:16px 0}.row{display:flex;justify-content:space-between;align-items:start;gap:18px}
.status{white-space:nowrap;background:#edf2f7;padding:3px 10px;border-radius:12px;font-size:13px}.data{font-size:13px;color:#607285;margin:8px 0}
.columns{display:grid;grid-template-columns:1fr 1fr;gap:28px}h3{font-size:14px;margin:8px 0}ul{padding-left:20px;margin:5px 0 16px}li{margin:5px 0}
.next{background:#eff6f4;padding:12px 15px;border-radius:6px}.next b{display:block;margin-bottom:3px}details{margin-top:12px;color:#637180;font-size:13px}
.muted,footer{color:#6c7c8c;font-size:13px}footer{margin:24px 0}a{color:#176581}@media(max-width:720px){.columns{grid-template-columns:1fr;gap:4px}.row{display:block}.status{display:inline-block;margin-top:8px}main{padding:0 12px}}
</style><main><h1>现有数据能做什么</h1><p class="intro">当前阶段：Animal PK 与 PD index。以下是数据支持的方法规划，尚未执行拟合。</p><p class="objective">'''
        + esc(view['objective']) + '</p><nav>' + ''.join(buttons) + '</nav>' + ''.join(sections) + '''
<footer>此视图直接整理本次 DR 的内容，不新增模型判断。<a href="modeling_options.json">精简 JSON</a> · <a href="requirements.json">完整 DR 与来源</a></footer>
</main><script>document.querySelectorAll('button').forEach(b=>b.onclick=()=>{document.querySelectorAll('section').forEach(s=>s.hidden=s.id!==b.dataset.target);document.querySelectorAll('button').forEach(x=>x.classList.toggle('selected',x===b));});</script></html>''')


def render(run):
    run = Path(run)
    requirements = read_json(run/'requirements.json')
    if 'proof_ref' in requirements['provenance']:
        from .data_modeling_requirements_publish import verify_proof
        check_ref(requirements['provenance']['proof_ref'])
        derived = verify_proof(requirements['provenance']['proof_ref']['path'])
        if any(requirements[k] != v for k, v in derived.items()):
            raise ValueError('Report source differs from checked derivation')
    else:
        check_ref(requirements['provenance']['bindings_ref'])
    bindings = read_json(run/'bindings.json')
    for ref in bindings['inputs'].values():
        check_ref(ref)
    view = build_view(requirements, read_json(run/'payload.json'))
    view['full_result'] = file_ref(run/'requirements.json')
    write_json(run/'modeling_options.json', view)
    (run/'modeling_options.html').write_text(html_view(view), encoding='utf-8')
    return view


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    result = render(parser.parse_args().run)
    print(json.dumps({'analyses': {k: len(v) for k, v in result['analyses'].items()}}))


if __name__ == '__main__':
    main()
