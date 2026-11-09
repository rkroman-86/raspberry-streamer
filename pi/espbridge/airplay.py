"""AirPlay : reglages gardes dans shairport-sync.conf + volume synchronise avec l'ecran.

En AirPlay, le volume appartient a l'appareil source (iPad...) : MPD ne le connait
pas, la barre de l'ecran ne faisait rien (meme histoire que le Bluetooth).

  * Lecture : shairport-sync envoie aussi ses metadonnees en UDP (127.0.0.1:5556),
    en plus du tuyau lu par moOde. On y lit le volume AirPlay ('pvol', -30..0 dB,
    -144 = muet) et ce qu'il faut pour piloter la source : DACP-ID, Active-Remote,
    adresse et port DACP de l'appareil.
  * Reglage : commande DACP envoyee a l'appareil source
    (/ctrl-int/1/setproperty?dmcp.device-volume=<dB>), comme le fait shairport-sync.
    L'appareil change son volume et le renvoie : ecran, moOde et source restent d'accord.

Reglages gardes dans /etc/shairport-sync.conf (verifies toutes les 60 s) :
  * service_type : AirPlay 2 ("auto", defaut de moOde) ou AirPlay 1 ("classic"), au choix
    dans la page Settings de l'ESP (commande AIRPLAY 1|2). Les vieux appareils (iPad
    sous iOS 13) n'ouvrent pas le canal audio en AirPlay 2 : titre et pochette, pas de son.
    Choix garde dans /var/lib/espbridge/airplay.json.
  * metadonnees UDP vers 127.0.0.1:5556 (voir plus haut).
Si le fichier change tout seul (moOde), AirPlay est relance hors lecture ; un changement
demande depuis la page Settings est applique tout de suite.
"""
import json
import logging
import os
import re
import socket
import subprocess
import threading
import time
import urllib.request

log = logging.getLogger("espbridge")

CONF = "/etc/shairport-sync.conf"
SETTINGS = "/var/lib/espbridge/airplay.json"
DEFAULT_VERSION = 2
PORT = 5556
CHECK_S = 60
SOCKET_LINES = ('\tsocket_address = "127.0.0.1"; // espbridge : volume AirPlay\n'
                '\tsocket_port = %d;\n'
                '\tsocket_msglength = 65000;\n' % PORT)

_st = {"vol": None, "daid": "", "acre": "", "clip": "", "dapo": "", "at": 0.0}
_lock = threading.Lock()
_pending_restart = [False]
_conf_lock = threading.Lock()


def _load_version():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            v = json.load(f).get("version")
        return v if v in (1, 2) else DEFAULT_VERSION
    except (OSError, ValueError, AttributeError):
        return DEFAULT_VERSION


_version = [_load_version()]


def get_version():
    """AirPlay 1 ou 2 (choix de la page Settings)."""
    return _version[0]


# --- reglages de shairport-sync.conf -------------------------------------------------
def _fix_conf(text, version=None):
    """Texte corrige (ou identique)."""
    st = "classic" if (version or _version[0]) == 1 else "auto"
    t = re.sub(r'^(\s*)service_type\s*=\s*"(auto|airplay2|classic)"', r'\1service_type = "%s"' % st,
               text, count=1, flags=re.M)
    if not re.search(r'^\s*socket_address\s*=', t, re.M):
        m = re.search(r'^metadata\s*=\s*\n?\s*\{[^\n]*\n', t, re.M)
        if m:
            t = t[:m.end()] + SOCKET_LINES + t[m.end():]
    return t


def ensure_conf(active, now=False):
    """Corrige le fichier ; relance AirPlay par moOde si besoin et si rien ne joue en AirPlay
    (now=True : relance meme en lecture, changement demande par l'utilisateur)."""
    with _conf_lock:
        _ensure_conf(active, now)


