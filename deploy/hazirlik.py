#!/usr/bin/env python3
"""Canliya alma hazirlik denetimi. Yalnizca standart kutuphane. Hicbir seyi degistirmez.

  python3 deploy/hazirlik.py yerel     # bu makinede yapilabilen sozdizimi/yapilandirma denetimleri
  python3 deploy/hazirlik.py sunucu    # GERCEK sunucuda, dagitimdan sonra: kullanicilar, izinler, disk, servisler

Her satirin durumu: PASS, FAIL, WARN, ATLANDI (arac yok ya da bu makinede anlamsiz). Kuru calistirma ve gercek
dagitim kaniti yerel makineden uretilemez; docs/canli-kontrol-listesi.md bunlari NOT_TESTED olarak tutar.
Sir degerleri asla yazdirilmaz.
"""
import argparse
import json
import os
import pwd
import grp
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
ANSIBLE = KOK / "deploy" / "ansible"
DISK_UYARI, DISK_HATA = 0.20, 0.10  # bos alan orani


def yukle_degiskenler():
    """group_vars/all.yml (duz anahtar: deger satirlari) -> dict. PyYAML gerekmez."""
    d = {}
    for satir in (ANSIBLE / "group_vars" / "all.yml").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*?)\s*(#.*)?$", satir)
        if m and m.group(2) not in ("",) and not m.group(2).startswith(("[", "{")):
            v = m.group(2).strip("\"'")
            d[m.group(1)] = int(v) if v.isdigit() else {"true": True, "false": False}.get(v, v)
        elif m and m.group(2) == "[]":
            d[m.group(1)] = []
    return d


# ---------------------------------------------------------------- yerel (sozdizimi, yapilandirma)

def _calistir(komut, **kw):
    return subprocess.run(komut, capture_output=True, text=True, timeout=120, **kw)


def yerel():
    sonuc = []
    ekle = lambda ad, durum, ayrinti="": sonuc.append((ad, durum, ayrinti))  # noqa: E731
    ap = shutil.which("ansible-playbook")
    for oyun in ("site.yml", "yayin.yml", "geri-al.yml"):
        ad = f"SOZDIZIMI ansible-playbook --syntax-check {oyun}"
        if not ap:
            ekle(ad, "ATLANDI", "ansible-playbook yok")
            continue
        gec = Path(tempfile.mkdtemp())
        (gec / "inv.ini").write_text("[alig]\nlocalhost ansible_connection=local\n")
        r = _calistir([ap, "-i", str(gec / "inv.ini"), "--syntax-check", str(ANSIBLE / oyun)], cwd=str(ANSIBLE))
        metin = r.stdout + r.stderr
        if r.returncode != 0 and re.search(r"couldn't resolve module/action|incorrect module path", metin):
            ekle(ad, "ATLANDI", "koleksiyon yuklu degil: ansible-galaxy collection install -r deploy/ansible/requirements.yml")
            continue
        ekle(ad, "PASS" if r.returncode == 0 else "FAIL", "" if r.returncode == 0 else metin.strip()[-300:])
    sa = shutil.which("systemd-analyze")
    if sa and ap:
        for ad, durum, ayrinti in _birimleri_dogrula(ap, sa):
            ekle(ad, durum, ayrinti)
    else:
        ekle("SOZDIZIMI systemd-analyze verify", "ATLANDI", "systemd-analyze ya da ansible-playbook yok")
    for ad, durum in (("KURU CALISTIRMA ansible-playbook site.yml --check --diff", "NOT_TESTED"),
                      ("GERCEK DAGITIM ansible-playbook site.yml", "NOT_TESTED"),
                      ("GERCEK DAGITIM deploy/hazirlik.py sunucu", "NOT_TESTED")):
        ekle(ad, durum, "gercek sunucu gerekir")
    return sonuc


def _birimleri_dogrula(ap, sa):
    """Birim sablonlarini Ansible'in kendisiyle (projeye Jinja bagimliligi eklemeden) isler ve systemd-analyze ile denetler.
    Kosullu bloklar da denetlensin diye dogrudan_baglanti ve eposta_dogrulama acik verilir."""
    sablonlar = sorted((ANSIBLE / "roles" / "servisler" / "templates").glob("*.service.j2"))
    gec = Path(tempfile.mkdtemp())
    oyun = gec / "birimler.yml"
    oyun.write_text(
        "- hosts: localhost\n  connection: local\n  gather_facts: false\n"
        "  vars_files: [%s]\n  tasks:\n    - name: Birimleri isle\n      ansible.builtin.template:\n"
        "        src: \"{{ item }}\"\n        dest: \"%s/{{ item | basename | regex_replace('\\\\.j2$', '') }}\"\n        mode: \"0644\"\n"
        "      loop: %s\n" % (json.dumps(str(ANSIBLE / "group_vars" / "all.yml")), gec, json.dumps([str(x) for x in sablonlar])),
        encoding="utf-8")
    r = _calistir([ap, "-i", "localhost,", str(oyun), "-e", json.dumps({"dogrudan_baglanti": True, "eposta_dogrulama": True})],
                  env=dict(os.environ, ANSIBLE_LOCALHOST_WARNING="False", ANSIBLE_NOCOLOR="1"))
    if r.returncode != 0:
        return [("SOZDIZIMI birim sablonlari islenir", "FAIL", (r.stdout + r.stderr).strip()[-300:])]
    # Hedef makinede olan ama bu makinede olmayan yurutulebilir dosya ve kullanici uyarilari beklenir.
    gurultu = re.compile(r"(Command .* is not executable|No such file|Failed to resolve (user|group)|Unknown (user|group)|not found)", re.I)
    sonuc = []
    for sb in sablonlar:
        birim = gec / sb.name[:-3]
        r = _calistir([sa, "verify", str(birim)])
        gercek = [x for x in (r.stdout + r.stderr).splitlines() if x.strip() and not gurultu.search(x)]
        sonuc.append((f"SOZDIZIMI systemd-analyze verify {birim.name}", "FAIL" if gercek else "PASS", " | ".join(gercek)[:300]))
    return sonuc


# ---------------------------------------------------------------- sunucu (dagitimdan sonra)

def _mod(yol):
    return os.stat(yol).st_mode & 0o7777


def _sahip(yol):
    st = os.stat(yol)
    try:
        u = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        u = str(st.st_uid)
    try:
        g = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        g = str(st.st_gid)
    return u, g


def disk_durumu(yol, kullanilan=shutil.disk_usage):
    """(PASS|WARN|FAIL, 'bos alan %x') yol'un bulundugu diskte."""
    d = kullanilan(yol)
    oran = d.free / d.total if d.total else 0.0
    durum = "FAIL" if oran < DISK_HATA else "WARN" if oran < DISK_UYARI else "PASS"
    return durum, "bos %.0f%% (%d MB)" % (oran * 100, d.free // (1 << 20))


def sunucu(v=None, kok="/", servis_kontrol=True, disk=shutil.disk_usage):
    """Dagitilmis sunucuyu denetler. kok: sinama icin onek (gercekte '/'). Doner: [(ad, durum, ayrinti)]."""
    v = v or yukle_degiskenler()
    yol = lambda p: Path(kok) / str(p).lstrip("/")  # noqa: E731
    sonuc = []
    ekle = lambda ad, durum, ayrinti="": sonuc.append((ad, durum, ayrinti))  # noqa: E731
    servis = v["servis_kullanici"]
    try:
        pw = pwd.getpwnam(servis)
        ekle(f"kullanici {servis} var", "PASS")
        ekle(f"kullanici {servis} oturum acamaz", "PASS" if pw.pw_shell.endswith(("nologin", "false")) else "FAIL", pw.pw_shell)
    except KeyError:
        ekle(f"kullanici {servis} var", "FAIL", "yok")
    if v.get("dogrudan_baglanti"):
        try:
            pwd.getpwnam(v["calistirici_kullanici"])
            ekle("kullanici %s var" % v["calistirici_kullanici"], "PASS")
        except KeyError:
            ekle("kullanici %s var" % v["calistirici_kullanici"], "FAIL", "yok")
    else:
        ekle("Kip B kapali: calistirici kullanicisi beklenmez", "PASS")

    # (yol, beklenen mod, beklenen sahip:grup ya da None, aciklama)
    beklenen = [("/etc/alig", 0o750, ("root", servis)), ("/etc/alig/env", 0o640, ("root", servis)),
                (v["veri_dizini"], 0o750, (servis, servis)), (v["yedek_dizini"], 0o700, (servis, servis))]
    for p, mod, sahip in beklenen:
        y = yol(p)
        if not y.exists():
            ekle(f"{p} izinleri", "FAIL", "yok")
            continue
        m, s = _mod(y), _sahip(y)
        iyi = m == mod and (kok != "/" or s == sahip)
        ekle(f"{p} izinleri {oct(mod)[2:]} {sahip[0]}:{sahip[1]}", "PASS" if iyi else "FAIL", f"{oct(m)[2:]} {s[0]}:{s[1]}")
    env = yol("/etc/alig/env")
    if env.exists():
        icerik = env.read_text(encoding="utf-8", errors="replace")
        for anahtar, min_uzunluk in (("ALIG_FORM_SALT", 32), ("ALIG_DENETIM_ANAHTARI", 32)):
            m = re.search(rf"^{anahtar}=(.*)$", icerik, re.M)
            ekle(f"/etc/alig/env {anahtar} tanimli ve >= {min_uzunluk} karakter", "PASS" if m and len(m.group(1)) >= min_uzunluk else "FAIL",
                 "" if m else "yok")  # deger asla yazdirilmaz
    if v.get("eposta_dogrulama") and env.exists():
        var = re.search(r"^ALIG_SMTP_PAROLA=.+$", env.read_text(encoding="utf-8", errors="replace"), re.M) is not None
        ekle("/etc/alig/env ALIG_SMTP_PAROLA tanimli (e-posta dogrulamasi acik)", "PASS" if var or not v.get("smtp_kullanici") else "FAIL",
             "" if var else "yok")
    for dizin, ad in ((v["veri_dizini"], "veri"), (v["yedek_dizini"], "yedek")):
        y = yol(dizin)
        for f in sorted(y.glob("*.sqlite")) if y.exists() else []:
            acik = _mod(f) & 0o077
            ekle(f"{ad} dosyasi yalniz sahibine acik: {f.name}", "FAIL" if acik else "PASS", oct(_mod(f))[2:])
    for dizin, ad in ((v["veri_dizini"], "veri"), (v["yedek_dizini"], "yedek")):
        y = yol(dizin)
        if y.exists():
            durum, a = disk_durumu(str(y), disk)
            ekle(f"disk doluluk ({ad}: {dizin})", durum, a)
    if servis_kontrol and shutil.which("systemctl") and _calistir(["systemctl", "is-system-running"]).stdout.strip() in ("running", "degraded", "starting"):
        birimler = (["alig-form", "alig-tarama", "alig-yonetim", "nginx"] + (["alig-calistirici"] if v.get("dogrudan_baglanti") else [])
                    + (["alig-posta"] if v.get("eposta_dogrulama") else []))
        for b in birimler:
            r = _calistir(["systemctl", "is-active", b])
            ekle(f"servis {b} calisiyor", "PASS" if r.stdout.strip() == "active" else "FAIL", r.stdout.strip() or r.stderr.strip())
        for zb in ("alig-bakim.timer", "alig-izleme.timer"):
            r = _calistir(["systemctl", "is-active", zb])
            ekle(f"zamanlayici {zb} etkin", "PASS" if r.stdout.strip() == "active" else "FAIL", r.stdout.strip())
        ss = shutil.which("ss")
        if ss:
            cikti = _calistir([ss, "-ltnH"]).stdout
            for ad, port in (("form", v["form_portu"]), ("tarama", v["tarama_portu"]), ("yonetim", v["yonetim_portu"])):
                adresler = re.findall(r"(\S+):%d\s" % port, cikti)
                disa = [a for a in adresler if a not in ("127.0.0.1", "[::1]")]
                ekle(f"{ad} yalniz 127.0.0.1 dinliyor (:{port})", "FAIL" if disa or not adresler else "PASS", ",".join(adresler) or "dinlemiyor")
    else:
        ekle("servis ve port denetimi", "ATLANDI", "systemd calismiyor ya da denetim kapatildi")
    return sonuc


def yazdir(sonuc, cikti=print):
    for ad, durum, ayrinti in sonuc:
        cikti("%-10s %s%s" % (durum, ad, f"  [{ayrinti}]" if ayrinti else ""))
    fail = sum(1 for _, d, _ in sonuc if d == "FAIL")
    warn = sum(1 for _, d, _ in sonuc if d == "WARN")
    cikti("\nOZET: %d satir, %d FAIL, %d WARN" % (len(sonuc), fail, warn))
    return 1 if fail else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mod", choices=("yerel", "sunucu"))
    a = ap.parse_args(argv)
    return yazdir(yerel() if a.mod == "yerel" else sunucu())


if __name__ == "__main__":
    sys.exit(main())
