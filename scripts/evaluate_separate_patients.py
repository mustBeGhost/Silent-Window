"""Evaluate frozen deployed models on a separately supplied, disjoint labelled cohort.

Default source is the public PhysioNet 2012 Set B. Cached downloads are excluded
from releases. No training, threshold tuning or model promotion is performed.
Run: python -m scripts.evaluate_separate_patients --download
"""
import argparse,hashlib,io,json,re,zipfile
from pathlib import Path
from datetime import datetime,timezone
from urllib.request import urlopen
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from backend.services.patient_service import get_patient_inference_service
from ml.alert_policy import probabilities_to_alert_timeline
from ml.data_loader import discover_patient_ids,parse_time_to_minutes
from ml.features import build_feature_matrix
from ml.preprocessing import preprocess_patient
from ml.coverage import usable_temporal_counts
from ml.error_review import summarize
ROOT=Path(__file__).resolve().parents[1]
SOURCE='https://physionet.org/files/challenge-2012/1.0.0/'

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def download(cache):
    cache.mkdir(parents=True,exist_ok=True)
    for name,limit in [('set-b.zip',12000000),('Outcomes-b.txt',200000)]:
        path=cache/name
        if not path.exists():
            with urlopen(SOURCE+name,timeout=60) as response:data=response.read(limit+1)
            if len(data)>limit:raise ValueError('Unexpected public download size')
            path.write_bytes(data)

