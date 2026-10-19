"""Recheck actual prepared files for the three requested indices; stop before fitting on gaps."""
import argparse
import os
from pathlib import Path
from research_pipeline.common import read_json, write_json, sha256, utcnow
from research_pipeline.index_screening import screen_index_dataset, PRIMARY_SPECS, EXPANDED_SPECS


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    source_group=parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument('--prepared',type=Path)
    source_group.add_argument('--prepared-manifest',type=Path,help='Scoped index handoff; only listed files are read')
    parser.add_argument('--previous-inventory',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--expanded',action='store_true',help='Also screen declared free trough/MIC and percent fT>4MIC candidates')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    log={'status':'RUNNING','started_at':utcnow(),'pid':os.getpid(),'script_sha256':sha256(__file__)}
    write_json(out/'execution.json',log)
    try:
        specs=EXPANDED_SPECS if args.expanded else PRIMARY_SPECS
        write_json(out/'candidate_specifications.json',{'concentration_basis':'free','candidates':specs,
          'policy':'Primary and exploratory comparisons remain separate; thresholds are declared before fitting, not optimized on observed response.',
          'calculation_status':'No new exposure values calculated; requires supplied or upstream-computed indices with provenance.',
          'same_drug_primary_support':['https://pmc.ncbi.nlm.nih.gov/articles/PMC5890666/','https://pmc.ncbi.nlm.nih.gov/articles/PMC10377753/'],
          'exploratory_support':'Additional hypotheses for review, not established preferred PMB indices.'})
        prior={Path(r['file']['path']).name:r['file']['sha256'] for r in read_json(args.previous_inventory)['datasets']}
        assessments=[]
        if args.prepared_manifest:
            selected=read_json(args.prepared_manifest)['datasets']
            for item in selected:
                if sha256(item['file']['path'])!=item['file']['sha256']: raise ValueError('Index input changed: '+item['id'])
            paths=[Path(item['file']['path']) for item in selected]
        else: paths=sorted(args.prepared.glob('*.json'))
        for path in paths:
            before=sha256(path);d=read_json(path);a=screen_index_dataset(d,specs)
            # Missing optional columns must not veto the primary three-index screen.
            a['primary_screen']=screen_index_dataset(d,PRIMARY_SPECS)
            if sha256(path)!=before: raise ValueError('Source changed during read: '+str(path))
            a.update(source={'path':str(path.resolve()),'sha256':before},unchanged_since_previous_review=prior.get(path.name)==before)
            assessments.append(a)
        if not assessments: raise ValueError('No prepared dataset JSON files found')
        candidates=[a for a in assessments if a['primary_screen']['status']=='CANDIDATE_REQUIRES_HUMAN_REVIEW']
        write_json(out/'dataset_screening.json',{'assessments':assessments})
        result={'schema_version':'1.0','status':'BLOCKED_NO_ELIGIBLE_MATCHED_DATA' if not candidates else 'WAITING_FOR_HUMAN_REVIEW',
          'requested_indices':[s['name'] for s in specs],'regression_families':['Emax_h_fixed_1','Hill_h_estimated'],
          'primary_indices':[s['name'] for s in PRIMARY_SPECS],
          'primary_complete_rows':sum(a['primary_screen']['n_complete_index_response_rows'] for a in assessments),
          'expanded_candidate_files':[a['source'] for a in assessments if a['status']=='CANDIDATE_REQUIRES_HUMAN_REVIEW'],
          'candidate_specifications':{'path':str(out/'candidate_specifications.json'),'sha256':sha256(out/'candidate_specifications.json')},
          'datasets_screened':len(assessments),'complete_index_response_rows':sum(a['n_complete_index_response_rows'] for a in assessments),
          'changed_or_new_files':[Path(a['source']['path']).name for a in assessments if not a['unchanged_since_previous_review']],
          'ready_candidates':[a['source'] for a in candidates],'best_index':None,'ranking':[],
          'fitting_executed':False,'raw_concentration_substitution':False,
          'missing_input':'Matched regimen/unit + strain MIC + common efficacy endpoint + three documented free-exposure indices (or matched PK profiles/model and binding data to calculate them).',
          'screening_attachment':{'path':str(out/'dataset_screening.json'),'sha256':sha256(out/'dataset_screening.json')},
          'human_review':{'decision':'PENDING','approved_for_downstream_use':False},
          'rule_limit':'An input eligibility check, not a universal sample-size rule or a model reliability approval.'}
        write_json(out/'index_output.json',result)
        log.update(status=result['status'],output_sha256=sha256(out/'index_output.json'))
    except Exception as exc:
        log.update(status='STOPPED_ON_ERROR',error=str(exc));raise
    finally:
        log['finished_at']=utcnow();write_json(out/'execution.json',log)
    print(result['status'],f"datasets={len(assessments)} complete_rows={result['complete_index_response_rows']}")


if __name__=='__main__':
    main()
