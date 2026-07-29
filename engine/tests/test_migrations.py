"""Structural tests over supabase/migrations/*.sql.

None of these need a database. They guard the properties that make migrations
usable as the schema source of truth: contiguous numbering, stable checksums,
and no table that exists in SQL without a declared access audience.
"""

from __future__ import annotations

import re

import pytest

from siap.doctor import TABLE_AUDIENCE, Audience
from siap.migrate import MigrationError, _checksum, discover

CREATE_TABLE_RE = re.compile(
    r"create\s+table\s+(?:if\s+not\s+exists\s+)?public\.(\w+)", re.IGNORECASE
)
ENABLE_RLS_RE = re.compile(
    r"alter\s+table\s+public\.(\w+)\s+enable\s+row\s+level\s+security", re.IGNORECASE
)


@pytest.fixture(scope="module")
def migrations():
    return discover()


@pytest.fixture(scope="module")
def all_sql(migrations) -> str:
    return "\n".join(m.sql for m in migrations)


def test_migrations_are_discovered(migrations) -> None:
    assert len(migrations) >= 6


def test_sequence_numbers_are_contiguous_from_one(migrations) -> None:
    assert [m.sequence for m in migrations] == list(range(1, len(migrations) + 1))


def test_filenames_follow_the_naming_convention(migrations) -> None:
    for m in migrations:
        assert re.fullmatch(r"\d{4}_[a-z0-9_]+\.sql", m.filename), m.filename


def test_checksum_ignores_line_endings() -> None:
    """Windows checkouts hold CRLF; the drift guard must not fire on that alone."""
    assert _checksum("create table x();\nselect 1;\n") == _checksum(
        "create table x();\r\nselect 1;\r\n"
    )


def test_checksum_changes_when_content_changes() -> None:
    assert _checksum("select 1;") != _checksum("select 2;")


def test_every_table_in_the_brief_exists_in_sql(all_sql: str) -> None:
    created = {m.lower() for m in CREATE_TABLE_RE.findall(all_sql)}
    required = {
        "commodities",
        "sources",
        "regions",
        "raw_snapshots",
        "fetch_failures",
        "price_observations",
        "price_daily_unified",
        "demand_signals",
        "analysis_runs",
        "anomaly_scores",
        "cluster_models",
        "cluster_assignments",
        "seasonal_components",
        "alerts",
        "gt_candidates",
        "gt_labels",
        "gt_events",
        "evaluation_results",
        "sus_responses",
    }
    assert required <= created, f"missing tables: {sorted(required - created)}"


def test_every_created_table_has_a_declared_audience(all_sql: str) -> None:
    """A new table without an entry in TABLE_AUDIENCE would slip past the RLS check."""
    created = {m.lower() for m in CREATE_TABLE_RE.findall(all_sql)}
    undeclared = created - set(TABLE_AUDIENCE) - {"schema_migrations"}
    assert not undeclared, f"tables with no declared audience: {sorted(undeclared)}"


def test_every_created_table_enables_rls(all_sql: str) -> None:
    created = {m.lower() for m in CREATE_TABLE_RE.findall(all_sql)}
    protected = {m.lower() for m in ENABLE_RLS_RE.findall(all_sql)}
    assert created <= protected, f"RLS never enabled on: {sorted(created - protected)}"


def test_no_anon_policy_exists_for_engine_only_tables(all_sql: str) -> None:
    """raw_snapshots and the ground-truth pool must be unreachable from the browser."""
    for table, audience in TABLE_AUDIENCE.items():
        if audience is not Audience.ENGINE:
            continue
        for match in re.finditer(
            rf"create\s+policy[^;]+?on\s+public\.{table}\b[^;]*;", all_sql, re.IGNORECASE | re.S
        ):
            statement = match.group(0)
            if re.search(r"\bfor\s+select\b", statement, re.IGNORECASE):
                pytest.fail(f"{table} is ENGINE-only but has a SELECT policy:\n{statement}")


