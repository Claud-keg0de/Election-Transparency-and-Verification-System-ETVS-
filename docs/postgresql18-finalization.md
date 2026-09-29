# PostgreSQL 18 ETVS finalization

The authoritative ETVS schema is `schema.sql`. It is PostgreSQL 18 compatible and is followed by the numbered migrations.

## Clean PG18 rebuild

The Debian VM currently has PostgreSQL 18 on port 5433. PostgreSQL 17 remains on port 5432 and must not be modified by this procedure.

From the repository root:

```bash
chmod +x tools/rebuild_pg18.sh
ETVS_REBUILD_PG18=YES ETVS_PG18_PORT=5433 ./tools/rebuild_pg18.sh
```

The rebuild:

1. terminates existing connections to the PG18 `etvs` database;
2. drops and recreates `etvs` from `template0`, owned by `etvs_owner`;
3. creates the authoritative schema;
4. applies every migration with `ON_ERROR_STOP=1`;
5. grants the runtime roles their intended database/schema/table/sequence access;
6. verifies the PostgreSQL version, table contract, foreign-key contract, and required triggers.

PostgreSQL documents that `CREATE DATABASE ... TEMPLATE template0` provides a pristine database base and that `pg_restore` can rebuild a database from an archive; the ETVS rebuild intentionally uses the repository schema instead of the old PG17 dump so obsolete/corrupt definitions are not carried forward.

## Optional controlled fixture

Only after the clean schema is structurally verified:

```bash
ETVS_REBUILD_PG18=YES ETVS_PG18_PORT=5433 ETVS_SEED=1 ./tools/rebuild_pg18.sh
```

The seed is a deterministic test fixture. It is not the normal ETVS data-entry interface.

## Connection test inside Debian

Use the explicit PG18 port:

```bash
sudo -u postgres psql -p 5433 -d etvs -c "SELECT current_database(), current_user, version();"
```

The result must report PostgreSQL 18.6.

For the Python application, activate the repository virtual environment and use:

```bash
source .venv/bin/activate
export ETVS_DB_HOST=127.0.0.1
export ETVS_DB_PORT=5433
export ETVS_DB_NAME=etvs
export ETVS_DB_USER=etvs_app
export ETVS_DB_PASSWORD='your-local-password'
python tools/check_db_connection.py
```

The checker must report `STATUS: CONNECTED` and `required public tables present=14/14`.

## DBeaver / VirtualBox

The PostgreSQL server inside Debian is on guest port 5433.

If the existing VirtualBox NAT rule is still:

`127.0.0.1:5433 -> 10.0.2.15:5432`

then Windows port 5433 still reaches PostgreSQL 17. Change the forwarding target to:

`127.0.0.1:5433 -> 10.0.2.15:5433`

and keep the DBeaver connection:

- Host: `127.0.0.1`
- Port: `5433`
- Database: `etvs`
- User: `etvs_app`
- Password: the local `etvs_app` password
- Schema: `public`

Then run in DBeaver:

```sql
SELECT current_database(), current_user, version();

SELECT
  (SELECT count(*) FROM etvs_regions) AS regions,
  (SELECT count(*) FROM counties) AS counties,
  (SELECT count(*) FROM constituencies) AS constituencies,
  (SELECT count(*) FROM wards) AS wards,
  (SELECT count(*) FROM registration_centres) AS registration_centres,
  (SELECT count(*) FROM polling_stations) AS polling_stations;
```

The first query must identify PostgreSQL 18. The geography counts should be verified after the controlled Kenya geography loader has populated the reference data.

## Safety

Do not drop PostgreSQL 17 until the PG18 database has been independently verified in Debian, the Flask application, and DBeaver. PostgreSQL client tools accept an explicit `-p` port, so always specify `-p 5433` while PG18 remains the secondary cluster.
