-- Candidates may withdraw their own unprocessed application, never another account's.
create or replace function public.withdraw_candidate_application(p_application_id bigint)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare a public.public_applications;
begin
 if auth.uid() is null then raise exception 'Sign in required'; end if;
 select * into a from public.public_applications where id=p_application_id and candidate_user_id=auth.uid() for update;
 if not found then raise exception 'Application not found'; end if;
 if a.status='Withdrawn' then return jsonb_build_object('ok',true); end if;
 if a.status <> 'Submitted' then raise exception 'Screening has started. Contact the hiring team to withdraw.'; end if;
 update public.public_applications set status='Withdrawn' where id=a.id;
 return jsonb_build_object('ok',true);
end $$;
revoke all on function public.withdraw_candidate_application(bigint) from public, anon;
grant execute on function public.withdraw_candidate_application(bigint) to authenticated;
create or replace function public.keep_withdrawn_application() returns trigger language plpgsql as $$
begin
 if old.status='Withdrawn' and new.status<>'Withdrawn' then raise exception 'This application was withdrawn'; end if;
 return new;
end $$;
create or replace trigger keep_withdrawn_application before update on public.public_applications for each row execute function public.keep_withdrawn_application();
notify pgrst, 'reload schema';

create or replace function public.candidate_withdrawal_available() returns boolean language sql stable as $$select true$$;
revoke all on function public.candidate_withdrawal_available() from public, anon;
grant execute on function public.candidate_withdrawal_available() to authenticated;
notify pgrst, 'reload schema';
