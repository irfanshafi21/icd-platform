(function(root){
  function score(value){
    if(value===null||value===undefined||typeof value==='boolean'||String(value).trim()==='')return null;
    const n=Number(value);return Number.isFinite(n)&&n>=0&&n<=100?n:null;
  }
  function eligibility(candidate){
    const ats=score(candidate.overall_score??candidate.score),interview=score(candidate.interview_score);
    const average=ats!==null&&interview!==null?(ats+interview)/2:null;
    const byAts=ats!==null&&ats>70,byAverage=average!==null&&average>70;
    return {ats,interview,average,byAts,byAverage,included:candidate.decision_status!=='Rejected'&&(byAts||byAverage)};
  }
  if(typeof module!=='undefined'&&module.exports)module.exports={eligibility};
  else root.IcdShortlist={eligibility};
})(typeof window!=='undefined'?window:globalThis);
