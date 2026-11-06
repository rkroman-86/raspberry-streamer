# boot_ui.be — écran de démarrage du streamer (page 0, ids 100 à 103)
#
# Affiché dès le démarrage de l'ESP, par-dessus tout le reste :
#   "Starting streamer", une jauge et le pourcentage.
# Pi -> ESP : "BOOT <0-95>" toutes les 2 s pendant le démarrage de moOde
#             (estimation d'après la durée du démarrage précédent).
# L'écran disparaît à READY (ou au premier STATUS, si le Pi tournait déjà).
# Si le Pi redémarre plus tard, les BOOT le font réapparaître.
# Sans aucune réponse du Pi après BOOT_TIMEOUT : message d'erreur, fermeture au toucher.

import haspmota
import json
import string

class BootUI
  var built, visible, last_msg_ts
  var done_already                  # READY / STATUS reçu avant la création des objets
  static IDS = [100, 101, 102, 103]
  static BOOT_TIMEOUT = 180000      # ms

  def init()
    self.built = false
    self.visible = false
    self.last_msg_ts = tasmota.millis()
    tasmota.add_rule("hasp#p0b100#event=up", / -> self.on_touch())
    self.boot_wait()
  end

  def obj(o)
    o["page"] = 0
    haspmota.parse(json.dump(o))
  end

  # dès que HASPmota a chargé les pages : création et affichage
  def boot_wait()
    if global.p0b3 == nil
      tasmota.set_timer(200, / -> self.boot_wait(), "boot_ui_wait")
      return
    end
    if !self.built
      self.obj({"id": 100, "obj": "obj", "x": 0, "y": 0, "w": 240, "h": 320,
                "bg_color": "#000000", "bg_opa": 255, "radius": 0, "border_width": 0, "hidden": true})
      self.obj({"id": 101, "obj": "label", "x": 0, "y": 120, "w": 240, "h": 24, "text": "Starting streamer",
                "text_color": "#FFFFFF", "align": "center", "hidden": true})
      self.obj({"id": 102, "obj": "bar", "x": 30, "y": 156, "w": 180, "h": 12, "min": 0, "max": 100, "val": 0,
                "radius": 6, "bg_color": "#333333", "bg_opa": 255, "bg_color10": "#00C853", "hidden": true})
      self.obj({"id": 103, "obj": "label", "x": 0, "y": 176, "w": 240, "h": 20, "text": "",
                "text_color": "#9E9E9E", "align": "center", "hidden": true})
      self.built = true
    end
    if !self.done_already  self.show(true)  end
    tasmota.set_timer(5000, / -> self.watchdog(), "boot_ui_wd")
  end

  def show(v)
    self.visible = v
    for id : self.IDS
      var o = global.("p0b" + str(id))
      if o != nil  o.hidden = !v  end
    end
  end

  def set_pct(p)
    var b = global.p0b102
    var l = global.p0b103
    if b != nil  b.val = p  end
    if l != nil  l.text = (p > 0) ? str(p) + "%" : ""  end
  end

  def finish()
    self.done_already = true
    if !self.visible return end
    self.set_pct(100)
    tasmota.set_timer(400, / -> self.show(false), "boot_ui_hide")
  end

  # appelé pour chaque ligne du Pi ; renvoie true si la ligne est consommée
  def on_line(line)
    self.last_msg_ts = tasmota.millis()
    if string.find(line, "BOOT ") == 0
      var p = int(line[5..])
      self.done_already = false
      if self.built
        if !self.visible
          global.p0b101.text = "Starting streamer"
          self.show(true)
        end
        self.set_pct(p)
      end
      return true
    elif line == "READY" || string.find(line, "STATUS ") == 0
      self.finish()
    end
    return false
  end

  # Pi muet depuis trop longtemps alors que l'écran est affiché
  def watchdog()
    if self.visible && tasmota.millis() - self.last_msg_ts > self.BOOT_TIMEOUT
      global.p0b101.text = "No response from streamer"
      global.p0b103.text = "Tap to close"
    end
    tasmota.set_timer(5000, / -> self.watchdog(), "boot_ui_wd")
  end

  def on_touch()
    if global.p0b103 != nil && global.p0b103.text == "Tap to close"
      self.show(false)
    end
  end
end

boot_ui = BootUI()
