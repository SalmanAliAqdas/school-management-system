from django.db import migrations

IMMUTABLE = [
    "creditlot",
    "allocation",
    "allocationrelease",
    "invoiceadjustment",
    "revenuerecognition",
    "refund",
    "onetimecharge",
    "concessionuse",
    "expensepayment",
    "financeevent",
    "periodevent",
    "reconciliation",
]

SQL = r"""
CREATE FUNCTION schoolos_finance_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Permanent financial history cannot be updated or deleted'; END $$;
CREATE FUNCTION schoolos_finance_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN PERFORM id FROM finance_financesettings WHERE id=1 FOR UPDATE; RETURN NEW; END $$;
CREATE FUNCTION schoolos_finance_journal() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE d numeric; c numeric; n integer; p finance_financialperiod%ROWTYPE; y finance_financialyear%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Journal history cannot be deleted'; END IF;
 IF TG_OP='UPDATE' AND OLD.state='posted' THEN RAISE EXCEPTION 'Posted journal entries are immutable'; END IF;
 SELECT * INTO p FROM finance_financialperiod WHERE id=NEW.period_id FOR UPDATE;
 SELECT * INTO y FROM finance_financialyear WHERE id=p.financial_year_id;
 IF p.is_closed OR y.is_closed OR NEW.occurred_on<p.starts_on OR NEW.occurred_on>p.ends_on THEN RAISE EXCEPTION 'Journal date must be in an open financial period'; END IF;
 IF NEW.currency IS DISTINCT FROM (SELECT currency FROM finance_financesettings WHERE id=1) THEN RAISE EXCEPTION 'Journal base currency mismatch'; END IF;
 IF NEW.state='posted' THEN
  SELECT sum(debit),sum(credit),count(*) INTO d,c,n FROM finance_journalline WHERE journal_id=NEW.id;
  IF n<2 OR d IS DISTINCT FROM c THEN RAISE EXCEPTION 'Posted journal must balance with at least two lines'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION schoolos_finance_journal_final() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE s text; d numeric; c numeric;
BEGIN
 SELECT state INTO s FROM finance_journalentry WHERE id=NEW.id;
 SELECT sum(debit),sum(credit) INTO d,c FROM finance_journalline WHERE journal_id=NEW.id;
 IF s IS DISTINCT FROM 'posted' OR d IS NULL OR d IS DISTINCT FROM c THEN RAISE EXCEPTION 'A complete balanced posting is required at commit'; END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION schoolos_finance_line() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE s text; a text;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Journal lines are immutable'; END IF;
 SELECT state INTO s FROM finance_journalentry WHERE id=NEW.journal_id;
 SELECT control INTO a FROM finance_account WHERE id=NEW.account_id;
 IF s IS DISTINCT FROM 'draft' THEN RAISE EXCEPTION 'Cannot append lines to a posted journal'; END IF;
 IF a IN ('receivable','advance','deposit','deposit_due') AND NEW.student_id IS NULL THEN RAISE EXCEPTION 'Student control requires student'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION schoolos_finance_document() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE token text; approved boolean; p finance_financialrequest%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Financial documents cannot be deleted'; END IF;
 token:=current_setting('schoolos.finance_request',true);
 IF TG_TABLE_NAME='finance_payment' THEN
  IF OLD.state<>'pending' OR (to_jsonb(NEW)-ARRAY['state','number','posted_by_id','posted_at','snapshot','updated_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','number','posted_by_id','posted_at','snapshot','updated_at']) THEN RAISE EXCEPTION 'Payment identity and posted receipts are immutable'; END IF;
  IF NEW.state='posted' AND (NEW.number='' OR NEW.posted_by_id IS NULL OR NEW.snapshot='{}'::jsonb OR NOT EXISTS(SELECT 1 FROM finance_journalentry WHERE source_key='payment:'||NEW.id AND state='posted')) THEN RAISE EXCEPTION 'Final receipt requires its permanent posting'; END IF;
  RETURN NEW;
 END IF;
 IF OLD.state IN ('issued','voided') THEN
  IF OLD.state='issued' AND NEW.state='voided' AND (to_jsonb(NEW)-ARRAY['state','updated_at'])=(to_jsonb(OLD)-ARRAY['state','updated_at']) THEN
   SELECT * INTO p FROM finance_financialrequest WHERE id::text=token AND kind='void' AND invoice_id=OLD.id AND state='approved';
   IF p.id IS NOT NULL THEN RETURN NEW; END IF;
  END IF;
  RAISE EXCEPTION 'Issued invoice history is immutable; use compensating adjustments';
 END IF;
 IF (to_jsonb(NEW)-ARRAY['state','snapshot','version','approval_id','updated_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','snapshot','version','approval_id','updated_at']) THEN RAISE EXCEPTION 'Draft invoice amounts are preserved; use an authorized replacement'; END IF;
 IF NEW.state='issued' THEN
  IF NEW.total IS DISTINCT FROM (SELECT sum(net) FROM finance_invoiceline WHERE invoice_id=NEW.id) OR NEW.subtotal IS DISTINCT FROM (SELECT sum(gross) FROM finance_invoiceline WHERE invoice_id=NEW.id) OR NEW.discount IS DISTINCT FROM (SELECT sum(discount) FROM finance_invoiceline WHERE invoice_id=NEW.id) THEN RAISE EXCEPTION 'Invoice arithmetic must match its preserved lines'; END IF;
  IF NEW.total>0 AND NOT EXISTS(SELECT 1 FROM finance_journalentry WHERE source_key='invoice:'||NEW.id AND state='posted') THEN RAISE EXCEPTION 'Issued invoice requires its permanent posting'; END IF;
  IF (SELECT invoice_approval FROM finance_financesettings WHERE id=1) AND NOT EXISTS(SELECT 1 FROM finance_financialrequest WHERE id=NEW.approval_id AND kind='issue_invoice' AND invoice_id=NEW.id AND state='approved') THEN RAISE EXCEPTION 'Independent invoice approval is required by policy'; END IF;
 END IF;
 IF NEW.state='approved' AND NOT EXISTS(SELECT 1 FROM finance_financialrequest WHERE id=NEW.approval_id AND state='approved' AND kind='issue_invoice' AND invoice_id=NEW.id) THEN RAISE EXCEPTION 'Invoice requires independent approval'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION schoolos_finance_invoice_line() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE i finance_invoice%ROWTYPE; e people_enrollment%ROWTYPE;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Preserved invoice lines cannot be edited or deleted'; END IF;
 SELECT * INTO i FROM finance_invoice WHERE id=NEW.invoice_id;
 SELECT * INTO e FROM people_enrollment WHERE id=NEW.enrollment_id;
 IF i.state<>'draft' OR e.student_id<>i.student_id OR e.academic_year_id<>i.academic_year_id THEN RAISE EXCEPTION 'Invoice lines require matching historical enrollment on a draft'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION schoolos_finance_request() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Approval history cannot be deleted'; END IF;
 IF OLD.state<>'pending' OR NEW.state NOT IN ('approved','rejected') OR
 (to_jsonb(NEW)-ARRAY['state','reviewed_by_id','reviewed_at','decision_reason','updated_at']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','reviewed_by_id','reviewed_at','decision_reason','updated_at']) THEN RAISE EXCEPTION 'Approval proposal is immutable and permits one independent decision'; END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION schoolos_finance_settings() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Financial settings cannot be deleted'; END IF;
 IF TG_TABLE_NAME='core_schoolsettings' THEN
  IF NEW.currency IS DISTINCT FROM OLD.currency AND EXISTS(SELECT 1 FROM finance_financesettings) THEN RAISE EXCEPTION 'Base currency is controlled by initialized finance settings'; END IF;
 ELSE
  IF (NEW.currency IS DISTINCT FROM OLD.currency OR NEW.decimal_places<>OLD.decimal_places) AND (EXISTS(SELECT 1 FROM finance_feeline) OR EXISTS(SELECT 1 FROM finance_payment) OR EXISTS(SELECT 1 FROM finance_invoice) OR EXISTS(SELECT 1 FROM finance_journalentry)) THEN RAISE EXCEPTION 'Currency and precision are frozen after financial pricing'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION schoolos_finance_period() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE token text; k text; p finance_financialrequest%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Financial periods cannot be deleted'; END IF;
 IF NEW.is_closed<>OLD.is_closed THEN
  token:=current_setting('schoolos.finance_request',true);
  k:=CASE WHEN TG_TABLE_NAME='finance_financialyear' THEN 'year' ELSE 'period' END;
  SELECT * INTO p FROM finance_financialrequest WHERE id::text=token AND state='approved' AND kind=(CASE WHEN NEW.is_closed THEN 'close_' ELSE 'reopen_' END)||k;
  IF p.id IS NULL OR (k='period' AND p.period_id<>OLD.id) OR (k='year' AND p.payload->>'year'<>OLD.id::text) THEN RAISE EXCEPTION 'Independent closing/reopening decision required'; END IF;
 ELSE
  IF TG_TABLE_NAME='finance_financialperiod' AND EXISTS(SELECT 1 FROM finance_journalentry WHERE period_id=OLD.id) THEN RAISE EXCEPTION 'Used period definition is protected'; END IF;
  IF TG_TABLE_NAME='finance_financialyear' AND EXISTS(SELECT 1 FROM finance_journalentry j JOIN finance_financialperiod p ON p.id=j.period_id WHERE p.financial_year_id=OLD.id) THEN RAISE EXCEPTION 'Used financial year definition is protected'; END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE FUNCTION schoolos_finance_allocation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE lot finance_creditlot%ROWTYPE; i finance_invoice%ROWTYPE; v numeric; spent numeric; released numeric; refunded numeric; target numeric;
BEGIN
 SELECT * INTO lot FROM finance_creditlot WHERE id=NEW.credit_id;
 SELECT * INTO i FROM finance_invoice WHERE id=NEW.invoice_id;
 IF i.student_id<>lot.student_id OR i.state<>'issued' THEN RAISE EXCEPTION 'Allocation student or invoice mismatch'; END IF;
 SELECT COALESCE(sum(amount),0) INTO spent FROM finance_allocation WHERE credit_id=lot.id;
 SELECT COALESCE(sum(r.amount),0) INTO released FROM finance_allocationrelease r JOIN finance_allocation a ON a.id=r.allocation_id WHERE a.credit_id=lot.id;
 SELECT COALESCE(sum(amount),0) INTO refunded FROM finance_refund WHERE credit_id=lot.id;
 IF NEW.amount>lot.amount-spent+released-refunded THEN RAISE EXCEPTION 'Advance credit cannot be overspent'; END IF;
 IF NEW.line_id IS NOT NULL THEN
  SELECT net INTO target FROM finance_invoiceline WHERE id=NEW.line_id AND invoice_id=i.id;
  SELECT target+COALESCE(sum(amount),0) INTO target FROM finance_invoiceadjustment WHERE line_id=NEW.line_id;
  SELECT COALESCE(sum(amount),0) INTO spent FROM finance_allocation WHERE line_id=NEW.line_id;
  SELECT COALESCE(sum(r.amount),0) INTO released FROM finance_allocationrelease r JOIN finance_allocation a ON a.id=r.allocation_id WHERE a.line_id=NEW.line_id;
 ELSE
  SELECT amount INTO target FROM finance_invoiceadjustment WHERE id=NEW.charge_id AND invoice_id=i.id AND amount>0;
  SELECT target+COALESCE(sum(amount),0) INTO target FROM finance_invoiceadjustment WHERE reverses_charge_id=NEW.charge_id;
  SELECT COALESCE(sum(amount),0) INTO spent FROM finance_allocation WHERE charge_id=NEW.charge_id;
  SELECT COALESCE(sum(r.amount),0) INTO released FROM finance_allocationrelease r JOIN finance_allocation a ON a.id=r.allocation_id WHERE a.charge_id=NEW.charge_id;
 END IF;
 IF target IS NULL OR NEW.amount>target-spent+released THEN RAISE EXCEPTION 'Invoice item cannot be overallocated'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER finance_journal_guard BEFORE INSERT OR UPDATE OR DELETE ON finance_journalentry FOR EACH ROW EXECUTE FUNCTION schoolos_finance_journal();
CREATE CONSTRAINT TRIGGER finance_journal_commit AFTER INSERT OR UPDATE ON finance_journalentry DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION schoolos_finance_journal_final();
CREATE TRIGGER finance_line_guard BEFORE INSERT OR UPDATE OR DELETE ON finance_journalline FOR EACH ROW EXECUTE FUNCTION schoolos_finance_line();
CREATE TRIGGER finance_invoice_guard BEFORE UPDATE OR DELETE ON finance_invoice FOR EACH ROW EXECUTE FUNCTION schoolos_finance_document();
CREATE TRIGGER finance_payment_guard BEFORE UPDATE OR DELETE ON finance_payment FOR EACH ROW EXECUTE FUNCTION schoolos_finance_document();
CREATE TRIGGER finance_invoice_line_guard BEFORE INSERT OR UPDATE OR DELETE ON finance_invoiceline FOR EACH ROW EXECUTE FUNCTION schoolos_finance_invoice_line();
CREATE TRIGGER finance_request_guard BEFORE UPDATE OR DELETE ON finance_financialrequest FOR EACH ROW EXECUTE FUNCTION schoolos_finance_request();
CREATE TRIGGER finance_settings_guard BEFORE UPDATE OR DELETE ON finance_financesettings FOR EACH ROW EXECUTE FUNCTION schoolos_finance_settings();
CREATE TRIGGER finance_school_currency_guard BEFORE UPDATE ON core_schoolsettings FOR EACH ROW EXECUTE FUNCTION schoolos_finance_settings();
CREATE TRIGGER finance_period_guard BEFORE UPDATE OR DELETE ON finance_financialperiod FOR EACH ROW EXECUTE FUNCTION schoolos_finance_period();
CREATE TRIGGER finance_year_guard BEFORE UPDATE OR DELETE ON finance_financialyear FOR EACH ROW EXECUTE FUNCTION schoolos_finance_period();
CREATE TRIGGER finance_allocation_guard BEFORE INSERT ON finance_allocation FOR EACH ROW EXECUTE FUNCTION schoolos_finance_allocation();
"""


def forwards(apps, schema_editor):
    schema_editor.execute(SQL, params=None)
    for table in IMMUTABLE:
        schema_editor.execute(
            f"CREATE TRIGGER finance_history_guard BEFORE UPDATE OR DELETE ON finance_{table} FOR EACH ROW EXECUTE FUNCTION schoolos_finance_append_only()"
        )
    for table in [
        "journalentry",
        "payment",
        "invoice",
        "allocation",
        "refund",
        "financ ialrequest".replace(" ", ""),
        "allocationrelease",
        "invoiceadjustment",
    ]:
        schema_editor.execute(
            f"CREATE TRIGGER finance_serialization_guard BEFORE INSERT ON finance_{table} FOR EACH ROW EXECUTE FUNCTION schoolos_finance_lock()"
        )


def backwards(apps, schema_editor):
    for name in [
        "append_only",
        "lock",
        "journal",
        "journal_final",
        "line",
        "document",
        "invoice_line",
        "request",
        "settings",
        "period",
        "allocation",
    ]:
        schema_editor.execute(f"DROP FUNCTION IF EXISTS schoolos_finance_{name}() CASCADE")


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0002_assignment_scope"),
        ("core", "0002_schoolsettings_address_schoolsettings_email_and_more"),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
