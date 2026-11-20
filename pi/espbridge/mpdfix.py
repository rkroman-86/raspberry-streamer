# mpdfix.py - reglages MPD a garder malgre moOde
#
# moOde reecrit /etc/mpd.conf a chaque enregistrement de sa page MPD : nos
# ajouts disparaissent. Ce module les remet au demarrage d'espbridge puis
# verifie toutes les CHECK_S secondes ; s'il a du modifier le fichier, il
# redemarre MPD (coupure de lecture d'une seconde environ).
#
# Reglage garde :
#   decodeur mpg123 desactive -> les MP3 passent par FFmpeg. mpg123 veut se
#   deplacer dans le fichier pour l'analyser ; un flux DLNA converti a la volee
#   (Windows "Caster sur un appareil") ne le permet pas : "cannot seek!", MPD
#   abandonne au bout de 2 a 5 s.
#
# Garde-fous MPD (toutes les WATCH_S secondes) :
#   * pause longue d'un flux du reseau local (DLNA, Windows Media Player...) :
#     au bout de LAN_PAUSE_S, la pause devient un stop. Le serveur coupe la
#     connexion d'un flux en pause ; a la reprise, MPD pouvait rester bloque et
#     ne plus repondre a rien (radios, ecran, telephone). La reprise DLNA repart
#     de la position retenue (dlna.resume).
#   * MPD qui ne repond plus (MPD_KO_N essais de suite) : redemarrage de MPD.
import re
import socket
import time
import logging
import threading
import subprocess

log = logging.getLogger("espbridge")

MPD_CONF = "/etc/mpd.conf"
CHECK_S = 60
WATCH_S = 15
LAN_PAUSE_S = 300          # pause d'un flux local plus longue : stop
MPD_KO_N = 2               # essais sans reponse de suite avant redemarrage
LAN_URL = re.compile(r"^https?://(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)")
_watch = {"ko": 0, "pause_since": None, "pause_file": None, "last_restart": -1e9}
BLOCKS = [
    ("mpg123", '\ndecoder {\n  plugin "mpg123"\n  enabled "no"\n}\n'),
]


def _has_disabled(text, plugin):
    for m in re.finditer(r"decoder\s*\{([^}]*)\}", text):
        body = m.group(1)
        if re.search(r'plugin\s+"%s"' % re.escape(plugin), body) and re.search(r'enabled\s+"no"', body):
            return True
    return False


