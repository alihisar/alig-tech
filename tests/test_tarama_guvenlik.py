"""ALIG-SCAN-001: scan security audit. The collector (Mode A) and the direct connection (Mode B).

Sections: (1) an allowlist for ALL the SQL texts that run, (2) the session is read-only with a short timeout,
(3) Mode B target validation (table-driven), (4) resource limits, (5) Mode B is off by default.
Real PostgreSQL trials: an external server if ALIG_TEST_PG_HOST is set, otherwise a temporary PG16 cluster with tests/pg_yardimci.py; SKIP if neither exists.
No network is used; it runs with a fake psql or a mock.
"""
import ast
import importlib.util
import ipaddress
import json
import os
import re
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from tarama import baglanti, calistirici, hedef, katalog, server as tserver, yukleme  # noqa: E402
import pg_yardimci  # noqa: E402
import test_tarama  # noqa: E402

temiz_belge = test_tarama.temiz_belge
del test_tarama

TOPLAYICI = ROOT / "site" / "assets" / "alig-toplayici.py"
TOPLAYICI_MSSQL = ROOT / "tarama" / "onsurum" / "alig-toplayici-mssql.py"

# ---------------------------------------------------------------- (1) SQL allowlist

YASAK_PG = re.compile(
    r"\b(insert|update|delete|alter|drop|create|truncate|grant|revoke|copy|vacuum|analyze|reindex|cluster|call|do|execute|"
    r"explain|lock|listen|notify|unlisten|prepare|deallocate|comment|security|refresh|merge|import|into|reset|discard|"
    r"checkpoint|load|program|set|begin|commit|rollback|savepoint|start|abort|declare|fetch|move|close)\b"
    r"|\b(set_config|nextval|setval|currval|lastval|pg_terminate_backend|pg_cancel_backend|pg_reload_conf|pg_rotate_logfile|"
    r"pg_switch_wal|pg_promote|pg_sleep|pg_read_file|pg_read_binary_file|pg_ls_dir|pg_stat_file|dblink\w*|lo_\w+|"
    r"pg_advisory\w*|pg_stat_reset\w*|pg_replication_slot_advance|pg_create_\w+|pg_drop_\w+|pg_wal_replay_\w+|"
    r"pg_logical_\w+|pg_export_snapshot|pg_import_system_collations|pg_start_backup|pg_backup_start|pg_backup_stop|"
    r"pg_stop_backup|pg_rotate\w*|pg_nextoid|txid_\w+)\b"
    r"|\bfor\s+(no\s+key\s+)?(update|share)\b|\bfor\s+key\s+share\b|\bat\s+time\s+zone\s+'?program")
YASAK_MS = re.compile(
    r"\b(insert|update|delete|merge|alter|drop|create|truncate|grant|revoke|deny|exec|execute|openrowset|openquery|"
    r"opendatasource|into|dbcc|backup|restore|kill|shutdown|waitfor|reconfigure|use|set|declare|bulk)\b|\bsp_\w+|\bxp_\w+")


_TOKEN = re.compile(r"""/\*.*?\*/|--[^\n]*|\$([A-Za-z_]*)\$.*?\$\1\$|'(?:[^']|'')*'|"(?:[^"]|"")*\"""", re.S)


def metinsiz(sql):
    """In a single pass: comments (whitespace), dollar-quoted blocks and quoted text literals are removed; the remainder is returned in lowercase.
    If a comment was found '#comment' is appended to the end of the string (the allowlist rejects a comment)."""
    yorum = []

    def degistir(m):
        t = m.group(0)
        if t.startswith("--") or t.startswith("/*"):
            yorum.append(1)
            return " "
        return '""' if t.startswith('"') else "''"
    s = _TOKEN.sub(degistir, sql).lower()
    return s + (" #yorum" if yorum else "")


def ihlaller(sql, motor="postgresql"):
    """Allowlist: only SELECT / SHOW / WITH ... SELECT, a single statement. Empty list = suitable."""
    s = metinsiz(sql).strip()
    out = []
    if s.endswith(";"):
        s = s[:-1].rstrip()
    if motor == "postgresql":
        if not re.match(r"(select|show|with)\b", s):
            out.append("select/show/with ile baslamiyor")
        if s.startswith("with") and not re.search(r"\bselect\b", s):
            out.append("with icinde select yok")
        kalip = YASAK_PG
    else:
        if not re.match(r"(select|with)\b", s):
            out.append("select/with ile baslamiyor")
        kalip = YASAK_MS
    if ";" in s:
        out.append("birden cok deyim")
    if s.endswith("#yorum"):
        s = s[:-6].rstrip()
        out.append("yorum")
    for m in kalip.finditer(s):
        out.append("yasakli: " + m.group(0))
    return out


def sql_sabitleri(yol):
    """All string constants in the Python file that look like SQL (AST)."""
    agac = ast.parse(Path(yol).read_text(encoding="utf-8"))
    bulunan = []
    for n in ast.walk(agac):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if re.match(r"\s*(select|with|insert|update|delete|alter|create|drop|truncate|grant|revoke|copy|call|do|set|"
                        r"begin|commit|vacuum|analyze|exec|execute)\b", n.value, re.I):
                bulunan.append(n.value)
    return bulunan


def katalog_json(yol):
    """The embedded KATALOG document of the generated collector."""
    m = re.search(r"KATALOG = json\.loads\(r'''(.*?)'''\)", Path(yol).read_text(encoding="utf-8"), re.S)
    return json.loads(m.group(1))


def txt_deyimleri(yol):
    """sorgu-katalogu*.txt: comment lines are dropped, statements are separated by a blank line or a semicolon."""
    govde = "\n".join(s for s in Path(yol).read_text(encoding="utf-8").splitlines() if not s.lstrip().startswith("--"))
    deyimler = [d.strip() for d in re.split(r";\s*(?:\n|$)|\n\s*\n", govde) if d.strip()]
    return [d for d in deyimler if not d.startswith("alig.tech")]   # the first block is the description header


