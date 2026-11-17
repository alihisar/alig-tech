-- 0007: atomic rate-limit window counters (ALIG-DB-003e, ortak/sinir_pg.py).
-- One row per (bucket, client digest, fixed window). The application increments the counter with a single
-- INSERT ... ON CONFLICT DO UPDATE ... WHERE adet < limit RETURNING statement, so concurrent requests cannot exceed the limit.
-- anahtar_sha256 is a digest of the client address (or account key), never the plain value. Expired windows are deleted by the application.
SET ROLE alig_owner;

CREATE TABLE alig.sinir_sayac(
  kova           text NOT NULL CHECK (kova ~ '^[a-z0-9_]{1,40}$'),
  anahtar_sha256 text NOT NULL CHECK (anahtar_sha256 ~ '^[0-9a-f]{64}$'),
  pencere_utc    timestamptz NOT NULL,
  bitis_utc      timestamptz NOT NULL,
  adet           integer NOT NULL CHECK (adet >= 1),
  PRIMARY KEY (kova, anahtar_sha256, pencere_utc),
  CHECK (bitis_utc > pencere_utc)
);
CREATE INDEX sinir_sayac_bitis ON alig.sinir_sayac(bitis_utc);

REVOKE ALL ON alig.sinir_sayac FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON alig.sinir_sayac TO alig_app;

RESET ROLE;
