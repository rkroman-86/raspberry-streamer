"""Services moOde activables depuis la page Settings de l'ESP : AirPlay, Spotify, Bluetooth.

Etat lu dans la base moOde (cfg_system : airplaysvc, spotifysvc, btsvc).
Changement fait comme la page Renderers de moOde : formulaire envoye a
ren-config.php (session moOde, base et service mis a jour par le worker de moOde),
l'interface moOde montre donc le meme etat.
"""
import logging
import sqlite3
import threading
import time
import urllib.parse
import urllib.request

log = logging.getLogger("espbridge")

MOODE_DB = "/var/local/www/db/moode-sqlite3.db"
REN_CONFIG = "http://127.0.0.1/ren-config.php"
# nom -> (parametre cfg_system, champ "update_..." du formulaire moOde)
SVC = {
    "airplay": ("airplaysvc", "update_airplay_settings"),
    "spotify": ("spotifysvc", "update_spotify_settings"),
    "bluetooth": ("btsvc", "update_bt_settings"),
}
_cache = {"at": 0.0, "val": None}
_lock = threading.Lock()


def _read():
    con = sqlite3.connect(f"file:{MOODE_DB}?mode=ro", uri=True, timeout=1)
    try:
        rows = dict(con.execute(
            "select param, value from cfg_system where param in "
            "('airplaysvc','spotifysvc','btsvc','btname','airplayname','spotifyname')").fetchall())
    finally:
        con.close()
    return rows


def get():
    """{"airplay": 0|1, "spotify": 0|1, "bluetooth": 0|1} (relu au plus toutes les 5 s)."""
    now = time.monotonic()
    if _cache["val"] is not None and now - _cache["at"] < 5:
        return _cache["val"]
    try:
        rows = _read()
        val = {k: 1 if str(rows.get(p)) == "1" else 0 for k, (p, _) in SVC.items()}
    except sqlite3.Error as e:
        log.warning("services : base moOde illisible : %s", e)
        return _cache["val"] or {}
    _cache.update(at=now, val=val)
    return val


def is_on(name):
    return get().get(name, 0) == 1


def set_service(name, on):
    """Active / coupe un service comme la page Renderers de moOde. True si accepte."""
    if name not in SVC:
        return False
    param, update = SVC[name]
    with _lock:
        try:
            rows = _read()
        except sqlite3.Error as e:
            log.warning("services : %s", e)
            return False
        form = {update: "1", param: "1" if on else "0"}
        if name == "bluetooth":                  # moOde renomme le Bluetooth avec ce champ
            form["btname"] = rows.get("btname", "")
        try:
            req = urllib.request.Request(REN_CONFIG, data=urllib.parse.urlencode(form).encode())
            with urllib.request.urlopen(req, timeout=20) as r:
                r.read(200)
        except Exception as e:
            log.warning("services : %s %s : %s", name, "on" if on else "off", e)
            return False
        _cache["at"] = 0.0
        log.info("services : %s %s", name, "active" if on else "coupe")
        return True
