-- 0004: idempotency_anahtari (docs/postgresql-gecis.md section 3). The same key gives the same request on upload and on scan start;
-- if the same key arrives with DIFFERENT content the application rejects it (istek_ozeti comparison; code in ALIG-DB-003c).
-- The record is written in the same transaction as the business data and the audit record.
SET ROLE alig_owner;

CREATE TABLE alig.idempotency_anahtari(
  anahtar     text PRIMARY KEY CHECK (length(anahtar) BETWEEN 1 AND 200),
  istek_ozeti text NOT NULL CHECK (istek_ozeti ~ '^[0-9a-f]{64}$'),
  sonuc       text NOT NULL DEFAULT '',
  zaman_utc   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idempotency_zaman ON alig.idempotency_anahtari(zaman_utc);

RESET ROLE;
