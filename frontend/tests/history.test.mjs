import assert from 'node:assert/strict'
import {test} from 'node:test'
import {historyFields} from '../src/utils/history.js'
test('history preserves admission and status meanings instead of calling them follow-ups or plans',()=>{
  assert.deepEqual(historyFields({source:'context',content:'Demo condition',follow_up:'Demo diagnosis'}),[{label:'Condition summary',value:'Demo condition'},{label:'Admission diagnosis',value:'Demo diagnosis'}])
  assert.deepEqual(historyFields({source:'review',content:'Demo review',plan:'acknowledged'}),[{label:'Action note',value:'Demo review'},{label:'Status',value:'acknowledged'}])
})
test('doctor-entered limit history renders readable limits rather than raw JSON',()=>{
  const fields=historyFields({source:'limits',content:'[{"parameter":"HR","lower":60,"upper":120}]'})
  assert.match(fields[0].value,/Heart rate.*60 to 120/)
  assert.doesNotMatch(fields[0].value,/parameter|lower|upper/)
})
