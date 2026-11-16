# web_ui.be — pages web de l'ESP (accessibles depuis le téléphone)
#
#   http://<ip-esp>/wsync    Wi-Fi : réseau commun ESP + streamer ; services AirPlay / Spotify / Bluetooth
#   http://<ip-esp>/player   Lecteur (squelette : affiche la lecture en cours,
#                            les commandes viendront plus tard)
#
# Nécessite wifi_sync.be chargé avant (objet global wifisync).
# Le statut lui est transmis par main_prog.be (webui.status).

import webserver
import string
import json
import persist

class WebUI
  var status       # dernier STATUS reçu du Pi (map), pour /player
  var ap_wanted    # reglages Services demandes, en attente de confirmation par le Pi

  static STATE_LABEL = {
    "idle":    "Waiting",
    "check":   "Checking...",
    "same":    "In sync",
    "diff":    "Updating streamer...",
    "set":     "Streamer switching...",
    "ok":      "Streamer updated",
    "fail":    "Failed",
    "noconf":  "Not set",
    "ap":      "ESP in AP mode",
    "stale":   "ESP network changed: re-enter password",
    "apply":   "Streamer testing...",
    "restart": "OK, ESP restarting...",
    "wait":    "Streamer booting, retrying...",
  }
  static BUSY = ["check", "diff", "set", "apply", "restart", "wait"]

  def init()
    self.status = nil
    self.ap_wanted = nil
    tasmota.add_driver(self)
    # Tasmota appelle web_add_handler() au démarrage du serveur web ; l'appel
    # manuel ne sert que si le serveur tourne déjà (chargement depuis la console)
    try
      self.web_add_handler()
    except .. as e, m
    end
  end

  # ---------- données venant du Pi ----------
  def on_line(line)
    if string.find(line, "STATUS ") == 0
      var st = json.load(line[7..])
      if st != nil self.status = st end
    end
    return false
  end

  # ---------- intégration Tasmota ----------
  def web_add_handler()
    webserver.on("/wsync",  / -> self.page_wsync(), webserver.HTTP_GET)
    webserver.on("/wsync",  / -> self.post_wsync(), webserver.HTTP_POST)
    webserver.on("/services", / -> self.post_services(), webserver.HTTP_POST)
    webserver.on("/player", / -> self.page_player())
  end

  def web_add_main_button()
    webserver.content_send("<p><form action='/player' method='get'><button>Player</button></form></p>")
  end

  def web_add_config_button()
    webserver.content_send("<p><form action='/wsync' method='get'><button>Streamer Wi-Fi</button></form></p>")
  end

  # ---------- outils ----------
  static def esc(s)
    if s == nil return "" end
    s = str(s)
    s = string.replace(s, "&", "&amp;")
    s = string.replace(s, "<", "&lt;")
    s = string.replace(s, ">", "&gt;")
    s = string.replace(s, "\"", "&quot;")
    s = string.replace(s, "'", "&#39;")
    return s
  end

  def row(label, value)
    webserver.content_send("<tr><td>" + label + "</td><td><b>" + self.esc(value) + "</b></td></tr>")
  end

  # ---------- /wsync ----------
  def page_wsync()
    if !webserver.check_privileged_access() return nil end
    var ws = global.wifisync
    webserver.content_start("Settings")
    webserver.content_send_style()
    var busy = self.BUSY.find(ws.state) != nil
    if busy
      webserver.content_send("<meta http-equiv='refresh' content='2;url=/wsync'>")
    end

    webserver.content_send("<fieldset><legend><b>&nbsp;Status&nbsp;</b></legend><table style='width:100%'>")
    var cur = ws.esp_ssid()
    self.row("ESP", cur != nil ? cur : "AP / offline")
    var pl = ws.pi_link
    self.row("Streamer", pl == nil ? "?" : (pl == "" ? "offline (" + str(ws.pi_ssid) + ")" : pl))
    self.row("Saved", persist.find("wifi_ssid", "-"))
    var eip = tasmota.wifi().find("ip", "")
    self.row("ESP IP", eip != "" ? eip : "-")
    var pip = self.status != nil ? self.status.find("ip", "") : ""
    self.row("Streamer IP", pip != "" ? pip : "-")
    self.row("Sync", self.STATE_LABEL.find(ws.state, ws.state))
    webserver.content_send("</table>")
    if ws.last_error != nil && ws.state == "fail"
      webserver.content_send("<p style='color:#e66'>" + self.esc(ws.last_error) + "</p>")
    end
    webserver.content_send("</fieldset><br>")

    self.services_box()

    if busy                                  # pas de formulaire pendant un changement
      webserver.content_button(webserver.BUTTON_CONFIGURATION)
      webserver.content_stop()
      return
    end
    var def_ssid = persist.find("wifi_ssid", cur != nil ? cur : "")
    webserver.content_send("<fieldset><legend><b>&nbsp;Change network&nbsp;</b></legend>"
      "<form method='post' action='/wsync'>"
      "<p><b>SSID</b><br><input name='s' maxlength='32' value='" + self.esc(def_ssid) + "'></p>"
      "<p><b>Password</b><br><input name='p' type='password' maxlength='63' autocomplete='off'></p>"
      "<p style='font-size:smaller'>Tested by the streamer first. ESP changes only if OK.</p>"
      "<button type='submit' class='button bgrn'>Apply</button>"
      "</form></fieldset>")

    webserver.content_button(webserver.BUTTON_CONFIGURATION)
    webserver.content_stop()
  end

  # ---------- Services : AirPlay (off / 2 / 1), Spotify, Bluetooth ----------
  def svc_now()
    var st = self.status
    if st == nil || st.find("svc") == nil  return nil  end
    var sv = st["svc"]
    var ap = sv.find("airplay", 0) == 1 ? str(st.find("airplay", 2)) : "off"
    return {"ap": ap, "sp": str(sv.find("spotify", 0)), "bt": str(sv.find("bluetooth", 0))}
  end

  def radio(name, val, cur, label)
    webserver.content_send(string.format("<p><label><input type='radio' name='%s' value='%s'%s> %s</label></p>",
                                         name, val, val == cur ? " checked" : "", label))
  end

  def services_box()
    var cur = self.svc_now()
    if self.ap_wanted != nil
      if cur != nil && cur["ap"] == self.ap_wanted["ap"] && cur["sp"] == self.ap_wanted["sp"] &&
         cur["bt"] == self.ap_wanted["bt"]
        self.ap_wanted = nil
      elif tasmota.millis() - self.ap_wanted["ms"] > 90000
        self.ap_wanted = nil                     # pas de confirmation : on reaffiche l'etat reel
      end
    end
    webserver.content_send("<fieldset><legend><b>&nbsp;Services&nbsp;</b></legend>"
      "<form method='post' action='/services'>")
    if cur == nil
      webserver.content_send("<p>Waiting for streamer...</p>")
    else
      var sm = "<span style='font-size:smaller'>"
      webserver.content_send("<p><b>AirPlay</b></p>")
      self.radio("ap", "2", cur["ap"], "AirPlay 2 " + sm + "(recommended)</span>")
      self.radio("ap", "1", cur["ap"], "AirPlay 1 " + sm + "(older iPhone / iPad: no sound in AirPlay 2)</span>")
      self.radio("ap", "off", cur["ap"], "Off")
      webserver.content_send("<p><b>Spotify Connect</b></p>")
      self.radio("sp", "1", cur["sp"], "On")
      self.radio("sp", "0", cur["sp"], "Off")
      webserver.content_send("<p><b>Bluetooth</b></p>")
      self.radio("bt", "1", cur["bt"], "On")
      self.radio("bt", "0", cur["bt"], "Off")
      if self.ap_wanted != nil
        webserver.content_send("<meta http-equiv='refresh' content='3;url=/wsync'>"
          "<p style='font-size:smaller'>Applying...</p>")
      else
        webserver.content_send("<p style='font-size:smaller'>A service set to Off disappears from the source list. "
          "Changing AirPlay restarts it: reconnect your device.</p>")
      end
      webserver.content_send("<button type='submit' class='button bgrn'>Save</button>")
    end
    webserver.content_send("</form></fieldset><br>")
  end

  def post_services()
    if !webserver.check_privileged_access() return nil end
    var cur = self.svc_now()
    var ap = webserver.arg("ap")
    var sp = webserver.arg("sp")
    var bt = webserver.arg("bt")
    if cur != nil && (ap == "off" || ap == "1" || ap == "2") && (sp == "0" || sp == "1") && (bt == "0" || bt == "1")
      if ap != cur["ap"]
        if ap == "off"
          global.pi("SVC airplay 0")
        else
          if self.status.find("airplay", 2) != int(ap)  global.pi("AIRPLAY " + ap)  end
          if cur["ap"] == "off"  global.pi("SVC airplay 1")  end
        end
      end
      if sp != cur["sp"]  global.pi("SVC spotify " + sp)  end
      if bt != cur["bt"]  global.pi("SVC bluetooth " + bt)  end
      self.ap_wanted = {"ap": ap, "sp": sp, "bt": bt, "ms": tasmota.millis()}
    end
    webserver.redirect("/wsync")
  end

  def post_wsync()
    if !webserver.check_privileged_access() return nil end
    var ws = global.wifisync
    var err = ws.apply(webserver.arg("s"), webserver.arg("p"))
    if err != nil
      ws.last_error = err
      ws.set_state("fail")
    end
    webserver.redirect("/wsync")
  end

  # ---------- /player (squelette) ----------
  def page_player()
    if !webserver.check_privileged_access() return nil end
    webserver.content_start("Player")
    webserver.content_send_style()
    webserver.content_send("<meta http-equiv='refresh' content='5;url=/player'>")
    var st = self.status
    if st == nil
      webserver.content_send("<p>Waiting for streamer...</p>")
    else
      var thumb = st.find("thumb", "")
      if thumb != ""
        webserver.content_send("<p style='text-align:center'><img src='" + self.esc(thumb) +
                               "' style='width:200px;height:200px;border-radius:8px'></p>")
      end
      webserver.content_send("<table style='width:100%'>")
      self.row("Source", st.find("source"))
      self.row("State", st.find("state"))
      var station = st.find("station", "")
      if station != "" self.row("Station", station) end
      self.row("Title", st.find("title"))
      var artist = st.find("artist", "")
      if artist != "" self.row("Artist", artist) end
      var vol = st.find("vol")
      if vol != nil self.row("Volume", vol) end
      webserver.content_send("</table>")
    end
    webserver.content_send("<p style='font-size:smaller'>Controls: coming soon.</p>")
    webserver.content_button(webserver.BUTTON_MAIN)
    webserver.content_stop()
  end
end

webui = WebUI()
