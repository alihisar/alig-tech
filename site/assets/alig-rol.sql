-- alig.tech sağlık taraması: salt okunur tarama hesabı
-- Çalıştırma: psql -h <sunucu> -U <yönetici rol> -d postgres -f alig-rol.sql
-- Gereken yetki: rol oluşturabilen bir hesap (süper kullanıcı ya da rol yöneticisi).
-- Bu dosya veri değiştirmez; yalnızca aşağıdaki rolü oluşturur.
-- Parola dosyada yoktur: son adımda psql sizden parolayı sorar.

\set ON_ERROR_STOP on

-- 1) Giriş yapabilen, en çok iki bağlantı açabilen rol.
CREATE ROLE alig_hc LOGIN CONNECTION LIMIT 2;

-- 2) Hesap yedi gün sonra kendiliğinden geçersiz olur.
SELECT format('ALTER ROLE alig_hc VALID UNTIL %L', (now() + interval '7 days')::text) \gexec

-- 3) Tek yetki: istatistik ve ayar görünümlerini okuma.
GRANT pg_monitor TO alig_hc;

-- 4) Oturum her zaman salt okunur açılır, uzun sorgu ve kilit beklemesi kesilir.
ALTER ROLE alig_hc SET default_transaction_read_only = on;
ALTER ROLE alig_hc SET statement_timeout = '15s';
ALTER ROLE alig_hc SET lock_timeout = '2s';
ALTER ROLE alig_hc SET idle_in_transaction_session_timeout = '60s';

-- 5) Parolayı belirleyin (ekrana yazılmaz, komut geçmişine girmez).
\password alig_hc