def _ensure_conf(active, now):
    try:
        with open(CONF, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        log.warning("airplay : lecture de %s impossible : %s", CONF, e)
        return
    new = _fix_conf(text)
    if new != text:
        try:
            with open(CONF, "w", encoding="utf-8") as f:
                f.write(new)
        except OSError as e:
            log.warning("airplay : ecriture de %s impossible : %s", CONF, e)
            return
        log.info("airplay : shairport-sync.conf corrige (AirPlay 1, metadonnees UDP)")
        _pending_restart[0] = True
    if _pending_restart[0] and (now or active() != "airplay"):
        _pending_restart[0] = False
        log.info("airplay : relance du recepteur AirPlay (AirPlay %d)", _version[0])
        if _version[0] == 2:                     # AirPlay 2 : horloge commune nqptp
            subprocess.run(["systemctl", "start", "nqptp"], capture_output=True, timeout=20)
        try:
            subprocess.run(["moodeutl", "-R", "--airplay"], capture_output=True, timeout=30)
        except subprocess.SubprocessError as e:
            log.warning("moodeutl -R --airplay : %s", e)


def set_version(v, active):
    """Choix AirPlay 1/2 depuis la page Settings : enregistre et applique tout de suite."""
    if v not in (1, 2):
        return False
    _version[0] = v
    try:
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump({"version": v}, f)
    except OSError as e:
        log.warning("airplay : %s : %s", SETTINGS, e)
    log.info("airplay : AirPlay %d choisi", v)
    ensure_conf(active, now=True)
    return True


# --- metadonnees UDP --------------------------------------------------------------
def _on_item(code, data):
    txt = data.decode("utf-8", "replace").strip("\x00").strip()
    with _lock:
        if code == "pvol":                       # "airplay,volume,bas,haut" en dB
            try:
                av = float(txt.split(",")[0])
            except ValueError:
                return
            _st["vol"] = 0 if av <= -30 else max(0, min(100, round((av + 30) * 100 / 30)))
        elif code in ("daid", "acre", "clip", "dapo"):
            _st[code] = txt
            if code == "daid":
                _st["dapo"] = ""                 # autre source : port a retrouver
        elif code == "pend":                     # fin de session
            _st.update(vol=None, acre="", dapo="")
        _st["at"] = time.time()


def _listen():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", PORT))
            while True:
                pkt, _ = s.recvfrom(70000)
                if len(pkt) >= 8 and pkt[:4] in (b"ssnc", b"core") and pkt[4:8] != b"chnk":
                    _on_item(pkt[4:8].decode("latin-1"), pkt[8:])
        except Exception as e:
            log.warning("airplay : ecoute UDP : %s", e)
            time.sleep(10)


def _loop(active):
    while True:
        try:
            ensure_conf(active)
        except Exception:
            log.exception("airplay")
        time.sleep(CHECK_S)


def start(active):
    """active() -> renderer actif ('airplay', 'bluetooth'...) ou None."""
    threading.Thread(target=_listen, daemon=True).start()
    threading.Thread(target=_loop, args=(active,), daemon=True).start()


# --- volume ----------------------------------------------------------------------
def get_volume():
    """Volume AirPlay 0..100, ou None si inconnu."""
    with _lock:
        return _st["vol"]


def _dacp_port(daid):
    """Port DACP de la source via mDNS (si shairport-sync ne l'a pas donne)."""
    try:
        out = subprocess.run(["avahi-browse", "-rpt", "_dacp._tcp"], capture_output=True,
                             text=True, timeout=4).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""
    for line in out.splitlines():
        f = line.split(";")
        if len(f) > 8 and f[0] == "=" and f[3].upper() == ("iTunes_Ctrl_" + daid).upper():
            return f[8]
    return ""


def set_volume(v):
    """Envoie le volume (0..100) a l'appareil source. True si accepte."""
    with _lock:
        daid, acre, clip, dapo = _st["daid"], _st["acre"], _st["clip"], _st["dapo"]
    if not (acre and clip and daid):
        log.info("airplay : volume impossible, source inconnue")
        return False
    if not dapo:
        dapo = _dacp_port(daid)
        with _lock:
            _st["dapo"] = dapo
    if not dapo:
        log.info("airplay : port DACP de la source introuvable")
        return False
    db = -144.0 if v <= 0 else -30.0 + 30.0 * v / 100
    host = "[%s]" % clip if ":" in clip else clip
    url = "http://%s:%s/ctrl-int/1/setproperty?dmcp.device-volume=%.6f" % (host, dapo, db)
    try:
        req = urllib.request.Request(url, headers={"Active-Remote": acre})
        with urllib.request.urlopen(req, timeout=3) as r:
            ok = r.status in (200, 204)
    except Exception as e:
        log.info("airplay : DACP volume : %s", e)
        with _lock:
            _st["dapo"] = ""                     # le port a peut-etre change
        return False
    if ok:
        with _lock:
            _st["vol"] = max(0, min(100, int(v)))
    return ok
