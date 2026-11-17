-- 0006: commercial process columns of the company (the last three steps of GOCLER in tarama/depo.py: surec, surec_notu, surec_utc).
-- They were missing from 0002; found by ALIG-DB-003c while porting tarama/depo.py. Expand-only: existing rows get the defaults.
-- The transition rules (aday -> gorusuluyor -> teklif -> musteri; any -> kapandi) stay in application code (SUREC_GECISLERI);
-- the database only guarantees the set of valid states.
SET ROLE alig_owner;

ALTER TABLE alig.firma ADD COLUMN surec text NOT NULL DEFAULT 'aday'
  CHECK (surec IN ('aday', 'gorusuluyor', 'teklif', 'musteri', 'kapandi'));
ALTER TABLE alig.firma ADD COLUMN surec_notu text NOT NULL DEFAULT '';
ALTER TABLE alig.firma ADD COLUMN surec_utc timestamptz;

-- The application role already has table-level DML on alig.firma (0005). Read-only: the status, not the note (it may contain personal data).
GRANT SELECT (surec, surec_utc) ON alig.firma TO alig_readonly;

RESET ROLE;