def ensure():
    """Ajoute les blocs manquants ; True si mpd.conf a ete modifie."""
    try:
        with open(MPD_CONF, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        log.warning("mpdfix : lecture de %s impossible : %s", MPD_CONF, e)
        return False
    missing = [blk for name, blk in BLOCKS if not _has_disabled(text, name)]
    if not missing:
        return False
    try:
        with open(MPD_CONF, "a", encoding="utf-8") as f:
            f.write("".join(missing))
    except OSError as e:
        log.warning("mpdfix : ecriture de %s impossible : %s", MPD_CONF, e)
        return False
    log.info("mpdfix : %d reglage(s) remis dans %s, redemarrage de MPD", len(missing), MPD_CONF)
    subprocess.run(["systemctl", "restart", "mpd"], timeout=30)
    return True


def _mpd(cmds, timeout=5):
    """Envoie des commandes MPD ; dict des reponses, None si MPD ne repond pas."""
    try:
        with socket.create_connection(("127.0.0.1", 6600), timeout=timeout) as sk:
            fh = sk.makefile("rwb")
            if not fh.readline().startswith(b"OK MPD"):
                return None
            out = {}
            for c in cmds:
                fh.write((c + "\n").encode())
                fh.flush()
                while True:
                    r = fh.readline().decode("utf-8", "replace").rstrip("\n")
                    if r == "OK":
                        break
                    if not r or r.startswith("ACK"):
                        return None
                    k, _, v = r.partition(": ")
                    out.setdefault(k, v)
            return out
    except OSError:
        return None


def watch():
    """Un passage des garde-fous (pause longue d'un flux local, MPD bloque)."""
    now = time.monotonic()
    st = _mpd(["status", "currentsong"])
    if st is None:
        _watch["ko"] += 1
        log.warning("mpdfix : MPD ne repond pas (%d)", _watch["ko"])
        if _watch["ko"] >= MPD_KO_N and now - _watch["last_restart"] > 60:
            _watch.update(ko=0, last_restart=now, pause_since=None)
            log.warning("mpdfix : MPD bloque, redemarrage")
            subprocess.run(["systemctl", "restart", "mpd"], capture_output=True, timeout=60)
        return
    _watch["ko"] = 0
    f = st.get("file", "")
    if st.get("state") == "pause" and LAN_URL.match(f):
        if _watch["pause_file"] != f or _watch["pause_since"] is None:
            _watch.update(pause_file=f, pause_since=now)
        elif now - _watch["pause_since"] >= LAN_PAUSE_S:
            log.info("mpdfix : pause longue d'un flux local, passage en stop")
            _mpd(["stop"])
            _watch.update(pause_since=None, pause_file=None)
    else:
        _watch.update(pause_since=None, pause_file=None)


def unblock(wait_s=20):
    """MPD ne repond pas (ex. en quittant un flux DLNA en lecture) : redemarrage
    immediat, puis attente qu'il reponde. True si MPD repond (avant ou apres)."""
    if _mpd(["status"], timeout=3) is not None:
        return True
    log.warning("mpdfix : MPD bloque sur une commande, redemarrage immediat")
    _watch.update(ko=0, last_restart=time.monotonic(), pause_since=None)
    try:
        subprocess.run(["systemctl", "restart", "mpd"], capture_output=True, timeout=60)
    except subprocess.SubprocessError as e:
        log.warning("mpdfix : redemarrage de MPD : %s", e)
    end = time.monotonic() + wait_s
    while time.monotonic() < end:
        if _mpd(["status"], timeout=3) is not None:
            return True
        time.sleep(1)
    return False


HEALTH_S = 600              # memoire et charge dans le journal toutes les 10 min
_health = {"at": -1e9}


def health():
    """Une ligne de sante dans le journal : memoire libre, swap, charge, memoire et
    threads du pont, plus gros processus. Sert a voir venir un blocage du Pi."""
    def meminfo():
        d = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                d[k] = int(v.split()[0]) // 1024
        return d
    m = meminfo()
    with open("/proc/loadavg") as f:
        load = f.read().split()[0]
    rss = thr = 0
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1]) // 1024
            elif line.startswith("Threads:"):
                thr = int(line.split()[1])
    try:
        top = subprocess.run(["ps", "-eo", "rss=,comm=", "--sort=-rss"], capture_output=True,
                             text=True, timeout=5).stdout.split("\n")[:3]
        top = ", ".join("%s %dM" % (t.split()[1], int(t.split()[0]) // 1024) for t in top if t.strip())
    except Exception:
        top = "?"
    log.info("sante : dispo %dM, swap %dM utilise, charge %s, pont %dM %d threads | %s",
             m.get("MemAvailable", 0), m.get("SwapTotal", 0) - m.get("SwapFree", 0), load, rss, thr, top)


def _watch_loop():
    while True:
        try:
            watch()
        except Exception:
            log.exception("mpdfix watch")
        if time.monotonic() - _health["at"] >= HEALTH_S:
            _health["at"] = time.monotonic()
            try:
                health()
            except Exception as e:
                log.info("sante : %s", e)
        time.sleep(WATCH_S)


def _loop():
    while True:
        try:
            ensure()
        except Exception:
            log.exception("mpdfix")
        time.sleep(CHECK_S)


def start():
    threading.Thread(target=_loop, daemon=True).start()
    threading.Thread(target=_watch_loop, daemon=True).start()
