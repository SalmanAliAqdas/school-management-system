from django.db import migrations

TABLES = [
    "learning_assignmentchange",
    "learning_submissionversion",
    "learning_feedback",
    "learning_attachment",
]
SQL = "\n".join(
    f"CREATE TRIGGER phase7_history BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION phase7_immutable();"
    for table in TABLES
)
REVERSE = "\n".join(f"DROP TRIGGER phase7_history ON {table};" for table in TABLES)


class Migration(migrations.Migration):
    dependencies = [("learning", "0001_initial"), ("scheduling", "0003_history_guards")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
