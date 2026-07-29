-- 0010_series_sources.sql
-- Which portals actually produced the number on a given dashboard page.
--
-- WHY
--
-- The commodity page named its sources from `source_regions`, which is the
-- *configured* coverage. For DI Yogyakarta that listed four: panelharga, pihps,
-- sp2kp and trends. Two of those are wrong:
--
--   panelharga  is_active = false. Its portal is broken upstream and it has
--               contributed zero observations. Naming it as a source of a
--               displayed price is simply untrue.
--   trends      is Google Trends, a demand signal. It never writes a price and
--               has nothing to do with the rupiah figure on the page.
--
-- `docs/architecture.md` claims every number can be walked back to a URL and a
-- timestamp, and `docs/design.md` puts provenance on the surface for that
-- reason. A provenance list that names portals which contributed nothing is
-- worse than no list: it looks like a guarantee and is not one.
--
-- The fix is to derive it from the observations rather than the configuration,
-- which makes both problems disappear on their own — neither portal has rows in
-- price_observations, so neither appears.
--
-- WHY A VIEW RATHER THAN OPENING price_observations
--
-- price_observations is ENGINE/LAB audience: it holds per-source prices, which
-- are the raw material of the analysis and not presentation data. This view
-- exposes only *metadata* — which source, how many rows, over what date range —
-- and no price at all, so the dashboard can be honest about provenance without
-- widening what anon can read about the prices themselves.

create or replace view public.series_sources as
    select o.commodity_id,
           o.region_id,
           s.slug          as source_slug,
           s.display_name  as source_name,
           s.base_url,
           count(*)        as observations,
           min(o.obs_date) as first_date,
           max(o.obs_date) as last_date
      from public.price_observations o
      join public.sources s on s.id = o.source_id
     group by o.commodity_id, o.region_id,
              s.slug, s.display_name, s.base_url;

comment on view public.series_sources is
    'Per commodity x region, the portals that actually contributed price observations, with counts and date ranges. Metadata only — no prices — so it is safe for the public dashboard while price_observations itself stays closed.';

-- Runs with the definer''s rights so it can read price_observations while that
-- table remains unreadable through the API. Deliberate, and the reason the view
-- exposes counts and dates but never price_idr.
alter view public.series_sources set (security_invoker = false);

grant select on public.series_sources to anon, authenticated;
