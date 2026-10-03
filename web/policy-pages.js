(() => {
 const current=location.pathname.replace(/\/$/,'')||'/';
 document.querySelectorAll('.policy-nav a').forEach(link=>{
  if(link.getAttribute('href')===current)link.setAttribute('aria-current','page');
 });
 if(current==='/cookies'){
  document.title='Cookies & storage | ICD Platform';
  const heading=document.querySelector('h1');if(heading)heading.textContent='Cookies & device storage';
  const device=document.querySelector('#device');
  if(device){const block=document.createElement('section');block.className='cookie-overview';let next=device.nextElementSibling;block.append(device);while(next&&next.tagName!=='H2'){const following=next.nextElementSibling;block.append(next);next=following}heading.after(block)}
 }
})();
