"""Demo API over original backend components; local notes use a separate store."""
import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .services import Catalog, read, sha
from .store import ReviewStore


class RetrievalRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    stage: Literal['data_eda', 'animal_pk', 'pkpd', 'translation', 'human_simulation', 'pta'] = 'data_eda'
    budget: int = Field(default=32768, ge=1000, le=48000)
    objective: str = Field(default='Assess source-specific nonhuman PK data for descriptive EDA and identify prerequisites for later PK modeling.', min_length=5, max_length=2000)
    allow_draft: Literal[True]
    branches: list[Literal['antibacterial', 'hepatic_ivive', 'turnover_pd', 'renal_clearance', 'dynamic_time_kill']] = Field(default_factory=list, max_length=5)


class NoteRequest(BaseModel):
    code: str = Field(max_length=120)
    affected_id: str = Field(max_length=80)
    report_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    reviewer: str = Field(min_length=1, max_length=100)
    decision: Literal['NEEDS_SOURCE', 'REQUEST_REVISION', 'ACKNOWLEDGE_LIMITATION']
    rationale: str = Field(min_length=5, max_length=5000)


def create_app(root, state):
    from research_pipeline.workbench import create_workbench, current_frontend_html
    catalog = Catalog(root)
    store = ReviewStore(state)
    app = create_workbench(outputs=state / 'workbench_outputs', state=state / 'workbench_state')
    app.state.canvas.require_final_data_review = True
    app.title = 'Translational PK/PD Demo'
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])
    # Reuse the original workbench at /workbench; the curated demo owns the entry route.
    app.router.routes[:] = [route for route in app.router.routes if getattr(route, 'path', None) != '/']

    @app.middleware('http')
    async def demo_boundary(request: Request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if origin and urlparse(origin).netloc != request.url.netloc:
                return JSONResponse({'detail': 'Cross-origin writes are not allowed.'}, 403)
            if request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse({'detail': 'Cross-site writes are not allowed.'}, 403)
            path = request.url.path
            live_write = (path.startswith('/workspace-api/') or path.startswith('/ui-api/workflow/')
                          or path in {'/pipeline/v1/attachments', '/pipeline/v1/intakes', '/pipeline/v1/data-preparation/source-tables', '/ui-api/jobs'}
                          or (path.startswith('/ui-api/jobs/') and path.endswith(('/resume', '/pause', '/pre-eda'))))
            # This demonstration ends at Data. Native gates remain authoritative.
            if '/nodes/' in path and path.endswith('/start') and path.split('/nodes/')[1].split('/')[0] not in {'intake', 'context', 'adequacy', 'prepare'}:
                return JSONResponse({'detail': 'This demo runs through Data only. This downstream stage is not enabled.'}, 409)
            if path not in {'/demo-api/retrieve', '/demo-api/context', '/demo-api/reviews'} and not live_write:
                return JSONResponse({'detail': 'This operation is not exposed by the demo. Use the connected workflow controls for execution and review through Data.'}, 403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/', include_in_schema=False)
    def home():
        return FileResponse(root / 'workspace/index.html')

    @app.get('/workbench', include_in_schema=False)
    def workbench():
        html = current_frontend_html()
        banner = '<div style="padding:14px;background:#eef4e9;text-align:center">Live workflow controls · intake through Data. <a href="/">Return to the two-workstream workspace →</a></div>'
        return HTMLResponse(html.replace('<body data-screen="canvas">', '<body data-screen="canvas">' + banner))

    @app.get('/demo-api/health')
    def health():
        return {'status': 'OK', 'mode': 'DEMO', 'demo_version': 'connected-20261019',
                'backend': 'research_pipeline.workbench', 'context_builder': 'CONTEXT_BUILDER_2.1'}

    @app.get('/demo-api/summary')
    def summary():
        return catalog.summary()

    @app.get('/demo-api/cards')
    def cards(q: str = '', stage: str = ''):
        return [c for c in catalog.cards if (not stage or stage in c.get('topics', []))
                and (not q or q.casefold() in json.dumps(c, ensure_ascii=False).casefold())]

    @app.get('/demo-api/sources')
    def sources():
        return catalog.sources

    def retrieve_result(body):
        try:
            return catalog.retrieve(body.query, body.stage, body.budget, body.objective, body.allow_draft, body.branches)
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post('/demo-api/retrieve')
    def retrieve(body: RetrievalRequest):
        return retrieve_result(body)

    @app.post('/demo-api/context')
    def context(body: RetrievalRequest):
        try:
            packet = retrieve_result(body)
            return {'retrieval': packet, 'bundle': catalog.context(packet), 'model_calls': 0}
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get('/demo-api/datasets')
    def datasets():
        return catalog.datasets

    @app.get('/demo-api/findings')
    def findings():
        return {'report_sha256': sha(catalog.report_path), 'findings': catalog.report()['findings']}

    @app.get('/demo-api/reviews')
    def reviews():
        return store.list()

    @app.get('/demo-api/reviews/export')
    def export():
        return Response(json.dumps({'scope': 'DEMO_REVIEW_NOTES_ONLY', 'scientific_approval': False,
                                   'notes': store.list()}, indent=2, ensure_ascii=False),
                        media_type='application/json', headers={'Content-Disposition': 'attachment; filename=demo-review-notes.json'})

    @app.post('/demo-api/reviews', status_code=201)
    def save_review(body: NoteRequest):
        if not body.reviewer.strip() or len(body.rationale.strip()) < 5:
            raise HTTPException(422, 'Reviewer and substantive rationale are required.')
        if body.report_sha256 != sha(catalog.report_path):
            raise HTTPException(409, 'Source report changed. Reload the findings before adding a note.')
        if not any(f['code'] == body.code and f['affected_id'] == body.affected_id for f in catalog.report()['findings']):
            raise HTTPException(422, 'Unknown finding.')
        return store.append(body.model_dump())

    @app.get('/demo-api/gallery')
    def gallery():
        pk = read(root / 'examples/pk/figure_manifest.json')
        figures = [{'title': f['title'], 'kind': f['kind'], 'url': '/examples/pk/' + Path(f['png']['path']).name} for f in pk['figures']]
        figures[:0] = [{'title': 'EDA subset test · ' + p.stem, 'kind': 'EDA_TEST_VISUAL_FINDINGS',
                       'url': '/examples/eda/ev/' + p.name} for p in sorted((root / 'examples/eda/ev').glob('*.png'))]
        return figures

    from .connected import connect_workspace
    connect_workspace(app, root, state)
    app.mount('/workspace-assets', StaticFiles(directory=root / 'workspace'), name='workspace-assets')
    app.mount('/recorded', StaticFiles(directory=root / 'examples/review', html=True), name='recorded')
    app.mount('/examples', StaticFiles(directory=root / 'examples', html=True), name='examples')
    app.mount('/knowledge-files', StaticFiles(directory=root / 'knowledge'), name='knowledge-files')
    app.mount('/documents', StaticFiles(directory=root / 'docs'), name='documents')
    return app
