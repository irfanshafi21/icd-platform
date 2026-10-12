const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/device-storage.js','utf8');
function environment(choice){
 const values=new Map([['icd-device-preferences',choice],['icd-ai-history','sensitive']]);
 const storage={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
 const window={};vm.runInNewContext(source,{window,localStorage:storage,Map,document:{addEventListener(){}}});
 return {window,values};
}
let e=environment('deny');e.window.icdStorage.setItem('icd-bookmarks','[1]');
assert.equal(e.values.has('icd-bookmarks'),false);
assert.equal(e.window.icdStorage.getItem('icd-bookmarks'),'[1]');
assert.equal(e.values.has('icd-ai-history'),false);
e=environment('allow');e.window.icdStorage.setItem('icd-bookmarks','[1]');
assert.equal(e.values.get('icd-bookmarks'),'[1]');
e.window.icdStorage.removeItem('icd-bookmarks');assert.equal(e.values.has('icd-bookmarks'),false);
console.log('Device storage opt-in and AI-history removal passed');

const sessionValues=new Map(),sessionStorage={getItem:k=>sessionValues.get(k)??null,setItem:(k,v)=>sessionValues.set(k,v),removeItem:k=>sessionValues.delete(k)};
function reloadSession(){const window={};vm.runInNewContext(source,{window,sessionStorage,localStorage:{getItem:k=>k==='icd-device-preferences'?'deny':null,removeItem(){}},Map,document:{addEventListener(){}}});return window.icdStorage}
let first=reloadSession();first.setItem('icd-notifications-read-company-items','["read-event"]');
assert.equal(reloadSession().getItem('icd-notifications-read-company-items'),'["read-event"]');
reloadSession().removeItem('icd-notifications-read-company-items');assert.equal(reloadSession().getItem('icd-notifications-read-company-items'),null);
console.log('Notification read state survives reload within a session');