class AllowlistKendiniSinar(unittest.TestCase):
    KOTU_PG = (
        "INSERT INTO t VALUES (1)", "UPDATE t SET a = 1", "DELETE FROM t", "ALTER SYSTEM SET work_mem='1GB'", "CREATE TABLE t(a int)",
        "DROP TABLE t", "TRUNCATE t", "GRANT ALL ON t TO PUBLIC", "COPY t TO PROGRAM 'id'", "COPY t FROM '/etc/passwd'",
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity", "SELECT pg_cancel_backend(1)", "SELECT pg_reload_conf()",
        "SELECT set_config('default_transaction_read_only', 'off', false)", "SELECT 1 INTO t", "SELECT 1; DROP TABLE t",
        "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x", "WITH x AS (INSERT INTO t VALUES (1) RETURNING 1) SELECT 1",
        "SELECT * FROM t FOR UPDATE", "SELECT nextval('s')", "SELECT setval('s', 1)", "SELECT lo_import('/etc/passwd')",
        "SELECT pg_read_file('/etc/passwd')", "SELECT pg_sleep(100)", "SELECT 1 /* x */; DROP TABLE t", "SET ROLE x", "DO $$ BEGIN END $$",
        "CALL p()", "VACUUM", "SELECT 1 -- yorum", "SELECT dblink('x', 'y')", "SELECT pg_advisory_lock(1)", "SELECT pg_stat_reset()", "BEGIN READ WRITE",
        "SELECT pg_create_restore_point('x')", "SELECT pg_switch_wal()", "SELECT pg_promote()", "EXPLAIN ANALYZE SELECT 1",
    )
    IYI_PG = ("SELECT 1", "select current_setting('server_version_num')::int AS surum_num", "SHOW server_version",
              "WITH a AS (SELECT 1 AS x) SELECT x FROM a", "SELECT 'insert; drop -- x'", "SELECT 1;",
              "SELECT current_setting('ssl') AS ssl, current_setting('pg_stat_statements.track', true) AS izleme")

    def test_kotu_deyimler_yakalanir(self):
        for sql in self.KOTU_PG:
            self.assertTrue(ihlaller(sql), sql)

    def test_iyi_deyimler_gecer(self):
        for sql in self.IYI_PG:
            self.assertEqual(ihlaller(sql), [], sql)

    def test_mssql_kotu_deyimler_yakalanir(self):
        for sql in ("SELECT 1; DROP TABLE t", "SELECT * INTO x FROM y", "EXEC xp_cmdshell 'dir'", "SELECT 1 FROM OPENROWSET('a')",
                    "UPDATE t SET a = 1", "SELECT 1 -- x", "SET NOCOUNT ON", "SELECT 1 /* x */"):
            self.assertTrue(ihlaller(sql, "mssql"), sql)
        self.assertEqual(ihlaller("SELECT TOP 5 name FROM sys.databases", "mssql"), [])


