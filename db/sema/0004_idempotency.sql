-- 0004: idempotency_anahtari (docs/postgresql-gecis.md bolum 3). Yukleme ve tarama baslatmada ayni anahtar ayni istegi
-- verir; ayni anahtar FARKLI icerikle gelirse uygulama reddeder (istek_ozeti karsilastirmasi; kod ALIG-DB-003c).
-- Kayit, is verisi ve denetim kaydiyla ayni islemde yazilir.
SET ROLE alig_owner;

CREATE TABLE alig.idempotency_anahtari(
  anahtar     text PRIMARY KEY CHECK (length(anahtar) BETWEEN 1 AND 200),
  istek_ozeti text NOT NULL CHECK (istek_ozeti ~ '^[0-9a-f]{64}$'),
  sonuc       text NOT NULL DEFAULT '',
  zaman_utc   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idempotency_zaman ON alig.idempotency_anahtari(zaman_utc);

RESET ROLE;
