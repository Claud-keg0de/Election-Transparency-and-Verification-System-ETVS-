/*
===============================================================================
ETVS PERMISSIONS V2
===============================================================================

Run this file as PostgreSQL superuser/administrative owner after schema_v2.sql.

Roles
-----
etvs_owner  : NOLOGIN ownership and schema maintenance role.
etvs_seed   : controlled import/seed role; may change source/input data but not
              audit output.
etvs_app    : application/audit role; reads source data and appends audit and
              evidence-validation data. It cannot alter existing source records
              or audit findings.
etvs_reader : reporting/dashboard role; SELECT-only on public ETVS data.

Sensitive elector/evidence data is in etvs_private. etvs_reader has no access
to that schema. etvs_app can append evidence and validation records but cannot
read the encrypted original elector reference ciphertext.
===============================================================================
*/

BEGIN;


/* ---------------------------------------------------------------------------
   1. CREATE ROLES ONLY IF THEY DO NOT ALREADY EXIST
   --------------------------------------------------------------------------- */

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etvs_owner') THEN
        CREATE ROLE etvs_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etvs_seed') THEN
        CREATE ROLE etvs_seed LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etvs_app') THEN
        CREATE ROLE etvs_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etvs_reader') THEN
        CREATE ROLE etvs_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;


/* Do not store or change passwords in the repository. Set LOGIN passwords
   separately with an administrator-managed secret mechanism. */


/* ---------------------------------------------------------------------------
   2. DATABASE / SCHEMA BOUNDARY
   --------------------------------------------------------------------------- */

REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA etvs_private FROM PUBLIC;

GRANT USAGE ON SCHEMA public
    TO etvs_owner, etvs_seed, etvs_app, etvs_reader;

GRANT USAGE ON SCHEMA etvs_private
    TO etvs_owner, etvs_seed, etvs_app;


/* ---------------------------------------------------------------------------
   3. REMOVE BROAD EXISTING TABLE/SEQUENCE ACCESS
   --------------------------------------------------------------------------- */

REVOKE ALL ON ALL TABLES IN SCHEMA public
    FROM etvs_seed, etvs_app, etvs_reader, PUBLIC;

REVOKE ALL ON ALL SEQUENCES IN SCHEMA public
    FROM etvs_seed, etvs_app, etvs_reader, PUBLIC;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public
    FROM etvs_seed, etvs_app, etvs_reader, PUBLIC;

REVOKE ALL ON ALL TABLES IN SCHEMA etvs_private
    FROM etvs_seed, etvs_app, PUBLIC;

REVOKE ALL ON ALL SEQUENCES IN SCHEMA etvs_private
    FROM etvs_seed, etvs_app, PUBLIC;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA etvs_private
    FROM etvs_seed, etvs_app, PUBLIC;


/* ---------------------------------------------------------------------------
   4. OWNER ROLE
   --------------------------------------------------------------------------- */

GRANT ALL ON ALL TABLES IN SCHEMA public TO etvs_owner;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO etvs_owner;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO etvs_owner;

GRANT ALL ON ALL TABLES IN SCHEMA etvs_private TO etvs_owner;
GRANT ALL ON ALL SEQUENCES IN SCHEMA etvs_private TO etvs_owner;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA etvs_private TO etvs_owner;


/* ---------------------------------------------------------------------------
   5. READER ROLE
   --------------------------------------------------------------------------- */

GRANT SELECT ON ALL TABLES IN SCHEMA public TO etvs_reader;


/* ---------------------------------------------------------------------------
   6. SEED/IMPORT ROLE
   ---------------------------------------------------------------------------

   etvs_seed can maintain source/reference/input data. Audit outputs are
   explicitly excluded.
   --------------------------------------------------------------------------- */

GRANT SELECT, INSERT, UPDATE, DELETE
    ON ALL TABLES IN SCHEMA public
    TO etvs_seed;

GRANT USAGE, SELECT, UPDATE
    ON ALL SEQUENCES IN SCHEMA public
    TO etvs_seed;

REVOKE ALL ON TABLE
    public.audit_runs,
    public.audit_findings,
    public.audit_passed_results,
    public.audit_failed_results,
    public.audit_position_results,
    public.source_comparisons
    FROM etvs_seed;

REVOKE ALL ON ALL TABLES IN SCHEMA etvs_private
    FROM etvs_seed;


/* ---------------------------------------------------------------------------
   7. APPLICATION/AUDIT ROLE
   ---------------------------------------------------------------------------

   Public source data is read-only to etvs_app.

   Audit output is append-only from the application's perspective.
   No UPDATE/DELETE/TRUNCATE is granted on audit output.

   Sensitive evidence is append-only. Existing evidence/validation rows are
   not editable by the application role.
   --------------------------------------------------------------------------- */

GRANT SELECT ON ALL TABLES IN SCHEMA public TO etvs_app;

GRANT INSERT
    ON TABLE
        public.audit_runs,
        public.audit_findings,
        public.audit_passed_results,
        public.audit_failed_results,
        public.audit_position_results,
        public.source_comparisons
    TO etvs_app;

GRANT USAGE, SELECT
    ON ALL SEQUENCES IN SCHEMA public
    TO etvs_app;


