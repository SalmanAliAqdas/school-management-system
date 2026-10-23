from django.db import migrations

SQL = r"""
CREATE FUNCTION schoolos_finance_source_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE approved boolean; used boolean:=false; payload jsonb; original jsonb;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Financial setup and source records cannot be deleted'; END IF;
 payload:=to_jsonb(NEW)-ARRAY['updated_at','is_active'];
 original:=to_jsonb(OLD)-ARRAY['updated_at','is_active'];
 CASE TG_TABLE_NAME
 WHEN 'finance_feecategory' THEN SELECT EXISTS(SELECT 1 FROM finance_invoiceline WHERE category_id=OLD.id) INTO used;
 WHEN 'finance_feestructure' THEN SELECT EXISTS(SELECT 1 FROM finance_invoiceline l JOIN finance_feeline f ON f.id=l.fee_line_id WHERE f.structure_id=OLD.id) INTO used;
 WHEN 'finance_feeline' THEN SELECT EXISTS(SELECT 1 FROM finance_invoiceline WHERE fee_line_id=OLD.id) INTO used;
 WHEN 'finance_feeassignment' THEN SELECT EXISTS(SELECT 1 FROM finance_invoiceline WHERE assignment_id=OLD.id) INTO used;
 WHEN 'finance_billingcycle' THEN SELECT EXISTS(SELECT 1 FROM finance_invoice WHERE cycle_id=OLD.id) INTO used;
 WHEN 'finance_concessiontype' THEN SELECT EXISTS(SELECT 1 FROM finance_concessionaward WHERE concession_type_id=OLD.id) INTO used;
 WHEN 'finance_paymentmethod' THEN
  IF NEW.account_id<>OLD.account_id AND EXISTS(SELECT 1 FROM finance_payment WHERE method_id=OLD.id) THEN RAISE EXCEPTION 'Used payment accounting account is protected'; END IF;
 WHEN 'finance_account' THEN
  IF (NEW.code<>OLD.code OR NEW.kind<>OLD.kind OR NEW.control<>OLD.control) AND EXISTS(SELECT 1 FROM finance_journalline WHERE account_id=OLD.id) THEN RAISE EXCEPTION 'Used account identity is protected'; END IF;
 WHEN 'finance_expense' THEN
  IF OLD.request_id IS NOT NULL OR (payload-'request_id') IS DISTINCT FROM (original-'request_id') THEN RAISE EXCEPTION 'Submitted expense is immutable'; END IF;
 END CASE;
 IF used AND payload IS DISTINCT FROM original THEN RAISE EXCEPTION 'Used financial definitions are preserved; create a revision'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION schoolos_finance_compensation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r finance_financialrequest%ROWTYPE; a finance_allocation%ROWTYPE; lot finance_creditlot%ROWTYPE;
spent numeric; released numeric; refunded numeric;
BEGIN
 SELECT * INTO r FROM finance_financialrequest WHERE id=NEW.request_id;
 IF r.state IS DISTINCT FROM 'approved' THEN RAISE EXCEPTION 'Compensating entries require approved independent requests'; END IF;
 IF TG_TABLE_NAME='finance_allocationrelease' THEN
  SELECT * INTO a FROM finance_allocation WHERE id=NEW.allocation_id;
  SELECT COALESCE(sum(amount),0) INTO released FROM finance_allocationrelease WHERE allocation_id=a.id;
  IF NEW.amount>a.amount-released OR EXISTS(SELECT 1 FROM finance_refund WHERE allocation_id=a.id) THEN RAISE EXCEPTION 'Release exceeds protected allocation balance'; END IF;
 ELSIF TG_TABLE_NAME='finance_refund' THEN
  IF NEW.student_id<>r.student_id OR NEW.account_id<>r.target_account_id THEN RAISE EXCEPTION 'Refund source mismatch'; END IF;
  IF NEW.credit_id IS NOT NULL THEN
   SELECT * INTO lot FROM finance_creditlot WHERE id=NEW.credit_id;
   IF lot.student_id<>NEW.student_id THEN RAISE EXCEPTION 'Refund student does not own this credit'; END IF;
   SELECT COALESCE(sum(amount),0) INTO spent FROM finance_allocation WHERE credit_id=lot.id;
   SELECT COALESCE(sum(x.amount),0) INTO released FROM finance_allocationrelease x JOIN finance_allocation alloc ON alloc.id=x.allocation_id WHERE alloc.credit_id=lot.id;
   SELECT COALESCE(sum(amount),0) INTO refunded FROM finance_refund WHERE credit_id=lot.id;
   IF NEW.amount>lot.amount-spent+released-refunded THEN RAISE EXCEPTION 'Refund exceeds credit funds available'; END IF;
  ELSE
   SELECT * INTO a FROM finance_allocation WHERE id=NEW.allocation_id;
   IF NOT EXISTS(SELECT 1 FROM finance_invoiceline WHERE id=a.line_id AND details->>'treatment'='deposit') THEN RAISE EXCEPTION 'Refund requires funded deposit'; END IF;
   IF NOT EXISTS(SELECT 1 FROM finance_creditlot WHERE id=a.credit_id AND student_id=NEW.student_id) THEN RAISE EXCEPTION 'Deposit belongs to another student'; END IF;
   SELECT COALESCE(sum(amount),0) INTO released FROM finance_allocationrelease WHERE allocation_id=a.id;
   SELECT COALESCE(sum(amount),0) INTO refunded FROM finance_refund WHERE allocation_id=a.id;
   IF NEW.amount>a.amount-released-refunded THEN RAISE EXCEPTION 'Refund exceeds funded deposit'; END IF;
  END IF;
 END IF;
 RETURN NEW;
END $$;
"""
TABLES = [
    "feecategory",
    "feestructure",
    "feeline",
    "feeassignment",
    "billingcycle",
    "concessiontype",
    "paymentmethod",
    "account",
    "expense",
]


def forwards(apps, schema_editor):
    schema_editor.execute(SQL, params=None)
    for table in TABLES:
        schema_editor.execute(
            f"CREATE TRIGGER finance_used_source_guard BEFORE UPDATE OR DELETE ON finance_{table} FOR EACH ROW EXECUTE FUNCTION schoolos_finance_source_guard()"
        )
    for table in ["allocationrelease", "refund", "revenuerecognition"]:
        schema_editor.execute(
            f"CREATE TRIGGER finance_compensation_guard BEFORE INSERT ON finance_{table} FOR EACH ROW EXECUTE FUNCTION schoolos_finance_compensation_guard()"
        )
    schema_editor.execute(
        "CREATE TRIGGER finance_award_guard BEFORE UPDATE OR DELETE ON finance_concessionaward FOR EACH ROW EXECUTE FUNCTION schoolos_finance_append_only()"
    )


def backwards(apps, schema_editor):
    schema_editor.execute("DROP FUNCTION IF EXISTS schoolos_finance_source_guard() CASCADE")
    schema_editor.execute("DROP FUNCTION IF EXISTS schoolos_finance_compensation_guard() CASCADE")
    schema_editor.execute("DROP TRIGGER IF EXISTS finance_award_guard ON finance_concessionaward")


class Migration(migrations.Migration):
    dependencies = [("finance", "0003_financial_guards")]
    operations = [migrations.RunPython(forwards, backwards)]
