# autoresume.py - acces internet, reprise webradio, relance si flux bloque
#
# Test internet toutes les 2 s : requete HTTP vers generate_204 (DNS + vraie
# reponse 204). Une borne sans internet ou un portail captif ne peut pas
# repondre 204 : pas de faux "en ligne".
#   hors ligne des NET_KO_N echecs parmi les NET_WINDOW derniers tests,
#   en ligne seulement apres NET_OK_N succes de suite
#   -> NET_KO / NET_OK vers l'ESP (image "Wi-Fi barre")
# on_wifi() (toutes les 2 s) :
#   - hors ligne : retient la station ; au retour stable : relance
#   - apres une relance automatique, surveille WATCH_S s : si la lecture
#     n'a pas vraiment repris (arret, compteur fige), relance toutes les RETRY_S s
#   - en ligne, compteur fige depuis STALL_S s : relance
#   - Wi-Fi connecte mais internet absent depuis REASSOC_S s : reconnexion Wi-Fi
# on_command() : une commande de l'utilisateur annule toute reprise prevue.
import sys
import time
import logging
import threading
import subprocess
import http.client

log = logging.getLogger("espbridge")

NET_HOST = "connectivitycheck.gstatic.com"
NET_PATH = "/generate_204"
NET_EVERY = 2       # s entre deux tests
NET_WINDOW = 5      # derniers tests pris en compte
NET_KO_N = 2        # echecs parmi les NET_WINDOW derniers -> hors ligne
NET_OK_N = 3        # succes de suite -> en ligne
STALL_S = 15        # s sans progression du compteur avant relance
RETRY_S = 30        # s minimum entre deux relances
WATCH_S = 600       # s de surveillance apres une relance automatique
PLAYING_OK_S = 5    # s de lecture reelle pour considerer la reprise reussie
REASSOC_S = 30      # s sans internet (Wi-Fi connecte) avant reconnexion
REASSOC_EVERY = 120 # s minimum entre deux reconnexions
DIAG = False        # True : envoie aussi "DIAG ..." a l'ESP a chaque test

_net = {"online": True, "ok": 0, "hist": [], "sent": None, "raw": True}
_state = {"url": None, "at": 0.0, "elapsed": None, "since": 0.0, "last_kick": 0.0,
          "last_url": None, "last_play": 0.0, "watch_url": None, "watch_until": 0.0}
_reassoc = {"since": None, "last": -1e9, "busy": False}


def _probe():
    c = http.client.HTTPConnection(NET_HOST, 80, timeout=2)
    try:
        c.request("GET", NET_PATH, headers={"Connection": "close"})
        return c.getresponse().status == 204
    except (OSError, http.client.HTTPException):
        return False
    finally:
        c.close()


def _net_step(ok):
    _net["raw"] = ok
    _net["hist"] = (_net["hist"] + [ok])[-NET_WINDOW:]
    _net["ok"] = _net["ok"] + 1 if ok else 0
    if _net["online"] and _net["hist"].count(False) >= NET_KO_N:
        _net["online"] = False
    elif not _net["online"] and _net["ok"] >= NET_OK_N:
        _net["online"] = True
        _net["hist"] = []


def _net_loop():
    while True:
        t = time.monotonic()
        _net_step(_probe())
        time.sleep(max(0.2, NET_EVERY - (time.monotonic() - t)))


threading.Thread(target=_net_loop, daemon=True).start()


def _bssid():
    try:
        out = subprocess.run(["iw", "dev", "wlan0", "link"], capture_output=True,
                             text=True, timeout=3).stdout
        return out.split()[2] if out.startswith("Connected to") else "-"
    except (OSError, subprocess.SubprocessError, IndexError):
        return "?"


def _is_radio(m, f):
    return f.startswith(("http://", "https://")) and not m.PRIVATE_URL.match(f)


def _kick(bridge, url, why):
    _state.update(url=None, at=0.0, elapsed=None, last_kick=time.monotonic())
    log.info("%s : relance de %s", why, url)
    bridge.handle("PLAY " + url)          # passe par on_command("PLAY")
    _state.update(watch_url=url, watch_until=time.monotonic() + WATCH_S)


def on_command(cmd):
    if cmd in ("PLAY", "STOP", "STANDBY", "PAUSE"):
        _state.update(url=None, at=0.0, elapsed=None, watch_url=None, watch_until=0.0)
    if cmd in ("STOP", "STANDBY", "PAUSE"):
        _state.update(last_url=None, last_play=0.0)