class TumSqlAllowlistTests(unittest.TestCase):
    """EVERY SQL text that the collector and Mode B run passes the allowlist."""

    def hepsi(self, adlar_ve_sqller, motor="postgresql"):
        kotu = {ad: ihlaller(sql, motor) for ad, sql in adlar_ve_sqller if ihlaller(sql, motor)}
        self.assertEqual(kotu, {})

    def test_katalog_butun_sorgu_bicimleri(self):
        liste = [(c["id"], q) for c in katalog.PG for q in katalog.sorgular(c)] + [("vt_liste", katalog.VT_LISTE_SQL)]
        self.assertGreater(len(liste), len(katalog.PG))   # there are old version forms too
        self.hepsi(liste)

    def test_uretilen_toplayicinin_gomulu_katalogu(self):
        doc = katalog_json(TOPLAYICI)
        liste = [(c["id"], c["sql"]) for c in doc["kontroller"]]
        liste += [(c["id"] + "/eski", v["sql"]) for c in doc["kontroller"] for v in c.get("eski_surum", ())]
        liste.append(("veritabani_listesi", doc["veritabani_listesi"]))
        self.assertEqual(len(doc["kontroller"]), len(katalog.PG))
        self.hepsi(liste)

    def test_uretilen_toplayicinin_kod_sabitleri(self):
        # SQL embedded in code outside the catalog (the first connection query, the wrapper) must also be suitable
        sabitler = sql_sabitleri(TOPLAYICI)
        self.assertTrue(any("is_superuser" in s for s in sabitler))
        self.hepsi([("toplayici", s) for s in sabitler])

    def test_kip_b_kod_sabitleri(self):
        sabitler = sql_sabitleri(ROOT / "tarama" / "baglanti.py")
        self.assertIn(baglanti.ILK_SORGU, sabitler)
        self.hepsi([("baglanti", s) for s in sabitler])
        self.hepsi([("ilk", baglanti.ILK_SORGU)])

    def test_sorgu_katalogu_metni(self):
        deyimler = txt_deyimleri(ROOT / "site" / "assets" / "sorgu-katalogu.txt")
        self.assertGreaterEqual(len(deyimler), len(katalog.PG))
        self.hepsi([("txt%d" % i, d) for i, d in enumerate(deyimler)])

    def test_mssql_toplayici_ve_katalog(self):
        doc = katalog_json(TOPLAYICI_MSSQL)
        self.hepsi([(c["id"], c["sql"]) for c in doc["kontroller"]], "mssql")
        deyimler = txt_deyimleri(ROOT / "tarama" / "onsurum" / "sorgu-katalogu-mssql.txt")
        self.assertEqual(len(deyimler), len(katalog.MSSQL))
        self.hepsi([("txt%d" % i, d) for i, d in enumerate(deyimler)], "mssql")

    def test_mssql_sabit_on_ek_yalniz_oturum_ayari(self):
        # SQL Server has no read-only session mode: the fixed prefix contains only these SETs and the DECLARE
        spec = importlib.util.spec_from_file_location("ms_topl", TOPLAYICI_MSSQL)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        deyimler = [d.strip() for d in m.ON_EK.split(";") if d.strip()]
        self.assertEqual(deyimler, ["SET NOCOUNT ON", "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED", "SET LOCK_TIMEOUT 2000",
                                    "SET DEADLOCK_PRIORITY LOW", "DECLARE @j nvarchar(max) = ("])
        self.assertEqual(m.SON_EK, " FOR JSON PATH, INCLUDE_NULL_VALUES); SELECT ISNULL(@j, N'[]');")

    def test_toplayici_sql_yalniz_sabitlerden_gelir(self):
        # query text is not added from outside (argument, environment, file) at run time: the SQL of calistir() calls comes from KATALOG
        agac = ast.parse(TOPLAYICI.read_text(encoding="utf-8"))
        cagrilar = [n for n in ast.walk(agac) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "calistir"
                    and len(n.args) == 3]
        self.assertGreaterEqual(len(cagrilar), 3)
        for c in cagrilar:
            sql = c.args[2]
            ok = isinstance(sql, ast.Constant) or (isinstance(sql, ast.Name) and sql.id == "sql") or (
                isinstance(sql, ast.Subscript) and isinstance(sql.value, ast.Name) and sql.value.id == "KATALOG")
            self.assertTrue(ok, ast.dump(sql))

    def test_kip_b_sql_yalniz_katalogdan_gelir(self):
        agac = ast.parse((ROOT / "tarama" / "baglanti.py").read_text(encoding="utf-8"))
        cagrilar = [n for n in ast.walk(agac) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_calistir"]
        self.assertGreaterEqual(len(cagrilar), 4)
        for c in cagrilar:
            sql = c.args[3]
            ok = (isinstance(sql, ast.Name) and sql.id in ("ILK_SORGU", "sql")) or (
                isinstance(sql, ast.Attribute) and sql.attr == "VT_LISTE_SQL")
            self.assertTrue(ok, ast.dump(sql))


# ---------------------------------------------------------------- (2) session: read-only and timeout

def toplayici_modulu():
    spec = importlib.util.spec_from_file_location("alig_toplayici_test", TOPLAYICI)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def zaman_asimlari(pgoptions):
    return {k: int(v) for k, v in re.findall(r"-c (statement_timeout|lock_timeout)=(\d+)", pgoptions)}


def oturum_denetle(test, env):
    po = env["PGOPTIONS"]
    test.assertIn("-c default_transaction_read_only=on", po)
    test.assertNotIn("=off", po)
    z = zaman_asimlari(po)
    test.assertEqual(set(z), {"statement_timeout", "lock_timeout"})
    test.assertTrue(0 < z["statement_timeout"] <= 30000, po)   # the single-query budget does not exceed 30 s
    test.assertTrue(0 < z["lock_timeout"] <= 5000, po)


class OturumTests(unittest.TestCase):
    def sahte_run(self, kayit):
        def run(cmd, **kw):
            kayit.append((cmd, kw))
            sql = cmd[cmd.index("-c") + 1]
            if "is_superuser" in sql:
                cikti = [{"super": False, "yedek": False, "tls": True, "surum": 160015}]
            elif "has_database_privilege" in sql:
                cikti = [{"veritabani": "postgres", "baglanir": True}]
            else:
                cikti = []
            return subprocess.CompletedProcess(cmd, 0, json.dumps(cikti), "")
        return run

    def test_kip_a_her_psql_cagrisi_salt_okunur_ve_zaman_asimli(self):
        m = toplayici_modulu()
        kayit = []
        d = tempfile.mkdtemp()
        # a hostile PGOPTIONS in the environment is not allowed to loosen the session setting
        with mock.patch.dict(os.environ, {"PGOPTIONS": "-c default_transaction_read_only=off -c statement_timeout=0"}), \
                mock.patch.object(m.subprocess, "run", self.sahte_run(kayit)), mock.patch("builtins.print"):
            m.main(["--host", "db.ornek.local", "--user", "alig_hc", "--out", os.path.join(d, "o.json")])
        self.assertGreater(len(kayit), len(katalog.PG))   # the first query, the database list and all the checks
        for cmd, kw in kayit:
            oturum_denetle(self, kw["env"])
            self.assertLessEqual(kw["timeout"], 30)   # there is a process timeout too
        oturum_denetle(self, {"PGOPTIONS": m.__dict__.get("PGOPTIONS", kayit[0][1]["env"]["PGOPTIONS"])})

    def test_kip_a_komut_satirindan_parola_ve_sql_gelmez(self):
        m = toplayici_modulu()
        kayit = []
        with mock.patch.object(m.subprocess, "run", self.sahte_run(kayit)):
            m.calistir("psql", ["-d", "dbname=x"], "SELECT 1 AS a")
        cmd, _ = kayit[0]
        self.assertEqual(cmd.count("-c"), 1)   # a single command; no -f or other SQL source
        self.assertNotIn("-f", cmd)
        self.assertEqual(cmd[cmd.index("-c") + 1], "SELECT coalesce(json_agg(t), '[]'::json) FROM (SELECT 1 AS a) t")

    def test_kip_b_her_psql_cagrisi_salt_okunur_ve_zaman_asimli(self):
        kayit = []
        h = hedef.Hedef("db.ornek.com", "93.184.216.34", 5432)
        kanit = "0123456789abcdef0123456789abcdef"

        def run(cmd, env, sure):
            kayit.append((cmd, env, sure))
            sql = cmd[cmd.index("-c") + 1]
            if "shobj_description" in sql:
                cikti = [{"super": False, "kanit": baglanti.kanit_metni(kanit), "surum": 160015}]
            elif "has_database_privilege" in sql:
                cikti = [{"veritabani": "postgres", "baglanir": True}]
            else:
                cikti = []
            return 0, json.dumps(cikti), ""
        with mock.patch.dict(os.environ, {"PGOPTIONS": "-c default_transaction_read_only=off"}), \
                mock.patch.object(baglanti, "_surec_calistir", run):
            try:
                baglanti.tara(h, "postgres", "alig_hc", "p", kanit)
            except baglanti.BaglantiHatasi:
                pass   # blank lines can invalidate the document; here only the calls are checked
        self.assertGreater(len(kayit), len(katalog.PG))
        for cmd, env, sure in kayit:
            oturum_denetle(self, env)
            self.assertLessEqual(sure, 30)

    def test_kip_b_toplam_sure_butcesi_asilmaz(self):
        # every call is limited by the remaining budget: when the budget runs out the later checks do not run (zaman_asimi)
        sureler = []

        def run(cmd, env, sure):
            sureler.append(sure)
            sql = cmd[cmd.index("-c") + 1]
            if "shobj_description" in sql:
                return 0, json.dumps([{"super": False, "kanit": baglanti.kanit_metni("a" * 32), "surum": 160015}]), ""
            return 0, "[]", ""
        with mock.patch.object(baglanti, "_surec_calistir", run):
            try:
                baglanti.tara(hedef.Hedef("db.ornek.com", "93.184.216.34", 5432), "postgres", "alig_hc", "p", "a" * 32, toplam_sure=0.001)
            except baglanti.BaglantiHatasi:
                pass
        self.assertEqual(len(sureler), 2)   # the first query and the database list; when the budget ran out the catalog checks did not run
        self.assertTrue(all(0 < s <= 30 for s in sureler))


@pg_yardimci.pg_testi(*pg_yardimci.dis_veya_gecici_var())
class GercekPgOturumTests(unittest.TestCase):
    """On PG16: the generated collector's session is read-only, with lock and query timeouts; writing is rejected.
    An external server if ALIG_TEST_PG_HOST is set, otherwise the temporary cluster of tests/pg_yardimci.py; SKIP if neither exists."""

    @classmethod
    def setUpClass(cls):
        pg_yardimci.hedef_hazirla(cls)

    def baglanti(self):
        return ["-h", self.pg_host, "-p", self.pg_port, "-U", self.pg_kullanici, "-d", "dbname=postgres"]

    def test_oturum_ayarlari_gercekten_uygulanir(self):
        m = toplayici_modulu()
        r = m.calistir("psql", self.baglanti(), "SELECT current_setting('default_transaction_read_only') AS ro, "
                       "current_setting('statement_timeout') AS st, current_setting('lock_timeout') AS lt")
        self.assertEqual(r["durum"], "ok", r)
        self.assertEqual(r["satirlar"], [{"ro": "on", "st": "15s", "lt": "2s"}])

    def test_yazma_denemesi_reddedilir(self):
        m = toplayici_modulu()
        # a text that tries to break the wrapper and add a second statement (which the allowlist already rejects): as a second layer the session
        # default refuses to write
        kotu = "SELECT 1) t; CREATE TABLE alig_yazma_denemesi(i int); SELECT coalesce(json_agg(t),'[]'::json) FROM (SELECT 1"
        r = m.calistir("psql", self.baglanti(), kotu)
        self.assertEqual(r["durum"], "hata")
        v = subprocess.run(["psql", "-X", "-A", "-t"] + self.baglanti() + ["-c", "SELECT to_regclass('alig_yazma_denemesi') IS NULL"],
                           capture_output=True, text=True)
        self.assertEqual(v.stdout.strip(), "t")

    def test_kip_b_ortami_ayni_ayarlari_verir(self):
        env = baglanti._ortam("x")
        r = subprocess.run(["psql", "-X", "-A", "-t"] + self.baglanti() + ["-c", "SELECT current_setting('default_transaction_read_only') "
                           "|| ',' || current_setting('statement_timeout') || ',' || current_setting('lock_timeout')"],
                           capture_output=True, text=True, env=dict(env, PGPASSWORD="x"))
        self.assertEqual(r.stdout.strip(), "on,15s,2s", r.stderr)

    def test_butun_katalog_salt_okunur_oturumda_calisir(self):
        m = toplayici_modulu()
        for c in katalog.PG:
            sql = katalog.sorgu(c, 16)
            if sql is None:
                continue
            r = m.calistir("psql", self.baglanti(), sql)
            self.assertTrue(r["durum"] == "ok" or r["neden"] in ("yetki", "yedek_sunucu"), (c["id"], r))


# ---------------------------------------------------------------- (3) Mode B target validation (table-driven)

def sahte_cozumleyici(*adresler):
    def coz(ad, port, *a, **k):
        coz.cagri += 1
        out = []
        for adr in adresler:
            aile = socket.AF_INET6 if ":" in adr else socket.AF_INET
            out.append((aile, socket.SOCK_STREAM, 6, "", (adr, port) if aile == socket.AF_INET else (adr, port, 0, 0)))
        return out
    coz.cagri = 0
    return coz


def kod(ad, port=5432, coz=None):
    try:
        hedef.dogrula(ad, port, cozumleyici=coz or sahte_cozumleyici("93.184.216.34"))
    except hedef.Reddedildi as e:
        return e.kod
    return None


class HedefTablosuTests(unittest.TestCase):
    # (input, expected code). The input is directly the "sunucu" field; the resolver returns a public address (it must not be called).
    DOGRUDAN = [
        # loopback
        ("127.0.0.1", "ic_adres"), ("127.255.255.254", "ic_adres"), ("[::1]", "ic_adres"), ("[0:0:0:0:0:0:0:1]", "ic_adres"),
        ("[0000:0000:0000:0000:0000:0000:0000:0001]", "ic_adres"), ("127.0.0.1.", "ic_adres"),
        # RFC1918, CGNAT, link-local, cloud metadata
        ("10.0.0.1", "ic_adres"), ("10.255.255.255", "ic_adres"), ("172.16.0.1", "ic_adres"), ("172.31.255.255", "ic_adres"),
        ("192.168.0.1", "ic_adres"), ("100.64.0.1", "ic_adres"), ("100.127.255.255", "ic_adres"),
        ("169.254.169.254", "ic_adres"), ("169.254.0.1", "ic_adres"), ("[fe80::1]", "ic_adres"), ("[febf::1]", "ic_adres"),
        ("[fd00:ec2::254]", "ic_adres"),
        # IPv6 private/local
        ("[fc00::1]", "ic_adres"), ("[fdff:ffff::1]", "ic_adres"), ("[::]", "ic_adres"), ("[ff02::1]", "ic_adres"),
        ("[2001:db8::1]", "ic_adres"),
        # unspecified, broadcast, reserved
        ("0.0.0.0", "ic_adres"), ("255.255.255.255", "ic_adres"), ("224.0.0.1", "ic_adres"), ("240.0.0.1", "ic_adres"),
        ("192.0.0.1", "ic_adres"), ("198.51.100.1", "ic_adres"), ("203.0.113.1", "ic_adres"),
        # IPv6 forms that carry IPv4
        ("[::ffff:127.0.0.1]", "ic_adres"), ("[::ffff:7f00:1]", "ic_adres"), ("[::ffff:10.0.0.1]", "ic_adres"),
        ("[::ffff:a00:1]", "ic_adres"), ("[::ffff:169.254.169.254]", "ic_adres"), ("[::ffff:a9fe:a9fe]", "ic_adres"),
        ("[0:0:0:0:0:ffff:7f00:1]", "ic_adres"), ("[::ffff:0:7f00:1]", "ic_adres"), ("[64:ff9b::7f00:1]", "ic_adres"),
        ("[64:ff9b::a00:1]", "ic_adres"), ("[64:ff9b:1::1]", "ic_adres"), ("[2002:7f00:1::]", "ic_adres"),
        ("[2002:a9fe:a9fe::1]", "ic_adres"), ("[::127.0.0.1]", "ic_adres"), ("[::7f00:1]", "ic_adres"),
        # scope id (zone id): both direct and connection string injection
        ("[fe80::1%eth0]", "ic_adres"), ("[fe80::1%25eth0]", "ic_adres"), ("[::1%lo]", "ic_adres"),
        ("[2606:2800:220:1::1%eth0]", "ad"), ("[2606:2800:220:1::1%x hostaddr=127.0.0.1]", "ad"),
        ("[2606:2800:220:1::1%x hostaddr=10.0.0.5 sslmode=disable]", "ad"),
        ("[2606:2800:220:1::1%x options=-c_default_transaction_read_only=off]", "ad"),
        ("[2606:2800:220:1::1%1]", "ad"),
        # unusual spellings and name tricks
        ("2130706433", "ad"), ("0x7f000001", "ad"), ("0177.0.0.1", "ad"), ("127.1", "ad"), ("0", "ad"), ("0x7f.1", "ad"),
        ("localhost", "ad"), ("LOCALHOST", "ad"), ("localhost.", "ad"), ("db.localhost", "ad"), ("metadata.google.internal", "ad"),
        ("db.ornek.com:5432", "ad"), ("db.ornek.com@127.0.0.1", "ad"), ("db.ornek.com/", "ad"), ("db.ornek.com\n", "ad"),
        ("db.ornek.com\x00", "ad"), ("db.ornek.com\t", "ad"), (" db.ornek.com", "ad"), ("db ornek.com", "ad"),
        ("db.ornek.com hostaddr=127.0.0.1", "ad"), ("db.ornek.com,127.0.0.1", "ad"), ("db.ornek.com%00", "ad"),
        ("db.ornek.com'", "ad"), ("db.ornek.com\\", "ad"), ("１２７.0.0.1", "ad"), ("db。ornek.com", "ad"),
        ("127.0.0.1:5432", "ad"), ("http://127.0.0.1", "ad"), ("[127.0.0.1]", "ad"), ("[::1", "ad"), ("::1", "ad"), ("fe80::1", "ad"),
        ("", "ad"), (None, "ad"), (127, "ad"), (["127.0.0.1"], "ad"), (b"127.0.0.1", "ad"),
    ]
    KABUL = ["93.184.216.34", "db.ornek.com", "[2606:2800:220:1::1]", "DB.Ornek.COM.", "8.8.8.8", "1.1.1.1"]

    def test_dogrudan_adres_tablosu(self):
        for girdi, beklenen in self.DOGRUDAN:
            coz = sahte_cozumleyici("93.184.216.34")
            self.assertEqual(kod(girdi, 5432, coz), beklenen, repr(girdi))
            if beklenen == "ic_adres":
                self.assertEqual(coz.cagri, 0, repr(girdi))   # an IP spelling never goes to the resolver

    def test_kabul_edilenler_dizgeye_guvenle_girer(self):
        for girdi in self.KABUL:
            h = hedef.dogrula(girdi, 5432, cozumleyici=sahte_cozumleyici("93.184.216.34"))
            self.assertRegex(h.ad, r"^[0-9a-z.:-]+$", girdi)
            self.assertRegex(h.ip, r"^[0-9a-f.:]+$", girdi)
            d = baglanti.baglanti_dizgisi(h, "postgres", "alig_hc")
            self.assertEqual(len(re.findall(r"\bhostaddr=", d)), 1, d)
            self.assertEqual(len(re.findall(r"\bhost=", d)), 1, d)
            self.assertEqual(len(d.split()), 9, d)   # each field is a single word: a field cannot be added with a space

    # DNS rebinding: address check after resolution
    COZUM = [
        (["10.0.0.5"], "ic_adres"), (["127.0.0.1"], "ic_adres"), (["169.254.169.254"], "ic_adres"), (["0.0.0.0"], "ic_adres"),
        (["::1"], "ic_adres"), (["fe80::1"], "ic_adres"), (["fe80::1%eth0"], "ic_adres"), (["fc00::1"], "ic_adres"),
        (["::ffff:127.0.0.1"], "ic_adres"), (["::ffff:10.0.0.1"], "ic_adres"), (["::ffff:0:7f00:1"], "ic_adres"),
        (["64:ff9b::7f00:1"], "ic_adres"), (["100.64.0.1"], "ic_adres"), (["172.16.5.5"], "ic_adres"),
        (["93.184.216.34", "127.0.0.1"], "ic_adres"), (["127.0.0.1", "93.184.216.34"], "ic_adres"),
        (["2606:2800:220:1::1", "fe80::1"], "ic_adres"), (["93.184.216.34", "::ffff:10.0.0.1"], "ic_adres"),
        ([], "cozulemedi"),
        (["93.184.216.34"], None), (["2606:2800:220:1::1"], None), (["93.184.216.34", "93.184.216.35"], None),
    ]

    def test_cozumleme_sonrasi_adres_tablosu(self):
        for adresler, beklenen in self.COZUM:
            self.assertEqual(kod("db.ornek.com", 5432, sahte_cozumleyici(*adresler)), beklenen, adresler)

    def test_cozumleyici_bozuk_kayit_dondururse(self):
        for kayitlar in ([(socket.AF_INET, 1, 6, "", ("db.ornek.com", 5432))], [(socket.AF_INET, 1, 6, "", ())], [(1, 2)], [None],
                         [(socket.AF_INET, 1, 6, "", (None, 5432))], [(socket.AF_INET, 1, 6, "", ("localhost", 5432))]):
            self.assertEqual(kod("db.ornek.com", 5432, lambda *a, **k: kayitlar), "cozulemedi", kayitlar)

    def test_hedef_yalniz_dogrulanan_ipye_baglanir_ve_ad_yeniden_cozulmez(self):
        yanitlar = [["93.184.216.34"], ["127.0.0.1"], ["10.0.0.1"]]

        def degisen(ad, port, *a, **k):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (yanitlar.pop(0)[0], port))]
        h = hedef.dogrula("db.ornek.com", 5432, cozumleyici=degisen)
        d = baglanti.baglanti_dizgisi(h, "postgres", "alig_hc")
        self.assertIn("hostaddr=93.184.216.34", d)
        self.assertEqual(len(yanitlar), 2)   # the name was resolved once

    def test_yasak_aglar_ek_olarak_uygulanir(self):
        for adr, ag in (("203.0.114.9", "203.0.114.0/24"), ("2606:2800:220:1::1", "2606:2800:220::/48")):
            self.assertEqual(kod("db.ornek.com", 5432, sahte_cozumleyici(adr)), None)
            with self.assertRaises(hedef.Reddedildi):
                hedef.dogrula("db.ornek.com", 5432, cozumleyici=sahte_cozumleyici(adr), yasak_aglar=(ag,))
            with self.assertRaises(hedef.Reddedildi):
                hedef.dogrula(adr if ":" not in adr else "[%s]" % adr, 5432, yasak_aglar=(ag,))

    PORT_KABUL = (5432, 1433, 1024, 6432, 15432, 65535, "5432", "1433", "65535", "05432")
    PORT_RED = (0, 1, 21, 22, 23, 25, 53, 80, 110, 443, 445, 1023, 65536, 70000, 99999, -1, -5432, "-1", "x", "", " 5432", "5432 ",
                "5432\n", "+5432", "5432.0", "0x1538", "5e3", "٥٤٣٢", "123456", None, True, False, 5432.0, 5432.5,
                [5432], {"p": 1}, b"5432")

    def test_port_tablosu(self):
        for p in self.PORT_KABUL:
            self.assertIsNone(kod("db.ornek.com", p), repr(p))
        for p in self.PORT_RED:
            self.assertEqual(kod("db.ornek.com", p), "port", repr(p))

    def test_ic_adres_ve_port_hatasi_ayni_musteri_iletisini_verir(self):
        iletiler = set()
        for ad, port in (("127.0.0.1", 5432), ("[::1]", 5432), ("db.ornek.com", 22), ("localhost", 5432), ("[fe80::1%eth0]", 5432)):
            try:
                hedef.dogrula(ad, port, cozumleyici=sahte_cozumleyici("93.184.216.34"))
            except hedef.Reddedildi as e:
                iletiler.add((e.ileti("tr"), e.ileti("en")))
        self.assertEqual(len(iletiler), 1)


