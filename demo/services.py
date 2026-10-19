"""Read-only evidence catalog and adapters to the existing RAG and ContextBuilder."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Catalog:
    def __init__(self, root):
        self.root = root
        self.library = root / 'knowledge'
        self.review = root / 'examples/review'
        self.report_path = self.review / 'evidence/latest_run/data_preparation/data_report.json'
        self.cards = read(self.library / 'cards.json')
        self.sources = read(self.library / 'source_registry.json')
        self.by_id = {c['id']: c for c in self.cards}
        with (self.review / 'dataset_status.csv').open(encoding='utf-8-sig', newline='') as stream:
            self.datasets = list(csv.DictReader(stream))
        spec = importlib.util.spec_from_file_location('demo_pinned_library', self.library / 'layered_context.py')
        self.rag = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.rag)

    def report(self):
        return read(self.report_path)

    def summary(self):
        report = self.report()
        return {'name': 'Translational PK/PD Workbench', 'mode': 'CONNECTED_DEMO_THROUGH_DATA',
                'library': {'cards': len(self.cards), 'sources': len(self.sources),
                            'method_cards': sum(c.get('knowledge_layer') in {'general_method', 'conditional_method'} for c in self.cards),
                            'snapshot': 'round12_general_reviewed_v1', 'scientific_approval': False},
                'data': {'datasets': len(self.datasets), 'retained_rows': sum(int(d['retained_records']) for d in self.datasets),
                         'source_rows': sum(int(d['source_records']) for d in self.datasets),
                         'quarantined_rows': sum(int(d['quarantined_records']) for d in self.datasets),
                         'status': report['status'], 'scope': report['execution_scope'],
                         'findings': len(report['findings']),
                         'human_review': sum(f['severity'] == 'HUMAN_REVIEW' for f in report['findings']),
                         'scientific_release': report['scientific_release'], 'fit_ready': report['fit_ready'],
                         'report_sha256': sha(self.report_path)},
                'eda': read(self.root / 'examples/eda/run_status.json'),
                'features': ['Live workflow through Data', 'Direct file intake without model calls',
                             'Original RAG adapter', 'Original ContextBuilder',
                             '58 source-bound tables', 'Persistent demo review notes', 'Recorded EDA / PK previews']}

    def retrieve(self, query, stage, budget, objective, allow_draft, branches):
        return self.rag.build_context(self.library, query=query, stage=stage,
            project_context={'objective': objective, 'scope': 'DEMO_TASK_NOT_PROJECT_APPROVAL'},
            allowed_source_ids=[s['id'] for s in self.sources if not s['id'].startswith('IN_')],
            branches=branches, allow_draft=allow_draft, character_budget=budget,
            max_methods=3, consumer_route='method_background')

    def context(self, packet):
        from research_pipeline import context_builder as cb
        project = self.review / 'evidence/upstream_human_review/artifacts/main.json'
        labels = self.review / 'evidence/latest_run/inputs/direct_labels.json'
        original = read(project)
        payload = {'stage': 'DR', 'operation': 'REQUIREMENT_PLAN_6.0',
            'instructions': 'Demonstrate requirements-context assembly. Use source-bound data descriptions and methodological background. Do not execute a model, infer source sufficiency, or grant approval. Historical project Rules are shown for inspection and require reconciliation before a new scientific run.',
            'project_context': packet['project_context'], 'project_rules': original['rules'],
            'method_knowledge': packet,
            'data_overviews': read(labels)['labels'],
            'overview_notes': ['Recorded run04 source labels; source files retain their historical references.',
                               'Historical project Rules are not a new approval. Demo scope: nonhuman descriptive data inspection.'],
            'scientific_approval': False}
        bindings = {'historical_project_snapshot': cb.file_ref(project),
                    'recorded_labels': cb.file_ref(labels), 'data_report': cb.file_ref(self.report_path)}
        for name in ['cards.json', 'chunks.jsonl', 'source_registry.json', 'retrieval_policy.json',
                     'reviewed_retrieval_metadata.json', 'layered_context.py']:
            bindings['knowledge:' + name] = cb.file_ref(self.library / name)
        for sid, source in packet['applicability_and_examples']['cited_originals'].items():
            bindings['source:' + sid] = cb.file_ref(self.library / source['local_path'])
        # The demonstrated output contract is explicit, not a production DR result.
        schema = {'type': 'object', 'properties': {'review_notes': {'type': 'array', 'items': {'type': 'string'}}},
                  'required': ['review_notes'], 'additionalProperties': False}
        bundle = cb.build_context('data', 'requirements', payload, schema, input_bindings=bindings)
        cb.verify_bundle(bundle)
        return bundle
