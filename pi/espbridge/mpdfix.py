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
import re
import time
import logging
import threading
import subprocess

log = logging.getLogger("espbridge")

MPD_CONF = "/etc/mpd.conf"
CHECK_S = 60
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


def _loop():
    while True:
        try:
            ensure()
        except Exception:
            log.exception("mpdfix")
        time.sleep(CHECK_S)


def start():
    threading.Thread(target=_loop, daemon=True).start()
