from django.db import migrations

SQL = """
CREATE TRIGGER phase7_publication_history BEFORE UPDATE OR DELETE ON communications_publicationhistory
FOR EACH ROW EXECUTE FUNCTION phase7_immutable();
CREATE TRIGGER phase7_document_history BEFORE UPDATE OR DELETE ON communications_document
FOR EACH ROW EXECUTE FUNCTION phase7_immutable();
CREATE FUNCTION phase7_message_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Messages retain history'; END IF;
 IF NEW.body <> OLD.body OR NEW.sender_id <> OLD.sender_id OR NEW.conversation_id <> OLD.conversation_id THEN
  RAISE EXCEPTION 'Message identity and content are immutable';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER phase7_message_history BEFORE UPDATE OR DELETE ON communications_message
FOR EACH ROW EXECUTE FUNCTION phase7_message_guard();
"""
REVERSE = """
DROP TRIGGER phase7_message_history ON communications_message;
DROP FUNCTION phase7_message_guard();
DROP TRIGGER phase7_document_history ON communications_document;
DROP TRIGGER phase7_publication_history ON communications_publicationhistory;
"""


class Migration(migrations.Migration):
    dependencies = [("communications", "0003_initial"), ("scheduling", "0003_history_guards")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
