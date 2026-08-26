revoke all on table public.linkedin_connections from anon;

alter table public.linkedin_connections
  alter column company_id type uuid
  using company_id::text::uuid;

alter table public.linkedin_connections
  alter column company_id set not null;

alter table public.linkedin_connections
  drop constraint if exists linkedin_connections_company_id_fkey;

alter table public.linkedin_connections
  add constraint linkedin_connections_company_id_fkey
  foreign key (company_id) references public.companies(id) on delete cascade;

grant select, insert, update, delete
  on table public.linkedin_connections to authenticated;

grant usage
  on sequence public.linkedin_connections_id_seq to authenticated;

alter table public.linkedin_connections enable row level security;

create policy "Company owners can view LinkedIn connection"
on public.linkedin_connections for select
to authenticated
using (
  exists (
    select 1 from public.companies
    where companies.id = linkedin_connections.company_id
      and companies.owner_user_id = (select auth.uid())
  )
);

create policy "Company owners can create LinkedIn connection"
on public.linkedin_connections for insert
to authenticated
with check (
  exists (
    select 1 from public.companies
    where companies.id = linkedin_connections.company_id
      and companies.owner_user_id = (select auth.uid())
  )
);

create policy "Company owners can update LinkedIn connection"
on public.linkedin_connections for update
to authenticated
using (
  exists (
    select 1 from public.companies
    where companies.id = linkedin_connections.company_id
      and companies.owner_user_id = (select auth.uid())
  )
)
with check (
  exists (
    select 1 from public.companies
    where companies.id = linkedin_connections.company_id
      and companies.owner_user_id = (select auth.uid())
  )
);

create policy "Company owners can delete LinkedIn connection"
on public.linkedin_connections for delete
to authenticated
using (
  exists (
    select 1 from public.companies
    where companies.id = linkedin_connections.company_id
      and companies.owner_user_id = (select auth.uid())
  )
);
