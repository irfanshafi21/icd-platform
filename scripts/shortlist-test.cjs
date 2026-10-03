const assert=require('node:assert/strict');
const {eligibility}=require('../web/shortlist.js');
assert.equal(eligibility({score:70}).included,false);
assert.equal(eligibility({score:70.01}).included,true);
assert.equal(eligibility({score:60,interview_score:80}).included,false);
let result=eligibility({score:60,interview_score:90});
assert.equal(result.average,75);assert.equal(result.byAverage,true);assert.equal(result.byAts,false);assert.equal(result.included,true);
result=eligibility({score:74,interview_score:90});assert.equal(result.average,82);assert.equal(result.byAverage,true);assert.equal(result.byAts,true);
for(const interview_score of [null,undefined,'',false,'bad',101,-1]){
 result=eligibility({score:65,interview_score});assert.equal(result.average,null);assert.equal(result.included,false);
}
assert.equal(eligibility({score:74,interview_score:0}).average,37);
assert.equal(eligibility({score:99,interview_score:99,decision_status:'Rejected'}).included,false);
assert.equal(eligibility({score:null,interview_score:99}).included,false);
assert.equal(eligibility({overall_score:65,score:99,interview_score:90}).average,77.5);
console.log('PASS shortlist: strict threshold, averages, missing scores, zero scores, rejected records.');
