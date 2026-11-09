#!/usr/bin/env python3
"""
espbridge — pont UART Raspberry Pi <-> ESP32-S3 (moOde / MPD)

Pi -> ESP (spontané)
  READY                 le système est démarré
  WIFI_OK <ssid>        Wi-Fi connecté (associé + IPv4)
  WIFI_NONE             pas de Wi-Fi
  STATUS {json}         envoyé à chaque changement de lecture/source/volume

ESP -> Pi (commande -> réponse)
  PING                  -> PONG
  SYNC                  -> READY + WIFI_OK/WIFI_NONE + STATUS
  PLAY <url>            -> OK PLAY    | ERR PLAY
  PLAY                  -> OK RESUME  | ERR PLAY
  STATION <json>        -> (pas de reponse) station de /ui ajoutee a la bibliotheque moOde
  AIRPLAY 1|2           -> OK AIRPLAY n : recepteur AirPlay 1 (vieux appareils) ou 2
  STOP                  -> OK STOP
  PAUSE                 -> OK PAUSE
  VOL <0-100>           -> OK VOL <n> | ERR VOL
  STATUS                -> STATUS {json}
  autre                 -> ERR UNKNOWN

STATUS json : state (play/pause/stop), source (webradio, dlna, library,
airplay, spotify, bluetooth, squeezelite, roon, plexamp, qobuz, input,
multiroom, none), title, artist, album, station, vol, mute, cover (URL),
format, elapsed, duration
"""
import hashlib
import io
import json
import os
import urllib.parse
import urllib.request
import logging
import re
import sqlite3
import subprocess
import threading
import time

import serial
from autoresume import on_wifi, on_command
from bootgauge import uptime, boot_expected, boot_save, BOOT_POLL
import mpdfix
import dlna
import moode_radio
import airplay

PORT = "/dev/serial0"
BAUD = 115200
IFACE = "wlan0"
BOOT_WIFI_TIMEOUT = 30     # s : délai laissé au Wi-Fi avant d'annoncer WIFI_NONE
WIFI_POLL = 2              # s
STATUS_POLL = 1            # s
READY_FLAG = "/run/moode-ready"   # cree par ready-script.sh de moOde
READY_TIMEOUT = 120        # s : sans signal de moOde, READY envoye quand meme

CURRENTSONG = "/var/local/www/currentsong.txt"   # nécessite "LCD updater" activé
MOODE_DB = "/var/local/www/db/moode-sqlite3.db"
THUMB_SIZE = 200           # px, côté max de la miniature pour l'ESP
THUMB_KEEP = 100           # nombre de miniatures gardées en cache
THUMB_DIR = "/var/local/www/imagesw/esp-thumbs"
THUMB_URL_PATH = "imagesw/esp-thumbs/"

RENDERERS = [("aplactive", "airplay"), ("spotactive", "spotify"),
             ("btactive", "bluetooth"), ("slactive", "squeezelite"),
             ("rbactive", "roon"), ("paactive", "plexamp"),
             ("qbzactive", "qobuz"), ("inpactive", "input"),
             ("rxactive", "multiroom")]
PRIVATE_URL = re.compile(r"^https?://(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)")

log = logging.getLogger("espbridge")


# ---------- outils système ----------

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout


def wifi_state():
    """(ssid, ip) si wlan0 est associé ET a une IPv4, sinon (None, None)."""
    try:
        m = re.search(r"^\s*SSID: (.+)$", run(["iw", "dev", IFACE, "link"]), re.M)
        a = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", run(["ip", "-4", "-o", "addr", "show", IFACE]))
        if m and a:
            return m.group(1), a.group(1)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        log.warning("lecture Wi-Fi impossible : %s", e)
    return None, None


def mpc(*args):
    """Exécute mpc ; renvoie la sortie, ou None en cas d'échec."""
    try:
        r = subprocess.run(["mpc", *args], capture_output=True, text=True, timeout=10)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        log.warning("mpc %s : %s", " ".join(args), e)
        return None
    if r.returncode != 0:
        log.warning("mpc %s : %s", " ".join(args), r.stderr.strip())
        return None
    return r.stdout.strip()


# ---------- état moOde ----------

def read_currentsong():
    d = {}
    try:
        with open(CURRENTSONG, encoding="utf-8", errors="replace") as f:
            for line in f:
                k, sep, v = line.rstrip("\n").partition("=")
                if sep:
                    d[k] = v
    except OSError:
        pass
    return d


