#!/usr/bin/env python3
"""Generates docs/kural-katalogu.md from the rule records, and docs/surum-matrisi.md from the catalog and the verification result.
The documents are not edited by hand; tests/test_kanit.py and tests/test_surum.py check that they are up to date.

  python3 tarama/uret_kurallar.py            # writes
  python3 tarama/uret_kurallar.py --kontrol  # returns 1 if out of date
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tarama import eol, kanit, katalog, kurallar, kurallar_mssql, puan, rapor  # noqa: E402

HEDEF = ROOT / "docs" / "kural-katalogu.md"
MATRIS = ROOT / "docs" / "surum-matrisi.md"
DOGRULAMA = ROOT / "docs" / "surum-dogrulama.json"
BELGELER = ROOT / "tests" / "veri" / "surum"   # raw documents collected during verification: <major version>/<account>.json
HESAP_AD = {"pg_monitor": "pg_monitor account", "yetkisiz": "Unprivileged account", "super": "Superuser", "yedek": "Standby server (pg_monitor)"}
YETKI_AD = {"herkes": "everyone", "pg_read_all_stats": "pg_read_all_stats (pg_monitor)",
            "pg_read_all_settings": "pg_read_all_settings (pg_monitor)", "superuser": "superuser"}
YETKI_YOKSA = {"herkes": "-",
               "pg_read_all_stats": "The query runs but other users' sessions are not visible; the rule becomes Unknown.",
               "pg_read_all_settings": "The query fails with a privilege error; the rule becomes Unavailable.",
               "superuser": "The query fails with a privilege error; the rule becomes Unavailable."}
# English rendering of the version notes in tarama/katalog.py (the Turkish text there is part of the catalog digest)
SURUM_NOTU = {"wal_status kolonu PostgreSQL 13'te geldi, 12'de boş döner": "the wal_status column arrived in PostgreSQL 13 and returns empty in 12"}
SATIR_AD = {"tek": "single row", "en_az_bir": "at least one row", "herhangi": "empty result is valid"}

DURUM_ACIKLAMA = {
    "FAIL": "The rule produced at least one critical or high severity finding.",
    "WARNING": "The rule produced only medium, low or informational findings.",
    "UNKNOWN": "Data arrived but is not enough for a conclusion: invalid format or type, a required value is empty, an expected row is missing, "
               "some databases on the server were not scanned, or an additional source did not arrive.",
    "UNAVAILABLE": "Data could not be obtained: not run, no privilege, timeout, not available in this version, standby server, error, limit.",
    "NOT_APPLICABLE": "The data shows that the rule's subject does not exist on the server (for example, there is no replication slot).",
    "PASS": "All sources arrived completely, the rule ran and there are no findings. PASS never appears when data is missing.",
}
GUVEN_ACIKLAMA = {
    "HIGH": "A setting or catalog state was read directly.",
    "MEDIUM": "A statistical estimate or a snapshot of the scan moment: the statistics reset time and the scan time affect the result.",
    "LOW": "An indirect sign: extra context is needed for a decision (for example, usage on replicas).",
}


def _kaynaklar(k, by_id):
    out = []
    for kay in k.kaynaklar:
        notlar = (["additional"] if kay.ek else []) + (["in every database"] if by_id.get(kay.kontrol, {}).get("kapsam") == "veritabani" else [])
        ad = "document: `superuser`" if kay.kontrol == kanit.TOPLAYICI else "`%s`" % kay.kontrol
        out.append("%s (%s)" % (ad, ", ".join(notlar + [SATIR_AD[kay.satir]])))
    return "<br>".join(out)


def _tablo(liste, by_id):
    m = rapor.M["en"]
    satirlar = ["| ID | Check | Category | Risk | Confidence | Collection check | Source read | Pass condition |",
                "|---|---|---|---|---|---|---|---|"]
    for k in sorted(liste, key=lambda x: x.kimlik):
        kaynak = list(k.kaynak) or sorted({a for kay in k.kaynaklar for a in by_id.get(kay.kontrol, {}).get("kaynak", ())})
        guven = k.guven
        tavan = kanit.GUVEN_TAVANI.get(k.motor)
        if tavan and kanit.GUVENLER.index(tavan) > kanit.GUVENLER.index(guven):
            guven = "%s (shown: %s)" % (guven, tavan)
        satirlar.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            k.kimlik, k.ad["en"], m["kategori"][k.kategori], m["onem"][k.risk], guven, _kaynaklar(k, by_id),
            ", ".join("`%s`" % a for a in kaynak), k.beklenen["en"]))
    return "\n".join(satirlar)


def _sayi(v):
    return "%g" % v


def _puan_bolumu():
    m, v = rapor.M["en"], puan.VARSAYILAN
    p = ["## Health score", "",
         "The score (0-100) is the weighted credit ratio of the applicable rules (`tarama/puan.py`):", "",
         "```text", "score = 100 × Σ(category multiplier × weight × credit) / Σ(category multiplier × weight)", "```", "",
         "The weight comes from the rule's risk level. The risk level is the highest finding severity the rule can produce "
         "(`tests/test_puan.py` checks this with random documents). The credit comes from the rule's status:", "",
         "| Risk level | Default weight |", "|---|---|"]
    p += ["| %s | %s |" % (m["onem"][o], _sayi(w)) for o, w in v["agirlik"].items()]
    p += ["", "| Status | Credit |", "|---|---|"]
    for d in kanit.DURUMLAR:
        if d == "WARNING":
            kredi = "by the finding's severity, default: " + "; ".join("%s %s" % (m["onem"][o].lower(), _sayi(c)) for o, c in v["kredi_uyari"].items())
        elif d == "NOT_APPLICABLE":
            kredi = "not counted"
        else:
            kredi = "%s (fixed)" % _sayi(puan.KREDI[d])
        p.append("| %s | %s |" % (d, kredi))
    p += ["", "The default of the category multipliers is %s." % ", ".join(sorted({_sayi(c) for c in v["kategori_carpani"].values()})), "",
          "An unknown status does not raise the score: a rule with no evidence loses as many points as a failed rule; a rule whose "
          "evidence disappears does not improve the score. For this reason the score is always shown together with the evidence coverage (the ratio of "
          "applicable rules that have evidence, unweighted) and the report separates whether each loss comes from a finding or from missing "
          "evidence. If none of the rules that enter the score has evidence, the score is not computed. The integers shown are rounded down: 100 "
          "appears only if there is no loss, and 100% coverage only if every rule has evidence. The category score is computed with the same "
          "formula, only with the rules of that category and without multipliers.", "",
          "The weights, the warning credits and the category multipliers can be set from the JSON file given with `%s` (`docs/runbook.md`); "
          "the status credits are fixed. The default values are an engineering choice, not taken from a standard." % puan.ORTAM, ""]
    return p


def _eol_bolumu():
    v = eol.VARSAYILAN
    p = ["### PostgreSQL end-of-life table (PG-MAINT-009)", "",
         "Source: <%s>, retrieved %s. The final release is the last minor release the community publishes for a major version; "
         "`tarama/eol.py` holds the table. Versions older than the first row are reported as no longer supported, without a date." % (eol.KAYNAK_URL, eol.ALINMA_TARIHI), "",
         "| Major version | First release | Final release (EOL) |", "|---|---|---|"]
    p += ["| %d | %s | %s |" % (m, d["ilk"], d["son"]) for m, d in sorted(v["tablo"].items())]
    p += ["", "PG-MAINT-009 is informational and advisory only: it evaluates the end date against the scan date taken from the scan document "
          "(there is no clock call in the evaluation), reports a version whose end date has passed, and also one whose end date is within "
          "%d days (`pencere_gun`, default). Its risk level is Info, so it has weight 0 and does not lower the health score; it never "
          "recommends an automatic change. The older PG-MAINT-001 reads the same table with its own severities (High after the end date, Medium within 90 days). "
          "The window and the dates can be overridden without a code change with the JSON file given with `%s` "
          "(`docs/runbook.md`)." % (v["pencere_gun"], eol.ORTAM), ""]
    return p


def uret():
    p = ["# Rule catalog", "",
         "<!-- This file is generated with `python3 tarama/uret_kurallar.py`; do not edit it by hand. -->", "",
         "Every rule produces a single evidence record in every scan (`tarama/kanit.py`): status, severity, confidence level, source, "
         "collection time, observed values and findings. Ids are permanent: if a rule is removed its id is not reused, "
         "and the id stays the same even if the category changes.", "",
         "## Statuses", "", "| Status | Name in the report | Meaning |", "|---|---|---|"]
    p += ["| %s | %s | %s |" % (d, rapor.M["en"]["durum"][d], DURUM_ACIKLAMA[d]) for d in kanit.DURUMLAR]
    p += ["", "If there is a finding, the status is FAIL or WARNING even if coverage is partial: a problem that is found is real. "
          "Mapping of severity to status: critical and high are FAIL; medium, low and info are WARNING.", "",
          "## Confidence levels", "", "| Level | Meaning |", "|---|---|"]
    p += ["| %s | %s |" % (g, GUVEN_ACIKLAMA[g]) for g in kanit.GUVENLER]
    p += ["", "Confidence is given only for statuses that have evidence (FAIL, WARNING, NOT_APPLICABLE, PASS). "
          "SQL Server rules are a preview: the queries were not tested on a real server, and the confidence shown in the report is at most MEDIUM.", ""]
    p += _puan_bolumu()
    p += ["## Data conditions", "",
          "Data condition: for *single row* exactly one row is expected in the source; for *at least one row* an empty result in the source means no data; "
          "for *empty result is valid* an empty result in the source means no problem. A row with a required value empty or of the wrong type "
          "does not enter the evaluation and makes the result partial. If an *additional* source does not arrive the rule still runs and reports the finding, but cannot give PASS. "
          "For a source that runs *in every database*, PASS requires that all connectable databases on the server were scanned "
          "(`pg_kapsam`); if a database was skipped or not selected, the result is partial.", "",
          "## PostgreSQL (%d rules)" % len(kurallar.KURALLAR), "", _tablo(kurallar.KURALLAR, katalog.PG_BY_ID), "",
          "Information checks that are not a rule source: %s." % ", ".join("`%s`" % x for x in kurallar.BILGI), "",
          "Rules evaluated only on the primary server: %s. Table statistics (dead rows, index usage) are not kept on a standby "
          "and archiving is made primary-only; these rules become Not applicable on a standby. The server role is read from the `pg_sunucu_rolu` "
          "check; if it cannot be read, these rules cannot be Pass." % ", ".join(sorted(k.kimlik for k in kurallar.KURALLAR if k.birincil)), "",
          ] + _eol_bolumu() + [
          "## SQL Server, preview (%d rules)" % len(kurallar_mssql.KURALLAR), "", _tablo(kurallar_mssql.KURALLAR, katalog.MSSQL_BY_ID), ""]
    return "\n".join(p)


def dogrulama():
    return json.loads(DOGRULAMA.read_text(encoding="utf-8")) if DOGRULAMA.exists() else {"surumler": {}}


def sinandigi_surumler(cid, kayit):
    """Major versions on which the check's query ran on a real server (with the super account for a superuser check)."""
    hesap = "super" if katalog.PG_BY_ID[cid]["yetki"] == "superuser" else "pg_monitor"
    return sorted(int(v) for v, s in kayit["surumler"].items()
                  if s["hesaplar"][hesap]["kontroller"].get(cid, {}).get("durum") == "ok")


