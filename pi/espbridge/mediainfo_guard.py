"""Empeche moOde d'ouvrir une 2e connexion vers un serveur DLNA pendant la lecture.

A l'ouverture de son interface, moOde lance `mediainfo <url>` sur le morceau DLNA
en cours (affichage du format). Le serveur Windows Media Player du PC supporte mal
cette 2e connexion vers le meme fichier : la connexion de lecture de MPD se fige,
STOP ne passe plus, puis tout tombe au bout d'une minute environ.

On installe /usr/local/bin/mediainfo (avant /usr/bin dans le PATH de moOde) :
pour une adresse http du reseau local, reponse immediate (16 bits, 44.1 kHz,
2 canaux) sans connexion ; pour tout le reste, le vrai /usr/bin/mediainfo.
"""
import logging
import os

log = logging.getLogger("espbridge")

PATH = "/usr/local/bin/mediainfo"
SCRIPT = r'''#!/bin/sh
# espbridge (mediainfo_guard.py) : pas de 2e connexion vers un serveur DLNA local
for a in "$@"; do
  case "$a" in
    http://192.168.*|http://10.*|http://172.1[6-9].*|http://172.2[0-9].*|http://172.3[01].*)
      case "$*" in
        *--Output=JSON*) echo '{"media":{"track":[]}}' ;;
        *) printf '16\n44100\n2\nMPEG Audio\n\nLossy\n' ;;
      esac
      exit 0 ;;
  esac
done
exec /usr/bin/mediainfo "$@"
'''


def ensure():
    """Installe ou remet le script si absent ou different."""
    try:
        try:
            with open(PATH, encoding="utf-8") as f:
                if f.read() == SCRIPT:
                    return
        except OSError:
            pass
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(SCRIPT)
        os.chmod(PATH, 0o755)
        log.info("mediainfo_guard : %s installe", PATH)
    except OSError as e:
        log.warning("mediainfo_guard : %s", e)
