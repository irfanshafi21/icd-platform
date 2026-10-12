(() => {
 const current=location.pathname.replace(/\/$/,'')||'/';
 document.querySelectorAll('.policy-nav a').forEach(link=>{
  if(link.getAttribute('href')===current)link.setAttribute('aria-current','page');
 });
 const headings=[...document.querySelectorAll('main>h2')];
 if(headings.length>2){const contents=document.createElement('details');contents.className='policy-contents';const summary=document.createElement('summary');summary.textContent='On this page';contents.append(summary);const links=document.createElement('nav');links.setAttribute('aria-label','Page sections');headings.forEach((heading,i)=>{heading.id||='section-'+(i+1);const link=document.createElement('a');link.href='#'+heading.id;link.textContent=heading.textContent;links.append(link)});contents.append(links);document.querySelector('main>h1')?.after(contents)}
 if(current==='/cookies'){
  document.title='Cookies & storage | ICD Platform';
  const heading=document.querySelector('h1');if(heading)heading.textContent='Cookies & device storage';
  const device=document.querySelector('#device');
  if(device){const block=document.createElement('section');block.className='cookie-overview';let next=device.nextElementSibling;block.append(device);while(next&&next.tagName!=='H2'){const following=next.nextElementSibling;block.append(next);next=following}heading.after(block)}
 }
})();