def active_renderer():
    try:
        con = sqlite3.connect(f"file:{MOODE_DB}?mode=ro", uri=True, timeout=1)
        try:
            rows = dict(con.execute(
                "select param, value from cfg_system where param like '%active'").fetchall())
        finally:
            con.close()
    except sqlite3.Error as e:
        log.warning("base moOde illisible : %s", e)
        return None
    for param, name in RENDERERS:
        if str(rows.get(param)) == "1":
            return name
    return None


def num(s):
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return 0


def make_thumb(cover, ip):
    """Miniature JPEG baseline THUMB_SIZE px de la pochette, servie par moOde. Cache sur disque."""
    if not cover.startswith("http") or not ip:
        return cover
    name = hashlib.md5(cover.encode()).hexdigest() + ".jpg"
    path = os.path.join(THUMB_DIR, name)
    url = f"http://{ip}/{THUMB_URL_PATH}{name}"
    if os.path.exists(path):
        return url
    try:
        from PIL import Image
        with urllib.request.urlopen(cover, timeout=5) as r:
            img = Image.open(io.BytesIO(r.read())).convert("RGB")
        img.thumbnail((THUMB_SIZE, THUMB_SIZE))
        os.makedirs(THUMB_DIR, exist_ok=True)
        tmp = path + ".tmp"
        img.save(tmp, "JPEG", quality=85)          # baseline, pas progressif
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
        files = sorted((os.path.join(THUMB_DIR, f) for f in os.listdir(THUMB_DIR)),
                       key=os.path.getmtime)
        for f in files[:-THUMB_KEEP]:              # on garde les plus récentes
            os.remove(f)
        return url
    except Exception as e:
        log.warning("miniature impossible pour %s : %s", cover, e)
        return cover


def build_status(ip):
    cs = read_currentsong()
    src = active_renderer()
    f = cs.get("file", "")
    if not src:
        if PRIVATE_URL.match(f):
            src = "dlna"
        elif f.startswith(("http://", "https://")) or cs.get("artist") == "Radio station":
            src = "webradio"
        elif f:
            src = "library"
        else:
            src = "none"

    cover = cs.get("coverurl", "")
    if cover and not cover.startswith("http") and ip:
        path = urllib.parse.unquote(cover).lstrip("/")
        cover = f"http://{ip}/{urllib.parse.quote(path, safe='/')}"

    thumb = make_thumb(cover, ip)

    renderer = src not in ("webradio", "dlna", "library", "none")
    radio = src == "webradio"
    return {
        "state": "play" if renderer else cs.get("state", "stop"),
        "source": src,
        "title": cs.get("title", ""),
        "artist": "" if radio else cs.get("artist", ""),
        "album": "" if radio else cs.get("album", ""),
        "station": cs.get("album", "") if radio else "",
        "vol": None if renderer else num(cs.get("volume")),
        "mute": cs.get("mute") == "1",
        "cover": cover,
        "thumb": thumb,
        "format": cs.get("outrate", ""),
        "elapsed": num(cs.get("elapsed")),
        "duration": num(cs.get("duration")),
    }


RESTART_ARG = {"airplay": "--airplay", "spotify": "--spotify", "bluetooth": "--bluetooth",
               "roon": "--roonbridge", "plexamp": "--plexamp"}


def release_renderer():
    """Déconnecte le renderer actif (AirPlay, Spotify...) pour rendre la sortie à MPD."""
    r = active_renderer()
    if r not in RESTART_ARG:
        return True
    log.info("déconnexion du renderer %s", r)
    try:
        subprocess.run(["moodeutl", "-R", RESTART_ARG[r]], capture_output=True, timeout=20)
    except subprocess.SubprocessError as e:
        log.warning("moodeutl -R : %s", e)
    for _ in range(20):
        time.sleep(0.5)
        if active_renderer() is None:
            return True
    log.warning("le renderer %s est toujours actif", r)
    return False


RENDERER_LABEL = {"airplay": "AirPlay", "spotify": "Spotify", "bluetooth": "Bluetooth",
                  "squeezelite": "Squeezelite", "roon": "Roon", "plexamp": "Plexamp",
                  "qobuz": "Qobuz", "input": "Entree", "multiroom": "Multiroom"}

APLMETA = "/var/local/www/aplmeta.json"


