alter table public.companies
  add column if not exists verification_status text not null default 'approved'
    check (verification_status in ('pending','demo_approved','approved','rejected','suspended')),
  add column if not exists billing_plan text not null default 'lifetime_free',
  add column if not exists approved_at timestamptz,
  add column if not exists approved_by text;

update public.companies
set verification_status = 'demo_approved', billing_plan = 'lifetime_free',
    approved_at = coalesce(approved_at, created_at),
    approved_by = coalesce(approved_by, 'prototype_grandfathering')
where billing_plan = 'lifetime_free';

create table if not exists public.company_registrations (
  id uuid primary key default gen_random_uuid(),
  company_name text not null check (char_length(trim(company_name)) between 2 and 120),
  contact_name text not null check (char_length(trim(contact_name)) between 2 and 120),
  business_email text not null check (business_email ~* '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'),
  website text, industry text, company_size text, phone text,
  registration_number text, message text, logo_base64 text,
  status text not null default 'pending' check (status in ('pending','approved','rejected')),
  review_notes text, access_code text,
  company_id uuid references public.companies(id) on delete set null,
  created_at timestamptz not null default now(), reviewed_at timestamptz,
  constraint company_registrations_email_pending unique (business_email, status)
);

alter table public.company_registrations enable row level security;
revoke all on public.company_registrations from anon, authenticated;
grant insert on public.company_registrations to anon, authenticated;
grant select, update on public.company_registrations to authenticated;

create policy "public can submit pending company registrations"
on public.company_registrations for insert to anon, authenticated
with check (status = 'pending' and company_id is null and access_code is null and reviewed_at is null);

create policy "owner can review company registrations"
on public.company_registrations for select to authenticated
using (lower(coalesce((select auth.jwt()) ->> 'email','')) = 'irfanshafi210608@gmail.com');

create policy "owner can update company registrations"
on public.company_registrations for update to authenticated
using (lower(coalesce((select auth.jwt()) ->> 'email','')) = 'irfanshafi210608@gmail.com')
with check (lower(coalesce((select auth.jwt()) ->> 'email','')) = 'irfanshafi210608@gmail.com');

create index if not exists company_registrations_status_created_idx
on public.company_registrations(status, created_at desc);
create index if not exists company_registrations_company_id_idx
on public.company_registrations(company_id);
