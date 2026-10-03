// Executes the real migration against an isolated PostgreSQL-compatible database.
const {PGlite}=require(process.env.PGLITE_MODULE||'@electric-sql/pglite');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const db=new PGlite();
 try{
  await db.exec(`
   create role anon; create role authenticated; create schema auth;
   create function auth.jwt() returns jsonb language sql as $$select coalesce(nullif(current_setting('request.jwt.claims',true),''),'{}')::jsonb$$;
   create table companies(id uuid primary key,name text);
   create table screening_history(company_id uuid,overall_score numeric,decision_status text,status text,screened_at timestamptz);
   create table jobs(company_id uuid,status text);
   create table public_applications(company_id uuid);
   create table interviews(company_id uuid,status text);
   insert into companies values ('00000000-0000-0000-0000-000000000001','Active company'),('00000000-0000-0000-0000-000000000002','Empty company');
   insert into screening_history select '00000000-0000-0000-0000-000000000001',80,'Selected','active',now() from generate_series(1,1501);
   insert into screening_history values ('00000000-0000-0000-0000-000000000001',10,'Rejected','cleared',now()),('00000000-0000-0000-0000-000000000001',null,'Waiting','active',now()-interval '40 days');
   insert into jobs values ('00000000-0000-0000-0000-000000000001','active'),('00000000-0000-0000-0000-000000000001','closed');
   insert into public_applications values ('00000000-0000-0000-0000-000000000001');
   insert into interviews values ('00000000-0000-0000-0000-000000000001','Scheduled'),('00000000-0000-0000-0000-000000000001','Completed');
  `);
  await db.exec(fs.readFileSync(path.join(__dirname,'../supabase/migrations/20260916090000_owner_activity_analytics.sql'),'utf8'));
  await db.exec('set role anon');
  await assert.rejects(db.query('select public.owner_platform_analytics()'),/permission denied/);
  await db.exec('reset role; set role authenticated');
  await assert.rejects(db.query('select public.owner_platform_analytics()'),/Owner access required/);
  await db.query("select set_config('request.jwt.claims',$1,false)",[JSON.stringify({email:'irfanshafi210608@gmail.com'})]);
  const {rows}=await db.query('select public.owner_platform_analytics() as report');
  const report=rows[0].report,active=report.companies[0],empty=report.companies[1];
  assert.equal(active.screened,1502);assert.equal(active.strong,1501);assert.equal(active.unscored,1);
  assert.equal(active.average_score,80);assert.equal(active.selected,1501);assert.equal(active.low,0);
  assert.equal(active.jobs,2);assert.equal(active.active_jobs,1);assert.equal(active.interviews,2);
  assert.equal(active.trend.reduce((n,p)=>n+p.count,0),1501);
  assert.equal(empty.screened,0);assert.equal(empty.average_score,null);assert.deepEqual(empty.trend,[]);
  assert(!JSON.stringify(report).includes('candidate_name'));
  console.log('Owner analytics: authorization, 1500+ rows, cleared records, score averages, empty companies and date window passed.');
 }finally{await db.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
