import numpy as np
import pytest
from ml.error_review import warning_counts,summarize

def test_error_review_keeps_unscored_deaths_separate_from_scored_misses():
    result=summarize([1,1,1,0,0],[.8,.1,np.nan,.7,.05],['HIGH_ALERT','NO_ALERT',None,'WATCH','NO_ALERT'])
    assert result['unscored_death_labels']==1 and result['scored']==4
    assert result['any_warning']['detected_deaths']==1 and result['any_warning']['missed_deaths']==1
    assert result['any_warning']['survivor_warnings']==1
    assert result['any_warning']['recall']==.5
    assert result['any_warning']['detected_fraction_of_all_death_labels']==pytest.approx(1/3)
    assert result['high_alert']['survivor_warnings']==0

def test_error_review_handles_empty_groups_and_rejects_invalid_scores():
    assert summarize([],[],[])['patients']==0
    assert summarize([1],[np.nan],[None])['not_scored']==1
    for score,state in [(float('inf'),None),(-.1,'NO_ALERT'),(.2,None),(np.nan,'NO_ALERT')]:
        with pytest.raises(ValueError):summarize([1],[score],[state])
    with pytest.raises(ValueError):warning_counts([1,2],[True,False])
