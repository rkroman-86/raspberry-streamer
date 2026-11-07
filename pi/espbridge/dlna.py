# dlna.py - lecture depuis les serveurs DLNA/UPnP du reseau (point de controle)
#
# Le Pi recherche les serveurs de medias (NAS, Plex, Windows...), parcourt
# leurs dossiers et met un dossier dans la file de MPD a partir du morceau
# choisi. La page /ui du telephone l'interroge directement en HTTP (un
# navigateur ne peut ni decouvrir les serveurs DLNA ni les interroger).
#
# API HTTP (JSON, CORS ouvert), port HTTP_PORT :
#   /dlna/servers[?refresh=1]              serveurs trouves (recherche SSDP ~3 s)
#   /dlna/browse?s=<udn>&id=<objet>&start=0&count=100
#                                          contenu d'un dossier (sous-dossiers + morceaux)
#   /dlna/play?s=<udn>&c=<dossier>&i=<morceau>
#                                          file MPD = morceaux du dossier, lecture depuis i
#   /dlna/mode[?m=<mode>]                  mode de lecture (lu / change)
#   /dlna/next, /dlna/prev                 morceau suivant / precedent
#   /dlna/seek?t=<secondes>                position dans le morceau
#   /dlna/resume                           reprend la derniere lecture (dossier, morceau, position)
#   /dlna/state                            mode, dernier serveur, file en cours
#
# Modes (reglages MPD repeat / random / single) :
#   loop_all  dossier en boucle (defaut)   all_once  dossier une fois
#   random    aleatoire                    one_loop  un morceau en boucle
#   one_once  un morceau une fois
import os
import re
import sys
import json
import time
import socket
import logging
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

log = logging.getLogger("espbridge")

HTTP_PORT = 8091
STATE_FILE = "/var/lib/espbridge/dlna.json"
MAX_QUEUE = 1000            # morceaux au plus dans la file MPD
PAGE = 200                  # taille des pages demandees au serveur
SSDP_ADDR = ("239.255.255.250", 1900)
SSDP_WAIT = 3

MODES = {                   # (repeat, random, single)
    "loop_all": (1, 0, 0),
    "all_once": (0, 0, 0),
    "random":   (1, 1, 0),
    "one_loop": (1, 0, 1),
    "one_once": (0, 0, 1),
}

NS = {
    "d": "urn:schemas-upnp-org:device-1-0",
    "didl": "urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "upnp": "urn:schemas-upnp-org:metadata-1-0/upnp/",
}

_servers = {}               # udn -> {udn, name, model, icon, control, location}
_lock = threading.Lock()
_art = {}                   # url du morceau -> pochette (pour le STATUS)
_dur = {}                   # url du morceau -> duree en s (si MPD ne la trouve pas)
_ids = {}                   # url du morceau -> identifiant DLNA (reprise sur le bon morceau)
_state = {"mode": "loop_all", "server": "", "queue": None,
          "last": None}     # derniere lecture : server, container, item, url, title, elapsed
_saved = {"at": 0.0}


# ---------- etat persistant ----------
def _load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("mode") in MODES:
            _state["mode"] = d["mode"]
        _state["server"] = d.get("server", "")
        if isinstance(d.get("last"), dict):
            _state["last"] = d["last"]
    except (OSError, ValueError):
        pass


def _save_state():
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"mode": _state["mode"], "server": _state["server"], "last": _state["last"]}, f)
        os.replace(tmp, STATE_FILE)
    except OSError as e:
        log.warning("dlna : sauvegarde impossible : %s", e)


# ---------- decouverte (SSDP) ----------
def _http_get(url, timeout=4):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def _describe(location):
    """Description d'un appareil : serveurs de medias qu'il contient (souvent un seul)."""
    root = ET.fromstring(_http_get(location))
    base = (root.findtext("d:URLBase", "", NS) or location).strip()
    found = []
    for dev in root.iter("{%s}device" % NS["d"]):
        if "MediaServer" not in (dev.findtext("d:deviceType", "", NS) or ""):
            continue
        control = None
        for svc in dev.findall("d:serviceList/d:service", NS):
            if "ContentDirectory" in (svc.findtext("d:serviceType", "", NS) or ""):
                control = urllib.parse.urljoin(base, svc.findtext("d:controlURL", "", NS).strip())
        if not control:
            continue
        icon, best = "", -1
        for ic in dev.findall("d:iconList/d:icon", NS):
            url = (ic.findtext("d:url", "", NS) or "").strip()
            mime = ic.findtext("d:mimetype", "", NS) or ""
            try:
                w = int(ic.findtext("d:width", "0", NS))
            except ValueError:
                w = 0
            score = w + (1000 if "png" in mime else 0)
            if url and score > best:
                icon, best = urllib.parse.urljoin(base, url), score
        found.append({"udn": (dev.findtext("d:UDN", "", NS) or "").strip(),
                      "name": (dev.findtext("d:friendlyName", "", NS) or "?").strip(),
                      "model": (dev.findtext("d:modelName", "", NS) or "").strip(),
                      "icon": icon, "control": control, "location": location})
    return found


