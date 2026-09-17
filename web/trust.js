// Add notices and accessible names without changing existing form submissions.
let serial=0,scheduled=false;
const activeDialogs=new Map();
function notice(form,text){if(!form||form.querySelector('[data-trust-notice]'))return;const p=document.createElement('p');p.className='trust-notice';p.dataset.trustNotice='';p.innerHTML=text;form.append(p)}
function enhance(){
 const interviewList=document.querySelector('.interview-list');if(interviewList&&!interviewList.dataset.deliveryEnhanced){interviewList.dataset.deliveryEnhanced='1';const refresh=document.createElement('button');refresh.type='button';refresh.className='secondary';refresh.textContent='Refresh email status';interviewList.prepend(refresh);refresh.onclick=()=>loadDeliveries(interviewList,refresh);loadDeliveries(interviewList,refresh)}
 document.querySelectorAll('label').forEach(label=>{if(label.htmlFor||label.querySelector('input,select,textarea'))return;const next=label.nextElementSibling;if(next?.matches('input,select,textarea')){next.id=next.id||`accessible-field-${++serial}`;label.htmlFor=next.id}});
 notice(document.querySelector('#registration-form'),'ICD is a free recruitment prototype intended for adults aged 18 and over. We use these details to review your organization. Please provide only business information you are authorized to share. <a href="/privacy" target="_blank" rel="noopener">Privacy policy</a> · <a href="/terms" target="_blank" rel="noopener">Terms</a>.');
 notice(document.querySelector('#screen-form'),'Upload only résumés you are authorized to process. Relevant résumé text and job requirements may be processed by configured AI providers. Review the evidence before making a hiring decision. <a href="/privacy" target="_blank" rel="noopener">How data is used</a>.');
 const host=document.querySelector('.owner-nav')||document.querySelector('.candidate-portal header');
 if(host&&!host.querySelector('[data-privacy-center]')){const a=document.createElement('a');a.href='/privacy-center';a.className='privacy-link';a.dataset.privacyCenter='';a.textContent='Privacy requests';host.append(a)}
 const dialogs=[...document.querySelectorAll('.modal-shell')];
 for(const shell of dialogs){if(activeDialogs.has(shell))continue;const dialog=shell.querySelector('[role="dialog"],section,form');if(!dialog)continue;activeDialogs.set(shell,document.activeElement);dialog.setAttribute('role','dialog');dialog.setAttribute('aria-modal','true');const h=dialog.querySelector('h1,h2,h3');if(h){h.id=h.id||`accessible-dialog-${++serial}`;dialog.setAttribute('aria-labelledby',h.id)}}
 for(const [shell,opener]of activeDialogs){if(shell.isConnected)continue;activeDialogs.delete(shell);if(!dialogs.length&&opener?.isConnected&&!opener.closest('.modal-shell'))opener.focus({preventScroll:true})}
}
document.addEventListener('keydown',event=>{const shell=[...document.querySelectorAll('.modal-shell')].filter(e=>!e.hidden&&e.getClientRects().length).at(-1);if(!shell)return;
 const items=[...shell.querySelectorAll('button,a[href],input:not([type=hidden]),select,textarea,[tabindex]')].filter(e=>!e.disabled&&e.tabIndex>=0&&e.getClientRects().length);
 if(event.key==='Escape'){const close=shell.querySelector('.modal-close,[data-close-questions]');if(close){event.preventDefault();close.click()}}
 if(event.key==='Tab'&&items.length){const first=items[0],last=items.at(-1);if(!shell.contains(document.activeElement)){event.preventDefault();first.focus()}else if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}}
});
new MutationObserver(()=>{if(scheduled)return;scheduled=true;queueMicrotask(()=>{scheduled=false;enhance()})}).observe(document.body,{childList:true,subtree:true});
enhance();

async function loadDeliveries(container,refresh){
 refresh.disabled=true;
 try{const response=await fetch('/api/interview-deliveries');if(!response.ok)throw new Error('Email status unavailable');const rows=await response.json();
 container.querySelectorAll('[data-delivery-state]').forEach(e=>e.remove());
 for(const row of rows){const card=[...container.querySelectorAll('[data-interview-status]')].find(e=>e.dataset.interviewStatus===String(row.interview_id))?.closest('.interview-card');if(!card)continue;
 const box=document.createElement('div');box.className='trust-notice';box.dataset.deliveryState='';const label={sent:'Invitation accepted by the email service',failed:'Invitation delivery failed',queued:'Invitation waiting to send',sending:'Sending, or delivery status not confirmed'};box.textContent=label[row.status]||'Delivery status unavailable';
 if(['failed','queued'].includes(row.status)){const retry=document.createElement('button');retry.type='button';retry.className='secondary';retry.textContent='Retry invitation';retry.onclick=async()=>{if(!confirm('Retry this interview invitation? Check whether the candidate already received it to avoid duplicate emails.'))return;retry.disabled=true;try{const r=await fetch('/api/interview-deliveries/'+encodeURIComponent(row.id)+'/retry',{method:'POST'});if(!r.ok){const data=await r.json();throw new Error(data.detail||'Retry unavailable')}box.textContent='Retry queued. Refresh email status shortly.'}catch(error){box.textContent=error.message}};box.append(document.createElement('br'),retry)}
 if(row.status==='sending'){const text=document.createElement('p');text.textContent='Refresh shortly. If this persists, check with the candidate before sending another invitation.';box.append(text)}card.append(box)}
 refresh.textContent='Refresh email status';
 }catch(_){refresh.textContent='Email status unavailable · Retry'}finally{refresh.disabled=false}
}
