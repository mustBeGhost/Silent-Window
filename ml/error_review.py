"""Aggregate fixed-policy model diagnostics, without retaining patient scores."""
import numpy as np
from sklearn.metrics import roc_auc_score,average_precision_score,brier_score_loss

def warning_counts(labels,warned):
    y=np.asarray(labels)
    w=np.asarray(warned,dtype=bool)
    if y.ndim!=1 or w.shape!=y.shape or not np.isin(y,[0,1]).all():raise ValueError('Expected aligned binary labels and warning flags')
    deaths=y==1;survivors=~deaths
    tp=int((w&deaths).sum());fn=int((~w&deaths).sum());fp=int((w&survivors).sum());tn=int((~w&survivors).sum())
    return {'detected_deaths':tp,'missed_deaths':fn,'survivor_warnings':fp,'survivors_without_warning':tn,
      'recall':tp/(tp+fn) if tp+fn else None,'precision':tp/(tp+fp) if tp+fp else None,'survivor_warning_rate':fp/(fp+tn) if fp+tn else None}

def summarize(labels,scores,states):
    y=np.asarray(labels);s=np.asarray(scores,dtype=float);states=np.asarray(states,dtype=object)
    if s.shape!=y.shape or states.shape!=y.shape or not np.isin(y,[0,1]).all():raise ValueError('Misaligned evaluation rows')
    if np.isinf(s).any():raise ValueError('Infinite model scores')
    covered=np.isfinite(s)
    if ((s[covered]<0)|(s[covered]>1)).any():raise ValueError('Invalid model scores')
    if any((state not in {'NO_ALERT','WATCH','HIGH_ALERT'}) for state in states[covered]):raise ValueError('Unknown alert state')
    if any(state is not None for state in states[~covered]):raise ValueError('Missing scores must have no alert state')
    result={'patients':len(y),'death_labels':int(y.sum()),'scored':int(covered.sum()),'not_scored':int((~covered).sum()),'unscored_death_labels':int(y[~covered].sum())}
    if covered.any():
        for name,warning in [('any_warning',np.isin(states[covered],['WATCH','HIGH_ALERT'])),('high_alert',states[covered]=='HIGH_ALERT')]:
            result[name]=warning_counts(y[covered],warning)
            result[name]['detected_fraction_of_all_death_labels']=result[name]['detected_deaths']/int(y.sum()) if y.sum() else None
        result['brier_score']=float(brier_score_loss(y[covered],s[covered]))
        result['roc_auc']=float(roc_auc_score(y[covered],s[covered])) if len(np.unique(y[covered]))==2 else None
        result['average_precision']=float(average_precision_score(y[covered],s[covered])) if (y[covered]==1).any() else None
    return result