def _reassoc_run(m):
    try:
        p = m.wifi_profile()
        if p:
            log.info("internet absent : reconnexion Wi-Fi (borne %s)", _bssid())
            m.nm("device", "wifi", "rescan")
            m.nm("--wait", "25", "connection", "up", p[2], timeout=35)
    finally:
        _reassoc["busy"] = False


def _check_reassoc(m, ssid, now):
    if not ssid or _net["online"]:
        _reassoc["since"] = None
        return
    if _reassoc["since"] is None:
        _reassoc["since"] = now
    if (now - _reassoc["since"] >= REASSOC_S and now - _reassoc["last"] >= REASSOC_EVERY
            and not _reassoc["busy"]):
        _reassoc.update(busy=True, last=now, since=None)
        threading.Thread(target=_reassoc_run, args=(m,), daemon=True).start()


def on_wifi(bridge, ssid):
    m = sys.modules["__main__"]
    now = time.monotonic()
    online = bool(ssid) and _net["online"]

    # etat internet vers l'ESP (seulement aux changements)
    if online != _net["sent"]:
        _net["sent"] = online
        bridge.send("NET_OK" if online else "NET_KO")
        log.info("internet %s (borne %s)", "revenu" if online else "perdu", _bssid())
    if DIAG:
        bridge.send("DIAG %s ssid=%s internet=%s stable=%s" % (
            time.strftime("%H:%M:%S"), ssid or "-", "OK" if _net["raw"] else "KO",
            "OK" if online else "KO"))
    _check_reassoc(m, ssid, now)

    q = m.mpd_query("status", "currentsong") or {}
    f = q.get("file", "")
    playing = q.get("state") == "play" and _is_radio(m, f)
    try:
        el = float(q.get("elapsed", "0"))
    except ValueError:
        el = 0.0
    if _state["watch_url"] and now > _state["watch_until"]:
        _state.update(watch_url=None, watch_until=0.0)

    # 1. hors ligne : on retient la station ; retour stable : relance
    if not online:
        if not _state["url"]:
            if playing:
                url = f
            elif _state["watch_url"]:
                url = _state["watch_url"]
            elif now - _state["last_play"] < 30:
                url = _state["last_url"]
            else:
                url = None
            if url:
                _state.update(url=url, at=0.0)
                log.info("hors ligne : reprise prevue de %s", url)
        _state.update(elapsed=None, at=0.0)
        return
    if _state["url"]:
        if not _state["at"]:
            _state["at"] = now + 2
        if now >= _state["at"]:
            url = _state["url"]
            if m.active_renderer() is None:
                _kick(bridge, url, "internet revenu")
            else:
                _state.update(url=None, at=0.0)
        return


    # 2. surveillance apres relance : la lecture a-t-elle vraiment repris ?
    if _state["watch_url"]:
        if playing and el >= PLAYING_OK_S:
            log.info("lecture reprise")
            _state.update(watch_url=None, watch_until=0.0)
        elif not playing and m.active_renderer() is None:
            if now - _state["last_kick"] >= RETRY_S:
                _kick(bridge, _state["watch_url"], "lecture pas reprise")
            return

    # 3. en ligne, flux en lecture mais compteur fige
    if not playing:
        _state.update(elapsed=None)
        return
    _state.update(last_url=f, last_play=now)
    if _state["elapsed"] is None or el != _state["elapsed"]:
        _state.update(elapsed=el, since=now)
        return
    if (now - _state["since"] >= STALL_S and now - _state["last_kick"] >= RETRY_S
            and m.active_renderer() is None):
        _kick(bridge, f, "flux bloque depuis %d s" % (now - _state["since"]))


# --- anti-oscillation : si internet n'a tenu que peu de temps (borne qui
# oscille), on exige ensuite plus de succes de suite avant de le redeclarer ---
NET_OK_FLAP = 10    # succes de suite exiges apres une periode en ligne courte (20 s)
FLAP_S = 60         # periode en ligne plus courte que ca = oscillation
_net.update(up_at=-1e9, flap=False)


def _net_step(ok):
    _net["raw"] = ok
    _net["hist"] = (_net["hist"] + [ok])[-NET_WINDOW:]
    _net["ok"] = _net["ok"] + 1 if ok else 0
    now = time.monotonic()
    if _net["online"] and _net["hist"].count(False) >= NET_KO_N:
        _net["online"] = False
        _net["flap"] = now - _net["up_at"] < FLAP_S
    elif not _net["online"] and _net["ok"] >= (NET_OK_FLAP if _net["flap"] else NET_OK_N):
        _net["online"] = True
        _net["hist"] = []
        _net["up_at"] = now
