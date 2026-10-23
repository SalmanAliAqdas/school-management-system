"""Fingerprint existing PostgreSQL rows without exporting private row contents."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")


def main():
    import django

    django.setup()
    from django.db import connection
    from psycopg import sql

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["snapshot", "verify"])
    args = parser.parse_args()
    path = ROOT / ".local" / "phase6-preservation.json"
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
        tables = connection.introspection.table_names(cursor)
        fingerprints = {}
        for table in tables:
            cursor.execute(
                sql.SQL(
                    "SELECT row_to_json(t)::text FROM {} t ORDER BY row_to_json(t)::text"
                ).format(sql.Identifier(table))
            )
            rows = cursor.fetchall()
            digest = hashlib.sha256()
            for (value,) in rows:
                digest.update(value.encode())
                digest.update(b"\n")
            fingerprints[table] = {"rows": len(rows), "sha256": digest.hexdigest()}
    if args.action == "snapshot":
        if path.exists():
            raise SystemExit("Snapshot already exists; refusing to replace preservation evidence.")
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(fingerprints, indent=2), encoding="utf-8")
    else:
        original = json.loads(path.read_text(encoding="utf-8"))
        changed = [table for table, value in original.items() if fingerprints.get(table) != value]
        if changed:
            raise SystemExit("Preservation mismatch in tables: " + ", ".join(changed))
    print(
        f"Preservation {args.action}: {sum(v['rows'] for v in fingerprints.values())} rows "
        f"across {len(fingerprints)} tables; no private values exported."
    )


if __name__ == "__main__":
    main()