class BaglantiDizgisiSavunmasi(unittest.TestCase):
    """Even if the target object comes through another path (the runner socket), no extra key can enter the string."""

    def test_enjeksiyonlu_hedef_dizgi_uretmez(self):
        for ad, ip in (("db.ornek.com", "2606:2800:220:1::1%x hostaddr=127.0.0.1"), ("db.ornek.com hostaddr=127.0.0.1", "93.184.216.34"),
                       ("db.ornek.com", "93.184.216.34 options=-c_default_transaction_read_only=off"), ("a'b.com", "93.184.216.34"),
                       ("db.ornek.com", "93.184.216.34\n"), ("db.ornek.com", ""), ("", "93.184.216.34"), ("db.ornek.com", "93.184.216.34;")):
            with self.assertRaises(baglanti.BaglantiHatasi, msg=repr((ad, ip))) as e:
                baglanti.baglanti_dizgisi(hedef.Hedef(ad, ip, 5432), "postgres", "alig_hc")
            self.assertEqual(e.exception.kod, "bicim")

    def test_veritabani_ve_kullanici_adinda_satir_sonu_yok(self):
        h = hedef.Hedef("db.ornek.com", "93.184.216.34", 5432)
        for ad in ("postgres\n", "post gres", "a=b", "a'b", "", "1abc", "x" * 64, "a;b"):
            for alan in ("veritabani", "kullanici"):
                a = {"veritabani": "postgres", "kullanici": "alig_hc"}
                a[alan] = ad
                with self.assertRaises(baglanti.BaglantiHatasi, msg=repr(ad)):
                    baglanti.baglanti_dizgisi(h, a["veritabani"], a["kullanici"])

    def test_port_sayi_olmali(self):
        for port in ("5432 hostaddr=1.1.1.1", None, 5432.5):
            with self.assertRaises(baglanti.BaglantiHatasi):
                baglanti.baglanti_dizgisi(hedef.Hedef("db.ornek.com", "93.184.216.34", port), "postgres", "alig_hc")

    def test_ipv6_hedef_dizgide_tek_sozcuk(self):
        h = hedef.dogrula("[2606:2800:220:1::1]", 5432)
        d = baglanti.baglanti_dizgisi(h, "postgres", "alig_hc")
        self.assertIn("hostaddr=2606:2800:220:1::1 ", d)


