# ui.be — page web "AndroRadio" du Raspberry Streamer : http://<ip-esp>/ui
#
# Fichiers du dossier /ui de Tasmota :
#   index.html, style.css, app.js   interface (le navigateur fait tout le travail :
#                                   recherche Radio Browser, pochettes, tuner)
#   ui.be                           ce driver : sert les fichiers + petite API JSON
#   library.json                    favoris (20) et historique (10), cree au besoin
#
# Charge par main_prog.be (a la fin), qui transmet chaque STATUS du Pi :
#   ui_drv.on_status(st)
#
# Routes :
#   /ui            index.html
#   /ui/f?n=...    fichier du dossier /ui (ou A/src_*.png : icones des sources)
#   /ui/api?a=...  state | lib | play | toggle | stop | next | prev | mode | seek | vol | src
#                  | fsave | fdel | fmove

import webserver
import string
import json
import path
import global

# copie d'une station (map) : la page et l'historique ne partagent pas le meme objet
def ui_copy(m)
  var r = {}
  for k : m.keys()  r[k] = m[k]  end
  return r
end

class RadioUI
  static DIR    = "/ui/"
  static LIB    = "/ui/library.json"
  static NB_FAV = 20
  static NB_REC = 10
  static MIME   = {"html":"text/html; charset=utf-8", "htm":"text/html; charset=utf-8",
                   "css":"text/css", "js":"application/javascript", "json":"application/json",
                   "png":"image/png", "svg":"image/svg+xml", "jpg":"image/jpeg", "ico":"image/x-icon"}
  static FIELDS = ["uuid", "name", "url", "favicon", "country", "codec"]

  var fav        # 20 cases : station (map) ou nil
  var rec        # 10 dernieres stations, la plus recente en tete
  var rev        # change a chaque modification de fav / rec (la page recharge la liste)
  var cur        # station en cours (infos completes : logo, pays, codec...)
  var pending    # station demandee depuis la page, en attente du STATUS du Pi
  var rec_url    # URL suivie pour l'historique (ajout apres 5 s de lecture)
  var st_ms      # reception du dernier STATUS (la page en deduit la position du morceau)

  def init()
    self.rev = 1
    self.cur = nil
    self.pending = nil
    self.rec_url = ""
    self.st_ms = tasmota.millis()
    self.load_lib()
    tasmota.add_driver(self)
    # Tasmota appelle web_add_handler() au demarrage du serveur web ; l'appel
    # manuel ne sert que si le serveur tourne deja (chargement depuis la console)
    try
      self.web_add_handler()
    except .. as e, m
    end
  end

  # ---------- favoris / historique ----------
  def load_lib()
    self.fav = []
    self.rec = []
    var ok = false
    try
      var f = open(self.LIB, "r")
      var d = json.load(f.read())
      f.close()
      if isinstance(d, map)
        self.fav = d.find("fav", [])
        self.rec = d.find("rec", [])
        ok = true
      end
    except .. as e, m
    end
    if !ok  self.migrate()  end
    while size(self.fav) < self.NB_FAV  self.fav.push(nil)  end
    while size(self.fav) > self.NB_FAV  self.fav.pop()  end
    while size(self.rec) > self.NB_REC  self.rec.pop()  end
    if !ok  self.save_lib()  end
  end

  # premier demarrage : reprend les favoris (SaveFav) et les stations recentes de main_prog
  def migrate()
    var fl = global.fav_list
    if isinstance(fl, list)
      for x : fl
        if isinstance(x, map) && x.find("url", "") != ""
          self.fav.push({"name": x.find("name", ""), "url": x["url"]})
        end
      end
    end
    var rl = global.recent
    if isinstance(rl, list)
      for x : rl
        if isinstance(x, map) && x.find("url", "") != ""
          self.rec.push({"name": x.find("name", ""), "url": x["url"]})
        end
      end
    end
    print("UI: library created, " + str(size(self.fav)) + " favorites imported")
  end

  def save_lib()
    self.rev += 1
    try
      var f = open(self.LIB, "w")
      f.write(json.dump({"fav": self.fav, "rec": self.rec}))
      f.close()
    except .. as e, m
      print("UI: save failed", e, m)
    end
  end

  # station connue (favoris, historique) pour une URL, ou nil
  def find_url(url)
    for s : self.fav
      if s != nil && s.find("url") == url  return s  end
    end
    for s : self.rec
      if s.find("url") == url  return s  end
    end
    return nil
  end

  def rec_add(s)
    if s == nil || s.find("url", "") == ""  return  end
    var nl = [s]
    for r : self.rec
      if r.find("url") != s["url"] && size(nl) < self.NB_REC  nl.push(r)  end
    end
    self.rec = nl
    self.save_lib()
  end

  # ---------- donnees venant du Pi (appele par main_prog.be) ----------
  def on_status(st)
    self.st_ms = tasmota.millis()
    if st.find("source") != "webradio" || st.find("state") != "play"  return  end
    var url = st.find("file", "")
    if url == ""  return  end
    if self.cur == nil || self.cur.find("url") != url
      var s = nil
      if self.pending != nil && self.pending.find("url") == url
        s = self.pending
      else
        s = self.find_url(url)
      end
      if s == nil
        s = {"name": st.find("station", ""), "url": url}
      end
      s = ui_copy(s)
      if s.find("name", "") == ""  s["name"] = st.find("station", "web")  end
      self.cur = s
    end
    # logo absent (station lancee depuis l'ecran) : celui du Pi
    var cv = st.find("cover", "")
    if self.cur.find("favicon", "") == "" && string.find(cv, "http") == 0
      self.cur["favicon"] = cv
    end
    # historique : apres 5 s de lecture, comme sur l'ecran
    if url != self.rec_url
      self.rec_url = url
      tasmota.remove_timer("ui_rec")
      tasmota.set_timer(5000, def ()
        if self.rec_url == url && self.cur != nil && self.cur.find("url") == url
          self.rec_add(ui_copy(self.cur))
        end
      end, "ui_rec")
    end
  end

  # ---------- actions ----------
  def arg(name)
    return webserver.has_arg(name) ? webserver.arg(name) : ""
  end

  # station decrite par les arguments de la requete
  def arg_station()
    var s = {}
    for k : self.FIELDS
      var v = self.arg(k)
      if v != ""  s[k] = v  end
    end
    var b = int(self.arg("bitrate"))
    if b > 0  s["bitrate"] = b  end
    return s
  end

  def do_play()
    var s = self.arg_station()
    var url = s.find("url", "")
    if url == ""  return false  end
    if s.find("name", "") == ""  s["name"] = "web"  end
    self.pending = s
    self.cur = s
    global.manual_ts = tasmota.millis()
    global.play_radio(s["name"], url)
    global.set_source("webradio")
    return true
  end

  # meme logique que le bouton play/stop de l'ecran ; en DLNA (morceaux) : pause / reprise
  def do_toggle()
    var dlna = global.cur_source == "dlna"
    if global.play_state == "play"
      global.pi(dlna ? "PAUSE" : "STANDBY")
      global.play_state = dlna ? "pause" : "stop"
      global.play_btn_show()
    elif dlna
      global.pi("PLAY")                 # sans URL : reprend la file MPD la ou elle en etait
    elif global.cur_source == "webradio" || global.cur_source == ""
      var lr = global.last_radio
      global.manual_ts = tasmota.millis()
      global.play_radio(lr["name"], lr["url"])
      global.set_source("webradio")
    elif global.RENDERERS.find(global.cur_source) == nil
      global.pi("PLAY")
    end
    return true
  end

  def do_vol()
    var v = int(self.arg("v"))
    if v < 0 || v > 100  return false  end
    global.vol_send(v, true)
    if global.p0b5 != nil  global.p0b5.val = v  end
    return true
  end

  def do_src()
    var i = global.SOURCES.find(self.arg("s"))
    if i == nil  return false  end
    global.select_source(i)
    return true
  end

  def do_mode()
    var m = self.arg("m")
    if global.MODES.find(m) == nil  return false  end
    global.play_mode = m
    global.mode_show()                  # bouton de l'ecran tout de suite, le STATUS confirmera
    global.pi("MODE " + m)
    return true
  end

  def do_seek()
    var t = int(self.arg("t"))
    if t < 0  return false  end
    global.pi("SEEK " + str(t))
    return true
  end

  def slot(name, n)
    var i = int(self.arg(name)) - 1
    return (i >= 0 && i < n) ? i : nil
  end

  def do_fsave()
    var i = self.slot("slot", self.NB_FAV)
    var s = self.arg_station()
    if i == nil || s.find("url", "") == ""  return false  end
    self.fav[i] = s
    self.save_lib()
    return true
  end

  def do_fdel()
    var i = self.slot("slot", self.NB_FAV)
    if i == nil  return false  end
    self.fav[i] = nil
    self.save_lib()
    return true
  end

  def do_fmove()
    var a = self.slot("from", self.NB_FAV)
    var b = self.slot("to", self.NB_FAV)
    if a == nil || b == nil  return false  end
    if a != b
      var s = self.fav[a]
      self.fav.remove(a)
      self.fav.insert(b, s)
      self.save_lib()
    end
    return true
  end

  def state_json()
    var wu = global.webui
    var st = (wu != nil) ? wu.status : nil
    return json.dump({"st": st, "src": global.cur_source, "ps": global.play_state,
                      "cur": self.cur, "rev": self.rev, "last": global.last_radio,
                      "age": tasmota.millis() - self.st_ms})
  end

  # ---------- integration Tasmota ----------
  def web_add_handler()
    webserver.on("/ui",     / -> self.page_index())
    webserver.on("/ui/f",   / -> self.page_file())
    webserver.on("/ui/api", / -> self.page_api())
  end

  def web_add_main_button()
    webserver.content_send("<p><form action='/ui' method='get'><button>Radio</button></form></p>")
  end

  def send(code, mime, body)
    webserver.content_open(code, mime)
    webserver.content_send(body)
    webserver.content_close()
  end

  def send_file(p)
    if !path.exists(p)
      self.send(404, "text/plain", "not found")
      return
    end
    var ext = string.split(p, ".").pop()
    var f = open(p, "r")
    webserver.content_open(200, self.MIME.find(ext, "application/octet-stream"))
    while true
      var b = f.readbytes(1024)
      if size(b) == 0  break  end
      webserver.content_send(b)
    end
    f.close()
    webserver.content_close()
  end

  def page_index()
    if !webserver.check_privileged_access()  return nil  end
    self.send_file(self.DIR + "index.html")
  end

  def page_file()
    var n = self.arg("n")
    if n == "" || string.find(n, "..") >= 0 || n == "library.json"
      self.send(404, "text/plain", "not found")
    elif string.find(n, "A/src_") == 0
      self.send_file("/" + n)
    else
      self.send_file(self.DIR + n)
    end
  end

  def page_api()
    if !webserver.check_privileged_access()  return nil  end
    var a = self.arg("a")
    var out = nil
    try
      if a == "state"
        out = self.state_json()
      elif a == "lib"
        out = json.dump({"fav": self.fav, "rec": self.rec, "rev": self.rev})
      else
        var ok = false
        if   a == "play"   ok = self.do_play()
        elif a == "toggle" ok = self.do_toggle()
        elif a == "stop"   global.pi("STOP")  ok = true
        elif a == "next"   global.pi("NEXT")  ok = true
        elif a == "prev"   global.pi("PREV")  ok = true
        elif a == "mode"   ok = self.do_mode()
        elif a == "seek"   ok = self.do_seek()
        elif a == "vol"    ok = self.do_vol()
        elif a == "src"    ok = self.do_src()
        elif a == "fsave"  ok = self.do_fsave()
        elif a == "fdel"   ok = self.do_fdel()
        elif a == "fmove"  ok = self.do_fmove()
        end
        out = ok ? '{"ok":true,"rev":' + str(self.rev) + '}' : '{"ok":false}'
      end
    except .. as e, m
      print("UI api " + a + ":", e, m)
      out = '{"ok":false,"err":' + json.dump(str(e) + " " + str(m)) + '}'
    end
    self.send(200, "application/json", out)
  end
end

ui_drv = RadioUI()
