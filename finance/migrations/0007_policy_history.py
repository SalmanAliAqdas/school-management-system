from django.db import migrations, models

SQL = r"""
CREATE FUNCTION schoolos_finance_reconciliation_history() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r finance_financialrequest%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Reconciliation history cannot be deleted'; END IF;
 SELECT q.* INTO r FROM finance_financialrequest q JOIN finance_reconciliation rec ON rec.request_id=q.id WHERE rec.id=OLD.reconciliation_id;
 IF NOT OLD.is_active OR NEW.is_active OR r.state<>'rejected' OR r.id::text IS DISTINCT FROM current_setting('schoolos.finance_request',true) OR
 (to_jsonb(NEW)-ARRAY['is_active','updated_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['is_active','updated_at']) THEN RAISE EXCEPTION 'Only rejection can retire a reserved reconciliation line'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER finance_reconciliation_history BEFORE UPDATE OR DELETE ON finance_reconciliationline FOR EACH ROW EXECUTE FUNCTION schoolos_finance_reconciliation_history();
CREATE TRIGGER finance_exemption_approval BEFORE INSERT ON finance_latefeeexemption FOR EACH ROW EXECUTE FUNCTION schoolos_finance_compensation_guard();
CREATE TRIGGER finance_exemption_history BEFORE UPDATE OR DELETE ON finance_latefeeexemption FOR EACH ROW EXECUTE FUNCTION schoolos_finance_append_only();
"""


def forwards(apps, schema_editor):
    schema_editor.execute(SQL, params=None)


def backwards(apps, schema_editor):
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS finance_exemption_approval ON finance_latefeeexemption"
    )
    schema_editor.execute(
        "DROP FUNCTION IF EXISTS schoolos_finance_reconciliation_history() CASCADE"
    )
    schema_editor.execute(
        "DROP TRIGGER IF EXISTS finance_exemption_history ON finance_latefeeexemption"
    )


class Migration(migrations.Migration):
    dependencies = [("finance", "0006_late_fee_exemptions")]
    operations = [
        migrations.AddConstraint(
            model_name="financesettings",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    senior_discount_percent__gte=0,
                    senior_discount_percent__lte=100,
                    discount_ceiling_percent__gte=0,
                    discount_ceiling_percent__lte=100,
                    reminder_repeat_days__gte=1,
                ),
                name="finance_policy_percent_ranges",
            ),
        ),
        migrations.RunPython(forwards, backwards),
    ]
