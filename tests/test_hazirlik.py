"""Saglik taramasi hazirlik kilavuzu: sayfa, rol SQL dosyalari ve tutarlilik."""
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))

import build  # noqa: E402

ASSETS = ROOT / "site" / "assets"
ROL = "alig_hc"
YAZMA = re.compile(r"\b(INSERT|UPDATE|DELETE|TRUNCATE|COPY|CREATE\s+TABLE|SUPERUSER|CREATEDB|CREATEROLE|REPLICATION|BYPASSRLS)\b", re.I)


def sql_kodu(metin):
    """Yorum satirlarini atar."""
    return "\n".join(s for s in metin.splitlines() if not s.strip().startswith("--"))


class RolSqlTests(unittest.TestCase):
    def setUp(self):
        self.kur = (ASSETS / "alig-rol.sql").read_text(encoding="utf-8")
        self.kaldir = (ASSETS / "alig-rol-kaldir.sql").read_text(encoding="utf-8")

    def test_rol_yalniz_izleme_yetkisi_alir(self):
        kod = sql_kodu(self.kur)
        self.assertIn(f"CREATE ROLE {ROL}", kod)
        self.assertIn(f"GRANT pg_monitor TO {ROL}", kod)
        self.assertEqual(re.findall(r"GRANT\s+(\S+)", kod), ["pg_monitor"])
        self.assertIsNone(YAZMA.search(kod), "rol dosyasinda yazma ya da genis yetki olmamali")

    def test_rol_salt_okunur_ve_sinirli(self):
        kod = sql_kodu(self.kur)
        self.assertIn("default_transaction_read_only = on", kod)
        self.assertIn("statement_timeout", kod)
        self.assertIn("CONNECTION LIMIT", kod)
        self.assertIn("VALID UNTIL", kod)

    def test_parola_dosyada_yok(self):
        kod = sql_kodu(self.kur)
        self.assertNotRegex(kod, r"(?i)\bPASSWORD\s+'")
        self.assertIn(f"\\password {ROL}", kod)

    def test_kaldirma_yalniz_rolu_siler(self):
        kod = sql_kodu(self.kaldir)
        self.assertIn(f"DROP ROLE IF EXISTS {ROL}", kod)
        self.assertIsNone(re.search(r"\bDROP\s+(?!ROLE)", kod, re.I))

    def test_toplayici_ornegi_ayni_rolu_kullanir(self):
        self.assertIn(f"--user {ROL}", (ASSETS / "alig-toplayici.py").read_text(encoding="utf-8"))


class SayfaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "c"
        assert build.main(["--theme", "c", "--out", str(cls.out)]) == 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def oku(self, yol):
        return (self.out / yol / "index.html").read_text(encoding="utf-8")

    def test_iki_dilde_uretilir(self):
        for yol in ("tarama-hazirlik", "en/tarama-hazirlik"):
            sayfa = self.oku(yol)
            self.assertIn(ROL, sayfa)
            self.assertIn("/assets/alig-rol.sql", sayfa)
            self.assertIn("/assets/alig-rol-kaldir.sql", sayfa)
            self.assertIn("pg_monitor", sayfa)
            self.assertNotIn("{{", sayfa)

    def test_yukleme_sayfasi_kilavuza_baglanir(self):
        self.assertIn('href="/tarama-hazirlik/"', self.oku("saglik-taramasi"))
        self.assertIn('href="/en/tarama-hazirlik/"', self.oku("en/saglik-taramasi"))

    def test_sql_dosyalari_ciktida(self):
        for ad in ("alig-rol.sql", "alig-rol-kaldir.sql"):
            self.assertTrue((self.out / "assets" / ad).is_file())


if __name__ == "__main__":
    unittest.main()
