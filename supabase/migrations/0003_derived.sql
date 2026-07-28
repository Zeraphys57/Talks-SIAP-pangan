-- 0003_derived.sql
-- Series derived from ingestion: the cross-source reconciled price series and
-- the Google Trends demand signal.

-- ---------------------------------------------------------------------------
-- price_daily_unified: one row per commodity x region x day, reconciled across
-- however many sources reported that day.
--
-- Median rather than mean: with two to four sources, one portal publishing a
-- stale or mistyped figure would drag a mean noticeably. The spread is kept
-- alongside so disagreement stays visible instead of being averaged away.
-- ---------------------------------------------------------------------------
create table if not exists public.price_daily_unified (
    commodity_id      bigint        not null references public.commodities (id),
    region_id         bigint        not null references public.regions (id),
    obs_date          date          not null,

    price_median      numeric(14,2),
    price_min         numeric(14,2),
    price_max         numeric(14,2),
    n_sources         integer       not null default 0,
    source_spread_pct numeric(8,4),

    -- Interpolation is permitted only for gaps of <= 3 days. Longer gaps stay
    -- NULL. Imputed rows are excluded from ground-truth evaluation (M7) and
    -- rendered with a distinct visual treatment in the dashboard (M8).
    is_imputed        boolean       not null default false,
    imputation_method text,

    updated_at        timestamptz   not null default now(),

    primary key (commodity_id, region_id, obs_date),

    constraint pdu_imputed_has_method
        check (is_imputed = false or imputation_method is not null),
    constraint pdu_bounds_ordered
        check (price_min is null or price_max is null or price_min <= price_max),
    constraint pdu_n_sources_nonneg
        check (n_sources >= 0)
);

create index if not exists price_daily_unified_date_idx
    on public.price_daily_unified (obs_date);
create index if not exists price_daily_unified_real_idx
    on public.price_daily_unified (commodity_id, region_id, obs_date)
    where is_imputed = false;

comment on table public.price_daily_unified is
    'Cross-source reconciled daily series. The single input to every analysis module.';
comment on column public.price_daily_unified.source_spread_pct is
    '(price_max - price_min) / price_median * 100. A large spread signals a unit-conversion bug more often than a real market split.';
comment on column public.price_daily_unified.is_imputed is
    'True for gap-filled rows. Excluded from ground-truth evaluation; visually distinguished in the UI.';

-- ---------------------------------------------------------------------------
-- demand_signals: weekly Google Trends interest, the fusion D component.
--
-- Weekly resolution is a property of the source, not a limitation to hide.
-- It is forward-filled within the week when joined to daily prices, never
-- interpolated into a fake daily curve.
-- ---------------------------------------------------------------------------
create table if not exists public.demand_signals (
    id           bigint generated always as identity primary key,
    commodity_id bigint      not null references public.commodities (id),
    region_scope text        not null,
    keyword      text        not null,
    week_start   date        not null,

    interest     numeric(6,2),
    interest_z52 numeric(10,4),

    fetched_at   timestamptz not null default now(),

    constraint demand_signals_unique
        unique (commodity_id, region_scope, keyword, week_start),
    constraint demand_signals_interest_range
        check (interest is null or (interest >= 0 and interest <= 100))
);

create index if not exists demand_signals_lookup_idx
    on public.demand_signals (commodity_id, region_scope, week_start desc);

comment on table public.demand_signals is
    'Google Trends demand proxy via pytrends. Best-effort: when unavailable, fusion D degrades to 0 with a recorded reason.';
comment on column public.demand_signals.interest is
    'Raw Google Trends interest, 0-100, normalized by Google within the requested window.';
comment on column public.demand_signals.interest_z52 is
    'z-score of interest against a trailing 52-week baseline. This is what feeds fusion D, not the raw 0-100 value.';
