// Optional preferences stay in memory unless the user opts into device storage.
(() => {
 const choiceKey='icd-device-preferences', memory=new Map();
 const read=k=>{try{return localStorage.getItem(k)}catch{return null}};
 let allowed=read(choiceKey)==='allow';
 window.icdStorage={
  getItem:k=>allowed?read(k):(memory.get(k)??null),
  setItem:(k,v)=>{memory.set(k,String(v));if(allowed){try{localStorage.setItem(k,String(v))}catch{}}},
  removeItem:k=>{memory.delete(k);try{localStorage.removeItem(k)}catch{}}
 };
 // Historical AI conversations are intentionally no longer retained.
 try{localStorage.removeItem('icd-ai-history')}catch{}
 function settings(){
  if(document.querySelector('#device-preferences'))return;
  const box=document.createElement('section');box.id='device-preferences';
  box.setAttribute('aria-label','Device storage preferences');
  box.innerHTML='<strong>Your device, your choice</strong><p>Remember bookmarks and notification read status on this browser? Sign-in works either way. AI conversations are not saved to this device.</p><div><button type="button" data-choice="deny">Use this session only</button><button type="button" data-choice="allow">Remember preferences</button><button type="button" data-choice="clear">Clear saved preferences</button></div><a href="/cookies">Storage details</a>';
  box.style.cssText='position:fixed;bottom:16px;left:16px;z-index:10001;max-width:440px;width:calc(100% - 32px);box-sizing:border-box;padding:22px;background:white;color:#183c35;border:1px solid #9bb9ae;border-radius:18px;box-shadow:0 8px 32px #0003;font:14px/1.6 system-ui';
  box.querySelectorAll('button').forEach(button=>{
   button.style.cssText='padding:10px;margin:4px 4px 4px 0;border:1px solid #527e70;border-radius:8px;background:#eef6f2;color:#183c35;cursor:pointer;min-height:44px';
   button.onclick=()=>{
    const choice=button.dataset.choice;allowed=choice==='allow';
    try {
     localStorage.setItem(choiceKey,allowed?'allow':'deny');
     if(!allowed)for(const key of Object.keys(localStorage)){if(key.startsWith('icd-')&&key!==choiceKey)localStorage.removeItem(key)}
    }catch{}
    if(choice==='clear')memory.clear();
    box.remove();
   };
  });
  document.body.append(box);
 }
 window.icdDevicePreferences=settings;
 if(!read(choiceKey))settings();
 document.addEventListener('click',e=>{if(e.target.closest('[data-device-preferences]'))settings()});
})();
