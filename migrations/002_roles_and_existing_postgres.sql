-- Preserve the original schema migration and add current role/session support.
ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user';
ALTER TABLE users ADD COLUMN IF NOT EXISTS session_version INTEGER NOT NULL DEFAULT 1;
DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='users' AND column_name='is_admin') THEN
  UPDATE users SET role='admin' WHERE is_admin=1 AND role='user';
 END IF;
 IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='users' AND column_name='is_active' AND data_type<>'boolean') THEN
  ALTER TABLE users ALTER COLUMN is_active DROP DEFAULT;
  ALTER TABLE users DROP CONSTRAINT IF EXISTS users_is_active_check;
  ALTER TABLE users ALTER COLUMN is_active TYPE BOOLEAN USING (is_active<>0);
  ALTER TABLE users ALTER COLUMN is_active SET DEFAULT TRUE;
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='users'::regclass AND conname='users_role_values') THEN
  ALTER TABLE users ADD CONSTRAINT users_role_values CHECK(role IN ('user','admin','superadmin'));
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='users'::regclass AND conname='superadmin_always_active') THEN
  ALTER TABLE users ADD CONSTRAINT superadmin_always_active CHECK(role<>'superadmin' OR is_active);
 END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS users_one_superadmin ON users(role) WHERE role='superadmin';
CREATE OR REPLACE FUNCTION protect_superadmin() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.role='superadmin' AND (TG_OP='DELETE' OR NEW.role<>'superadmin') THEN
  RAISE EXCEPTION 'The Super Admin account is protected' USING ERRCODE='insufficient_privilege';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
DO $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid='users'::regclass AND tgname='users_protect_superadmin') THEN
  CREATE TRIGGER users_protect_superadmin BEFORE UPDATE OF role OR DELETE ON users FOR EACH ROW EXECUTE FUNCTION protect_superadmin();
 END IF;
END $$;
ALTER TABLE estimates ALTER COLUMN inputs TYPE JSONB USING inputs::jsonb;
ALTER TABLE estimates ALTER COLUMN lines TYPE JSONB USING lines::jsonb;
ALTER TABLE estimates ALTER COLUMN total TYPE NUMERIC USING total::numeric;
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id,id DESC);
CREATE INDEX IF NOT EXISTS failed_logins_expiry ON failed_logins(at);
REVOKE ALL ON TABLE users, estimates, audit_log, failed_logins FROM PUBLIC;
DO $$
DECLARE api_role TEXT;
BEGIN
 FOREACH api_role IN ARRAY ARRAY['anon','authenticated'] LOOP
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=api_role) THEN
   EXECUTE format('REVOKE ALL ON TABLE users, estimates, audit_log, failed_logins FROM %I',api_role);
   EXECUTE format('REVOKE ALL ON SEQUENCE users_id_seq, estimates_id_seq, audit_log_id_seq FROM %I',api_role);
  END IF;
 END LOOP;
END $$;
REVOKE ALL ON SEQUENCE users_id_seq, estimates_id_seq, audit_log_id_seq FROM PUBLIC;
