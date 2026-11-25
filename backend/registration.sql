begin;

create unique index if not exists registrations_event_user_uidx
    on public.registrations (event_id, user_id);

create or replace function public.register_for_event(p_user_id uuid, p_event_id uuid)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    event_capacity public.events.capacity%type;
    registration public.registrations%rowtype;
begin
    -- Serialize registration RPCs for the same event without a table UPDATE grant.
    perform pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended('register_for_event:' || p_event_id::text, 0)
    );

    select capacity into event_capacity
    from public.events
    where id = p_event_id;

    if not found then
        raise sqlstate 'PT404' using message = 'Event not found.';
    end if;

    perform 1 from public.users where id = p_user_id;
    if not found then
        raise sqlstate 'PT404' using message = 'User not found.';
    end if;

    if exists (
        select 1 from public.registrations
        where event_id = p_event_id and user_id = p_user_id
    ) then
        raise sqlstate 'PT409' using message = 'This user is already registered for the event.';
    end if;

    if event_capacity is not null and (
        select count(*) from public.registrations where event_id = p_event_id
    ) >= event_capacity then
        raise sqlstate 'PT409' using message = 'The event has reached capacity.';
    end if;

    insert into public.registrations (id, user_id, event_id, created_at)
    values (gen_random_uuid(), p_user_id, p_event_id, now())
    returning * into registration;

    return jsonb_build_object(
        'id', registration.id,
        'user_id', registration.user_id,
        'event_id', registration.event_id,
        'created_at', registration.created_at
    );
end;
$$;

revoke execute on function public.register_for_event(uuid, uuid)
    from public, anon, authenticated;
grant execute on function public.register_for_event(uuid, uuid) to service_role;

notify pgrst, 'reload schema';
commit;
