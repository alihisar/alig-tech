-- 0005: table privileges. PUBLIC holds no privilege on any alig table. No separate privilege is needed on identity sequences:
-- INSERT takes the new id without needing a sequence privilege.
-- Every migration that adds a new table also writes its own privileges; a table without privileges is open to no one.
SET ROLE alig_owner;

REVOKE ALL ON ALL TABLES IN SCHEMA alig FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA alig FROM PUBLIC;

-- Application: per table, only the DML the code performs.
GRANT SELECT, INSERT, UPDATE, DELETE ON
  alig.firma, alig.firma_silinen, alig.rapor, alig.baglanti_istegi, alig.posta, alig.esitleme,
  alig.portal_kullanici, alig.portal_oturum, alig.portal_talep,
  alig.kullanici, alig.oturum, alig.talep_durum, alig.giris_ip
  TO alig_app;
GRANT SELECT, INSERT, DELETE ON
  alig.kullanim, alig.portal_kod, alig.portal_deneme, alig.giris_denemesi, alig.contact, alig.idempotency_anahtari
  TO alig_app;
-- Audit chains: append and read only. No UPDATE, DELETE, TRUNCATE.
GRANT SELECT, INSERT ON alig.denetim, alig.yonetim_denetim TO alig_app;

-- Read-only: secret or personal columns (login credential, TOTP, token digest, report document, email, message text) are not granted.
GRANT SELECT (id, anahtar, ad, durum, kaynak, kayit_utc, son_utc, dogrudan_izin) ON alig.firma TO alig_readonly;
GRANT SELECT (id, olusturma_utc, bitis_utc, motor, dil, firma_id, dogrulandi) ON alig.rapor TO alig_readonly;
GRANT SELECT (id, zaman_utc) ON alig.kullanim TO alig_readonly;
GRANT SELECT ON alig.denetim, alig.yonetim_denetim, alig.talep_durum TO alig_readonly;

RESET ROLE;
