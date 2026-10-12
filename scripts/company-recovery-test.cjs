const {PGlite}=require(process.env.PGLITE_MODULE||'@electric-sql/pglite');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const db=new PGlite();
 try{
 await db.exec(`create role anon; create role authenticated; create schema auth;
 create function auth.jwt() returns jsonb language sql as $$select '{"email":"irfanshafi210608@gmail.com"}'::jsonb$$;
 create table companies(id uuid primary key,name text,logo_base64 text,industry text,website text,company_size text,created_at timestamptz,verification_status text,billing_plan text,approved_at timestamptz,approved_by text,access_code text);
 create table company_registrations(id uuid primary key,business_email text,status text,company_id uuid,reviewed_at timestamptz,review_notes text,access_code text,constraint company_registrations_email_pending unique(business_email,status));
 create table jobs(company_id uuid,status text);
 create table screening_history(company_id uuid,status text,decision_status text,overall_score int,screened_at timestamptz);
 create table public_applications(company_id uuid);
 create table interviews(company_id uuid,status text);
 insert into companies(id,name,logo_base64,industry,website,company_size,verification_status,approved_by,access_code) select id::uuid,'Zoho','same-logo','Technology','https://www.zoho.com/','1000+','approved','irfanshafi210608@gmail.com','0037' from unnest(array['964f998f-fb6a-4d6f-85db-c0c66430057f','8312edd1-5d7f-43fc-b494-b05a9af011cb','12508009-263f-43ba-b431-4b2d65aeade0','f3cd6bd3-f912-4673-8e4d-248cf51edc90']) id;
 insert into companies(id,name,verification_status) values ('45ee6600-5fcc-48e4-b015-4abb2af8019c','nvidia','approved'),('94e4f265-9fec-49a7-a67f-b477b13d52db','Nvidia','suspended');
 insert into jobs values ('94e4f265-9fec-49a7-a67f-b477b13d52db','active');
 insert into company_registrations(id,business_email,status,access_code) values ('ee162c64-a48a-4bf3-a4b6-0479c323bd46','same@example.test','pending','0037'),('00000000-0000-0000-0000-000000000001','same@example.test','approved','7777');`);
 await db.exec(fs.readFileSync(path.join(__dirname,'../supabase/migrations/20260916183000_company_duplicate_recovery.sql'),'utf8'));
 assert.equal((await db.query('select count(*)::int as n from companies')).rows[0].n,6,'All original records are preserved');
 assert.equal((await db.query('select count(*)::int as n from companies where duplicate_of is not null')).rows[0].n,4);
 assert.equal((await db.query('select count(*)::int as n from companies_public')).rows[0].n,2);
 assert.equal((await db.query('select count(*)::int as n from jobs')).rows[0].n,1,'Archived Nvidia jobs are preserved');
 assert.equal((await db.query("select count(*)::int as n from company_registrations where status='approved'")).rows[0].n,2,'Same contact can have multiple approved organizations');
 assert.equal((await db.query('select jsonb_array_length(owner_platform_analytics()->\'companies\') as n')).rows[0].n,2);
 await assert.rejects(db.exec("insert into companies(id,name,logo_base64,industry,website,company_size) values ('00000000-0000-0000-0000-000000000007',' zoho ','same-logo','technology','HTTPS://WWW.ZOHO.COM','1000+')"),/duplicate key/);
 await db.exec("insert into company_registrations(id,business_email,status) values ('00000000-0000-0000-0000-000000000008','same@example.test','pending')");
 await assert.rejects(db.exec("insert into company_registrations(id,business_email,status) values ('00000000-0000-0000-0000-000000000009','SAME@example.test','pending')"),/duplicate key/);
 console.log('Company recovery: duplicate archival, retained jobs, approval repair, unique identities and pending requests passed.');
 }finally{await db.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
