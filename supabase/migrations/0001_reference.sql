-- 0001_reference.sql
-- Reference tables: the fixed vocabulary everything else joins against.
-- Rows are seeded from engine/config/*.yaml by `siap seed` (idempotent upsert).

-- ---------------------------------------------------------------------------
-- commodities
-- ---------------------------------------------------------------------------
create table if not exists public.commodities (
    id                bigint generated always as identity primary key,
    slug              text        not null unique,
    display_name      text        not null,
    canonical_unit    text        not null,
    sort_order        integer     not null default 0,

    -- Guard against unit-conversion bugs (a missed litre/kg or per-ekor
    -- conversion produces a 10x "anomaly" that looks like a finding).
    -- Normalization raises outside this band instead of inserting.
    price_min_plausible numeric(14,2) not null,
    price_max_plausible numeric(14,2) not null,

    trends_keywords   text[]      not null default '{}',
    source_aliases    jsonb       not null default '{}'::jsonb,

    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),

    constraint commodities_slug_format
        check (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    constraint commodities_unit_known
        check (canonical_unit in ('kg', 'liter', 'butir', 'ikat')),
    constraint commodities_plausible_band
        check (price_min_plausible > 0 and price_max_plausible > price_min_plausible)
);

comment on table  public.commodities is
    'The 12 tracked food commodities. Seeded from engine/config/commodities.yaml.';
comment on column public.commodities.price_min_plausible is
    'Lower bound of the sanity band. Deliberately wide: catches order-of-magnitude unit bugs, not market anomalies.';
comment on column public.commodities.source_aliases is
    'jsonb map of source slug -> array of that portal''s spellings for this commodity. Unmapped names raise during normalization.';

-- ---------------------------------------------------------------------------
-- regions
-- ---------------------------------------------------------------------------
create table if not exists public.regions (
    id           bigint generated always as identity primary key,
    slug         text        not null unique,
    display_name text        not null,
    level        text        not null,
    parent_slug  text        references public.regions (slug) on update cascade,
    bps_code     text,
    created_at   timestamptz not null default now(),

    constraint regions_level_known
        check (level in ('national', 'province', 'city'))
);

comment on table public.regions is
    'Geographic scopes. Seeded from engine/config/regions.yaml. Slugs use underscores by brief convention.';

-- ---------------------------------------------------------------------------
-- sources
-- ---------------------------------------------------------------------------
create table if not exists public.sources (
    id                  bigint generated always as identity primary key,
    slug                text        not null unique,
    display_name        text        not null,
    owner               text        not null,
    base_url            text        not null,
    robots_url          text,
    scope               text        not null,
    cadence             text        not null,

    -- Which reporting convention obs_date follows for this portal, e.g. whether
    -- a row published on day D describes prices collected on D or D-1.
    -- NULL until confirmed against the live portal in M1; never guessed.
    obs_date_convention text,

    is_active           boolean     not null default true,
    notes               text,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),

    constraint sources_cadence_known
        check (cadence in ('daily', 'weekly'))
);

comment on table public.sources is
    'Upstream portals. Panel Harga (Bapanas) and SP2KP (Kemendag) are distinct systems; SISKAPERBAPO is Jawa Timur.';
comment on column public.sources.obs_date_convention is
    'Source reporting convention for obs_date, in WIB. NULL means not yet confirmed against the live portal.';

-- ---------------------------------------------------------------------------
-- source_regions: which regions each source actually covers.
-- Coverage is what makes the fusion corroboration term C meaningful — C is
-- n_sources_flagging / n_sources_reporting, and "reporting" is defined here.
-- ---------------------------------------------------------------------------
create table if not exists public.source_regions (
    source_id bigint not null references public.sources (id) on delete cascade,
    region_id bigint not null references public.regions (id) on delete cascade,
    primary key (source_id, region_id)
);

comment on table public.source_regions is
    'Declared coverage matrix. Defines the denominator of the fusion corroboration term C.';
