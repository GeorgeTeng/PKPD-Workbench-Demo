"""Export distribution and elimination findings together, linked to the native case pages."""
import argparse
from html import escape, unescape
from pathlib import Path
import re


def export(collection, destination):
    nav, sections = [], []
    for case in sorted(collection.iterdir()):
        if not (case / "portal_publication.json").is_file():
            continue
        heading = re.search(r"<h1>([^<]+)</h1>", (case / "index.html").read_text(encoding="utf8"))
        drug = escape(unescape(heading[1])) if heading else escape(case.name)
        links = []
        for stage, label in (("distribution", "分布"), ("elimination", "消除")):
            page = case / stage / "index.html"
            summaries = re.findall(r'<div class="hsumtext">(.*?)</div>', page.read_text(encoding="utf8"), re.S)
            if len(summaries) != 1 or not summaries[0].strip():
                raise ValueError(f"Expected one populated summary on {page}")
            key = escape(f"{case.name}-{stage}", quote=True)
            links.append(f'<a href="#{key}">{label}</a>')
            sections.append(f'<section id="{key}"><h2>{drug} · {label}</h2>{summaries[0]}'
                            f'<p><a href="{page.as_uri()}">完整{label}报告</a> · '
                            f'<a href="{(case / "index.html").as_uri()}">主项目 EDA 界面</a> · '
                            '<a href="#contents">返回目录</a></p></section>')
        nav.append(f'<li>{drug}　' + '　'.join(links) + '</li>')
    if not sections:
        raise ValueError(f"No published cases found in {collection}")
    header = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>动物 PK · 分布和消除总结</title>
<style>body{max-width:840px;margin:32px auto;padding:0 22px 44px;color:#203033;font:17px/1.65 'Microsoft YaHei',Arial,sans-serif}h2{border-top:1px solid #bccac6;padding-top:18px}section b{display:block}a{color:#075d68}p{overflow-wrap:anywhere}</style></head><body>
<h1 id="contents">分布和消除总结</h1>"""
    destination.write_text(header+"<ul>"+"".join(nav)+"</ul>"+"".join(sections)+"</body></html>",encoding="utf8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    export(args.collection.resolve(), args.destination)
