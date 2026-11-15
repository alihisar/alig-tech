-- 0005: tablo yetkileri. PUBLIC hicbir alig tablosunda yetki tasimaz. Kimlik dizilerinde (identity) ayrica yetki
-- gerekmez: INSERT dizi yetkisi istemeden yeni kimligi alir.
-- Yeni tablo ekleyen her goc kendi yetkilerini de yazar; yetkisiz tablo kimseye acik degildir.
SET ROLE alig_owner;

REVOKE ALL ON ALL TABLES IN SCHEMA alig FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA alig FROM PUBLIC;

-- Uygulama: tablo basina yalniz kodun yaptigi DML.
GRANT SELECT, INSERT, UPDATE, DELETE ON
  alig.firma, alig.firma_silinen, alig.rapor, alig.baglanti_istegi, alig.posta, alig.esitleme,
  alig.portal_kullanici, alig.portal_oturum, alig.portal_talep,
  alig.kullanici, alig.oturum, alig.talep_durum, alig.giris_ip
  TO alig_app;
GRANT SELECT, INSERT, DELETE ON
  alig.kullanim, alig.portal_kod, alig.portal_deneme, alig.giris_denemesi, alig.contact, alig.idempotency_anahtari
  TO alig_app;
-- Denetim zincirleri: yalniz ekleme ve okuma. UPDATE, DELETE, TRUNCATE yok.
GRANT SELECT, INSERT ON alig.denetim, alig.yonetim_denetim TO alig_app;

-- Salt okuma: gizli ya da kisisel sutunlar (parola, TOTP, belirtec ozeti, rapor belgesi, e-posta, ileti metni) verilmez.
GRANT SELECT (id, anahtar, ad, durum, kaynak, kayit_utc, son_utc, dogrudan_izin) ON alig.firma TO alig_readonly;
GRANT SELECT (id, olusturma_utc, bitis_utc, motor, dil, firma_id, dogrulandi) ON alig.rapor TO alig_readonly;
GRANT SELECT (id, zaman_utc) ON alig.kullanim TO alig_readonly;
GRANT SELECT ON alig.denetim, alig.yonetim_denetim, alig.talep_durum TO alig_readonly;

RESET ROLE;
