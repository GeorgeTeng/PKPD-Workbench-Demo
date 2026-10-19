"""Prepare the existing reviewed-context Data entry; never start Data or create approval."""
import argparse
import json
from pathlib import Path

from ctxcomp.handoff import verify_main
from .adequacy import check_ref, file_ref, import_reviewed_context
from .common import PipelineError, read_json, write_json, utcnow


def _references(main):
    """Validate bytes only; no attachment interpretation, sheet parsing or model calls."""
    verify_main(main)
    refs=[]
    for item in main['data']['files']:
        refs.append({'id':item['id'], 'role':item['role'], 'path':item['path'], 'sha256':item['sha256']})
        if item.get('snapshot_path'):
            snapshot={'path':item['snapshot_path'],'sha256':item['snapshot_sha256']}
            check_ref(snapshot);refs.append({'id':item['id']+':snapshot',**snapshot})
    return refs


def prepare(main_path, output, approval_path=None):
    """Write a pending receipt, or import through the unchanged real Data input function."""
    output=Path(output).resolve();main_ref=file_ref(main_path);main=read_json(main_ref['path'])
    if output.exists() and any(output.iterdir()):
        raise PipelineError('HANDOFF_OUTPUT_EXISTS','Use a new empty handoff directory; preserve earlier receipts.')
    refs=_references(main);pending=[];approval_ref=None;approval=None;approved_main=None;pack=None
    if approval_path:
        from .workflow_canvas import CanvasStore, fingerprint
        approval_ref=file_ref(approval_path);approval=read_json(approval_ref['path']);node=approval['context']
        for artifact in node['artifacts']:check_ref(artifact)
        if node.get('output_signature')!=fingerprint(node['artifacts']):
            raise PipelineError('CONTEXT_APPROVAL_CHANGED','Context artifact signature does not match its approval.')
        approved_main=next(a for a in node['artifacts'] if a['name']=='main.json')
        if not CanvasStore.approved(node):pending.append('PENDING_CONTEXT_APPROVAL')
        if approval.get('scope_amendment'):
            raise PipelineError('HANDOFF_SCOPE_AMENDMENT','Provide the final reviewed context and matching published rules; this handoff does not apply amendments.')
    else:pending.append('PENDING_CONTEXT_APPROVAL')
    rules_ref=(approval or {}).get('project_rules_ref') or main.get('project_rules_ref')
    if not rules_ref:
        pending.append('PENDING_PROJECT_RULES')
    else:
        from .project_rule_agent import verify_published
        pack=verify_published(rules_ref)
        if main.get('project_rules_ref') and main['project_rules_ref']!=rules_ref:
            raise PipelineError('PROJECT_RULES_CONTEXT_MISMATCH','Input main and approval refer to different rule packs.')
        if main_ref['sha256'] not in {pack['base_main_ref']['sha256'],pack['main_ref']['sha256']}:
            raise PipelineError('PROJECT_RULES_CONTEXT_MISMATCH','Published rules do not belong to the supplied main.')
        if approved_main and approved_main['sha256']!=pack['base_main_ref']['sha256']:
            raise PipelineError('PROJECT_RULES_CONTEXT_MISMATCH','Approval must bind the exact base main used by the published rules.')
        _references(read_json(pack['main_ref']['path']))
        # The unchanged consumer only discovers rules in the approval or its approved main.
        if approval and not (approval.get('project_rules_ref') or read_json(approved_main['path']).get('project_rules_ref')):
            pending.append('PENDING_RULES_LINK_IN_CONTEXT_APPROVAL')
    if approved_main:
        expected={approved_main['sha256']} | ({pack['main_ref']['sha256']} if pack else set())
        if main_ref['sha256'] not in expected:
            raise PipelineError('CONTEXT_APPROVAL_MISMATCH','Supplied main is not the context bound by this approval.')
    receipt={'schema_version':'1.0','at':utcnow(),'workflow':'MAIN_TO_DATA_ENTRY',
        'consumer':'research_pipeline.adequacy.import_reviewed_context',
        'source_main_ref':main_ref,'approval_ref':approval_ref,'project_rules_ref':rules_ref,
        'reference_checks':refs,'pending':pending,'status':'PENDING' if pending else 'IMPORTED_AT_DATA_ENTRY',
        'data_input_ref':None,'source_main_preserved':True,'data_started':False,
        'data_adequacy_assessed':False,'scientific_results_accepted':False,
        'scope':'Complete main transfer only; no regimen extraction, rule adoption, data processing or model call.'}
    if not pending:
        imported_path=output/'B1/main.json'
        imported=import_reviewed_context(approval_ref,imported_path)
        expected=read_json(pack['main_ref']['path'])
        if imported!=expected or read_json(imported_path)!=expected:
            raise PipelineError('HANDOFF_IMPORT_CHANGED','Data entry differs from the complete published main.')
        receipt['reference_checks']=_references(imported)
        receipt['data_input_ref']=file_ref(imported_path)
        receipt['provenance_ref']=file_ref(output/'B1/context_provenance.json')
    check_ref(main_ref)
    if approval_ref:check_ref(approval_ref)
    write_json(output/'handoff_receipt.json',receipt)
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--main',required=True,help='Final compression or matching published effective main.json')
    parser.add_argument('--approval',help='Existing genuine Context approval artifact; never synthesized here')
    parser.add_argument('--out',required=True,help='New handoff directory')
    args=parser.parse_args()
    print(json.dumps(prepare(args.main,args.out,args.approval),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
