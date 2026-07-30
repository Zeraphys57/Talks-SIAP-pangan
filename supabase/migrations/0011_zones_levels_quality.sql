-- Separate the cluster zone from the fusion level, and give both a fourth state
-- for "we do not know".
--
-- ## Why the two vocabularies split
--
-- `cluster_assignments.zone` and `alerts.level` were both `merah/kuning/hijau`,
-- and both are rendered on the commodity page — the zone under "Kelompok
-- pergerakan harga", the level in the status card. They are different
-- quantities: the zone is a monthly regime from K-Means, the level is a daily
-- fusion score. Measured on run #64 against the latest fusion run, they disagree
-- on **22.6% of 39,089 pairs**, including 272 cells where the zone is `merah`
-- while the level on the same page is `hijau`. Both correct, both spelled the
-- same, on one screen.
--
-- The zone keeps the colour words: proposal Tujuan 3 commits in writing to
-- K-Means producing "zona strategis (merah, kuning, hijau)". Fusion carries no
-- such commitment, so fusion is what moves — to an escalation vocabulary that is
-- not a colour at all:
--
--     hijau  -> tenang
--     kuning -> waspada
--     merah  -> siaga
--
-- A side benefit that matters for design.md: the dashboard's primary signal now
-- has names that carry meaning without colour, which is the rule that document
-- argues for and the level labels were quietly leaning on colour to satisfy.
--
-- ## The fourth state
--
-- Both quantities could previously only say "safe". A date whose detectors
-- produced NULL scores fell through `anomaly_term`'s `max(scores) if scores else
-- 0.0` and landed in the lowest band, indistinguishable from a date that was
-- examined and found calm. Absence of evidence was rendered as evidence of
-- safety, on 41.31% of `nasional` dates, 13.66% of di_yogyakarta, and 100% of
-- kota_yogyakarta.
--
-- `alerts.level` gains `belum_dapat_dinilai`. `cluster_assignments.zone` becomes
-- nullable and gains `quality_reason`: a gated cell keeps its row and its
-- features for the audit trail, but takes no zone and does not enter the fit.

begin;

-- ---------------------------------------------------------------------------
-- alerts: rename the vocabulary, add the fourth state
-- ---------------------------------------------------------------------------
alter table public.alerts drop constraint if exists alerts_level_known;

update public.alerts set level = case level
    when 'hijau'  then 'tenang'
    when 'kuning' then 'waspada'
    when 'merah'  then 'siaga'
    else level
end
where level in ('hijau', 'kuning', 'merah');

alter table public.alerts add constraint alerts_level_known
    check (level in ('tenang', 'waspada', 'siaga', 'belum_dapat_dinilai'));

comment on column public.alerts.level is
    'Daily fusion escalation: tenang < waspada < siaga, or belum_dapat_dinilai '
    'when no detector could score the date. Deliberately not the cluster zone '
    'vocabulary — see cluster_assignments.zone.';

-- Written against the old vocabulary in 0004 and wrong the moment the rename
-- lands. A stale comment on the column that explains a downgrade rule is worse
-- than no comment.
comment on column public.alerts.corroboration is
    'The C term: n_sources_flagging / n_sources_reporting. siaga additionally '
    'requires C >= 0.5; single-source coverage caps at waspada.';

-- A score of 0 is meaningful for a scored date and meaningless for an unscored
-- one, so the two must not be told apart by the number alone.
alter table public.alerts drop constraint if exists alerts_score_range;
alter table public.alerts add constraint alerts_score_range
    check (
        (level = 'belum_dapat_dinilai' and fusion_score is null)
        or (level <> 'belum_dapat_dinilai'
            and fusion_score >= 0 and fusion_score <= 1)
    );
alter table public.alerts alter column fusion_score drop not null;

-- ---------------------------------------------------------------------------
-- cluster_assignments: gated cells keep their row, lose their zone
-- ---------------------------------------------------------------------------
alter table public.cluster_assignments drop constraint if exists cluster_assignments_zone_known;
alter table public.cluster_assignments alter column zone drop not null;
alter table public.cluster_assignments alter column cluster_id drop not null;

alter table public.cluster_assignments
    add column if not exists quality_reason text;

alter table public.cluster_assignments add constraint cluster_assignments_zone_known
    check (zone is null or zone in ('merah', 'kuning', 'hijau'));

-- A gated cell has no zone and states why; a fitted cell has a zone and no
-- reason. Anything else is a bug in the writer rather than a state we want.
alter table public.cluster_assignments add constraint cluster_assignments_gate_consistent
    check (
        (zone is null and cluster_id is null and quality_reason is not null)
        or (zone is not null and cluster_id is not null and quality_reason is null)
    );

comment on column public.cluster_assignments.zone is
    'Monthly regime zone from K-Means: merah/kuning/hijau, or NULL when the cell '
    'was gated out on data provenance. Named per proposal Tujuan 3, which commits '
    'to "zona strategis (merah, kuning, hijau)".';

comment on column public.cluster_assignments.quality_reason is
    'Why this cell was excluded from the fit: insufficient_real_obs, '
    'insufficient_distinct_values, or stale_dominated. NULL for fitted cells. '
    'The row is kept rather than deleted so coverage stays reportable.';

commit;