def read_cohort(archive,outcomes,excluded):
    target=pd.read_csv(outcomes)
    if not {'RecordID','In-hospital_death'}<=set(target) or target.RecordID.duplicated().any() or target.RecordID.isna().any() or not target['In-hospital_death'].isin([0,1]).all():raise ValueError('Unique patient IDs and complete binary mortality labels are required')
    if not np.equal(target.RecordID,target.RecordID.astype(int)).all():raise ValueError('Patient IDs must be integers')
    target=target.set_index('RecordID').sort_index()
    if set(target.index)&set(excluded):raise ValueError('Evaluation patients overlap existing local patients; refusing a reused test')
    patients={}
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if info.is_dir():continue
            if not re.fullmatch(r'(?:set-b/)?[0-9]{6}\.txt',info.filename):raise ValueError('Unexpected archive member')
            if info.file_size>1000000:raise ValueError('Unexpected patient file size')
            patient_id=int(Path(info.filename).stem)
            if patient_id in patients:raise ValueError('Duplicate patient record')
            frame=pd.read_csv(io.BytesIO(z.read(info)))
            if set(frame.columns)!={'Time','Parameter','Value'}:raise ValueError('Unexpected observation format')
            frame['Time_minutes']=frame.Time.apply(parse_time_to_minutes)
            frame['Value']=pd.to_numeric(frame.Value,errors='raise')
            if np.isinf(frame.Value.to_numpy(dtype=float)).any():raise ValueError('Infinite observation')
            recorded=frame.loc[frame.Parameter=='RecordID','Value'].tolist()
            if recorded!=[patient_id]:raise ValueError('Patient identity differs from its file')
            patients[patient_id]=preprocess_patient(frame.sort_values('Time_minutes',kind='stable'))
    if set(patients)!=set(target.index):raise ValueError('Observation and outcome membership must match exactly')
    return patients,target['In-hospital_death'].astype(int)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download',action='store_true')
    parser.add_argument('--cache',type=Path,default=ROOT/'.release-check/physionet-2012-set-b')
    parser.add_argument('--archive',type=Path)
    parser.add_argument('--outcomes',type=Path)
    parser.add_argument('--source-description',help='Required provenance label for user-supplied files')
    parser.add_argument('--source-url')
    parser.add_argument('--source-license')
    parser.add_argument('--website-summary',type=Path,help='Optionally write an aggregate frontend JSON summary')
    parser.add_argument('--output',type=Path,default=ROOT/'data/processed/evaluation_v3/separate_patient_metrics.json')
    args=parser.parse_args()
    if bool(args.archive)!=bool(args.outcomes):parser.error('Supply both --archive and --outcomes')
    if args.archive and not args.source_description:parser.error('Describe the source with --source-description')
    if args.website_summary and args.website_summary.exists():raise RuntimeError('Refuse to overwrite an existing website evaluation summary')
    if args.output.exists():raise RuntimeError('Refuse to overwrite an examined evaluation; use a new explicit output path if intentionally repeating')
    if args.download:download(args.cache)
    archive=args.archive or args.cache/'set-b.zip';outcomes=args.outcomes or args.cache/'Outcomes-b.txt'
    protected={p:digest(p) for p in (ROOT/'ml/artifacts').rglob('*') if p.is_file()}
    patients,target=read_cohort(archive,outcomes,discover_patient_ids())
    ids=list(target.index);labels=target.to_numpy()
    print(f'Evaluating {len(ids)} disjoint labelled patients with fixed saved models. No fitting or threshold tuning.',flush=True)
    matrices={};cutoffs={'6h':360,'9h':540,'12h':720,'18h':1080,'24h':1440}
    for checkpoint,minute in cutoffs.items():
        print('Building prefix-only features at '+checkpoint,flush=True)
        matrices[checkpoint]=build_feature_matrix(ids,patients,minute,version=2)
    results={}
    with threadpool_limits(limits=1):
        for profile in ('original','calibrated','expanded'):
            service=get_patient_inference_service(profile)
            checkpoints=list(service.cutoffs)
            scores=[]
            for checkpoint in checkpoints:
                model=service.models[checkpoint]
                workers={key:1 for key in model.get_params(deep=True) if key=='n_jobs' or key.endswith('__n_jobs')}
                if workers:model.set_params(**workers)
                X=matrices[checkpoint];covered=usable_temporal_counts(X)>0
                score=np.full(len(X),np.nan)
                score[covered]=model.predict_proba(X.loc[covered])[:,service.positive_class_indices[checkpoint]]
                scores.append(score)
            scores=np.array(scores).T
            states=np.array([[point['alert_state'] for point in probabilities_to_alert_timeline([None if not np.isfinite(s) else float(s) for s in row],service.medium_threshold,service.high_threshold)] for row in scores],dtype=object)
            checkpoints_report={}
            for k,cp in enumerate(checkpoints):
                summary=summarize(labels,scores[:,k],states[:,k])
                groups={}
                for icu in (1,2,3,4):
                    mask=matrices[cp].ICUType.to_numpy()==icu
                    groups['icu_'+str(icu)]=summarize(labels[mask],scores[mask,k],states[mask,k])
                counts=usable_temporal_counts(matrices[cp]).to_numpy()
                for name,mask in [('observations_1_to_10',(counts>0)&(counts<=10)),('observations_over_10',counts>10),('age_below_65',matrices[cp].Age.to_numpy()<65),('age_65_or_more',matrices[cp].Age.to_numpy()>=65)]:
                    groups[name]=summarize(labels[mask],scores[mask,k],states[mask,k])
                checkpoints_report[cp]={**summary,'descriptive_groups':groups}
                print(profile+' '+cp+': '+json.dumps({key:summary.get(key) for key in ('scored','any_warning','high_alert')}),flush=True)
            results[profile]={'medium_threshold':service.medium_threshold,'high_threshold':service.high_threshold,'checkpoints':checkpoints_report}
    if any(digest(path)!=value for path,value in protected.items()):raise RuntimeError('A saved artifact changed')
    report={'status':'FIXED_MODEL_SEPARATE_PATIENT_EVALUATION_NOT_CLINICALLY_VALIDATED','completed_at_utc':datetime.now(timezone.utc).isoformat(),'source_url':args.source_url or (SOURCE if not args.archive else None),'evaluation_source_sha256':{name:digest(ROOT/name) for name in ('scripts/evaluate_separate_patients.py','ml/error_review.py','ml/features.py','ml/preprocessing.py','ml/coverage.py','ml/alert_policy.py','backend/services/patient_service.py')},'source_license':args.source_license or ('Open Data Commons Attribution License v1.0' if not args.archive else 'Not provided'),'source_paper':'Silva et al. Predicting In-Hospital Mortality of Patients in ICU: The PhysioNet/Computing in Cardiology Challenge 2012. Computing in Cardiology 2012;39:245-248.','cohort':'PhysioNet Challenge 2012 Set B' if not args.archive and not args.outcomes else args.source_description,'archive_sha256':digest(archive),'outcomes_sha256':digest(outcomes),'patients':len(ids),'death_labels':int(labels.sum()),'overlap_with_existing_local_patients':0,'fitting_performed':False,'threshold_tuning_performed':False,'model_artifact_sha256':{path.relative_to(ROOT).as_posix():value for path,value in protected.items()},'results':results,'limitations':['Patient-disjoint same-source evaluation; not independent-hospital or prospective validation.','This cohort has now been examined. Do not treat it as untouched for later model selection.','No exact death or ICU discharge timestamps establish checkpoint eligibility.','Recall among scored patients is separate from detection among all death labels; unscored deaths are reported.','Subgroups are descriptive, may be small and overlapping, and do not explain causes or establish fairness.','No patient-level scores or identifiers are saved. Saved models and alert thresholds were not changed.']}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    if args.website_summary:
        keys=('status','completed_at_utc','source_url','source_license','cohort','patients','death_labels','overlap_with_existing_local_patients','fitting_performed','threshold_tuning_performed','results','limitations')
        args.website_summary.parent.mkdir(parents=True,exist_ok=True)
        args.website_summary.write_text(json.dumps({key:report[key] for key in keys},indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('Saved aggregate report: '+str(args.output),flush=True)
if __name__=='__main__':main()