def airplay_meta(ip):
    """Metadonnees AirPlay ecrites par moOde (titre, artiste, pochette...)."""
    try:
        with open(APLMETA, encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        return None
    ip = ip or wifi_state()[1]
    cover = m.get("cover_url", "")
    if cover and not cover.startswith("http") and ip:
        cover = f"http://{ip}/{cover.lstrip('/')}"
    thumb = ""
    if cover:
        try:
            thumb = make_thumb_png(cover, ip)
        except Exception as e:
            log.warning("vignette AirPlay : %s", e)
    return {"title": m.get("title", ""), "artist": m.get("artist", ""),
            "album": m.get("album", ""), "station": "AirPlay",
            "cover": cover, "thumb": thumb, "format": m.get("sformat", ""),
            "elapsed": 0, "duration": num(m.get("duration", 0)) // 1000,
            "state": "pause" if m.get("playstate") == "Pause" else "play"}


THUMB_DIR = "/var/local/www/imagesw/esp-thumbs"
THUMB_PX = 200
_thumb_fail = set()


def make_thumb_png(cover, ip):
    """Vignette PNG THUMB_PX x THUMB_PX pour l'ESP (son LVGL ne decode pas le JPEG).
    Mise en cache par URL : l'image n'est generee qu'une fois."""
    import hashlib, io, os, urllib.request
    from PIL import Image, ImageOps
    if not cover or cover in _thumb_fail:
        return ""
    name = hashlib.md5(f"{cover}|{THUMB_PX}".encode()).hexdigest() + ".png"
    dest = os.path.join(THUMB_DIR, name)
    if not os.path.exists(dest):
        host_of = urllib.parse.urlparse(cover).hostname or ""
        own = host_of in ("127.0.0.1", "localhost", ip or "", wifi_state()[1] or "")
        local = re.sub(r"^https?://[^/]+", "http://127.0.0.1", cover) if own else cover
        try:
            with urllib.request.urlopen(local, timeout=3) as r:
                data = r.read()
            im = Image.open(io.BytesIO(data)).convert("RGB")
            im = ImageOps.fit(im, (THUMB_PX, THUMB_PX), Image.LANCZOS)
            os.makedirs(THUMB_DIR, exist_ok=True)
            tmp = dest + ".tmp"
            im.save(tmp, "PNG", optimize=True)
            os.replace(tmp, dest)
        except Exception as e:
            _thumb_fail.add(cover)          # pas de nouvel essai a chaque seconde
            log.warning("vignette PNG impossible (%s) : %s", cover, e)
            return ""
    host = ip or wifi_state()[1]
    return f"http://{host}/imagesw/esp-thumbs/{name}"


def mpd_query(*cmds):
    """Interroge MPD directement (127.0.0.1:6600) ; renvoie un dict ou None."""
    import socket
    out = {}
    try:
        with socket.create_connection(("127.0.0.1", 6600), timeout=2) as sk:
            fh = sk.makefile("rwb")
            fh.readline()                               # "OK MPD x.y.z"
            for c in cmds:
                fh.write((c + "\n").encode())
                fh.flush()
                while True:
                    line = fh.readline().decode("utf-8", "replace").rstrip("\n")
                    if not line or line == "OK" or line.startswith("ACK"):
                        break
                    key, _, val = line.partition(": ")
                    out.setdefault(key, val)
    except OSError as e:
        log.warning("MPD injoignable : %s", e)
        return None
    return out


def radio_name(url):
    """Nom de la station dans la base moOde (cfg_radio), sinon None."""
    try:
        con = sqlite3.connect(f"file:{MOODE_DB}?mode=ro", uri=True, timeout=1)
        try:
            row = con.execute("select name from cfg_radio where station = ?", (url,)).fetchone()
        finally:
            con.close()
        return row[0] if row else None
    except sqlite3.Error as e:
        log.warning("cfg_radio illisible : %s", e)
        return None


def mpd_fields(ip):
    """Champs STATUS lus dans MPD (remplace currentsong.txt, fige sans interface web)."""
    import os
    from urllib.parse import quote
    m = mpd_query("status", "currentsong")
    if m is None:
        return {}
    ip = ip or wifi_state()[1]
    state = m.get("state", "stop")
    f = m.get("file", "")
    if not f:
        src = "none"
    elif PRIVATE_URL.match(f):
        src = "dlna"
    elif f.startswith(("http://", "https://")):
        src = "webradio"
    else:
        src = "library"

    d = {"state": state, "source": src, "file": f,
         "title": m.get("Title", ""), "artist": m.get("Artist", ""),
         "album": m.get("Album", ""), "station": "",
         "elapsed": num(m.get("elapsed")), "duration": num(m.get("duration"))}

    vol = num(m.get("volume", "-1"))
    d["vol"] = vol if vol >= 0 else None

    fmt = ""
    audio = m.get("audio", "")                      # ex. "44100:24:2"
    if audio.count(":") == 2:
        rate, bits, ch = audio.split(":")
        fmt = f"{bits}/{num(rate) / 1000:g} kHz, {ch}ch"
    if src == "webradio" and m.get("bitrate"):
        fmt = f"{m['bitrate']} kbps, " + fmt if fmt else f"{m['bitrate']} kbps"
    d["format"] = fmt

    cover = "images/default-radio-cover.jpg"
    if src == "webradio":
        name = radio_name(f) or m.get("Name", "") or "web"
        d["station"] = name
        if os.path.exists(f"/var/local/www/imagesw/radio-logos/{name}.jpg"):
            cover = f"imagesw/radio-logos/{quote(name)}.jpg"
    elif src == "library":
        cover = "coverart.php/" + quote(f)
    d["cover"] = f"http://{ip}/{cover}" if ip else ""   # sans IP : pas de pochette

    d["thumb"] = ""
    try:
        d["thumb"] = make_thumb_png(d["cover"], ip)
    except Exception as e:
        log.warning("vignette : %s", e)
    return d


_build_status_mpd = build_status


def build_status(*a, **k):
    """En mode renderer, efface les metadonnees MPD perimees (derniere radio...)."""
    st = _build_status_mpd(*a, **k)
    as_str = isinstance(st, str)
    d = json.loads(st) if as_str else st
    if d.get("source") not in RENDERER_LABEL:
        d.update(mpd_fields(a[0] if a else k.get("ip")))
    label = RENDERER_LABEL.get(d.get("source"))
    meta = airplay_meta(a[0] if a else k.get("ip")) if d.get("source") == "airplay" else None
    if meta:
        d.update(meta)
    elif label:
        d.update({"title": "", "artist": "", "album": "", "station": label,
                  "cover": "", "thumb": "", "format": "", "elapsed": 0, "duration": 0})
    return json.dumps(d, ensure_ascii=False) if as_str else d


def wifi_profile():
    """(ssid, psk) du profil Wi-Fi NetworkManager (actif sur wlan0 en priorité), ou None."""
    try:
        out = run(["nmcli", "-t", "-f", "UUID,TYPE,DEVICE", "connection", "show"])
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        log.warning("nmcli : %s", e)
        return None
    cands = [c for c in (l.split(":") for l in out.splitlines())
             if len(c) == 3 and c[1] == "802-11-wireless"]
    cands.sort(key=lambda c: c[2] != IFACE)        # connexion active sur wlan0 d'abord
    for uuid, _, _ in cands:
        def get(field):
            return run(["nmcli", "-e", "no", "-s", "-g", field,
                        "connection", "show", uuid]).rstrip("\n")
        if get("802-11-wireless.mode") == "ap":     # hotspot de moOde : ignoré
            continue
        return get("802-11-wireless.ssid"), get("802-11-wireless-security.psk"), uuid
    return None


def psk_hex(ssid, psk):
    """Clé WPA en hexadécimal : telle quelle si déjà 64 hex, sinon calculée (PBKDF2)."""
    if re.fullmatch(r"[0-9a-fA-F]{64}", psk):
        return psk.lower()
    if not psk:
        return ""                                   # réseau ouvert
    return hashlib.pbkdf2_hmac("sha1", psk.encode(), ssid.encode(), 4096, 32).hex()


WIFI_SET_TIMEOUT = 30     # s : délai max pour se connecter au nouveau réseau
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def nm(*args, timeout=10):
    try:
        r = subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout + r.stderr
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return 1, str(e)


def wifi_settled():
    """NetworkManager actif et Pi démarré depuis plus de 2 min."""
    try:
        with open("/proc/uptime") as f:
            up = float(f.read().split()[0])
    except (OSError, ValueError):
        up = 999
    rc, out = nm("-t", "-f", "RUNNING", "general")
    return rc == 0 and out.strip() == "running" and up > 120


def wifi_apply(ssid, key):
    """Bascule wlan0 sur (ssid, clé hex). Revient à l'ancien profil en cas d'échec."""
    old = wifi_profile()
    old_uuid = old[2] if old else None
    if old_uuid:          # clone : garde les réglages IP, pays, priorité... de l'ancien profil
        rc, out = nm("connection", "clone", old_uuid, ssid)
    else:
        rc, out = nm("connection", "add", "type", "wifi", "ifname", IFACE,
                     "con-name", ssid, "ssid", ssid)
    ids = [u for u in UUID_RE.findall(out) if u != old_uuid]
    if rc != 0 or not ids:
        log.warning("création du profil impossible : %s", out.strip())
        return False
    new_uuid = ids[-1]
    rc, out = nm("connection", "modify", new_uuid,
                 "802-11-wireless.ssid", ssid,
                 "802-11-wireless-security.key-mgmt", "wpa-psk",
                 "802-11-wireless-security.psk", key,
                 "connection.autoconnect", "yes")
    if rc == 0:
        rc, out = nm("--wait", str(WIFI_SET_TIMEOUT), "connection", "up", new_uuid,
                     timeout=WIFI_SET_TIMEOUT + 10)
    if rc != 0:
        log.warning("connexion à %s impossible : %s", ssid, out.strip())
        nm("connection", "delete", new_uuid)
        if old_uuid:
            log.info("retour à l'ancien réseau %s", old[0])
            nm("--wait", str(WIFI_SET_TIMEOUT), "connection", "up", old_uuid,
               timeout=WIFI_SET_TIMEOUT + 10)
        return False
    if old_uuid:
        nm("connection", "delete", old_uuid)
    try:                  # base moOde : moOde ne stocke que la clé hex, dans les deux champs
        con = sqlite3.connect(MOODE_DB, timeout=5)
        with con:
            con.execute("update cfg_network set wlanssid=?, wlanpwd=?, wlanpsk=?, wlanuuid=? "
                        "where iface='wlan0'", (ssid, key, key, new_uuid))
        con.close()
    except sqlite3.Error as e:
        log.warning("mise à jour de la base moOde impossible : %s", e)
    log.info("Wi-Fi basculé sur %s", ssid)
    return True


def bt_info():
    """Appareil Bluetooth connecté + morceau en cours (AVRCP), lus dans BlueZ."""
    try:
        r = subprocess.run(["busctl", "--system", "--json=short", "call", "org.bluez", "/",
                            "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"],
                           capture_output=True, text=True, timeout=2)
        objs = json.loads(r.stdout)["data"][0]
    except (subprocess.SubprocessError, FileNotFoundError, ValueError, KeyError, IndexError) as e:
        log.warning("bluez : %s", e)
        return None

    def val(props, k, d=""):
        v = props.get(k)
        return v.get("data", d) if isinstance(v, dict) else d

    devices = [(path, i["org.bluez.Device1"]) for path, i in objs.items()
               if "org.bluez.Device1" in i and val(i["org.bluez.Device1"], "Connected", False)]
    best = None
    for dev_path, dev in devices:
        info = {"name": val(dev, "Alias") or val(dev, "Name")}
        for path, i in objs.items():
            pl = i.get("org.bluez.MediaPlayer1")
            if pl and path.startswith(dev_path + "/"):
                t = val(pl, "Track", {}) or {}
                info.update(app=val(pl, "Name"), status=val(pl, "Status"),
                            title=val(t, "Title"), artist=val(t, "Artist"),
                            album=val(t, "Album"), duration=int(val(t, "Duration", 0)) // 1000)
                return info                    # appareil qui joue : prioritaire
        best = best or info                    # sinon le premier connecté (clavier, etc.)
    return best


_build_status_moode = build_status


def build_status(ip):
    """STATUS de moOde, complété par BlueZ quand la source est le Bluetooth."""
    st = _build_status_moode(ip)
    if st.get("source") == "bluetooth":
        bt = bt_info()
        if bt:
            st["station"] = bt.get("name", "")
            st["app"] = bt.get("app", "")
            st["title"] = bt.get("title", "")
            st["artist"] = bt.get("artist", "")
            st["album"] = bt.get("album", "")
            st["duration"] = bt.get("duration", 0)
            if bt.get("status") == "paused":
                st["state"] = "pause"
    return st


def bt_pcm():
    """Chemin bluez-alsa du flux Bluetooth reçu (téléphone -> Pi), ou None."""
    try:
        out = subprocess.run(["bluealsa-cli", "list-pcms"], capture_output=True,
                             text=True, timeout=2).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    for line in out.splitlines():
        if "/a2dpsnk/" in line:
            return line.strip()
    return None


def bt_get_volume():
    """Volume Bluetooth en 0..100 (bluez-alsa : 0..127)."""
    pcm = bt_pcm()
    if not pcm:
        return None
    try:
        out = subprocess.run(["bluealsa-cli", "info", pcm], capture_output=True,
                             text=True, timeout=2).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    m = re.search(r"^Volume:\s*L:\s*(\d+)\s*R:\s*(\d+)", out, re.M)
    if not m:
        return None
    return round(max(int(m.group(1)), int(m.group(2))) * 100 / 127)


def bt_set_volume(arg):
    """VOL en Bluetooth : True si traité ici (sinon VOL habituel, MPD)."""
    rend = globals().get("active_renderer")
    if not rend or rend() != "bluetooth" or not arg.isdigit() or int(arg) > 100:
        return False
    pcm = bt_pcm()
    if not pcm:
        return False
    v = str(round(int(arg) * 127 / 100))
    try:
        r = subprocess.run(["bluealsa-cli", "volume", pcm, v, v], capture_output=True,
                           text=True, timeout=2)
        return r.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


_build_status_bt = build_status


def build_status(ip):
    """Ajoute le volume Bluetooth (MPD ne le connaît pas)."""
    st = _build_status_bt(ip)
    if st.get("source") == "bluetooth":
        v = bt_get_volume()
        if v is not None:
            st["vol"] = v
    return st


_build_status_ap = build_status


def build_status(ip):
    """Ajoute le volume AirPlay (celui de l'appareil source, MPD ne le connait pas)."""
    st = _build_status_ap(ip)
    st["airplay"] = airplay.get_version()      # 1 ou 2, affiche dans la page Settings de l'ESP
    if st.get("source") == "airplay":
        v = airplay.get_volume()
        if v is not None:
            st["vol"] = v
    return st


_build_status_vol = build_status


def build_status(ip):
    """Mode de lecture (d'apres MPD) ; source DLNA : pochette et duree donnees par le serveur."""
    st = _build_status_vol(ip)
    m = mpd_query("status") or {}
    if "repeat" in m:
        st["mode"] = dlna.mode_from(m.get("repeat") == "1", m.get("random") == "1", m.get("single") == "1")
    if st.get("source") == "dlna":
        dlna.note_playing(st.get("file", ""), st.get("elapsed", 0))
        if not st.get("duration"):
            st["duration"] = dlna.duration_for(st.get("file", ""))
        art = dlna.art_for(st.get("file", ""))
        if art:
            st["cover"] = art
            try:
                st["thumb"] = make_thumb_png(art, ip)
            except Exception as e:
                log.warning("vignette DLNA : %s", e)
    return st


# ---------- pont ----------

EARLY_CMDS = ("PING", "SYNC", "WIFI_GET", "WIFI_CHECK", "WIFI_SET")


class Bridge:
    def __init__(self, ser):
        self.ser = ser
        self.ssid = None
        self.ip = None
        self.wifi_reported = False
        self.last_status_key = None
        self.pending_key = None
        self.ready = False
        self.sync_pending = False

    def send(self, msg):
        self.ser.write((msg + "\n").encode("utf-8"))
        self.ser.flush()
        log.info("PI> %s", msg)

    def announce(self, boot_deadline):
        self.ready = True
        self.send("READY")
        self.send_cred()
        self.check_wifi(boot_deadline)
        if self.sync_pending:
            self.sync_pending = False
            self.send_status(force=True)

    # --- Wi-Fi ---
    def send_cred(self):
        p = wifi_profile()
        self.send("WIFI_CRED " + json.dumps({"ssid": p[0] if p else ""},
                                            ensure_ascii=False, separators=(",", ":")))

    def set_cred(self, arg):
        try:
            c = json.loads(arg)
            ssid, psk = str(c["ssid"]), str(c.get("psk", ""))
        except (ValueError, KeyError, TypeError, AttributeError):
            self.send("ERR WIFI_SET")
            return
        if not 1 <= len(ssid.encode()) <= 32 or not (
                8 <= len(psk) <= 63 or re.fullmatch(r"[0-9a-fA-F]{64}", psk)):
            self.send("ERR WIFI_SET")          # SSID vide/trop long, ou réseau ouvert (non géré)
            return
        key = psk_hex(ssid, psk)
        p = wifi_profile()
        if p is None and not wifi_settled():
            self.send("WIFI_WAIT")             # démarrage : profils pas encore lisibles
            return
        if p and p[0] == ssid and psk_hex(p[0], p[1]) == key:
            self.send("WIFI_SET_OK")           # déjà sur ce réseau : rien à faire
            return
        self.send("WIFI_SET_START")
        self.send("WIFI_SET_OK" if wifi_apply(ssid, key) else "WIFI_SET_FAIL")
        self.send_cred()

    def check_cred(self, arg):
        try:
            c = json.loads(arg)
            ssid, psk = str(c["ssid"]), str(c.get("psk", ""))
        except (ValueError, KeyError, TypeError, AttributeError):
            self.send("ERR WIFI_CHECK")
            return
        p = wifi_profile()
        if p is None and not wifi_settled():
            self.send("WIFI_WAIT")             # démarrage : profils pas encore lisibles
            return
        same = p is not None and p[0] == ssid and psk_hex(p[0], p[1]) == psk_hex(ssid, psk)
        self.send("WIFI_SAME" if same else "WIFI_DIFF")

    def send_wifi(self):
        self.send(f"WIFI_OK {self.ssid}" if self.ssid else "WIFI_NONE")
        self.wifi_reported = True

    def check_wifi(self, boot_deadline):
        old_ip = self.ip
        ssid, self.ip = wifi_state()
        on_wifi(self, ssid)
        if not self.wifi_reported:
            if ssid or time.monotonic() >= boot_deadline:
                self.ssid = ssid
                self.send_wifi()
        elif ssid != self.ssid:
            self.ssid = ssid
            self.send_wifi()
        if self.ip and self.ip != old_ip and self.last_status_key is not None:
            self.send_status(force=True)

    # --- statut lecture ---
    def send_status(self, force=False):
        st = build_status(self.ip)
        key = {k: v for k, v in st.items() if k not in ("elapsed", "format")}
        now = time.monotonic()
        el = st.get("elapsed") or 0
        last = getattr(self, "last_el", None)
        jumped = False
        if last is not None and st.get("duration"):
            expected = last[0] + (now - last[1] if st.get("state") == "play" else 0)
            jumped = abs(el - expected) > 4
        if jumped:
            force = True
        if not force:
            if key == self.last_status_key:
                self.pending_key = None
                return
            if key != self.pending_key:      # 1re fois : on attend confirmation
                self.pending_key = key
                return
        self.pending_key = None
        self.last_status_key = key
        self.last_el = (el, now)
        self.send("STATUS " + json.dumps(st, ensure_ascii=False, separators=(",", ":")))

    # --- commandes ESP ---
    def handle(self, line):
        if not line:
            return
        if "\ufffd" in line or not line.isprintable():
            log.warning("ligne parasite ignorée (%d caractères)", len(line))
            return
        if line.upper().startswith(("WIFI_CHECK", "WIFI_SET")):
            log.info("ESP> %s (identifiants masqués)", line.split(" ", 1)[0])
        else:
            log.info("ESP> %s", line)
        parts = line.split(" ", 1)
        cmd = parts[0].upper()
        arg = parts[1].strip() if len(parts) > 1 else ""
        on_command(cmd)

        if not self.ready and cmd not in EARLY_CMDS:
            self.send("ERR BUSY")
            return

        if cmd == "PING":
            self.send("PONG")

        elif cmd == "WIFI_GET":
            self.send_cred()

        elif cmd == "WIFI_CHECK":
            self.check_cred(arg)

        elif cmd == "WIFI_SET":
            self.set_cred(arg)

        elif cmd == "SYNC":
            if not self.ready:
                self.sync_pending = True
                return
            self.send("READY")
            if self.wifi_reported:
                self.send_wifi()
            self.send_status(force=True)

        elif cmd == "PLAY":
            if not release_renderer():
                self.send("ERR BUSY")
                return
            if arg:
                seq = (["clear"], ["add", arg], ["play"])
                ok = all(mpc(*a) is not None for a in seq)
                if not ok:
                    log.info("PLAY : nouvel essai")
                    time.sleep(0.5)
                    ok = all(mpc(*a) is not None for a in seq)
                self.send("OK PLAY" if ok else "ERR PLAY")
            else:
                self.send("OK RESUME" if mpc("play") is not None else "ERR PLAY")

        elif cmd == "STATION":                 # station lancee depuis /ui : ajout a moOde (logo)
            try:
                st = json.loads(arg)
            except ValueError:
                log.info("STATION illisible : %s", arg[:80])
                return
            if isinstance(st, dict):
                moode_radio.add_async(st)

        elif cmd == "STANDBY":                 # bouton off de l'écran
            rel = globals().get("release_renderer")
            if rel:
                rel()                          # coupe AirPlay / Spotify / Bluetooth...
            self.handle("STOP")                # puis arrêt MPD habituel

        elif cmd == "STOP":
            mpc("stop")
            self.send("OK STOP")

        elif cmd == "PAUSE":
            mpc("pause")
            self.send("OK PAUSE")

        elif cmd == "DLNA_RESUME":             # source DLNA / Play : derniere lecture DLNA
            try:
                r = dlna.resume()
                self.send("OK DLNA_RESUME " + r.get("resumed", ""))
            except Exception as e:
                log.info("DLNA_RESUME impossible : %s", e)
                self.send("ERR DLNA_RESUME")
            self.send_status(force=True)

        elif cmd == "MODE":                    # mode de lecture (loop_all, all_once, random, one_loop, one_once)
            try:
                dlna.set_mode(arg)
                self.send("OK MODE " + arg)
            except Exception as e:
                log.warning("MODE %s : %s", arg, e)
                self.send("ERR MODE")
            self.send_status(force=True)

        elif cmd == "SEEK":                    # position dans le morceau, en secondes
            try:
                dlna.seek(float(arg))
                self.send("OK SEEK")
            except Exception as e:
                log.warning("SEEK %s : %s", arg, e)
                self.send("ERR SEEK")
            self.send_status(force=True)

        elif cmd in ("NEXT", "PREV"):          # morceau suivant / precedent (file MPD : DLNA)
            on_command("PLAY")
            ok = mpc("next" if cmd == "NEXT" else "previous") is not None
            self.send(("OK " if ok else "ERR ") + cmd)

        elif cmd == "VOL" and bt_set_volume(arg):    # Bluetooth : volume bluez-alsa
            self.send("OK VOL " + arg)

        elif cmd == "AIRPLAY":                 # page Settings de l'ESP : AirPlay 1 ou 2
            if arg in ("1", "2"):
                threading.Thread(target=airplay.set_version, args=(int(arg), active_renderer),
                                 daemon=True).start()
                self.send("OK AIRPLAY " + arg)
            else:
                self.send("ERR AIRPLAY")

        elif cmd == "VOL" and active_renderer() == "airplay" and arg.isdigit() and int(arg) <= 100:
            ok = airplay.set_volume(int(arg))          # AirPlay : volume de l'appareil source
            self.send(("OK VOL " if ok else "ERR VOL ") + arg)
            self.send_status(force=True)

        elif cmd == "VOL":
            if arg.isdigit() and 0 <= int(arg) <= 100 and mpc("volume", arg) is not None:
                self.send("OK VOL " + arg)
            else:
                self.send("ERR VOL")

        elif cmd == "STATUS":
            self.send_status(force=True)

        else:
            self.send("ERR UNKNOWN")


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    mpdfix.start()                   # reglages MPD que moOde efface (decodeur mpg123)
    airplay.start(active_renderer)   # AirPlay 1 + volume AirPlay (metadonnees UDP, DACP)
    try:
        dlna.start()                 # serveurs DLNA du reseau : API HTTP pour la page /ui
    except OSError as e:
        log.warning("dlna : API HTTP indisponible : %s", e)
    ser = serial.Serial(PORT, BAUD, timeout=0.1)
    ser.reset_input_buffer()
    bridge = Bridge(ser)

    ready_deadline = time.monotonic() + READY_TIMEOUT
    expected = boot_expected()
    next_boot = 0.0
    boot_deadline = 0.0
    next_wifi = next_status = 0.0
    buf = b""

    while True:
        data = ser.read(256)
        if data:
            buf += data
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                try:
                    bridge.handle(raw.decode("utf-8", errors="replace").strip())
                except Exception:
                    log.exception("erreur sur la commande %r", raw)
            if len(buf) > 1024:
                buf = b""

        now = time.monotonic()
        if not bridge.ready:
            flag = os.path.exists(READY_FLAG)
            if not flag and now >= next_boot:
                bridge.send(f"BOOT {min(95, int(uptime() * 100 / expected))}")
                next_boot = now + BOOT_POLL
            if flag or now >= ready_deadline:
                if flag:
                    boot_save()
                if not flag:
                    log.warning("pas de %s : READY quand meme", READY_FLAG)
                boot_deadline = now + BOOT_WIFI_TIMEOUT
                try:
                    bridge.announce(boot_deadline)
                except Exception:
                    log.exception("erreur annonce READY")
                next_wifi = now + WIFI_POLL
                next_status = now + STATUS_POLL
            continue

        if now >= next_wifi:
            bridge.check_wifi(boot_deadline)
            next_wifi = now + WIFI_POLL
        if now >= next_status:
            try:
                bridge.send_status()
            except Exception:
                log.exception("erreur statut")
            next_status = now + STATUS_POLL


if __name__ == "__main__":
    main()
