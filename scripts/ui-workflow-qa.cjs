/* Isolated browser QA. Uses local source plus in-memory fixtures; never calls production. */
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const os = require('node:os');
function loadPlaywright() {
  if (process.env.PLAYWRIGHT_MODULE) return require(process.env.PLAYWRIGHT_MODULE);
  try { return require('playwright'); } catch (error) { if (error.code !== 'MODULE_NOT_FOUND') throw error; }
  const cached = path.join(process.env.USERPROFILE || os.homedir(), '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules', 'playwright');
  if (fs.existsSync(cached)) return require(cached);
  throw new Error('Install playwright locally or set PLAYWRIGHT_MODULE to an installed Playwright module.');
}
const { chromium } = loadPlaywright();
const repo = path.resolve(__dirname, '..');
const phase = process.argv[2] || 'after';
const output = path.join(__dirname, 'qa-output', phase);
fs.mkdirSync(output, { recursive: true });
const company = { id: 'qa-company', name: 'Northstar', industry: 'Technology', website: 'https://example.com', company_size: '51–200', email: 'team@example.test' };
function fixtures() {
  const titles = ['Senior Product Designer', 'Full Stack Developer', 'Machine Learning Engineer'];
  const jobs = titles.map((title, i) => ({ id: i + 1, title, company, company_id: company.id, department: ['Design', 'Engineering', 'Data Science'][i], status: 'active', published: i > 0, posted_on_app: i > 0, is_public: i > 0, public_enabled: i > 0, location: 'Bengaluru · Hybrid', employment_type: 'Full-time', experience_level: 'Mid–Senior level', description: 'Create thoughtful products that help people do their best work. Partner with a collaborative team and bring clarity to complex challenges.', responsibilities: 'Own projects from discovery to delivery and collaborate across disciplines.', benefits: 'Flexible work, learning budget, and health coverage.', required_skills: [['Figma', 'Design systems', 'Research', 'Prototyping'], ['TypeScript', 'React', 'Python', 'PostgreSQL'], ['Python', 'PyTorch', 'MLOps', 'SQL']][i] }));
  const candidates = ['Aarav Shah', 'Sophia Brown', 'Meera Krishnan'].map((candidate_name, i) => ({ id: 11 + i, candidate_name, filename: candidate_name + '.pdf', email: 'candidate' + i + '@example.test', job_role: titles[i], job_id: i + 1, score: [92, 84, 77][i], overall_score: [92, 84, 77][i], years_experience: '5 years', decision_status: ['Shortlisted', 'Interview Scheduled', 'Selected'][i], matched_skills: jobs[i].required_skills, gaps: ['Leadership evidence'], education: 'Bachelor of Science', created_at: '2026-09-08T09:30:00Z', screened_at: new Date(Date.now() - (i + 1) * 3600000).toISOString(), recruiter_summary: 'Strong evidence of practical work, clear communication, and relevant experience.', notes: '', score_json: { breakdown: { skills_match: 90, experience_fit: 84, education_fit: 80 } } }));
  const interviews = candidates.slice(0, 2).map((c, i) => ({ id: 31 + i, candidate_id: c.id, candidate_name: c.candidate_name, candidate_email: c.email, job_role: c.job_role, status: i ? 'Completed' : 'Scheduled', interview_score: i ? 81 : null, scheduled_at: '2026-09-12T09:30:00Z', interview_type: 'Technical', mode: 'Online', meeting_link: 'https://meet.google.com/test-fixture-room' }));
  Object.assign(candidates[1], { interview_score: 81, decision_status: 'Selected' });
  candidates[2].decision_status = 'Interview Eligible';
  const applications = [{ id: 61, job_id: 1, applicant_name: 'Alex Morgan', applicant_email: 'alex@example.test', resume_filename: 'Alex-Morgan.pdf', status: 'Screening', applied_at: '2026-09-08T10:30:00Z', jobs: jobs[0] }];
  jobs.forEach((j, i) => j.published_to_portal = i > 0);
  return { company, jobs, candidates, interviews, applications, integrations: { ai: true, email: true, google_candidate_login: true, resume_inbox: false, linkedin: false }, summary: { active_jobs: 3, candidates: 3, shortlisted: 1, selected: 1, scheduled_interviews: 1 } };
}
const report = { phase, screenshots: [], layouts: [], checks: [], pageErrors: [], unexpectedApi: [], requests: [], blockedExternal: [] };
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  let file = pathname === '/' || pathname === '/index.html' ? 'web/index.html' : pathname.startsWith('/static/') ? 'web/' + pathname.slice(8) : pathname.slice(1);
  const resolved = path.resolve(repo, file);
  if (!resolved.startsWith(repo + path.sep)) { res.writeHead(403); return res.end(); }
  try { const body = fs.readFileSync(resolved); res.writeHead(200, { 'Content-Type': resolved.endsWith('.css') ? 'text/css' : resolved.endsWith('.js') ? 'text/javascript' : resolved.endsWith('.html') ? 'text/html' : 'image/png' }); res.end(body); }
  catch { res.writeHead(404); res.end(); }
});
async function setup(browser, width, mode) {
  const context = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' });
  let data = fixtures();
  if (mode === 'score-recovery') {
    const c = data.candidates[0];
    Object.assign(c, { email: '', profile_json: JSON.stringify({ email: 'recovery@example.test' }), score: 40, overall_score: 40, interview_score: 0, decision_status: 'Interview Completed' });
    Object.assign(data.interviews[0], { status: 'Completed', interview_score: 0 });
    data.applications[0].applicant_email = 'recovery@example.test';
  }
  let candidateSignedIn = mode === 'candidate';
  let candidateApplications = [];
  let rejectionAttempts = 0;
  let scoreSaveAttempts = 0;
  let heldInsight;
  const controls = { deferNextInsight() { let release; const promise = new Promise(resolve => release = resolve); heldInsight = { promise, release }; return release; } };
  await context.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url());
    if (url.origin !== origin) { report.blockedExternal.push({ width, mode, url: url.origin + url.pathname }); return route.abort(); }
    if (phase === 'before' && url.pathname === '/static/experience.css') return route.fulfill({ contentType: 'text/css', body: '' });
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const api = url.pathname, method = req.method();
    const payload = req.headers()['content-type']?.includes('application/json') ? req.postDataJSON() : null;
    report.requests.push({ width, mode, api, method, ...(payload ? { payload } : {}) });
    let result = {};
    let status = 200;
    if (api === '/api/organizations') result = [company, { id: 'qa-two', name: 'Arc Studio', industry: 'Design' }, { id: 'qa-three', name: 'Vertex Labs', industry: 'Technology' }, { id: 'qa-four', name: 'Meridian', industry: 'Consulting' }];
    else if (api === '/api/session/recruiter' || api === '/api/session' || api === '/api/candidate/session') result = { ok: true };
    else if (api === '/api/bootstrap') result = data;
    else if (api === '/api/candidate/me') { if (!candidateSignedIn) { status = 401; result = { detail: 'Sign in required' }; } else result = { email: 'alex@example.test', profile: { full_name: 'Alex Morgan', phone: '5551234567' }, jobs: data.jobs, applications: candidateApplications }; }
    else if (api === '/api/candidate/applications' && method === 'POST') { candidateApplications.push({ id: 62, job_id: 1, jobs: data.jobs[0], status: 'Submitted', applied_at: '2026-09-09T10:00:00Z', resume_filename: 'QA-Resume.pdf' }); result = { id: 62, submitted: true }; }
    else if (api === '/api/candidate/send-otp') result = { sent: true };
    else if (api === '/api/candidate/verify-otp') { candidateSignedIn = true; result = { ok: true }; }
    else if (api === '/api/owner/registrations') result = { owner_email: 'owner@example.test', companies: [company, { ...company, id: 'qa-two', name: 'Arc Studio', industry: 'Design' }, { ...company, id: 'qa-three', name: 'Vertex Labs' }], registrations: [{ id: 91, company_id: company.id, company_name: company.name, status: 'approved', industry: 'Technology', company_size: '51–200', contact_name: 'Taylor Rivers', business_email: 'team@example.test', website: 'https://example.com', reviewed_at: '2026-09-07T10:00:00Z' }, { id: 92, company_name: 'Helios Research', status: 'pending', industry: 'Research', company_size: '11–50', contact_name: 'Jordan Lee', business_email: 'jordan@example.test', website: 'https://example.com', message: 'We are growing a team of designers and engineers.' }] };
    else if (api === '/api/linkedin/connection') result = { connected: false };
    else if (/^\/api\/interviews\/\d+$/.test(api) && method === 'PATCH') {
      const item = data.interviews.find(i => i.id === +api.split('/').pop()); Object.assign(item, payload);
      if (item.id === 31 && payload.interview_score != null && mode !== 'score-recovery' && scoreSaveAttempts++ === 0) { status = 503; result = { detail: 'Your interview score was saved, but candidate progress could not be updated. Retry the same score to finish syncing' }; }
      else {
        const c = data.candidates.find(c => c.id === item.candidate_id), average = (c.overall_score + item.interview_score) / 2, decision = average > 70 ? 'Selected' : 'Interview Completed';
        Object.assign(c, { interview_score: item.interview_score, decision_status: decision });
        const profile = typeof c.profile_json === 'string' ? JSON.parse(c.profile_json) : c.profile_json || {};
        data.applications.filter(a => a.applicant_email === (c.email || profile.email) && a.job_id === c.job_id).forEach(a => a.status = decision);
        result = { ...item, decision_status: decision, hiring_average: average };
      }
    }
    else if (/^\/api\/candidates\/\d+\/ats-rerun$/.test(api) && method === 'POST') { result = { ok: true }; }
    else if (/^\/api\/candidates\/\d+$/.test(api) && method === 'PATCH') {
      const id = +api.split('/').pop(), item = data.candidates.find(c => c.id === id);
      if (payload.status === 'Rejected' && rejectionAttempts++ === 0) { status = 503; result = { detail: 'Rejection email not delivered. Candidate data has been retained.' }; }
      else if (payload.status === 'Rejected') { data.candidates = data.candidates.filter(c => c.id !== id); result = { deleted: true, email_delivery: { sent: true } }; }
      else { Object.assign(item, payload, payload.status ? { decision_status: payload.status } : {}); result = item; }
    }
    else if (api === '/api/interviews' && method === 'POST') { const item = { ...payload, id: 39, status: 'Scheduled', interview_score: null }; data.interviews.push(item); result = { ...item, email_delivery: { sent: true } }; }
    else if (api === '/api/interview-questions') result = { questions: { Technical: [{ question: 'How would you validate the quality of a design system?', what_good_looks_like: 'Discuss adoption, accessibility, consistency, and delivery outcomes.' }] } };
    else if (api === '/api/insights') { if (heldInsight) { const held = heldInsight; heldInsight = null; await held.promise; } result = { answer: '## Your strongest matches\n\nAarav Shah leads with strong role evidence.\n\n- Review the portfolio\n- Prepare a focused interview\n\n' + Array.from({ length: 12 }, (_, i) => `### Finding ${i + 1}\nKeep decisions grounded in role evidence.\n`).join('\n') }; }
    else if (api === '/api/offers.zip' && method === 'POST') return route.fulfill({ contentType: 'application/zip', body: Buffer.from('504b0506000000000000000000000000000000000000', 'hex') });
    else if (api === '/api/screen') result = { processed: 1, skipped: [] };
    else if (/^\/api\/public\/jobs\/\d+$/.test(api)) result = data.jobs.find(j => j.id === +api.split('/').pop());
    else if (/^\/api\/jobs\/\d+/.test(api) && method === 'PATCH') { const item = data.jobs.find(j => j.id === +api.split('/')[3]); Object.assign(item, payload); result = item; }
    else if (api === '/api/jobs' && method === 'POST') { const item = { ...payload, id: 4, company }; data.jobs.push(item); result = item; }
    else { report.unexpectedApi.push({ api, method }); status = 404; result = { detail: 'Unmocked endpoint: ' + api }; }
    return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(result) });
  });
  const page = await context.newPage();
  page.on('pageerror', e => report.pageErrors.push({ width, mode, message: e.message }));
  page.setDefaultTimeout(8000);
  return { context, page, controls };
}
async function snap(page, width, name) {
  await page.waitForTimeout(180);
  const layout = await page.evaluate(() => {
    const viewport = innerWidth;
    const overflow = [...document.querySelectorAll('main *, .workspace *, .notification-panel')].filter(el => { const r = el.getBoundingClientRect(); return el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) && r.width && r.height && (r.left < -2 || r.right > viewport + 2) && !el.closest('.ticker-track, .marquee-track, .landing-marquee, .sidebar, nav, [hidden], details:not([open])>div'); }).slice(0, 18).map(el => ({ tag: el.tagName, cls: String(el.className).slice(0, 100), text: el.textContent.trim().slice(0, 45), x: Math.round(el.getBoundingClientRect().left), right: Math.round(el.getBoundingClientRect().right) }));
    const popovers = [...document.querySelectorAll('.card-action-popover:popover-open')].map(el => { const r = el.getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height }; });
    const measure = selector => { const el = document.querySelector(selector); if (!el) return null; const r = el.getBoundingClientRect(), s = getComputedStyle(el); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height, display: s.display, position: s.position, inset: s.inset, transform: s.transform, gap: s.gap, justifyContent: s.justifyContent, gridTemplateRows: s.gridTemplateRows }; };
    return { viewport, documentWidth: document.documentElement.scrollWidth, overflow, popovers, header: { title: measure('.workspace-head h1'), actions: measure('.header-actions'), notification: measure('.notification-button'), brand: measure('.company-sidebar-brand'), signout: measure('#signout') }, publicCard: measure('.premium-job-card') };
  });
  report.layouts.push({ width, name, ...layout });
  if (name === 'jobs' && layout.header.title && layout.header.notification) {
    const a = layout.header.title, b = layout.header.notification;
    check(width, 'notification bell does not overlap page heading', !(a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom), layout.header);
  }
  if (width === 1440 && ['jobs', 'candidates', 'candidate-portal'].includes(name)) {
    const selector = name === 'candidate-portal' ? '.public-jobs > article' : '.job-admin-cards > article';
    const row = await page.locator(selector).evaluateAll(cards => cards.slice(0, 3).map(card => { const r = card.getBoundingClientRect(); return { left: r.left, top: r.top, width: r.width }; }));
    check(width, `${name} shows three cards per desktop row`, row.length === 3 && new Set(row.map(r => Math.round(r.left))).size === 3 && Math.max(...row.map(r => r.top)) - Math.min(...row.map(r => r.top)) < 8, { row });
  }
  const filename = `${width}-${name}.png`;
  // Full-page capture resizes Chrome internally and triggers the app's legitimate
  // resize handler, closing popovers. Capture transient UI at its real viewport.
  const transient = /menu|notifications|profile|picker|questions|floating-ai/.test(name);
  await page.screenshot({ path: path.join(output, filename), fullPage: !transient });
  report.screenshots.push(filename);
  console.log(`Captured ${filename}; document ${layout.documentWidth}px; overflow nodes ${layout.overflow.length}`);
  if (layout.overflow.length) console.log(JSON.stringify(layout.overflow));
}
function check(width, name, condition, detail = {}) {
  report.checks.push({ width, name, passed: Boolean(condition), ...detail });
}
async function checkMenu(page, width, menu, name) {
  await openMenu(page, menu);
  const panel = menu.locator('.card-action-popover');
  await panel.waitFor({ state: 'visible' });
  const geometry = await panel.evaluate(el => {
    const r = el.getBoundingClientRect();
    const controls = [...el.querySelectorAll('button, a, label')].map(control => { const c = control.getBoundingClientRect(); return { text: control.textContent.trim(), left: c.left, right: c.right, top: c.top, bottom: c.bottom }; });
    const anchor = el.parentElement.querySelector('summary').getBoundingClientRect();
    return { open: el.matches(':popover-open'), left: r.left, right: r.right, top: r.top, bottom: r.bottom, viewportWidth: innerWidth, viewportHeight: innerHeight, anchor: { left: anchor.left, right: anchor.right, top: anchor.top, bottom: anchor.bottom }, controls };
  });
  check(width, `${name} stays inside viewport`, geometry.open && geometry.left >= 0 && geometry.right <= width && geometry.top >= 0 && geometry.bottom <= geometry.viewportHeight, geometry);
  check(width, `${name} controls fit panel`, geometry.controls.every(c => c.left >= geometry.left - 1 && c.right <= geometry.right + 1), { controls: geometry.controls });
  check(width, `${name} stays beside its trigger`, geometry.left <= geometry.anchor.right + 1 && geometry.right >= geometry.anchor.left - 1 && (Math.abs(geometry.top - geometry.anchor.bottom) <= 24 || Math.abs(geometry.bottom - geometry.anchor.top) <= 24 || geometry.bottom === geometry.viewportHeight - 12), { panel: { left: geometry.left, right: geometry.right, top: geometry.top, bottom: geometry.bottom }, anchor: geometry.anchor });
  await snap(page, width, name);
  await page.keyboard.press('Escape');
  assert.equal(await menu.getAttribute('open'), null);
  assert.equal(await menu.locator('summary').getAttribute('aria-expanded'), 'false');
  check(width, `${name} closes with Escape`, true);
}
async function openMenu(page, menu) {
  // Complete the user's scroll before opening. A queued scroll event legitimately
  // dismisses an already-open card menu so it cannot float away from its anchor.
  await menu.locator('summary').scrollIntoViewIfNeeded();
  await page.waitForTimeout(100);
  await menu.locator('summary').click();
}
async function checkContained(page, width, selector, parentSelector, name) {
  const failures = await page.locator(selector).evaluateAll((elements, parentSelector) => elements.filter(el => !el.closest('details:not([open])')).map(el => {
    const r = el.getBoundingClientRect(), parent = el.closest(parentSelector)?.getBoundingClientRect();
    return { text: el.textContent.trim().slice(0, 45), left: r.left, right: r.right, top: r.top, bottom: r.bottom, parent: parent && { left: parent.left, right: parent.right, top: parent.top, bottom: parent.bottom } };
  }).filter(r => r.parent && (r.left < r.parent.left - 1 || r.right > r.parent.right + 1 || r.top < r.parent.top - 1 || r.bottom > r.parent.bottom + 1)), parentSelector);
  check(width, name, failures.length === 0, { failures });
}
async function checkButtonContrast(page, width, locator, name) {
  await locator.hover();
  const style = await locator.evaluate(el => {
    const rgba = value => { const match = value.match(/rgba?\(([^)]+)\)/); if (!match) return null; const a = match[1].split(/[\s,\/]+/).map(Number); return [a[0], a[1], a[2], a.length > 3 ? a[3] : 1]; };
    const over = (a, b) => a.slice(0, 3).map((v, i) => v * a[3] + b[i] * (1 - a[3]));
    const luminance = rgb => rgb.slice(0, 3).map(v => { const c = v / 255; return c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4; }).reduce((sum, c, i) => sum + c * [.2126, .7152, .0722][i], 0);
    const chain = []; for (let node = el; node; node = node.parentElement) chain.unshift(getComputedStyle(node));
    let background = [255, 255, 255], samples = [];
    for (const computed of chain) { const color = rgba(computed.backgroundColor); if (color) background = over(color, background); if (computed.backgroundImage !== 'none') samples = [...computed.backgroundImage.matchAll(/rgba?\([^)]+\)/g)].map(m => over(rgba(m[0]), background)); else if (color?.[3] === 1) samples = []; }
    const computed = getComputedStyle(el), text = rgba(computed.color), backgrounds = samples.length ? samples : [background];
    const ratios = backgrounds.map(bg => { const a = luminance(over(text, bg)), b = luminance(bg); return (Math.max(a, b) + .05) / (Math.min(a, b) + .05); });
    return { text: computed.color, background: computed.backgroundColor, image: computed.backgroundImage, minimumRatio: Math.min(...ratios), fontSize: computed.fontSize, disabled: el.disabled, label: el.textContent.trim() };
  });
  check(width, `${name} hover text contrast`, style.disabled || style.minimumRatio >= 4.5, style);
}
async function goRecruiter(page, name) {
  if (page.viewportSize().width <= 900) await page.getByRole('button',{name:'Open navigation',exact:true}).click();
  const button = page.locator(`button[data-page="${name}"]`).first();
  await button.click();
  await page.locator(`.page-${name}`).waitFor();
}
let origin;
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    for (const width of process.env.QA_WIDTHS ? process.env.QA_WIDTHS.split(',').map(Number) : [1440, 768, 390]) {
      const { page, context, controls } = await setup(browser, width, 'recruiter');
      await page.goto(origin); await snap(page, width, 'landing');
      await page.locator('.landing-cta .recruiter-go').scrollIntoViewIfNeeded();
      await page.locator('.landing-cta .recruiter-go').click();
      await page.locator('.recruiter-access').waitFor();
      check(width, 'bottom recruiter CTA opens recruiter access', true);
      await page.locator('#back').click();
      await page.locator('.landing-cta .candidate-go').scrollIntoViewIfNeeded();
      await page.locator('.landing-cta .candidate-go').click();
      await page.locator('.candidate-access').waitFor();
      check(width, 'bottom candidate CTA opens candidate access', true);
      await page.goto(origin + '/?recruiter=1'); await page.locator('[data-org]').first().waitFor(); await snap(page, width, 'recruiter-login');
      await page.locator('[data-org]').first().click(); await page.locator('#code').fill('123456'); await page.locator('#login').click(); await page.locator('.workspace').waitFor();
      if (width > 900) {
        await page.setViewportSize({ width, height: 620 });
        const sidebarPosition = await page.locator('.workspace>aside').evaluate(sidebar => { window.scrollTo(0, 360); return { position: getComputedStyle(sidebar).position, top: Math.round(sidebar.getBoundingClientRect().top) }; });
        assert.deepEqual(sidebarPosition, { position: 'fixed', top: 0 });
        const nav = page.locator('.workspace>aside nav');
        const savedNavTop = await nav.evaluate(element => { element.scrollTop = Math.min(90, element.scrollHeight - element.clientHeight); return element.scrollTop; });
        assert(savedNavTop > 0, 'Short desktop viewport should make sidebar navigation scrollable');
        await page.locator('button[data-page="reports"]').first().click(); await page.locator('.page-reports').waitFor();
        assert(Math.abs(await page.locator('.workspace>aside nav').evaluate(element => element.scrollTop) - savedNavTop) <= 1, 'Sidebar navigation position should survive page changes');
        check(width, 'desktop sidebar stays fixed and preserves its navigation position', true, { savedNavTop });
        await page.setViewportSize({ width, height: 1000 }); await page.evaluate(() => window.scrollTo(0, 0));
      }
      for (const name of ['home', 'jobs', 'screening', 'candidates', 'interviews', 'reports', 'offers', 'insights', 'settings']) {
        await goRecruiter(page, name); await snap(page, width, name);
        if(name==='home'&&width<=900){
          const trigger=page.getByRole('button',{name:'Open navigation',exact:true});
          await trigger.click();await snap(page,width,'navigation-drawer');
          assert.equal(await trigger.getAttribute('aria-expanded'),'true');
          await page.keyboard.press('Escape');assert.equal(await trigger.getAttribute('aria-expanded'),'false');
          await trigger.click();await page.locator('.mobile-sidebar-backdrop').click({position:{x:width-10,y:100}});
          assert.equal(await trigger.getAttribute('aria-expanded'),'false');
          check(width,'drawer opens and closes with Escape and backdrop',true);
        }
        if (name === 'settings') {
          const upload=page.locator('.company-logo-editor input[type=file]');
          await upload.setInputFiles({name:'logo.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a6XkAAAAASUVORK5CYII=','base64')});
          await page.locator('.company-logo-editor [role=status]').filter({hasText:'Logo ready'}).waitFor();
          assert((await page.locator('[name=logo_base64]').inputValue()).length>20);
          check(width,'company logo upload produces preview and serializable form value',true);
        }
        check(width, `${name} navigation is reachable`, await page.locator(`.page-${name}`).isVisible());
        if (name === 'interviews') await checkContained(page, width, '.interview-actions input, .interview-actions button, .interview-actions select, .interview-person button, .interview-person a', '.interview-card', 'interview controls stay inside their cards');
      }
      {
        await goRecruiter(page, 'jobs'); const menu = page.locator('.job-actions-menu').first(); await checkMenu(page, width, menu, 'jobs-menu');
        await checkButtonContrast(page, width, page.locator('[data-edit-job]').first(), 'edit role');
        await checkButtonContrast(page, width, page.locator('[data-screen]').first(), 'screen candidates');
        await page.locator('.notification-button').click(); await snap(page, width, 'notifications'); const interviewNotice=page.locator('.notification-item').filter({ hasText: 'Interview Scheduled' }); const unreadBefore=Number(await page.locator('.notification-summary b').innerText()); assert.equal(await interviewNotice.isVisible(),true); await interviewNotice.click(); await page.locator('.page-interviews').waitFor(); await page.locator('.notification-button').click(); assert.equal(await page.locator('.notification-item').filter({ hasText: 'Interview Scheduled' }).evaluate(item=>item.classList.contains('unread')),false); assert.equal(Number(await page.locator('.notification-summary b').innerText()),Math.max(0,unreadBefore-1)); await page.locator('#mark-notifications-read').click(); assert.equal(await page.locator('.notification-summary b').innerText(), '0'); await page.locator('.notification-close').click(); await goRecruiter(page,'jobs'); report.checks.push({ width, name: 'notification click marks one item read and opens its accurate page', passed: true });
        await page.locator('[data-post-app="1"]').click(); await page.locator('[data-post-app="1"]').filter({ hasText: 'Posted on app' }).waitFor(); assert.equal(await page.locator('[data-post-app="1"]').isDisabled(), true); assert.equal(await page.locator('.page-jobs').count(), 1); report.checks.push({ width, name: 'publish job locks button and stays on jobs page', passed: true });
        await goRecruiter(page, 'candidates');
        const searchWidth = await page.locator('#talent-search').evaluate(el => el.getBoundingClientRect().width);
        check(width, 'candidate search field has usable width', searchWidth >= 140, { searchWidth });
        if (searchWidth >= 140) { await page.locator('#talent-search').fill('Aarav'); check(width, 'candidate search hides unmatched cards', await page.locator('.candidate-job-card:visible').count() === 1); await page.locator('#talent-search').fill(''); }
        await page.locator('#talent-filter').selectOption('selected'); check(width, 'candidate status filter hides unmatched cards', await page.locator('.candidate-job-card:visible').count() === 1); await page.locator('#talent-filter').selectOption('all');
        const candidateMenu = page.locator('.candidate-actions-menu').first(); await checkMenu(page, width, candidateMenu, 'candidates-menu');
        await page.locator('[data-view-candidate]').first().click(); await page.locator('#candidate-modal').waitFor(); await snap(page, width, 'candidate-profile');
        check(width, 'candidate details omit requested tools', await page.locator('#candidate-modal .ai-prep,#candidate-notes,.candidate-record-tools').count() === 0);
        if (await page.locator('#candidate-modal').count()) await page.locator('#modal-close').click();
        await openMenu(page, page.locator('.candidate-actions-menu').first()); await page.locator('[data-compare-candidate]').first().check(); await page.keyboard.press('Escape'); assert.match(await page.locator('#compare-selected').innerText(), /1/); check(width, 'candidate comparison selection updates count', true);
        await goRecruiter(page, 'screening'); await page.locator('#screening-candidates-link').click(); await page.locator('.page-candidates').waitFor(); check(width, 'screening results button opens candidates page', true); await goRecruiter(page, 'screening'); await page.locator('.screening-results [data-view-candidate]').first().click(); await page.locator('#candidate-modal').waitFor(); await page.locator('#modal-close').click(); check(width, 'screening result card opens candidate profile', true); await page.locator('#job-picker-trigger').click(); await snap(page, width, 'screening-picker'); await page.locator('[data-job-option="1"]').click(); assert.equal(await page.locator('#role').inputValue(), 'Senior Product Designer');
        await page.locator('#files').setInputFiles({ name: 'QA-Resume.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 mock resume for isolated UI test') }); await page.locator('.screen-submit').click(); await page.locator('#toast').filter({ hasText: 'Results added below' }).waitFor(); assert.equal(await page.locator('.page-screening').count(), 1); report.checks.push({ width, name: 'screening upload preserves screening page', passed: true });
        await goRecruiter(page, 'interviews'); const card = page.locator('.interview-card').filter({ has: page.locator('[data-interview-status="31"]') });
        await checkButtonContrast(page, width, card.locator('.interview-score button'), 'save score');
        const scoreRequestsBefore = report.requests.filter(r => r.width === width && r.api === '/api/interviews/31' && r.method === 'PATCH').length;
        await card.locator('.interview-score input').fill('84.5'); await card.locator('.interview-score button').click(); await page.locator('#toast').filter({ hasText: 'whole number' }).waitFor(); assert.equal(report.requests.filter(r => r.width === width && r.api === '/api/interviews/31' && r.method === 'PATCH').length, scoreRequestsBefore); check(width, 'fractional interview score is rejected before request', true);
        await card.locator('.interview-score input').fill('84'); await card.locator('.interview-score button').click();
        await card.locator('.interview-score button').filter({ hasText: 'Sync saved score' }).waitFor(); assert.equal(await card.locator('.interview-score input').isDisabled(), true); assert.equal(await card.locator('.interview-score input').inputValue(), '84'); check(width, 'partial score save keeps immutable value and offers sync recovery', true);
        await page.reload(); await page.locator('[data-org]').first().click(); await page.locator('#code').fill('123456'); await page.locator('#login').click(); await page.locator('.workspace').waitFor(); await goRecruiter(page, 'interviews');
        await card.locator('.interview-score button').filter({ hasText: 'Sync saved score' }).waitFor(); await card.locator('.interview-score button').click(); await card.locator('.interview-score button').filter({ hasText: 'Score locked' }).waitFor(); assert.equal(await card.locator('.interview-score button').isDisabled(), true); assert.equal(await card.locator('.interview-score input').isDisabled(), true);
        const saves = report.requests.filter(r => r.width === width && r.mode === 'recruiter' && r.api === '/api/interviews/31' && r.method === 'PATCH'); assert.deepEqual(saves.map(r => r.payload.interview_score), [84, 84]); check(width, 'reload recovers saved score with identical retry then locks', true);
        await page.locator('[data-interview-questions]').first().click(); await page.locator('.question-plan-body').filter({ hasText: 'How would you validate' }).waitFor(); await snap(page, width, 'interview-questions'); await page.locator('[data-close-questions]').click();
        await goRecruiter(page, 'insights'); await page.locator('#insight-question').fill('Who should I review next?'); await page.locator('#generate-insight').click(); await page.locator('#insight-answer').filter({ hasText: 'Your strongest matches' }).waitFor(); report.checks.push({ width, name: 'AI insight renders answer', passed: true });
        await page.locator('.floating-ai').click(); await page.locator('#floating-ai-panel textarea').fill('Compare the strongest profiles'); await page.locator('[data-ai-send]').click(); await page.locator('.floating-ai-history').filter({ hasText: 'Your strongest matches' }).waitFor(); await page.waitForTimeout(200); const latest = await page.locator('.floating-ai-history').evaluate(history => ({ top: history.lastElementChild.getBoundingClientRect().top - history.getBoundingClientRect().top, scroll: history.scrollTop })); assert(latest.top >= 0 && latest.top < 45, 'Latest answer should be aligned near start of AI history'); report.checks.push({ width, name: 'floating AI scrolls to start of newest answer', passed: true, ...latest });
        await checkButtonContrast(page, width, page.locator('[data-ai-clear]'), 'AI clear'); await checkButtonContrast(page, width, page.locator('[data-ai-send]'), 'AI send'); await snap(page, width, 'floating-ai'); await page.locator('#floating-ai-panel header button').click();
        const releaseInsight = controls.deferNextInsight(); await goRecruiter(page, 'jobs'); await page.locator('.floating-ai').click(); await page.locator('#floating-ai-panel textarea').fill('Continue after I change pages'); const pendingRequest = page.waitForRequest(req => new URL(req.url()).pathname === '/api/insights'); await page.locator('[data-ai-send]').click(); await pendingRequest;
        await goRecruiter(page, 'candidates'); await page.locator('.floating-ai').click(); assert.equal(await page.locator('[data-ai-send]').isDisabled(), true); assert.equal(await page.locator('[data-ai-clear]').isDisabled(), true); releaseInsight(); await page.locator('[data-ai-send]:not([disabled])').waitFor(); await page.locator('.floating-ai-history .assistant').last().filter({ hasText: 'Your strongest matches' }).waitFor(); assert.equal(await page.locator('[data-ai-clear]').isDisabled(), false); check(width, 'pending AI reply follows page navigation and restores controls', true); await page.locator('#floating-ai-panel header button').click();
        await goRecruiter(page, 'offers'); await page.locator('#offer-salary').fill('1200000 per annum'); await page.locator('#offer-start').fill('2026-10-01'); await page.locator('#offer-manager').fill('Taylor Rivers');
        const downloadReady = page.waitForEvent('download'); await page.locator('#prepare-offers').click(); const download = await downloadReady; assert.equal(download.suggestedFilename(), 'ICD-offer-letters.zip'); await page.locator('#toast').filter({ hasText: 'Offer letters prepared' }).waitFor(); check(width, 'offer terms create downloadable archive with mocked PDF transport', true);
        await goRecruiter(page, 'jobs'); await page.locator('#new-job').click(); await page.locator('#job-form [name="title"]').fill('QA Test Role'); await page.locator('#job-form [name="skills"]').fill('Research, Writing'); await page.locator('#job-form button.primary').click(); await page.locator('[data-edit-job="4"]').waitFor(); check(width, 'create job adds role card', true);
        await page.locator('[data-edit-job="4"]').click(); await page.locator('#job-form [name="title"]').fill('QA Updated Role'); await page.locator('#job-form button.primary').click(); await page.locator('.job-admin-cards article').filter({ hasText: 'QA Updated Role' }).waitFor(); check(width, 'edit job refreshes card title', true);
        await goRecruiter(page, 'candidates'); await openMenu(page, page.locator('.candidate-actions-menu').last()); await page.locator('.candidate-actions-menu').last().locator('[data-status="Rejected"]').click(); await page.locator('#toast').filter({ hasText: 'not delivered' }).waitFor(); assert.equal(await page.locator('.candidate-job-card').count(), 3); check(width, 'failed rejection email retains candidate for retry', true);
        await openMenu(page, page.locator('.candidate-actions-menu').last()); await page.locator('.candidate-actions-menu').last().locator('[data-status="Rejected"]').click(); await page.locator('#toast').filter({ hasText: 'candidate data erased' }).waitFor(); assert.equal(await page.locator('.candidate-job-card').count(), 2); check(width, 'successful rejection email removes candidate from company view', true);
      }
      await goRecruiter(page,'interviews');
      await page.evaluate(()=>{const b=document.createElement('button');b.id='empty-schedule';b.textContent='Schedule the first interview';document.querySelector('.interview-card-list').append(b)});
      await page.locator('#empty-schedule').click();assert.equal(await page.locator('#interview-form').isVisible(),true);
      check(width,'dynamically rebuilt empty schedule action opens form',true);
      await goRecruiter(page,'candidates');
      await page.route('**/api/candidates',route=>route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({detail:'Test removal failure'})}));
      page.once('dialog',dialog=>dialog.accept());
      await page.locator('#clear-candidates').evaluate(b=>b.replaceWith(b.cloneNode(true)));
      await page.locator('#clear-candidates').click();await page.locator('#toast').filter({hasText:'Test removal failure'}).waitFor();
      assert.equal(await page.locator('#clear-candidates').isEnabled(),true);
      check(width,'rebuilt clear action reaches API and reports failure without removing cards',true);
      await context.close();
      const guest = await setup(browser, width, 'guest'); await guest.page.goto(origin + '/?candidate=1'); await guest.page.locator('#send').waitFor(); await snap(guest.page, width, 'candidate-login'); await checkButtonContrast(guest.page, width, guest.page.locator('#send'), 'candidate email sign in');
      if (width === 1440) { await guest.page.locator('#email').fill('alex@example.test'); await guest.page.locator('#send').click(); await guest.page.locator('#token').fill('123456'); await guest.page.locator('#verify').click(); await guest.page.locator('.candidate-portal').waitFor(); report.checks.push({ width, name: 'candidate email code flow reaches portal with mocked transport', passed: true }); }
      await guest.context.close();
      const candidate = await setup(browser, width, 'candidate'); await candidate.page.goto(origin + '/?candidate=1'); await candidate.page.locator('.candidate-portal').waitFor(); await snap(candidate.page, width, 'candidate-portal'); await candidate.page.locator('#search').fill('TypeScript'); assert.equal(await candidate.page.locator('[data-job]').count(), 1); await candidate.page.locator('#search').fill(''); check(width, 'candidate portal search filters jobs by skill', true); await candidate.page.locator('[data-job="1"]').click(); await candidate.page.locator('#apply').waitFor(); await snap(candidate.page, width, 'candidate-application'); await candidate.page.locator('[name="resume"]').setInputFiles({ name: 'QA-Resume.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 mock resume for isolated UI test') }); await candidate.page.locator('#apply button').click(); await candidate.page.locator('.candidate-portal').waitFor(); assert.equal(await candidate.page.locator('[data-job="1"]').isDisabled(), true); await candidate.page.locator('[data-tab="apps"]').click(); await candidate.page.locator('.application-list').filter({ hasText: 'Submitted' }).waitFor(); report.checks.push({ width, name: 'candidate apply records application and prevents duplicate apply', passed: true }); await candidate.context.close();
      const owner = await setup(browser, width, 'owner'); await owner.page.goto(origin + '/?owner=1'); await owner.page.locator('.owner-portal').waitFor(); await snap(owner.page, width, 'owner'); await owner.page.locator('[data-company-toggle]').first().click(); assert.equal(await owner.page.locator('.owner-company-card.expanded').count(), 1); check(width, 'owner company details expand', true); await owner.page.locator('#owner-company-search').fill('Arc'); check(width, 'owner company search filters cards', await owner.page.locator('.owner-company-card:visible').count() === 1); await owner.context.close();
    }
    const recovery = await setup(browser, 1440, 'score-recovery'); await recovery.page.goto(origin + '/?recruiter=1'); await recovery.page.locator('[data-org]').first().click(); await recovery.page.locator('#code').fill('123456'); await recovery.page.locator('#login').click(); await recovery.page.locator('.workspace').waitFor(); await goRecruiter(recovery.page, 'interviews');
    const zeroCard = recovery.page.locator('.interview-card').filter({ has: recovery.page.locator('[data-interview-status="31"]') }); await zeroCard.locator('.interview-score button').filter({ hasText: 'Sync saved score' }).waitFor(); assert.equal(await zeroCard.locator('.interview-score input').inputValue(), '0'); assert.equal(await zeroCard.locator('.interview-score input').isDisabled(), true); await zeroCard.locator('.interview-score button').click(); await zeroCard.locator('.interview-score button').filter({ hasText: 'Score locked' }).waitFor(); assert.equal(await zeroCard.locator('.interview-score button').isDisabled(), true); const zeroRequest = report.requests.find(r => r.mode === 'score-recovery' && r.method === 'PATCH'); assert.equal(zeroRequest.payload.interview_score, 0); check(1440, 'zero score recovers application status using profile email fallback', true); await recovery.context.close();
    assert.equal(report.pageErrors.length, 0, 'No uncaught browser errors');
    assert.equal(report.unexpectedApi.length, 0, 'Every tested API request is explicitly modeled');
    if (phase !== 'before') {
      assert.equal(report.layouts.filter(layout => layout.documentWidth > layout.width + 1 || layout.overflow.length).length, 0, 'No page or content overflow');
      assert.equal(report.checks.filter(item => item.passed === false).length, 0, 'All visual and workflow checks pass');
    }
  } catch (error) { report.failure = error.stack; console.error(error); process.exitCode = 1; }
  finally { fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2)); await browser.close(); server.close(); console.log(`Report: ${path.join(output, 'report.json')}`); }
})();
