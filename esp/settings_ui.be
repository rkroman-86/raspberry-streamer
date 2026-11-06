# settings_ui.be — fenêtres flottantes de l'écran (page 0, ids 70 à 94)
#
#   Réglages (70..77)       : Wi-Fi actuel, IP de l'ESP, état du streamer,
#                             bouton "Mode point d'accès"
#   Confirmation (80..84)   : avant de passer en point d'accès
#   Point d'accès (90..94)  : SSID diffusé, adresse http://192.168.4.1/wsync,
#                             bouton Redémarrer
#
# Les objets sont créés en Berry (haspmota.parse) au premier besoin :
# pages.jsonl n'est pas modifié. Ouverture : settings_ui.open()
#
# Passage en point d'accès : persist.ap_mode = true, puis "WifiConfig 2".
# Au redémarrage, si ap_mode est présent et que l'ESP n'est pas connecté,
# la fenêtre "Point d'accès" s'ouvre. Dès que l'ESP se reconnecte à un
# réseau (Wifi#Connected), le drapeau est effacé, la fenêtre fermée et
# WifiConfig est remis à 4 (pas de point d'accès automatique si la box coupe).

import haspmota
import json
import string
import persist

class SettingsUI
  var built
  var boot_wait     # secondes déjà attendues au démarrage

  static G_SET  = [70, 71, 72, 73, 74, 77]
  static G_CONF = [80, 81, 82, 83, 84]
  static G_AP   = [90, 91, 92, 93, 94]
  static AP_IP  = "192.168.4.1"

  def init()
    self.built = false
    self.boot_wait = 0
    tasmota.add_rule("hasp#p0b70#event=up", / -> self.close())          # toucher hors du panneau
    tasmota.add_rule("hasp#p0b73#event=up", / -> self.close())          # croix
    tasmota.add_rule("hasp#p0b77#event=up", / -> self.ask_ap())
    tasmota.add_rule("hasp#p0b80#event=up", / -> self.show(self.G_CONF, false))   # hors du panneau = annuler
    tasmota.add_rule("hasp#p0b83#event=up", / -> self.show(self.G_CONF, false))   # Annuler
    tasmota.add_rule("hasp#p0b84#event=up", / -> self.enter_ap())                 # Confirmer
    tasmota.add_rule("hasp#p0b94#event=up", / -> self.restart())
    tasmota.add_rule("Wifi#Connected", / -> self.on_connected())
    tasmota.set_timer(1000, / -> self.boot_check(), "settings_boot")
  end

  # ---------- création des objets ----------

  def obj(o)
    o["page"] = 0
    haspmota.parse(json.dump(o))
  end

  def veil(id)
    self.obj({"id": id, "obj": "obj", "x": 0, "y": 0, "w": 240, "h": 320,
              "bg_color": "#000000", "bg_opa": 170, "radius": 0, "border_width": 0, "hidden": true})
  end

  def panel(id, y, h)
    self.obj({"id": id, "obj": "obj", "x": 10, "y": y, "w": 220, "h": h,
              "bg_color": "#202020", "bg_opa": 255, "radius": 12,
              "border_width": 1, "border_color": "#606060", "hidden": true})
  end

  def label(id, x, y, w, h, text, align)
    self.obj({"id": id, "obj": "label", "x": x, "y": y, "w": w, "h": h, "text": text,
              "text_color": "#FFFFFF", "align": align, "hidden": true})
  end

  def btn(id, x, y, w, h, text, color)
    self.obj({"id": id, "obj": "btn", "x": x, "y": y, "w": w, "h": h, "text": text,
              "bg_color": color, "radius": 8, "hidden": true})
  end

  # renvoie false tant que les pages HASPmota ne sont pas chargées
  def build()
    if self.built return true end
    if global.p0b3 == nil return false end
    # l'ordre de création fixe l'empilement : voile, panneau, puis contenu
    # --- Réglages
    self.veil(70)
    self.panel(71, 45, 230)
    self.label(72, 25, 58, 160, 24, "Settings", "left")
    self.btn(73, 186, 53, 34, 34, "X", "#404040")
    self.label(74, 25, 98, 190, 100, "", "left")
    self.btn(77, 25, 210, 190, 50, "AP mode", "#1F5FA8")
    # --- Confirmation
    self.veil(80)
    self.panel(81, 70, 180)
    self.label(82, 25, 85, 190, 100,
               "Start AP mode?\n\nESP restarts as a Wi-Fi hotspot. Music keeps playing.", "center")
    self.btn(83, 25, 192, 88, 44, "Cancel", "#404040")
    self.btn(84, 127, 192, 88, 44, "OK", "#B03A2E")
    # --- Point d'accès
    self.veil(90)
    self.panel(91, 35, 250)
    self.label(92, 25, 48, 190, 24, "AP mode", "center")
    self.label(93, 25, 80, 190, 130, "", "left")
    self.btn(94, 25, 220, 190, 50, "Restart", "#1F5FA8")
    self.built = true
    return true
  end

  # ---------- outils ----------

  def show(group, visible)
    for id : group
      var o = global.("p0b" + str(id))
      if o != nil  o.hidden = !visible  end
    end
  end

  def set_text(id, t)
    var o = global.("p0b" + str(id))
    if o != nil  o.text = t  end
  end

  def wifi_up()
    var w = tasmota.wifi()
    return w != nil && w.find("up", false)
  end

  # nom réel de l'ESP = SSID du point d'accès. La commande "Hostname" renvoie
  # le modèle enregistré (%s-%04d) : le nom calculé est dans Status 5.
  def ap_ssid()
    try
      var h = tasmota.cmd("Status 5", true)["StatusNET"]["Hostname"]
      if h != nil && h != "" && string.find(h, "%") < 0  return h  end
    except .. as e
    end
    return "tasmota-..."
  end

  # ---------- Réglages ----------

  def open()
    if !self.build() return end
    var ws = global.wifisync
    var ssid = (ws != nil) ? ws.esp_ssid() : nil
    var w = tasmota.wifi()
    var ip = (w != nil) ? w.find("ip", "") : ""
    var t = "Wi-Fi: " + (ssid != nil ? ssid : "offline") + "\n"
    t += "IP: " + (ip != "" ? ip : "-") + "\n"
    if ws != nil
      var pl = ws.pi_link
      t += "Streamer: " + (pl == nil ? "?" : (pl == "" ? "offline" : pl))
    end
    self.set_text(74, t)
    self.show(self.G_SET, true)
  end

  def close()
    self.show(self.G_SET, false)
  end

  # ---------- passage en point d'accès ----------

  def ask_ap()
    self.close()
    self.show(self.G_CONF, true)
  end

  def enter_ap()
    self.show(self.G_CONF, false)
    persist.ap_mode = true
    persist.save()
    self.show_ap()                       # affichée tout de suite, et de nouveau au redémarrage
    print("SETTINGS: AP on")
    tasmota.set_timer(1500, / -> tasmota.cmd("WifiConfig 2"), "settings_ap")
  end

  def show_ap()
    if !self.build() return end
    self.set_text(93, "Join Wi-Fi:\n" + self.ap_ssid() + "\n\nOpen:\n" + self.AP_IP + "/wsync")
    self.show(self.G_AP, true)
  end

  def restart()
    persist.remove("ap_mode")
    persist.save()
    self.set_text(93, "Restarting...")
    print("SETTINGS: AP off")
    tasmota.set_timer(500, def ()
      tasmota.cmd("WifiConfig 4", true)  # rétablit le défaut (pas d'AP automatique)
      tasmota.cmd("Restart 1", true)
    end, "settings_rs")
  end

  # ---------- détection ----------

  def boot_check()
    if !self.build()
      tasmota.set_timer(1000, / -> self.boot_check(), "settings_boot")   # pages pas encore chargées
      return
    end
    if persist.find("ap_mode")
      if self.wifi_up()
        self.on_connected()
      elif self.boot_wait < 15
        # au démarrage, Tasmota peut encore être en train de se connecter :
        # on laisse 15 s avant d'afficher la fenêtre
        self.boot_wait += 1
        tasmota.set_timer(1000, / -> self.boot_check(), "settings_boot")
      else
        print("SETTINGS: AP boot")
        self.show_ap()
      end
    end
  end

  def on_connected()
    if !persist.find("ap_mode") return end
    persist.remove("ap_mode")
    persist.save()
    self.show(self.G_AP, false)
    # WifiConfig 2 est resté enregistré : on revient au défaut
    # (une coupure de la box ne doit pas ouvrir de point d'accès)
    try
      var v = str(tasmota.cmd("WifiConfig", true)["WifiConfig"])
      if string.find(v, "2") == 0
        print("SETTINGS: WifiConfig 2 -> 4")
        tasmota.cmd("WifiConfig 4", true)
      end
    except .. as e, m
      print("SETTINGS: WifiConfig :", e, m)
    end
  end
end

settings_ui = SettingsUI()
