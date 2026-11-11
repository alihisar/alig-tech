-- alig.tech sağlık taraması: tarama hesabını kaldırma
-- Çalıştırma: psql -h <sunucu> -U <yönetici rol> -d postgres -f alig-rol-kaldir.sql
-- Rol hiçbir nesnenin sahibi değildir; kaldırmak başka bir şeyi etkilemez.

\set ON_ERROR_STOP on
DROP ROLE IF EXISTS alig_hc;