class CalistiriciHedefTests(unittest.TestCase):
    """The runner does not trust the web process: a scope id/injection in the ip field is also rejected."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.soket = str(self.d / "c.sock")
        self.cagri = []
        self.srv = calistirici.Sunucu(self.soket, tara=lambda h, **k: (self.cagri.append(h), temiz_belge())[1])
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def kod(self, ad, ip, port=5432):
        try:
            calistirici.uzaktan_tara(self.soket, hedef.Hedef(ad, ip, port), "postgres", "alig_hc", "p", "ab" * 16)
        except baglanti.BaglantiHatasi as e:
            return e.kod
        return None

    def test_tablo(self):
        for ad, ip, beklenen in (
                ("db.ornek.com", "93.184.216.34", None),
                ("db.ornek.com", "2606:2800:220:1::1%x hostaddr=127.0.0.1", "hedef"),
                ("db.ornek.com", "2606:2800:220:1::1%eth0", "hedef"),
                ("db.ornek.com", "93.184.216.34 hostaddr=127.0.0.1", "hedef"),
                ("db.ornek.com", "127.0.0.1", "hedef"), ("db.ornek.com", "::ffff:10.0.0.1", "hedef"), ("db.ornek.com", "fe80::1%eth0", "hedef"),
                ("db.ornek.com", "0.0.0.0", "hedef"), ("db.ornek.com", "169.254.169.254", "hedef"), ("db.ornek.com", "", "hedef"),
                ("db.ornek.com", "ad", "hedef"), ("localhost", "93.184.216.34", "hedef"), ("db.ornek.com hostaddr=10.0.0.1", "93.184.216.34", "hedef"),
                ("93.184.216.35", "93.184.216.34", "hedef")):   # if the name is an IP it must be the same as ip
            self.cagri.clear()
            self.assertEqual(self.kod(ad, ip), beklenen, (ad, ip))
            self.assertEqual(len(self.cagri), 0 if beklenen else 1, (ad, ip))   # in a rejected request the scan does not run
        self.assertEqual(self.kod("db.ornek.com", "93.184.216.34", 22), "hedef")
        self.assertEqual(self.kod("db.ornek.com", "93.184.216.34", "5432 hostaddr=1.1.1.1"), "hedef")


# ---------------------------------------------------------------- (4) resource limits

class SinirTests(unittest.TestCase):
    def test_sabit_degerler(self):
        self.assertEqual(yukleme.MAX_BAYT, 5 * 1024 * 1024)
        self.assertEqual(yukleme.MAX_DERINLIK, 8)
        self.assertEqual(yukleme.MAX_SATIR, 200)
        self.assertGreaterEqual(yukleme.MAX_SATIR_VT, yukleme.MAX_SATIR)
        self.assertEqual(tserver.GOVDE_SINIRI, yukleme.MAX_BAYT + 64 * 1024)   # margin for the multi-section envelope
        self.assertEqual(calistirici.YANIT_SINIRI, yukleme.MAX_BAYT + 64 * 1024)
        self.assertLessEqual(calistirici.ISTEK_SINIRI, 64 * 1024)

    def test_bayt_siniri_sinirda_kabul_ustunde_red(self):
        belge = json.dumps(temiz_belge()).encode()
        bosluk = b" " * (yukleme.MAX_BAYT - len(belge))
        yukleme.coz(belge + bosluk)   # at exactly the limit
        with self.assertRaises(yukleme.Gecersiz) as e:
            yukleme.coz(belge + bosluk + b" ")
        self.assertEqual(e.exception.kod, "buyuk")

    def test_derinlik_sinirda_kabul_ustunde_red(self):
        def derin(n):
            return b'{"a":' * n + b"1" + b"}" * n
        for n in (yukleme.MAX_DERINLIK, yukleme.MAX_DERINLIK + 1, 1000):
            try:
                yukleme._derinlik_denetle(derin(n))
                kod_ = None
            except yukleme.Gecersiz as e:
                kod_ = e.kod
            self.assertEqual(kod_, None if n == yukleme.MAX_DERINLIK else "derin", n)
        with self.assertRaises(yukleme.Gecersiz):
            yukleme._derinlik_denetle(b"[" * (yukleme.MAX_DERINLIK + 1) + b"]" * (yukleme.MAX_DERINLIK + 1))
        # brackets inside text and escaped brackets are not counted
        yukleme._derinlik_denetle(b'{"a":"' + b"[{" * 500 + b'"}')
        yukleme._derinlik_denetle(b'{"a":"\\"' + b"[{" * 500 + b'"}')

    def test_yapi_sayisi_siniri(self):
        with self.assertRaises(yukleme.Gecersiz) as e:
            yukleme._derinlik_denetle(b"[]," * (yukleme.MAX_YAPI + 1))
        self.assertEqual(e.exception.kod, "derin")
        with self.assertRaises(yukleme.Gecersiz):
            yukleme._derinlik_denetle(b'"' * (yukleme.MAX_TIRNAK + 1))
        with self.assertRaises(yukleme.Gecersiz):
            yukleme._derinlik_denetle(b"\\" * (yukleme.MAX_KACIS + 1))

    def test_satir_siniri(self):
        def belge(adet, kontrol="pg_super_roller"):
            d = temiz_belge()
            d["kontroller"][kontrol]["satirlar"] = [{"rolname": "r%d" % i, "rolcanlogin": True} for i in range(adet)]
            return d
        yukleme.dogrula(belge(yukleme.MAX_SATIR))
        with self.assertRaises(yukleme.Gecersiz) as e:
            yukleme.dogrula(belge(yukleme.MAX_SATIR + 1))
        self.assertEqual(e.exception.kod, "satirlar")

    def test_veritabani_kapsamli_satir_siniri(self):
        def belge(adet):
            d = temiz_belge()
            d["kontroller"]["pg_eklentiler"]["satirlar"] = [{"veritabani": "d", "extname": "e%d" % i, "extversion": "1"} for i in range(adet)]
            return d
        yukleme.dogrula(belge(yukleme.MAX_SATIR_VT))
        with self.assertRaises(yukleme.Gecersiz):
            yukleme.dogrula(belge(yukleme.MAX_SATIR_VT + 1))

    def test_atlanan_siniri(self):
        def belge(adet):
            d = temiz_belge()
            e = d["kontroller"]["pg_eklentiler"]
            e["atlanan"] = [{"veritabani": "d%d" % i, "neden": "yetki"} for i in range(adet)]
            return d
        yukleme.dogrula(belge(yukleme.MAX_ATLANAN))
        with self.assertRaises(yukleme.Gecersiz):
            yukleme.dogrula(belge(yukleme.MAX_ATLANAN + 1))

    def test_metin_siniri(self):
        d = temiz_belge()
        d["kontroller"]["pg_super_roller"]["satirlar"] = [{"rolname": "a" * (yukleme.MAX_METIN + 1), "rolcanlogin": True}]
        with self.assertRaises(yukleme.Gecersiz):
            yukleme.dogrula(d)

    def test_kip_b_veritabani_siniri_toplayicidan_dusuk(self):
        self.assertLessEqual(baglanti.EN_COK_VERITABANI, katalog.EN_COK_VERITABANI)

    def test_kip_b_sunucudan_gelen_satirlar_kesilir(self):
        c = katalog.PG_BY_ID["pg_super_roller"]
        gelen = [{"rolname": "r%d" % i, "rolcanlogin": True, "fazla": "x"} for i in range(5000)] + ["metin", 5, None]
        out = baglanti._temizle(c, gelen)
        self.assertEqual(len(out), yukleme.MAX_SATIR)
        self.assertTrue(all(set(s) <= {"rolname", "rolcanlogin"} for s in out))

    def test_kip_b_tarama_yuvasi_ayni_anda_iki(self):
        alinan = []
        try:
            while tserver.TARAMA_YUVASI.acquire(blocking=False):
                alinan.append(1)
                self.assertLessEqual(len(alinan), 2)
            self.assertEqual(len(alinan), 2)
        finally:
            for _ in alinan:
                tserver.TARAMA_YUVASI.release()

    def test_calistirici_varsayilan_es_zamanlilik(self):
        d = Path(tempfile.mkdtemp())
        srv = calistirici.Sunucu(str(d / "c.sock"))
        try:
            self.assertTrue(srv.yuva.acquire(blocking=False))
            self.assertTrue(srv.yuva.acquire(blocking=False))
            self.assertFalse(srv.yuva.acquire(blocking=False))
        finally:
            srv.server_close()

    def test_calistirici_cerceve_siniri(self):
        a, b = socket.socketpair()
        try:
            a.sendall(struct.pack(">I", 1000))
            with self.assertRaises(ValueError):
                calistirici.cerceve_al(b, 999)
        finally:
            a.close()
            b.close()


class CiktiSiniriTests(unittest.TestCase):
    """Mode B: the server chosen by the customer may be hostile; psql output does not accumulate in memory without bound."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.psql = self.d / "psql"
        self.psql.write_text("#!%s\nimport sys\nfor _ in range(200):\n    sys.stdout.write('x' * 1048576)\n    sys.stdout.flush()\n" % sys.executable,
                             encoding="utf-8")
        self.psql.chmod(self.psql.stat().st_mode | stat.S_IEXEC)

    def test_asiri_cikti_kesilir_ve_surec_oldurulur(self):
        bas = time.monotonic()
        sonuc, _ = baglanti._calistir(str(self.psql), "dbname=x", "p", "SELECT 1", 20)
        self.assertEqual(sonuc, {"durum": "hata", "neden": "hata"})
        self.assertLess(time.monotonic() - bas, 15)
        self.assertLessEqual(baglanti.CIKTI_SINIRI, 4 * 1024 * 1024)

    def test_normal_cikti_gecer(self):
        self.psql.write_text("#!%s\nprint('[{\"a\": 1}]')\n" % sys.executable, encoding="utf-8")
        sonuc, _ = baglanti._calistir(str(self.psql), "dbname=x", "p", "SELECT 1 AS a", 20)
        self.assertEqual(sonuc, {"durum": "ok", "satirlar": [{"a": 1}]})


