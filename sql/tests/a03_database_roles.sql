\set ON_ERROR_STOP on

BEGIN;

DO $test$
DECLARE
    base_table_count integer;
    migrator_owned_count integer;
    loader_delete_count integer;
    reader_base_count integer;
    reader_view_count integer;
BEGIN
    SELECT
        count(*),
        count(*) FILTER (
            WHERE pg_get_userbyid(class.relowner) = 'arsia_migrator'
        ),
        count(*) FILTER (
            WHERE has_table_privilege(
                'arsia_loader',
                class.oid,
                'DELETE'
            )
        ),
        count(*) FILTER (
            WHERE has_table_privilege(
                'arsia_reader',
                class.oid,
                'SELECT'
            )
        )
    INTO
        base_table_count,
        migrator_owned_count,
        loader_delete_count,
        reader_base_count
    FROM pg_class AS class
    JOIN pg_namespace AS namespace
        ON namespace.oid = class.relnamespace
    WHERE namespace.nspname IN (
        'meta',
        'raw',
        'rv',
        'canonical',
        'dw',
        'qa'
    )
      AND class.relkind = 'r';

    SELECT count(*)
    INTO reader_view_count
    FROM pg_class AS class
    JOIN pg_namespace AS namespace
        ON namespace.oid = class.relnamespace
    WHERE namespace.nspname = 'published'
      AND class.relkind = 'v'
      AND has_table_privilege(
          'arsia_reader',
          class.oid,
          'SELECT'
      );

    IF base_table_count <> 17
       OR migrator_owned_count <> 17
       OR loader_delete_count <> 0
       OR reader_base_count <> 0
       OR reader_view_count <> 7 THEN
        RAISE EXCEPTION
            'role audit failed: tables %, owned %, loader delete %, reader base %, reader views %',
            base_table_count,
            migrator_owned_count,
            loader_delete_count,
            reader_base_count,
            reader_view_count;
    END IF;

    IF NOT pg_has_role(
        'arsia_owner',
        'arsia_migrator',
        'MEMBER'
    ) THEN
        RAISE EXCEPTION 'arsia_owner is not a migrator member';
    END IF;

    RAISE NOTICE
        'role audit passed: 17 migrator-owned tables, 0 loader deletes, 0 reader base tables, 7 reader views';
END
$test$;

INSERT INTO meta.batch (
    batch_id,
    dataset_kind,
    input_fingerprint,
    manifest,
    status,
    finished_at
)
VALUES
    (
        '00000000-0000-0000-0000-000000000931',
        'synthetic',
        repeat('c', 64),
        '{"test":"published"}'::jsonb,
        'succeeded',
        now()
    ),
    (
        '00000000-0000-0000-0000-000000000932',
        'official',
        repeat('d', 64),
        '{"test":"candidate"}'::jsonb,
        'running',
        NULL
    );

INSERT INTO meta.current_release (dataset_kind, batch_id)
VALUES ('synthetic', '00000000-0000-0000-0000-000000000931');

INSERT INTO qa.check_result (
    batch_id,
    rule_id,
    object_key,
    result,
    affected_count,
    actual,
    expected,
    evidence
)
VALUES
    (
        '00000000-0000-0000-0000-000000000931',
        'A03_TEST',
        'published',
        'pass',
        0,
        '{}'::jsonb,
        '{}'::jsonb,
        '{}'::jsonb
    ),
    (
        '00000000-0000-0000-0000-000000000932',
        'A03_TEST',
        'candidate',
        'pass',
        0,
        '{}'::jsonb,
        '{}'::jsonb,
        '{}'::jsonb
    );

SET LOCAL ROLE arsia_reader;

DO $test$
DECLARE
    base_read_blocked boolean := false;
    view_write_blocked boolean := false;
    visible_rows integer;
    candidate_rows integer;
BEGIN
    SELECT count(*) INTO visible_rows
    FROM published.current_qa_result
    WHERE rule_id = 'A03_TEST';

    SELECT count(*) INTO candidate_rows
    FROM published.current_qa_result
    WHERE batch_id = '00000000-0000-0000-0000-000000000932';

    IF visible_rows <> 1 OR candidate_rows <> 0 THEN
        RAISE EXCEPTION
            'reader publication filter failed: visible %, candidate %',
            visible_rows,
            candidate_rows;
    END IF;

    BEGIN
        PERFORM count(*) FROM meta.batch;
    EXCEPTION
        WHEN insufficient_privilege THEN
            base_read_blocked := true;
    END;

    IF NOT base_read_blocked THEN
        RAISE EXCEPTION 'reader unexpectedly read meta.batch';
    END IF;

    BEGIN
        UPDATE published.current_release
        SET switched_at = switched_at
        WHERE false;
    EXCEPTION
        WHEN insufficient_privilege THEN
            view_write_blocked := true;
    END;

    IF NOT view_write_blocked THEN
        RAISE EXCEPTION 'reader unexpectedly updated a published view';
    END IF;

    RAISE NOTICE
        'reader checks passed: one published row, zero candidate rows, base read and view write rejected';
END
$test$;

RESET ROLE;
SET LOCAL ROLE arsia_loader;

INSERT INTO qa.check_result (
    batch_id,
    rule_id,
    object_key,
    result,
    affected_count,
    actual,
    expected,
    evidence
)
VALUES (
    '00000000-0000-0000-0000-000000000932',
    'A03_LOADER_TEST',
    'candidate',
    'pass',
    0,
    '{}'::jsonb,
    '{}'::jsonb,
    '{}'::jsonb
);

UPDATE meta.batch
SET
    status = 'failed',
    finished_at = now(),
    error_details = '{"test":"expected"}'::jsonb
WHERE batch_id = '00000000-0000-0000-0000-000000000932';

DO $test$
DECLARE
    delete_blocked boolean := false;
    ddl_blocked boolean := false;
BEGIN
    BEGIN
        DELETE FROM qa.check_result WHERE false;
    EXCEPTION
        WHEN insufficient_privilege THEN
            delete_blocked := true;
    END;

    IF NOT delete_blocked THEN
        RAISE EXCEPTION 'loader unexpectedly received DELETE';
    END IF;

    BEGIN
        CREATE TABLE qa.a03_forbidden_ddl (id integer);
    EXCEPTION
        WHEN insufficient_privilege THEN
            ddl_blocked := true;
    END;

    IF NOT ddl_blocked THEN
        RAISE EXCEPTION 'loader unexpectedly received schema DDL';
    END IF;

    RAISE NOTICE
        'loader checks passed: INSERT and batch-state UPDATE allowed; DELETE and DDL rejected';
END
$test$;

RESET ROLE;
ROLLBACK;
