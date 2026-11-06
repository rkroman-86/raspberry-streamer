# web_ui.be — pages web de l'ESP (accessibles depuis le téléphone)
#
#   http://<ip-esp>/wsync    Wi-Fi : réseau commun ESP + streamer
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
    webserver.content_start("Streamer Wi-Fi")
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
    self.row("Sync", self.STATE_LABEL.find(ws.state, ws.state))
    webserver.content_send("</table>")
    if ws.last_error != nil && ws.state == "fail"
      webserver.content_send("<p style='color:#e66'>" + self.esc(ws.last_error) + "</p>")
    end
    webserver.content_send("</fieldset><br>")

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
