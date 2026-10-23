"""Fingerprint school records without exporting private row contents."""

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
SCHEMA_METADATA = {
    "django_migrations",
    "django_content_type",
    "auth_permission",
    "auth_group_permissions",
}


def main():
    import django

    django.setup()
    from django.db import connection, transaction
    from psycopg import sql

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["snapshot", "prepare-upgrade", "verify"])
    parser.add_argument("--phase", default="phase6", choices=["phase6", "phase7"])
    parser.add_argument("--allow-schema-additions", action="store_true")
    args = parser.parse_args()
    path = ROOT / ".local" / f"{args.phase}-preservation.json"
    original = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if args.action == "snapshot" and original:
        raise SystemExit("Snapshot already exists; refusing to replace evidence.")
    fingerprints = {}
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
        for table in connection.introspection.table_names(cursor):
            columns = original.get(table, {}).get("columns") or [
                c.name for c in connection.introspection.get_table_description(cursor, table)
            ]
            query = sql.SQL(
                "SELECT row_to_json(t)::text FROM (SELECT {} FROM {}) t "
                "ORDER BY row_to_json(t)::text"
            ).format(sql.SQL(",").join(map(sql.Identifier, columns)), sql.Identifier(table))
            cursor.execute(query)
            rows = cursor.fetchall()
            digest = hashlib.sha256()
            row_hashes = []
            for (value,) in rows:
                digest.update(value.encode())
                digest.update(b"\n")
                if table in SCHEMA_METADATA:
                    row_hashes.append(hashlib.sha256(value.encode()).hexdigest())
            fingerprints[table] = {
                "rows": len(rows),
                "sha256": digest.hexdigest(),
                "columns": columns,
            }
            if table in SCHEMA_METADATA:
                fingerprints[table]["row_hashes"] = row_hashes
    if args.action == "snapshot":
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(fingerprints, indent=2), encoding="utf-8")
    else:
        if not original:
            raise SystemExit("No preservation baseline exists.")
        changed = []
        added = {}
        for table, baseline in original.items():
            current = fingerprints.get(table)
            if (
                current
                and current["rows"] == baseline["rows"]
                and current["sha256"] == baseline["sha256"]
            ):
                continue
            if (
                args.allow_schema_additions
                and table in SCHEMA_METADATA
                and baseline.get("row_hashes")
                and current
            ):
                if not (Counter(baseline["row_hashes"]) - Counter(current["row_hashes"])):
                    added[table] = current["rows"] - baseline["rows"]
                    continue
            changed.append(table)
        if changed:
            raise SystemExit("Preservation mismatch: " + ", ".join(changed))
        if args.action == "prepare-upgrade":
            if args.allow_schema_additions:
                raise SystemExit("Prepare requires an exact pre-upgrade match.")
            # Enrich identical fingerprints with column names and metadata row hashes.
            # Original row counts and digests remain unchanged.
            path.write_text(json.dumps(fingerprints, indent=2), encoding="utf-8")
        if added:
            print(
                "Verified additive schema/permission metadata only: "
                + json.dumps(added, sort_keys=True)
            )
    baseline_rows = sum(v["rows"] for v in (original or fingerprints).values())
    baseline_tables = len(original or fingerprints)
    print(
        f"Preservation {args.action}: {baseline_rows} baseline rows across "
        f"{baseline_tables} original tables verified; no private values exported."
    )


if __name__ == "__main__":
    main()