def test_sus_score_is_generated_not_supplied(all_sql: str) -> None:
    """The scoring formula must live in one place, or the paper and form can drift."""
    assert re.search(
        r"sus_score\s+numeric\(\d+,\d+\)\s+generated\s+always\s+as", all_sql, re.IGNORECASE
    )


def test_imputed_rows_must_record_their_method(all_sql: str) -> None:
    assert "pdu_imputed_has_method" in all_sql


def test_evaluation_results_constrains_methods_to_the_four_arms(all_sql: str) -> None:
    match = re.search(r"evaluation_results_method_known[^;]+", all_sql, re.IGNORECASE | re.S)
    assert match, "no CHECK constraining evaluation_results.method"
    clause = match.group(0)
    for arm in ("zscore_only", "iforest_only", "union", "fusion"):
        assert arm in clause, f"ablation arm {arm} is not permitted by the CHECK"


def test_cluster_k_is_not_forced_to_three(all_sql: str) -> None:
    """The brief resolves the proposal's 'find optimal k' vs 'three zones' conflict."""
    assert "k_selected between 2 and 8" in all_sql


def test_discover_rejects_a_directory_with_gaps(tmp_path) -> None:
    (tmp_path / "0001_first.sql").write_text("select 1;", encoding="utf-8")
    (tmp_path / "0003_third.sql").write_text("select 3;", encoding="utf-8")
    with pytest.raises(MigrationError, match="gaps"):
        discover(tmp_path)


def test_discover_rejects_unrecognised_filenames(tmp_path) -> None:
    (tmp_path / "0001_first.sql").write_text("select 1;", encoding="utf-8")
    (tmp_path / "notes.sql").write_text("select 2;", encoding="utf-8")
    with pytest.raises(MigrationError, match="unrecognised"):
        discover(tmp_path)


# ---------------------------------------------------------------------------
# The /lab access model (0007, 0008)
# ---------------------------------------------------------------------------
def test_label_inserts_are_scoped_to_the_signed_in_annotator(all_sql: str) -> None:
    """Cohen's kappa assumes two independent label sets.

    If any signed-in team member could insert rows attributed to 'A2', that
    independence would rest on nobody having tried.
    """
    match = re.search(
        r"alter\s+policy\s+\"lab_insert_gt_labels\"[^;]+;", all_sql, re.IGNORECASE | re.S
    )
    assert match, "the gt_labels insert policy is never scoped to the caller"
    assert "current_annotator_code" in match.group(0)


def test_lab_functions_are_revoked_from_anon(all_sql: str) -> None:
    """Supabase's default privileges grant EXECUTE to anon explicitly.

    `revoke ... from public` does not remove an explicit grant, which is how
    0007 shipped a reachable function and `siap lab-check` caught it.
    """
    for function in ("current_annotator_code()", "lab_queue(integer)", "lab_progress()"):
        assert re.search(
            rf"revoke\s+all\s+on\s+function\s+public\.{re.escape(function)}\s+from\s+anon",
            all_sql,
            re.IGNORECASE,
        ), f"{function} is never revoked from anon"


def test_the_queue_function_reads_the_blind_view_not_the_pool(all_sql: str) -> None:
    """Structural blinding: the source has no sampling_stratum column to leak."""
    match = re.search(
        r"create\s+or\s+replace\s+function\s+public\.lab_queue.*?\$\$(.*?)\$\$",
        all_sql,
        re.IGNORECASE | re.S,
    )
    assert match, "lab_queue is not defined"
    body = match.group(1)
    assert "gt_labeling_queue" in body
    assert "gt_candidates" not in body, "lab_queue reads the unblinded pool directly"


def test_annotator_codes_are_pseudonymous(all_sql: str) -> None:
    """The code appears in the paper; it must not be someone's name."""
    assert "lab_annotators_code_is_pseudonymous" in all_sql