/* Sensitive evidence append boundary */
GRANT SELECT ON
    etvs_private.device_capabilities
    TO etvs_app;

GRANT SELECT, INSERT ON
    etvs_private.devices,
    etvs_private.device_capability_assignments,
    etvs_private.electors,
    etvs_private.elector_ballot_artifacts,
    etvs_private.counterfoil_artifacts,
    etvs_private.ballot_artifact_validations,
    etvs_private.ballot_artifact_validation_checks,
    etvs_private.ballot_artifact_security_links
    TO etvs_app;

GRANT USAGE, SELECT
    ON ALL SEQUENCES IN SCHEMA etvs_private
    TO etvs_app;


/* Do not expose the encrypted original elector reference to the application
   through SELECT. The application can use the hash/token, not plaintext. */
REVOKE SELECT ON etvs_private.electors FROM etvs_app;

GRANT SELECT (
    elector_id,
    election_id,
    polling_station_id,
    reference_type,
    elector_reference_hash,
    created_at,
    status
)
ON etvs_private.electors
TO etvs_app;


/* Application cannot rewrite or delete evidence/validation history. */
REVOKE UPDATE, DELETE, TRUNCATE
    ON TABLE
        etvs_private.electors,
        etvs_private.elector_ballot_artifacts,
        etvs_private.counterfoil_artifacts,
        etvs_private.ballot_artifact_validations,
        etvs_private.ballot_artifact_validation_checks,
        etvs_private.ballot_artifact_security_links
    FROM etvs_app;


/* ---------------------------------------------------------------------------
   8. DEFAULT PRIVILEGES FOR FUTURE OBJECTS CREATED BY etvs_owner
   --------------------------------------------------------------------------- */

ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA public
    REVOKE ALL ON TABLES FROM PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA public
    GRANT SELECT ON TABLES TO etvs_reader;

ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA public
    GRANT SELECT ON TABLES TO etvs_app;

ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO etvs_seed;

ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA public
    GRANT ALL ON TABLES TO etvs_owner;

ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA public
    REVOKE ALL ON SEQUENCES FROM PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA public
    GRANT ALL ON SEQUENCES TO etvs_owner;

ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO etvs_seed;

ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO etvs_app;

ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA public
    REVOKE ALL ON FUNCTIONS FROM PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA public
    GRANT ALL ON FUNCTIONS TO etvs_owner;

ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA etvs_private
    REVOKE ALL ON TABLES FROM PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA etvs_private
    GRANT ALL ON TABLES TO etvs_owner;

ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA etvs_private
    GRANT SELECT, INSERT ON TABLES TO etvs_app;

ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA etvs_private
    REVOKE ALL ON SEQUENCES FROM PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA etvs_private
    GRANT ALL ON SEQUENCES TO etvs_owner;

ALTER DEFAULT PRIVILEGES FOR ROLE etvs_owner IN SCHEMA etvs_private
    GRANT USAGE, SELECT ON SEQUENCES TO etvs_app;


/* ---------------------------------------------------------------------------
   9. OWNERSHIP TRANSFER
   ---------------------------------------------------------------------------

   Ownership is transferred to etvs_owner so application/reader roles do not
   accidentally become object owners and bypass ordinary GRANT restrictions.
   --------------------------------------------------------------------------- */

DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT schemaname, tablename
        FROM pg_tables
        WHERE schemaname IN ('public','etvs_private')
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.%I OWNER TO etvs_owner',
            r.schemaname, r.tablename
        );
    END LOOP;

    FOR r IN
        SELECT sequence_schema, sequence_name
        FROM information_schema.sequences
        WHERE sequence_schema IN ('public','etvs_private')
    LOOP
        EXECUTE format(
            'ALTER SEQUENCE %I.%I OWNER TO etvs_owner',
            r.sequence_schema, r.sequence_name
        );
    END LOOP;
END
$$;


/* Re-apply critical privileges after ownership transfer. */
GRANT USAGE ON SCHEMA public TO etvs_seed, etvs_app, etvs_reader;
GRANT USAGE ON SCHEMA etvs_private TO etvs_app, etvs_seed;

COMMIT;


/*
===============================================================================
PERMISSION VERIFICATION QUERIES
===============================================================================

-- Role attributes
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolinherit, rolcanlogin
FROM pg_roles
WHERE rolname IN ('etvs_owner','etvs_seed','etvs_app','etvs_reader')
ORDER BY rolname;

-- Public table ACLs
SELECT table_schema, table_name, grantee, privilege_type
FROM information_schema.role_table_grants
WHERE grantee IN ('etvs_seed','etvs_app','etvs_reader')
ORDER BY table_schema, table_name, grantee, privilege_type;

-- Sensitive schema ACLs
SELECT table_schema, table_name, grantee, privilege_type
FROM information_schema.role_table_grants
WHERE table_schema = 'etvs_private'
ORDER BY table_name, grantee, privilege_type;

-- Confirm the encrypted elector reference is not readable by etvs_app:
-- (run while connected as etvs_app)
-- SELECT elector_reference_ciphertext FROM etvs_private.electors;
-- Expected: permission denied.

===============================================================================
*/