def _surumler(c):
    if c["en_az"] == 0:
        metin = "every version"
    elif c.get("en_cok"):
        metin = "%d-%d" % (c["en_az"], c["en_cok"])
    else:
        metin = "%d and later" % c["en_az"]
    for v in c.get("eski_surum", ()):
        metin += "; separate query for %d and earlier (%s)" % (v["en_cok"], SURUM_NOTU[v["not"]])
    return metin


def _hucre(e):
    if e["durum"] != "ok":
        return "Unavailable: %s" % rapor.M["en"]["nedenler"].get(e["neden"], e["neden"])
    metin = "%d rows" % e["satir"] + (", %d databases skipped" % e["atlanan"] if e["atlanan"] else "")
    if "deger" in e:
        metin += "; " + ", ".join("%s: `%s`" % (k, {None: "-", True: "yes", False: "no"}.get(v, v) if not isinstance(v, int) or isinstance(v, bool) else v)
                                  for k, v in sorted(e["deger"].items()))
    return metin


def uret_matris():
    kayit = dogrulama()
    sinanan = ", ".join(str(v) for v in katalog.SINANAN) or "none"
    p = ["# PostgreSQL version and privilege matrix", "",
         "<!-- This file is generated with `python3 tarama/uret_kurallar.py`; do not edit it by hand. Source: tarama/katalog.py, "
         "docs/surum-dogrulama.json -->", "",
         "The collector and the direct connection (Mode B) read the server's major version and pick that version's query for each check. "
         "On a version the check does not support the query does not run at all; the check becomes \"Unavailable: not supported on this version\" in the report. "
         "The matrix covers PostgreSQL %d-%d; on a newer version the main query runs." % (katalog.SURUM_ALT, katalog.SURUM_UST), "",
         "Versions on which all the queries were tested on a real server: **%s**. On a version that was not tested the evidence confidence in the report is shown "
         "at most as medium (MEDIUM) and the report summary says so." % sinanan, "",
         "The recommended scan account is only a member of `pg_monitor` (`alig-rol.sql`). If a check requires a role inside `pg_monitor` "
         "and the account lacks it, the evidence engine counts the result as partial (the `pg_hesap` check reads the account's roles): "
         "that rule cannot be Pass.", "",
         "## Checks", "",
         "| Check | Versions | Required privilege | If the privilege is missing | Versions on which it ran on a real server |", "|---|---|---|---|---|"]
    for c in katalog.PG:
        p.append("| `%s` | %s | %s | %s | %s |" % (c["id"], _surumler(c), YETKI_AD[c["yetki"]], YETKI_YOKSA[c["yetki"]],
                                                    ", ".join(str(v) for v in sinandigi_surumler(c["id"], kayit)) or "not tested"))
    for v, s in sorted(kayit["surumler"].items(), key=lambda x: int(x[0])):
        h = s["hesaplar"]
        p += ["", "## PostgreSQL %s verification" % v, "",
              "%s, %s. Catalog digest `%s`." % (s["tam_surum"].split(" on ")[0], s["tarih"], s["katalog_sha256"][:16]), "",
              "Scenario objects were set up in a temporary cluster (an invalid index, an inactive replication slot on the primary and on the standby, "
              "dead rows and a table with autovacuum disabled, a sequence near its limit that the scan account could not read, an unused index over 10 MB, "
              "an idle open transaction, a role with an MD5 password, a database without connect privilege, a public schema with CREATE granted "
              "to PUBLIC, a sort that writes to a temporary file, pg_stat_statements if the package has it). A streaming standby was started with "
              "pg_basebackup and left behind by pausing its replay. The collector was run with three accounts on the primary and with the "
              "pg_monitor account on the standby.", "",
              "| Check | %s |" % " | ".join(HESAP_AD.values()), "|---|---|---|---|---|"]
        for cid in [c["id"] for c in katalog.PG]:
            p.append("| `%s` | %s |" % (cid, " | ".join(_hucre(h[a]["kontroller"][cid]) if cid in h[a]["kontroller"] else "none" for a in HESAP_AD)))
        durumlar = {a: {k["kural"]: k for k in kurallar.incele(json.loads((BELGELER / v / ("%s.json" % a)).read_text(encoding="utf-8"))).kayitlar}
                    for a in HESAP_AD if (BELGELER / v / ("%s.json" % a)).exists()}
        if len(durumlar) == len(HESAP_AD):
            p += ["", "Rule statuses: the same documents were evaluated with today's rule engine (`tests/veri/surum/%s/`)." % v, "",
                  "| Rule | %s |" % " | ".join(HESAP_AD.values()), "|---|---|---|---|---|"]
            for kural in sorted(durumlar["pg_monitor"]):
                p.append("| %s | %s |" % (kural, " | ".join(
                    rapor.M["en"]["durum"][durumlar[a][kural]["durum"]] +
                    (": " + rapor.M["en"]["nedenler"].get(durumlar[a][kural]["neden"], durumlar[a][kural]["neden"]) if durumlar[a][kural]["neden"] else "")
                    for a in HESAP_AD)))
    p += ["", "## Repeating the verification", "",
          "With the directory that holds the `initdb`, `pg_ctl` and `postgres` files of each PostgreSQL version, as a user who is not root:", "",
          "```sh",
          "python3 tarama/surum_dogrula.py --pg-bin /usr/lib/postgresql/18/bin --cikti docs/surum-dogrulama.json --belge-dizini tests/veri/surum",
          "python3 tarama/uret_kurallar.py",
          "```", "",
          "The tool connects only to the temporary cluster it set up itself and deletes it at the end. The result is appended to `docs/surum-dogrulama.json`; "
          "if all the queries ran on that version, the version is added to the `SINANAN` list in `tarama/katalog.py` (`tests/test_surum.py` "
          "checks the evidence).", ""]
    return "\n".join(p)


def main(argv):
    hedefler = [(HEDEF, uret()), (MATRIS, uret_matris())]
    if "--kontrol" in argv:
        eski = [str(h.relative_to(ROOT)) for h, m in hedefler if not h.exists() or h.read_text(encoding="utf-8") != m]
        if eski:
            print("out of date, run: python3 tarama/uret_kurallar.py ->", ", ".join(eski))
            return 1
        return 0
    for h, m in hedefler:
        h.write_text(m, encoding="utf-8")
        print("written", h)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
