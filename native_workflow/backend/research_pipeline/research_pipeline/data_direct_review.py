"""Original Data JSON artifacts connected to the existing LangGraph human gate."""
import argparse
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .common import read_json, write_json, require_id, utcnow, FRONTEND
from .data_direct_runtime import file_ref, verify_refs
from .graph_control import ReviewController
from .workflow_canvas import Decision, fingerprint


def effective_assessment(value):
    """Select only the version explicitly bound by this approval's signature."""
    refs = {a['name']: {'path':a['path'],'sha256':a['sha256']} for a in value['artifacts']}
    ref = value['inputs'].get('effective_assessment', refs['necessity.json'])
    name = next((name for name in ('necessity.json','necessity.reviewed.json') if refs.get(name)==ref), None)
    if not name:
        raise ValueError('Effective assessment is not a bound Necessity artifact')
    if name == 'necessity.reviewed.json':
        item=read_json(ref['path'])
        if (item.get('editorial_review',{}).get('original') != refs['necessity.json']
                or item['editorial_review'].get('corrections') != refs.get('editorial_corrections.json')):
            raise ValueError('Effective assessment differs from its bound original/corrections')
    return name, ref


class DirectDataReview:
    def __init__(self, state, outputs):
        self.root = Path(state)/'direct_data_reviews'
        self.outputs = Path(outputs).resolve()
        self.graph = ReviewController(state)
        self.lock = threading.RLock()

    def path(self, identifier):
        return self.root/require_id(identifier)/'review.json'

    def publish(self, run):
        """Trusted executor registration; no browser-supplied results or approval."""
        from .data_coverage_direct import verify_result as coverage_result
        from .data_necessity_direct import verify_result as necessity_result
        run = Path(run).resolve()
        if not run.is_relative_to(self.outputs):
            raise ValueError('Data review artifacts must be inside project outputs')
        necessity_path = run/'necessity/necessity.json'
        if (run/'necessity_ref.json').exists():
            reference = read_json(run/'necessity_ref.json')
            verify_refs({'necessity': reference})
            necessity_path = Path(reference['path'])
        version = read_json(necessity_path).get('version')
        is_assessment = version in {'DIRECT_NECESSITY_2.0','DIRECT_NECESSITY_3.0','DIRECT_NECESSITY_4.0','DIRECT_NECESSITY_5.0','DIRECT_NECESSITY_6.0'}
        if is_assessment:
            from .data_necessity_assessment import verify_result as necessity_result
        if version == 'DIRECT_NECESSITY_3.0':
            from .data_necessity_decisions import verify_result as necessity_result
        if version == 'DIRECT_NECESSITY_4.0':
            from .data_necessity_scoped import verify_result as necessity_result
            from .data_coverage_scoped import verify_result as coverage_result
        if version == 'DIRECT_NECESSITY_5.0':
            from .data_necessity_scoped_v5 import verify_result as necessity_result
            from .data_coverage_scoped_v3 import verify_result as coverage_result
        if version == 'DIRECT_NECESSITY_6.0':
            from .data_necessity_scoped_v6 import verify_result as necessity_result
            from .data_coverage_scoped_v3 import verify_result as coverage_result
        nec = necessity_result(necessity_path)
        coverage_path = Path(nec['bindings']['coverage']['path'])
        cov = coverage_result(coverage_path)
        if nec['bindings']['coverage'] != file_ref(coverage_path):
            raise ValueError('Necessity belongs to a different Coverage result')
        if cov['execution']['test_generator'] or nec['execution']['test_generator']:
            raise ValueError('Synthetic results cannot enter the real human review queue')
        paths = {'coverage.json': coverage_path, 'necessity.json': necessity_path,
                 'report.json': run/'report.json', 'plan.json': Path(cov['bindings']['plan']['path']),
                 'main.json': Path(cov['bindings']['main']['path'])}
        for index, reference in enumerate(cov['provenance']['accepted_receipts'], 1):
            receipt = read_json(reference['path'])
            paths[f'coverage.model.{index}.json'] = Path(receipt['raw']['path'])
        paths['necessity.model.json'] = Path(read_json(necessity_path.parent/'call/accepted.json')['raw']['path'])
        if is_assessment:
            from .data_human_summary import verify_result as summary_result
            if read_json(run/'human_summary/summary.json').get('version') == 'DATA_HUMAN_SUMMARY_2.0':
                from .data_human_summary_v2 import verify_result as summary_result
            if read_json(run/'human_summary/summary.json').get('version') == 'DATA_HUMAN_SUMMARY_3.0':
                from .data_human_summary_v3 import verify_result as summary_result
            summary = summary_result(run/'human_summary/summary.json')
            if summary['bindings']['necessity'] != file_ref(necessity_path):
                raise ValueError('Summary belongs to a different Necessity result')
            if summary['execution']['test_generator']:
                raise ValueError('Synthetic results cannot enter the real human review queue')
            paths['summary.json'] = run/'human_summary/summary.json'
            paths['summary.model.json'] = Path(read_json(run/'human_summary/call/accepted.json')['raw']['path'])
        if (run/'editorial/necessity.reviewed.json').exists():
            from .data_necessity_editorial import verify_result as reviewed_result
            reviewed=reviewed_result(run/'editorial/necessity.reviewed.json')
            if reviewed['editorial_review']['original']!=file_ref(necessity_path):
                raise ValueError('Editorial review belongs to another Necessity result')
            paths['necessity.reviewed.json']=run/'editorial/necessity.reviewed.json'
            paths['editorial_corrections.json']=run/'editorial/editorial_corrections.json'
        artifacts = [{'name': name, **file_ref(path)} for name, path in paths.items()]
        if any(not Path(a['path']).is_relative_to(self.outputs) for a in artifacts):
            raise ValueError('Review artifacts must stay within project outputs')
        inputs = {key: cov['bindings'][key] for key in ('main', 'plan', 'source_view')}
        inputs['local_method_profiles'] = nec['bindings']['local_method_profiles']
        inputs['effective_assessment'] = file_ref(paths.get('necessity.reviewed.json', necessity_path))
        signature = fingerprint({'artifacts': artifacts, 'inputs': inputs})
        identifier = 'data_' + signature[:24]
        with self.lock:
            if self.path(identifier).exists():
                return self.view(identifier)
            main = read_json(inputs['main']['path'])
            gate = self.graph.begin(identifier, 'adequacy', signature,
                [{'name': a['name'], 'sha256': a['sha256']} for a in artifacts],
                [{key: r[key] for key in ('id', 'text', 'conditions', 'exceptions', 'scope') if key in r}
                 for r in main['rules']])
            value = {'id': identifier, 'created_at': utcnow(), 'output_signature': signature,
                     'artifacts': artifacts, 'inputs': inputs, 'gate': gate, 'review': None,
                     'scope': 'DATA_ASSESSMENT_REVIEW', 'source_run': str(run),
                     'scientific_approval': False, 'downstream_started': False}
            write_json(self.path(identifier), value)
            return self.view(identifier)

    def load(self, identifier):
        path = self.path(identifier)
        if not path.is_file():
            raise HTTPException(404, 'Data review not found')
        return read_json(path)

    @staticmethod
    def unchanged(value):
        try:
            verify_refs(value['inputs'])
            verify_refs({a['name']: {'path': a['path'], 'sha256': a['sha256']} for a in value['artifacts']})
            effective_assessment(value)
            return fingerprint({'artifacts': value['artifacts'], 'inputs': value['inputs']}) == value['output_signature']
        except (ValueError, OSError):
            return False

    def view(self, identifier):
        value = self.load(identifier)
        current = self.unchanged(value) and not value.get('superseded_by')
        return {'id': identifier, 'scope': value['scope'], 'output_signature': value['output_signature'],
                'status': 'SUPERSEDED' if value.get('superseded_by') else value['gate']['status'] if current else 'STALE',
                'superseded_by': value.get('superseded_by'),
                'can_review': current and value['gate']['status'] == 'INTERRUPTED',
                'approved': current and value['gate']['status'] == 'APPROVED',
                'review': value['review'], 'artifacts': [{k: a[k] for k in ('name', 'sha256')} for a in value['artifacts']],
                'effective_assessment_name': effective_assessment(value)[0] if current else None,
                'scientific_approval': False, 'downstream_started': False,
                'url': '/data-review/' + identifier}

    def artifact(self, identifier, name):
        value = self.load(identifier)
        if not self.unchanged(value):
            raise HTTPException(409, 'Original results or inputs changed; this review is stale.')
        artifact = next((a for a in value['artifacts'] if a['name'] == name), None)
        if not artifact:
            raise HTTPException(404, 'Artifact not in this review')
        return artifact

    def decide(self, identifier, decision):
        with self.lock:
            value = self.load(identifier)
            if value.get('superseded_by') or not self.unchanged(value) or decision.output_signature != value['output_signature']:
                raise HTTPException(409, 'Result or input version changed; review the current version.')
            if value['gate']['status'] != 'INTERRUPTED':
                raise HTTPException(409, 'This review has already been submitted.')
            if not decision.reviewer.strip():
                raise HTTPException(422, 'Enter the reviewer name.')
            if decision.decision != 'APPROVE' and len(decision.rationale.strip()) < 5:
                raise HTTPException(422, 'Give a specific reason when requesting changes or rejecting.')
            record = {key: value for key, value in decision.model_dump().items()
                      if key not in ('objective_decision', 'objective_correction')}
            record.update(at=utcnow(), scope='DATA_ASSESSMENT_REVIEW')
            value['gate'] = self.graph.resume(value['gate'], record)
            value['review'] = record
            write_json(self.path(identifier), value)
            write_json(self.path(identifier).parent/'decision.json', record)
            return self.view(identifier)


def router(store):
    result = APIRouter()

    @result.get('/data-review/{identifier}', include_in_schema=False)
    def page(identifier: str):
        store.load(identifier)
        return FileResponse(FRONTEND/'data-direct-review.html', media_type='text/html')

    @result.get('/ui-api/data-reviews/{identifier}')
    def status(identifier: str):
        return store.view(identifier)

    @result.get('/ui-api/data-reviews/{identifier}/artifacts/{name}')
    def artifact(identifier: str, name: str, download: bool = False):
        item = store.artifact(identifier, name)
        return FileResponse(item['path'], media_type='application/json',
                            filename=name if download else None)

    @result.post('/ui-api/data-reviews/{identifier}/review')
    def review(identifier: str, decision: Decision):
        return store.decide(identifier, decision)

    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--state', required=True)
    parser.add_argument('--outputs', required=True)
    args = parser.parse_args()
    import json
    print(json.dumps(DirectDataReview(args.state, args.outputs).publish(args.run), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