def discover(wait=SSDP_WAIT):
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
           'MAN: "ssdp:discover"\r\nMX: 2\r\n'
           "ST: urn:schemas-upnp-org:device:MediaServer:1\r\n\r\n").encode()
    locations = set()
    sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sk.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sk.settimeout(0.5)
        sk.sendto(msg, SSDP_ADDR)
        time.sleep(0.1)
        sk.sendto(msg, SSDP_ADDR)
        end = time.monotonic() + wait
        while time.monotonic() < end:
            try:
                data, _ = sk.recvfrom(4096)
            except socket.timeout:
                continue
            m = re.search(rb"(?im)^location:\s*(\S+)", data)
            if m:
                locations.add(m.group(1).decode("latin-1"))
    finally:
        sk.close()
    found = {}
    threads = []

    def worker(loc):
        try:
            for s in _describe(loc):
                if s["udn"]:
                    found[s["udn"]] = s
        except Exception as e:
            log.info("dlna : description illisible %s : %s", loc, e)

    for loc in locations:
        t = threading.Thread(target=worker, args=(loc,), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(6)
    with _lock:
        _servers.clear()
        _servers.update(found)
    log.info("dlna : %d serveur(s) trouve(s)", len(found))
    return list(found.values())


def server(udn):
    with _lock:
        s = _servers.get(udn)
    if s is None:
        discover()
        with _lock:
            s = _servers.get(udn)
    if s is None:
        raise LookupError("server not found")
    return s


# ---------- parcours (ContentDirectory:Browse) ----------
def _soap_browse(control, object_id, start, count):
    body = ('<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            '<u:Browse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">'
            "<ObjectID>%s</ObjectID><BrowseFlag>BrowseDirectChildren</BrowseFlag>"
            "<Filter>*</Filter><StartingIndex>%d</StartingIndex>"
            "<RequestedCount>%d</RequestedCount><SortCriteria></SortCriteria>"
            "</u:Browse></s:Body></s:Envelope>") % (_xml_esc(object_id), start, count)
    req = urllib.request.Request(control, data=body.encode("utf-8"), headers={
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPACTION": '"urn:schemas-upnp-org:service:ContentDirectory:1#Browse"'})
    with urllib.request.urlopen(req, timeout=10) as r:
        root = ET.fromstring(r.read())
    result = total = None
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag == "Result":
            result = el.text or ""
        elif tag == "TotalMatches":
            total = int(el.text or 0)
    return result or "", total or 0


def _xml_esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _seconds(d):
    m = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", d or "")
    return int(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) if m else 0


def _parse_didl(xml_text, counts=None):
    """Sous-dossiers et morceaux audio d'une reponse Browse.
    counts (liste) recoit le nombre d'elements bruts lus (photos et videos comprises)."""
    out = []
    if not xml_text.strip():
        if counts is not None:
            counts.append(0)
        return out
    root = ET.fromstring(xml_text)
    if counts is not None:
        counts.append(len(root))
    for el in root:
        tag = el.tag.split("}")[-1]
        title = (el.findtext("dc:title", "", NS) or "").strip()
        art = (el.findtext("upnp:albumArtURI", "", NS) or "").strip()
        if tag == "container":
            try:
                cnt = int(el.get("childCount", "-1"))
            except ValueError:
                cnt = -1
            out.append({"id": el.get("id", ""), "kind": "folder", "title": title,
                        "count": cnt, "art": art})
        elif tag == "item":
            cls = el.findtext("upnp:class", "", NS) or ""
            url, dur, mime = "", 0, ""
            for res in el.findall("didl:res", NS):
                pi = res.get("protocolInfo", "")
                parts = pi.split(":")
                rm = parts[2] if len(parts) > 2 else ""
                if (rm.startswith("audio/") or (not rm and "audioItem" in cls)) and (res.text or "").strip():
                    url, dur, mime = res.text.strip(), _seconds(res.get("duration")), rm
                    break
            if not url or ("audioItem" not in cls and not mime.startswith("audio/")):
                continue                     # photos, videos : ignores
            artist = (el.findtext("upnp:artist", "", NS) or el.findtext("dc:creator", "", NS) or "").strip()
            out.append({"id": el.get("id", ""), "kind": "track", "title": title,
                        "artist": artist, "album": (el.findtext("upnp:album", "", NS) or "").strip(),
                        "art": art, "duration": dur, "url": url})
    return out


def browse(udn, object_id="0", start=0, count=100):
    s = server(udn)
    xml_text, total = _soap_browse(s["control"], object_id, start, count)
    items = _parse_didl(xml_text)
    if udn != _state["server"]:
        _state["server"] = udn
        _save_state()
    return {"total": total, "start": start, "items": items}


def tracks_of(udn, container):
    """Tous les morceaux audio d'un dossier (pages successives)."""
    s = server(udn)
    tracks, start = [], 0
    while len(tracks) < MAX_QUEUE:
        xml_text, total = _soap_browse(s["control"], container, start, PAGE)
        n = []
        page = _parse_didl(xml_text, n)
        returned = n[0]
        tracks += [x for x in page if x["kind"] == "track"]
        start += returned
        if returned == 0 or start >= total:
            break
    return tracks[:MAX_QUEUE]


# ---------- MPD ----------
def _q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


class Mpd:
    def __init__(self):
        self.sk = socket.create_connection(("127.0.0.1", 6600), timeout=5)
        self.fh = self.sk.makefile("rwb")
        self.fh.readline()

    def cmd(self, line):
        self.fh.write((line + "\n").encode("utf-8"))
        self.fh.flush()
        out = {}
        while True:
            r = self.fh.readline().decode("utf-8", "replace").rstrip("\n")
            if r == "OK":
                return out
            if r.startswith("ACK") or not r:
                raise RuntimeError(r or "MPD closed")
            k, _, v = r.partition(": ")
            out.setdefault(k, v)

    def close(self):
        try:
            self.sk.close()
        except OSError:
            pass


def _apply_mode(mpd, mode):
    rep, rnd, sgl = MODES[mode]
    mpd.cmd("repeat %d" % rep)
    mpd.cmd("random %d" % rnd)
    mpd.cmd("single %d" % sgl)
    mpd.cmd("consume 0")


def set_mode(mode):
    if mode not in MODES:
        raise ValueError("unknown mode")
    _state["mode"] = mode
    _save_state()
    mpd = Mpd()
    try:
        _apply_mode(mpd, mode)
    finally:
        mpd.close()


def play(udn, container, item_id):
    tracks = tracks_of(udn, container)
    if not tracks:
        raise LookupError("no playable track in this folder")
    pos = next((k for k, t in enumerate(tracks) if t["id"] == item_id), 0)
    main = sys.modules.get("__main__")
    rel = getattr(main, "release_renderer", None)
    if rel:
        rel()                                   # AirPlay / Spotify / Bluetooth rendent la main
    try:
        from autoresume import on_command
        on_command("PLAY")                      # annule une reprise de webradio prevue
    except ImportError:
        pass
    mpd = Mpd()
    try:
        mpd.cmd("clear")
        for t in tracks:
            sid = mpd.cmd("addid " + _q(t["url"])).get("Id")
            if not sid:
                continue
            for tag, key in (("Title", "title"), ("Artist", "artist"), ("Album", "album")):
                if t.get(key):
                    try:
                        mpd.cmd("addtagid %s %s %s" % (sid, tag, _q(t[key])))
                    except RuntimeError:
                        pass                    # MPD refuse parfois les tags sur les flux
            if t.get("art"):
                _art[t["url"]] = t["art"]
            if t.get("duration"):
                _dur[t["url"]] = t["duration"]
            _ids[t["url"]] = t["id"]
        _apply_mode(mpd, _state["mode"])
        mpd.cmd("play %d" % pos)
    finally:
        mpd.close()
    for cache in (_art, _dur, _ids):            # caches bornes
        if len(cache) > 3000:
            for k in list(cache)[:1000]:
                cache.pop(k, None)
    _state["queue"] = {"server": udn, "container": container, "count": len(tracks), "pos": pos}
    t = tracks[pos]
    _state["last"] = {"server": udn, "container": container, "item": t["id"], "url": t["url"],
                      "title": t.get("title", ""), "elapsed": 0}
    _save_state()
    log.info("dlna : %d morceau(x) dans la file, lecture depuis le n°%d", len(tracks), pos + 1)
    return {"ok": True, "count": len(tracks), "pos": pos}


def step(direction):
    mpd = Mpd()
    try:
        mpd.cmd("next" if direction > 0 else "previous")
    finally:
        mpd.close()


def art_for(url):
    return _art.get(url, "")


def duration_for(url):
    return _dur.get(url, 0)


def note_playing(url, elapsed):
    """Appele a chaque STATUS DLNA : retient le morceau et la position pour la reprise."""
    last = _state["last"]
    if not last or not url:
        return
    item = _ids.get(url)
    if item is None and url != last.get("url"):
        return                                  # morceau qui ne vient pas de notre file (cast)
    now = time.monotonic()
    changed = item is not None and item != last.get("item")
    if changed:
        last.update(item=item, url=url)
    last["elapsed"] = int(elapsed or 0)
    if changed or now - _saved["at"] > 30:
        _saved["at"] = now
        _save_state()


def resume():
    """Reprend la derniere lecture DLNA (meme dossier, morceau, position et mode).
    File MPD encore en place : simple reprise ; sinon la file est reconstruite."""
    last = _state["last"]
    m = {}
    try:
        mpd = Mpd()
        try:
            m.update(mpd.cmd("currentsong"))
            m.update(mpd.cmd("status"))
        finally:
            mpd.close()
    except (OSError, RuntimeError):
        pass
    f = m.get("file", "")
    if f and (f in _ids or (last and f == last.get("url"))):
        main = sys.modules.get("__main__")
        rel = getattr(main, "release_renderer", None)
        if rel:
            rel()
        mpd = Mpd()
        try:
            mpd.cmd("play")
        finally:
            mpd.close()
        return {"ok": True, "resumed": "queue"}
    if not last:
        raise LookupError("no previous DLNA playback")
    elapsed = last.get("elapsed", 0)
    r = play(last["server"], last["container"], last["item"])
    if elapsed > 5:
        try:
            time.sleep(0.8)                     # laisse MPD ouvrir le flux avant de s'y deplacer
            seek(elapsed)
        except Exception as e:
            log.info("dlna : reprise sans position (%s)", e)
    r["resumed"] = "rebuilt"
    return r


def mode_from(repeat, random, single):
    """Nom du mode d'apres les reglages reels de MPD (change aussi par moOde ou un controleur)."""
    if random:
        return "random"
    if single:
        return "one_loop" if repeat else "one_once"
    return "loop_all" if repeat else "all_once"


def seek(seconds):
    mpd = Mpd()
    try:
        mpd.cmd("seekcur %d" % max(0, int(seconds)))
    finally:
        mpd.close()


# ---------- HTTP ----------
class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path == "/dlna/servers":
                with _lock:
                    cached = list(_servers.values())
                lst = discover() if (q.get("refresh") or not cached) else cached
                self._send(200, {"servers": [{k: s[k] for k in ("udn", "name", "model", "icon")}
                                             for s in sorted(lst, key=lambda s: s["name"].lower())],
                                 "last": _state["server"]})
            elif u.path == "/dlna/browse":
                self._send(200, browse(q["s"], q.get("id", "0"), int(q.get("start", 0)),
                                       min(500, int(q.get("count", 100)))))
            elif u.path == "/dlna/play":
                self._send(200, play(q["s"], q["c"], q.get("i", "")))
            elif u.path == "/dlna/mode":
                if q.get("m"):
                    set_mode(q["m"])
                self._send(200, {"mode": _state["mode"], "modes": list(MODES)})
            elif u.path in ("/dlna/next", "/dlna/prev"):
                step(1 if u.path.endswith("next") else -1)
                self._send(200, {"ok": True})
            elif u.path == "/dlna/seek":
                seek(float(q["t"]))
                self._send(200, {"ok": True})
            elif u.path == "/dlna/resume":
                self._send(200, resume())
            elif u.path == "/dlna/state":
                self._send(200, {"mode": _state["mode"], "server": _state["server"],
                                 "queue": _state["queue"], "last": _state["last"]})
            else:
                self._send(404, {"ok": False, "err": "not found"})
        except KeyError as e:
            self._send(200, {"ok": False, "err": "missing parameter %s" % e})
        except Exception as e:
            log.warning("dlna %s : %s", u.path, e)
            self._send(200, {"ok": False, "err": str(e)})


def start(port=HTTP_PORT):
    _load_state()
    srv = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log.info("dlna : API sur le port %d", port)
    return srv