# ---------------------------------------------------------------- (5) Mode B is off by default

class KapaliTests(unittest.TestCase):
    def test_sunucu_sinifi_varsayilani_kapali(self):
        self.assertFalse(tserver.H.dogrudan)

    def test_ortam_degiskeni_olmadan_ve_degeri_1_degilse_acilmaz(self):
        for ortam in ({}, {"ALIG_DOGRUDAN": ""}, {"ALIG_DOGRUDAN": "0"}, {"ALIG_DOGRUDAN": "true"}, {"ALIG_DOGRUDAN": "yes"},
                      {"ALIG_DOGRUDAN": "1"}, {"ALIG_DOGRUDAN": "1", "ALIG_CALISTIRICI_SOKETI": ""},
                      {"ALIG_CALISTIRICI_SOKETI": "/run/x.sock"}, {"ALIG_DOGRUDAN": " 1", "ALIG_CALISTIRICI_SOKETI": "/run/x.sock"}):
            H = type("H", (tserver.H,), {})
            self.assertFalse(tserver.dogrudan_ayarla(ortam, H), ortam)
            self.assertFalse(H.dogrudan, ortam)

    def test_yapilandirma_ve_dagitim_varsayilanlari_kapali(self):
        for yol in ("config.example", "deploy"):
            for dosya in (ROOT / yol).rglob("*"):
                if not dosya.is_file() or dosya.suffix in (".png", ".woff2", ".sqlite"):
                    continue
                for n, satir in enumerate(dosya.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if re.match(r"\s*(export\s+)?ALIG_DOGRUDAN\s*=\s*1\b", satir) or re.match(r"\s*Environment=\"?ALIG_DOGRUDAN=1", satir):
                        onceki = dosya.read_text(encoding="utf-8").splitlines()[max(0, n - 4):n]
                        self.assertTrue(any("dogrudan_baglanti" in s for s in onceki), "%s:%d kosulsuz ALIG_DOGRUDAN=1" % (dosya, n))
        self.assertIn("dogrudan_baglanti: false", (ROOT / "deploy" / "ansible" / "group_vars" / "all.yml").read_text(encoding="utf-8"))


class KapaliUclarTests(unittest.TestCase):
    """While the server runs, the Mode B endpoints return 404 when off (and no connection is tried)."""

    def setUp(self):
        from http.server import ThreadingHTTPServer
        self.d = tempfile.mkdtemp()
        self.db = os.path.join(self.d, "t.sqlite")
        from tarama import depo
        depo.baglan(self.db).close()
        self.H = type("H", (tserver.H,), {"db_yolu": self.db, "dogrudan": False})
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), self.H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def istek(self, yontem, yol, govde=None):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_port, timeout=5)
        c.request(yontem, yol, body=govde, headers={"Content-Type": "application/x-www-form-urlencoded"} if govde is not None else {})
        r = c.getresponse()
        r.read()
        return r.status

    def test_butun_uclar_404(self):
        tok = "A" * 43
        for yontem, yol in (("GET", "/api/tarama/baglan"), ("GET", "/api/tarama/baglan?dil=en"), ("POST", "/api/tarama/baglan"),
                            ("POST", "/api/tarama/baglan/" + tok), ("GET", "/api/tarama/baglan/" + tok), ("POST", "/api/tarama/baglan/")):
            govde = b"sunucu=127.0.0.1&port=5432" if yontem == "POST" else None
            with mock.patch.object(baglanti, "tara", side_effect=AssertionError("baglanti denendi")), \
                    mock.patch.object(calistirici, "uzaktan_tara", side_effect=AssertionError("calistirici cagrildi")):
                self.assertEqual(self.istek(yontem, yol, govde), 404, (yontem, yol))


if __name__ == "__main__":
    unittest.main()
