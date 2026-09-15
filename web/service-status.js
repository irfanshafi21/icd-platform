// Local-only connectivity feedback. Never queues or automatically repeats a write.
const banner=document.createElement('aside');
banner.setAttribute('role','status');
banner.setAttribute('aria-live','polite');
banner.id='connection-status';
banner.style.cssText='position:fixed;top:0;left:0;right:0;z-index:10000;background:#fff2d7;color:#4f3814;padding:12px 20px;text-align:center;font:14px/1.5 system-ui;box-shadow:0 2px 12px #0002';
document.body.prepend(banner);
function updateConnection(){
 banner.hidden=navigator.onLine;
 banner.textContent='You appear to be offline. Changes cannot be submitted. Keep this page open and check saved results before retrying.';
}
window.addEventListener('offline',updateConnection);
window.addEventListener('online',updateConnection);
updateConnection();
