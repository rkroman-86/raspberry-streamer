"""Ajoute a la bibliotheque Radio de moOde une station lancee depuis la web UI /ui.

Sans ca, moOde ne connait pas l'URL jouee : ni l'interface moOde ni l'ecran ESP
n'ont de logo (image par defaut). Ici, comme le fait moOde a l'ajout d'une station :
  1. logo telecharge (favicon Radio Browser) et ecrit dans radio-logos/
     (<nom>.jpg, thumbs/<nom>.jpg, thumbs/<nom>_sm.jpg) ;
  2. commande moOde "new_station" (command/radio.php) : base cfg_radio, variable de
     session (logo dans l'interface moOde), fichier RADIO/<nom>.pls, mise a jour MPD.
Station deja presente (meme URL) : rien n'est fait.
"""
import io
import logging
import re
import sqlite3
import threading
import urllib.parse
import urllib.request

log = logging.getLogger("espbridge")

MOODE_DB = "/var/local/www/db/moode-sqlite3.db"
LOGO_DIR = "/var/local/www/imagesw/radio-logos/"
MOODE_URL = "http://127.0.0.1/command/radio.php?cmd=new_station"
UA = "RaspberryStreamer/1.0"
_lock = threading.Lock()


def _db():
    return sqlite3.connect(MOODE_DB, timeout=3)


def known(url):
    try:
        con = _db()
        try:
            return con.execute("select 1 from cfg_radio where station = ?", (url,)).fetchone() is not None
        finally:
            con.close()
    except sqlite3.Error as e:
        log.warning("cfg_radio illisible : %s", e)
        return True                      # dans le doute, on n'ajoute rien


def _name_taken(name):
    con = _db()
    try:
        return con.execute("select 1 from cfg_radio where name = ?", (name,)).fetchone() is not None
    finally:
        con.close()


def clean_name(name):
    """Nom utilisable comme fichier .pls / logo et dans les requetes de moOde."""
    n = re.sub(r"[\\/:*?\"'<>|`$~]", " ", name or "")
    n = re.sub(r"\s+", " ", n).strip()[:60]
    return n or "Web radio"


def _unique(name):
    import os
    base, i = name, 2
    while _name_taken(name) or os.path.exists(f"/var/lib/mpd/music/RADIO/{name}.pls"):
        name = f"{base} {i}"
        i += 1
    return name


def _save_logo(name, favicon):
    """Ecrit les 3 images moOde. Renvoie False si le logo est introuvable ou illisible."""
    if not favicon.startswith(("http://", "https://")):
        return False
    from PIL import Image
    try:
        req = urllib.request.Request(favicon, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = r.read(3_000_000)
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as e:
        log.info("logo station illisible (%s) : %s", favicon, e)
        return False
    im = im.convert("RGBA")
    side = max(im.size)
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 255))   # carre, logo centre sur fond noir
    sq.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
    sq = sq.convert("RGB")
    big = sq.resize((min(side, 600),) * 2, Image.LANCZOS) if side > 600 else sq
    if big.width < 200:
        big = sq.resize((200, 200), Image.LANCZOS)
    big.save(LOGO_DIR + name + ".jpg", quality=90)
    big.save(LOGO_DIR + "thumbs/" + name + ".jpg", quality=85)
    sq.resize((80, 80), Image.LANCZOS).save(LOGO_DIR + "thumbs/" + name + "_sm.jpg", quality=80)
    return True


def _add(st):
    url = (st.get("url") or "").strip()
    if not url.startswith(("http://", "https://")) or known(url):
        return
    name = _unique(clean_name(st.get("name")))
    has_logo = _save_logo(name, (st.get("favicon") or "").strip())
    codec = (st.get("codec") or "").upper()[:8]
    br = st.get("bitrate") or ""
    fields = {"name": name, "url": url, "id": "", "type": "r", "genre": "", "broadcaster": "",
              "language": "", "country": clean_name(st.get("country", ""))[:40] if st.get("country") else "",
              "region": "", "bitrate": str(br), "format": codec, "geo_fenced": "No",
              "home_page": "", "monitor": "No"}
    body = urllib.parse.urlencode({f"path[{k}]": v for k, v in fields.items()}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(MOODE_URL, data=body), timeout=20) as r:
            msg = r.read(300).decode("utf-8", "replace").strip()
    except Exception as e:
        log.warning("moOde new_station : %s", e)
        return
    log.info("station ajoutee a moOde : %s (logo %s) -> %s", name, "oui" if has_logo else "non", msg)


def add_async(st):
    """Ajout en arriere-plan (telechargement du logo + 3 s d'attente cote moOde)."""
    def run():
        with _lock:
            try:
                _add(st)
            except Exception as e:
                log.warning("ajout station moOde : %s", e)
    threading.Thread(target=run, daemon=True).start()
