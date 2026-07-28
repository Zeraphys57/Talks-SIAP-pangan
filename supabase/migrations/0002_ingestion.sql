-- 0002_ingestion.sql
-- Raw capture and normalized observations.
--
-- Provenance chain, end to end:
--   alerts -> price_daily_unified -> price_observations -> raw_snapshots -> URL + fetched_at
-- Every number rendered in the UI must be walkable back along this chain.

-- ---------------------------------------------------------------------------
-- raw_snapshots: the response body exactly as received.
-- Portals redesign. Keeping the body means history can be RE-PARSED with a new
-- parser_version instead of re-scraped from an archive that may not exist.
-- ---------------------------------------------------------------------------
create table if not exists public.raw_snapshots (
    id               bigint generated always as identity primary key,
    source_id        bigint      not null references public.sources (id),
    fetched_at       timestamptz not null default now(),
    url              text        not null,
    http_status      integer,
    content_hash     text        not null,
    body_compressed  bytea,
    parser_version   text        not null,
    request_headers  jsonb       not null default '{}'::jsonb,
    byte_size        integer
);

create index if not exists raw_snapshots_source_fetched_idx
    on public.raw_snapshots (source_id, fetched_at desc);
create index if not exists raw_snapshots_content_hash_idx
    on public.raw_snapshots (content_hash);

comment on table public.raw_snapshots is
    'Verbatim upstream responses, gzip-compressed. Enables re-parsing history when a portal changes structure.';
comment on column public.raw_snapshots.content_hash is
    'sha256 of the uncompressed body. Identical hash across fetches means the portal served unchanged content.';
comment on column public.raw_snapshots.parser_version is
    'Version of the parser that produced observations from this snapshot. Bumped whenever parsing logic changes.';

-- ---------------------------------------------------------------------------
-- fetch_failures: every error path writes here. There is no synthetic
-- fallback anywhere in this system; a failed fetch is recorded, not invented.
-- ---------------------------------------------------------------------------
create table if not exists public.fetch_failures (
    id           bigint generated always as identity primary key,
    source_id    bigint      references public.sources (id),
    attempted_at timestamptz not null default now(),
    url          text,
    error_class  text        not null,
    error_detail text,
    retry_count  integer     not null default 0,
    run_context  jsonb       not null default '{}'::jsonb
);

create index if not exists fetch_failures_source_attempted_idx
    on public.fetch_failures (source_id, attempted_at desc);

comment on table public.fetch_failures is
    'Loud failure log. A gap in price_observations must always be explainable by a row here.';

-- ---------------------------------------------------------------------------
-- price_observations: one price, from one source, for one commodity, region
-- and date — already converted to the commodity''s canonical unit.
-- ---------------------------------------------------------------------------
create table if not exists public.price_observations (
    id             bigint generated always as identity primary key,
    commodity_id   bigint        not null references public.commodities (id),
    source_id      bigint        not null references public.sources (id),
    region_id      bigint        not null references public.regions (id),
    obs_date       date          not null,

    price_idr      numeric(14,2) not null,
    raw_unit       text,
    canonical_unit text          not null,
    unit_factor    numeric(12,6) not null default 1,

    snapshot_id    bigint        references public.raw_snapshots (id),
    ingested_at    timestamptz   not null default now(),

    constraint price_observations_positive check (price_idr > 0),
    constraint price_observations_unit_factor_positive check (unit_factor > 0),
    constraint price_observations_unique
        unique (commodity_id, source_id, region_id, obs_date)
);

create index if not exists price_observations_series_idx
    on public.price_observations (commodity_id, region_id, obs_date);
create index if not exists price_observations_date_idx
    on public.price_observations (obs_date);

comment on table public.price_observations is
    'Normalized per-source prices in canonical units. UNIQUE key makes re-ingestion idempotent.';
comment on column public.price_observations.raw_unit is
    'Unit string as published by the portal, before conversion. Kept so a conversion bug is diagnosable after the fact.';
comment on column public.price_observations.unit_factor is
    'Multiplier applied to reach canonical_unit. 1 when the portal already published in the canonical unit.';
comment on column public.price_observations.obs_date is
    'Date in the source''s own reporting convention (WIB). See sources.obs_date_convention and docs/sources.md.';
