"""Publish existing descriptive EDA with the main project's native portal owner."""
import argparse
import hashlib
import importlib
import json
import shutil
import sys
import types
from pathlib import Path


NATIVE_REPO = Path.home() / 'Documents/Codex/PMB-Translational-PKPD-code'
NATIVE_OWNER = NATIVE_REPO / 'backend/research_pipeline/research_pipeline/eda_review_portal.py'
if Path(__file__).with_name('eda_review_portal.py').is_file():
    NATIVE_OWNER = Path(__file__).with_name('eda_review_portal.py')
STAGES = ('absorption', 'distribution', 'elimination')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_common():
    """eda_common.py next to this file, loaded by path so another copy on sys.path cannot shadow it."""
    import importlib.util
    path = Path(__file__).resolve().with_name('eda_common.py')
    spec = importlib.util.spec_from_file_location('_eda_common_publish', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def publish(root, *, title=None, collection_href=None, owner=NATIVE_OWNER):
    """Use frozen scientific modules and a frozen copy of the actual UI owner.

    Only HTML/CSS/navigation and publication provenance are produced. No result
    is recalculated, no source table is changed, and no workflow is registered.
    """
    root = Path(root).resolve()
    owner = Path(owner).resolve()
    engine = root / '_engine'
    scientific = [root / 'source_tables.json'] + [root / stage / (stage + '.json') for stage in STAGES]
    before = {p.relative_to(root).as_posix(): sha(p) for p in scientific}
    for stage in STAGES:
        path = engine / ('eda_' + stage + '.py')
        if not path.is_file():
            raise FileNotFoundError('Missing frozen run engine: ' + str(path))
    frozen_owner = engine / 'eda_review_portal.py'
    if owner != frozen_owner.resolve():
        shutil.copy2(owner, frozen_owner)
    # A separate package per run keeps one drug's frozen modules out of another.
    package_name = '_eda_publication_' + hashlib.sha256(str(root).encode()).hexdigest()[:16]
    old_modules = {name: value for name, value in sys.modules.items()
                   if name == package_name or name.startswith(package_name + '.')}
    for name in old_modules:
        del sys.modules[name]
    package = types.ModuleType(package_name)
    package.__path__ = [str(engine)]
    sys.modules[package_name] = package
    previous_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        importlib.invalidate_caches()
        modules = {stage: importlib.import_module(package_name + '.eda_' + stage) for stage in STAGES}
        native = importlib.import_module(package_name + '.eda_review_portal')
        if collection_href is None and (root.parent / 'index.html').is_file():
            collection_href = '../index.html'
        # Freeze the shared renderer before the native portal imports it.
        source = owner.with_name("figure_notes.py")
        if not source.is_file():  # legacy installations with no native figure renderer
            source = Path(__file__).with_name("figure_notes.py")
        target = engine / source.name
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        display_sources = {source.name: sha(target)}
        navigation = native.build_descriptive(root, modules, title=title, collection_href=collection_href)
        annotated_figures = navigation.get("figures_with_readings")
        if annotated_figures is None:  # older native portal snapshots
            annotated_figures = importlib.import_module(package_name + ".figure_notes").publish(root)
        coverage_path = root / 'coverage.json'
        if coverage_path.is_file():
            # Short "Input coverage" table (unused datasets only) on the drug overview.
            coverage = json.loads(coverage_path.read_text(encoding='utf-8'))
            page = root / 'index.html'
            html = page.read_text(encoding='utf-8')
            if 'id="input-coverage"' not in html and '</main>' in html:
                block = _load_common().coverage_table_html(coverage).replace(
                    '<section id="input-coverage">', '<section class="panel" id="input-coverage">', 1)
                page.write_text(html.replace('</main>', block + '</main>', 1), encoding='utf-8')
            navigation['input_coverage'] = {'path': 'coverage.json', 'sha256': sha(coverage_path),
                                            'unused_all_sections': coverage['summary']['unused_all_sections']}
        handoff = None
        if (engine / 'modeling_handoff.py').is_file():
            writer = importlib.import_module(package_name + '.modeling_handoff')
            context = writer.write_handoff(root)
            handoff = {'path': 'modeling_context.json', 'sha256': sha(root / 'modeling_context.json'),
                       'generator_sha256': sha(engine / 'modeling_handoff.py'),
                       'rules_sha256': sha(engine / 'eda_modeling_rules.json'), 'species': len(context['species'])}
            navigation['modeling_input'] = handoff
            (root / 'review_navigation.json').write_text(json.dumps(navigation, indent=2, ensure_ascii=False), encoding='utf-8')
            for name in ('index.html', 'human_review.html'):
                page = root / name
                html = page.read_text(encoding='utf-8')
                page.write_text(html.replace('</nav>', '<a href="modeling_context.json">Modeling context by species</a></nav>', 1),
                                encoding='utf-8')
    finally:
        sys.dont_write_bytecode = previous_bytecode
        for name in list(sys.modules):
            if name == package_name or name.startswith(package_name + '.'):
                del sys.modules[name]
        sys.modules.update(old_modules)
    after = {p.relative_to(root).as_posix(): sha(p) for p in scientific}
    if before != after:
        raise RuntimeError('Portal publishing changed scientific JSON')
    provenance = {
        'version': 'NATIVE_EDA_PORTAL_PUBLICATION_1',
        'execution_scope': 'DESCRIPTIVE_EDA_ONLY',
        'owner': str(owner), 'owner_sha256': sha(frozen_owner),
        'owner_snapshot': frozen_owner.relative_to(root).as_posix(),
        'entrypoint': 'build_descriptive',
        'modules': {stage: {'snapshot': '_engine/eda_' + stage + '.py',
                            'sha256': sha(engine / ('eda_' + stage + '.py'))} for stage in STAGES},
        'scientific_json_sha256': after, 'scientific_json_unchanged': before == after,
        'collection_href': collection_href, 'figure_count': navigation['figure_count'],
        'figure_readings': {'figures': annotated_figures, 'display_source_sha256': display_sources},
        'live_workflow_registration': False, 'scientific_release': False,
    }
    if handoff is not None:
        provenance['modeling_input'] = handoff
    (root / 'portal_publication.json').write_text(json.dumps(provenance, indent=2, ensure_ascii=False), encoding='utf-8')
    record_path = root / 'run_record.json'
    if record_path.is_file():
        record = json.loads(record_path.read_text(encoding='utf-8-sig'))
        interface = record.get('interface') or {}
        if interface.get('publication') == 'portal_publication.json':
            interface['owner_sha256'] = provenance['owner_sha256']
            if handoff is not None:
                record['modeling_input'] = handoff
            record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding='utf-8')
    return provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--title')
    parser.add_argument('--collection-href')
    parser.add_argument('--owner', type=Path, default=NATIVE_OWNER)
    args = parser.parse_args()
    result = publish(args.root, title=args.title, collection_href=args.collection_href, owner=args.owner)
    print(json.dumps({'entry': str(args.root / 'index.html'), 'figures': result['figure_count'],
                      'scientific_json_unchanged': result['scientific_json_unchanged']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
