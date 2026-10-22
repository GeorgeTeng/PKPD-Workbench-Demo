import os
import secrets
from uuid import uuid4
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, UploadFile, File, Depends, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from jsonschema import ValidationError
from . import __version__
from .attachments import store_upload, uploaded_path
from .common import PipelineError, read_json, state_root, require_id
from .engine import run_pipeline, SCHEMAS
from .literature import search, LocalLibrary
from .references import evaluate_reference
from .data_preparation import submit_review


class SearchRequest(BaseModel):
    provider: Literal["online","local"]
    query: str = Field(min_length=1,max_length=1000)
    drug: str = Field(min_length=1)
    limit: int = Field(default=10,ge=1,le=50)


class IndexRequest(BaseModel):
    upload_ids: list[str] = Field(min_length=1,max_length=100)


class ReferenceRequest(BaseModel):
    card_upload_id: str
    source_upload_ids: list[str]
    drug: str
    metadata: dict = Field(default_factory=dict)


class IntakeRequest(BaseModel):
    package_upload_id: str
    reference_only: list[str] = Field(default_factory=list)


class SourcePreparationRequest(BaseModel):
    intake_id: str
    table_plan: dict = Field(default_factory=dict)


def create_app(state=None):
    root = state_root(state)
    def authenticate(authorization: str | None = Header(default=None)):
        token = os.getenv("RESEARCH_PIPELINE_API_TOKEN")
        if token and not secrets.compare_digest(authorization or "", "Bearer "+token):
            raise HTTPException(401,"Invalid API token")
    app = FastAPI(title="PK/PD Research Pipeline",version=__version__,dependencies=[Depends(authenticate)])

    @app.exception_handler(PipelineError)
    async def pipeline_error(request,exc):
        return JSONResponse(status_code=409 if exc.code=="RUN_EXISTS" else 422,
            content={"status":"FAILED","errors":[{"code":exc.code,"message":str(exc)}]})

    @app.exception_handler(ValidationError)
    async def schema_error(request,exc):
        return JSONResponse(status_code=422,content={'status':'FAILED','errors':[{'code':'INVALID_JSON_CONTRACT','message':exc.message}]})

    @app.get("/v1/health")
    def health():
        return {"status":"OK","version":__version__,"modules":["data_preparation","pk_longitudinal","pkpd_index"]}

    @app.get("/v1/schemas/{name}")
    def schema(name:str):
        if name not in ("request","module-output","data-preparation","data-review"):
            raise HTTPException(404,"Unknown schema")
        return read_json(SCHEMAS/(name+".schema.json"))

    @app.post("/v1/attachments")
    def upload(file:UploadFile=File(...)):
        try:
            return store_upload(root,file.file,file.filename)
        finally:
            file.file.close()

    @app.post("/v1/runs")
    def run(request:dict):
        """Synchronous JSON execution. Contract: GET /v1/schemas/request. Uploaded IDs only."""
        return run_pipeline(request,root,allow_paths=False)

    @app.post('/v1/intakes')
    def intake(request:IntakeRequest):
        from ctxcomp.intake import intake_files
        identifier = 'intake_' + uuid4().hex
        try:
            result = intake_files(root/'intakes'/identifier, package=uploaded_path(root,request.package_upload_id),
                                  reference_only=request.reference_only)
        except (ValueError, OSError) as error:
            raise PipelineError('INTAKE_FAILED', str(error)) from error
        return {'status': 'READ_COMPLETE', 'intake_id':identifier, 'manifest':result['manifest'],
                'context_generation':'NOT_RUN', 'scientific_qc':'NOT_RUN'}

    @app.post('/v1/data-preparation/source-tables')
    def source_tables(request:SourcePreparationRequest):
        from .source_preparation import prepare_sources
        require_id(request.intake_id)
        manifest = root/'intakes'/request.intake_id/'manifest.json'
        if not manifest.is_file():
            raise PipelineError('INTAKE_NOT_FOUND', request.intake_id)
        identifier = 'sourceprep_' + uuid4().hex
        result = prepare_sources(manifest, root/'source_preparations'/identifier, request.table_plan or None)
        return {'source_preparation_id':identifier, **result}

    @app.get('/v1/source-preparations/{preparation_id}/files/{artifact_path:path}')
    def source_artifact(preparation_id:str, artifact_path:str):
        require_id(preparation_id)
        base=(root/'source_preparations'/preparation_id).resolve()
        path=(base/artifact_path).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            raise HTTPException(404,'Artifact not found')
        return FileResponse(path, filename=path.name)

    @app.post("/v1/modules/{module}/run")
    def module_run(module:str,request:dict):
        if module not in ("data_preparation","pk_longitudinal","pkpd_index") or len(request.get("steps",[]))!=1 or request["steps"][0].get("module")!=module:
            raise PipelineError("MODULE_REQUEST", "Supply exactly one step matching this endpoint's module.")
        return run_pipeline(request,root,allow_paths=False)

    @app.get("/v1/runs/{request_id}")
    def result(request_id:str):
        require_id(request_id)
        path=root/"runs"/request_id/"output.json"
        if not path.is_file():
            raise HTTPException(404,"Run not found")
        return read_json(path)

    @app.get("/v1/runs/{request_id}/files/{artifact_path:path}")
    def artifact(request_id:str,artifact_path:str):
        require_id(request_id)
        base=(root/"runs"/request_id).resolve(); path=(base/artifact_path).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            raise HTTPException(404,"Artifact not found")
        return FileResponse(path,filename=path.name)

    @app.post("/v1/search")
    def find(request:SearchRequest):
        return search(request.provider,request.query,root,request.limit,request.drug)

    @app.post('/v1/data-reviews')
    def data_review(submission:dict):
        return submit_review(root,submission)

    @app.post("/v1/library/index")
    def index(request:IndexRequest):
        library=LocalLibrary(root/"library.sqlite3")
        return {"results":[library.index_file(uploaded_path(root,i)) for i in request.upload_ids]}

    @app.get("/v1/library/status")
    def library_status():
        return LocalLibrary(root/"library.sqlite3").status()

    @app.post("/v1/references/evaluate")
    def reference(request:ReferenceRequest):
        from .common import sha256
        card=read_json(uploaded_path(root,request.card_upload_id))
        hashes=[sha256(uploaded_path(root,i)) for i in request.source_upload_ids]
        return evaluate_reference(card,request.drug,request.metadata,hashes)
    return app


app=create_app()
