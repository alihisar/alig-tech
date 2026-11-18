-- 0009: transactional outbox (ALIG-DB-006). Expand-only on alig.posta; existing rows keep working.
-- * mesaj_anahtari: idempotency key of the message. UNIQUE, so enqueueing the same business event twice stores ONE message
--   (INSERT ... ON CONFLICT DO NOTHING). The same key is sent to the receiver in the Message-ID and X-Alig-Idempotency-Key headers,
--   so a receiver can drop a message that was delivered twice (at-least-once delivery, see docs/postgresql-gecis.md section 4.2).
-- * durum 'gonderiliyor': claimed by a worker (lease). The worker claims with FOR UPDATE SKIP LOCKED in a short transaction, COMMITS,
--   and only then talks to the mail server. kilit_utc is the lease expiry: a worker that died after the claim leaves a row that
--   becomes claimable again once the lease has passed. deneme is incremented AT CLAIM time, so a crash counts as an attempt and a
--   message that keeps killing its worker still reaches the dead state 'basarisiz'. deneme also acts as the claim token: the
--   "mark sent" / "mark failed" statements only match the attempt number they claimed.
-- * sonraki_utc: earliest time of the next attempt (backoff).
-- The application role already has table-level SELECT/INSERT/UPDATE/DELETE on alig.posta (0005); nothing else is granted.
SET ROLE alig_owner;

-- The volatile default gives every existing row (and any insert that names no key) its own random key; the application normally supplies one.
ALTER TABLE alig.posta ADD COLUMN mesaj_anahtari text NOT NULL DEFAULT gen_random_uuid()::text;
ALTER TABLE alig.posta ADD CONSTRAINT posta_mesaj_anahtari_bicim CHECK (mesaj_anahtari ~ '^[A-Za-z0-9._-]{1,100}$');
ALTER TABLE alig.posta ADD CONSTRAINT posta_mesaj_anahtari_tekil UNIQUE (mesaj_anahtari);

ALTER TABLE alig.posta ADD COLUMN sonraki_utc timestamptz NOT NULL DEFAULT now();
ALTER TABLE alig.posta ADD COLUMN kilit_utc timestamptz;

ALTER TABLE alig.posta DROP CONSTRAINT posta_durum_check;
ALTER TABLE alig.posta ADD CONSTRAINT posta_durum_check CHECK (durum IN ('bekliyor', 'gonderiliyor', 'gonderildi', 'basarisiz'));
-- A claimed row always has a lease expiry.
ALTER TABLE alig.posta ADD CONSTRAINT posta_kilit_tutarli CHECK (durum <> 'gonderiliyor' OR kilit_utc IS NOT NULL);

CREATE INDEX posta_sonraki ON alig.posta(sonraki_utc, id) WHERE durum = 'bekliyor';
CREATE INDEX posta_kilit ON alig.posta(kilit_utc) WHERE durum = 'gonderiliyor';

RESET ROLE;
