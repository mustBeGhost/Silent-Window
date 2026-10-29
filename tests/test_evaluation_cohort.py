import zipfile
import pytest
from scripts.evaluate_separate_patients import read_cohort

def files(tmp_path,labels='RecordID,In-hospital_death\n123456,1\n',record=123456):
    archive=tmp_path/'cohort.zip';outcomes=tmp_path/'outcomes.txt';outcomes.write_text(labels)
    with zipfile.ZipFile(archive,'w') as z:z.writestr('set-b/123456.txt',f'Time,Parameter,Value\n00:00,RecordID,{record}\n00:00,Age,70\n01:00,HR,80\n')
    return archive,outcomes

def test_separate_cohort_requires_exact_membership_and_no_reused_patient_ids(tmp_path):
    archive,outcomes=files(tmp_path)
    patients,target=read_cohort(archive,outcomes,[999999])
    assert list(patients)==[123456] and target.tolist()==[1]
    with pytest.raises(ValueError,match='overlap'):read_cohort(archive,outcomes,[123456])
    outcomes.write_text('RecordID,In-hospital_death\n123457,1\n')
    with pytest.raises(ValueError,match='membership'):read_cohort(archive,outcomes,[])

@pytest.mark.parametrize('labels',['RecordID,In-hospital_death\n123456,2\n','RecordID,In-hospital_death\n123456,1\n123456,0\n','RecordID,In-hospital_death\n123456,\n'])
def test_separate_cohort_rejects_invalid_or_duplicate_outcome_labels(tmp_path,labels):
    archive,outcomes=files(tmp_path,labels)
    with pytest.raises(ValueError):read_cohort(archive,outcomes,[])

def test_separate_cohort_rejects_identity_mismatch_and_unsafe_archive_members(tmp_path):
    archive,outcomes=files(tmp_path,record=654321)
    with pytest.raises(ValueError,match='identity'):read_cohort(archive,outcomes,[])
    with zipfile.ZipFile(archive,'w') as z:z.writestr('../123456.txt','untrusted')
    with pytest.raises(ValueError,match='member'):read_cohort(archive,outcomes,[])
