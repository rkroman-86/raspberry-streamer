# wifi_sync.be — synchronisation du Wi-Fi du streamer (Pi) avec celui de l'ESP
#
# Tasmota ne laisse pas relire son mot de passe Wi-Fi : l'ESP garde donc
# sa propre copie (SSID + mot de passe) dans persist.
#
# Contrôle automatique :
#   Pi -> READY, puis WIFI_OK/WIFI_NONE (Wi-Fi du Pi stabilisé)
#                          => ESP envoie WIFI_CHECK {"ssid","psk"}
#   Pi -> WIFI_WAIT        => Pi pas encore prêt (démarrage) : nouvel essai dans 15 s
#   Pi -> WIFI_SAME        => rien à faire
#   Pi -> WIFI_DIFF        => ESP envoie WIFI_SET (une seule fois par READY)
#   Pi -> WIFI_SET_START / WIFI_SET_OK / WIFI_SET_FAIL => état
# Garde-fou : rien n'est envoyé si l'ESP n'est pas connecté (mode AP) ou
# s'il est connecté à un autre SSID que la copie mémorisée (copie périmée).
#
# Changement de réseau (page web /wsync, voir web_ui.be) : wifisync.apply(ssid, psk)
#   1. WIFI_SET au Pi, qui teste le mot de passe et revient seul en arrière si faux
#   2. seulement sur WIFI_SET_OK : copie persist + SSId1/Password1 Tasmota, redémarrage
#
# Commande console Tasmota (secours) : WifiSync ssid|mdp  /  WifiSync  /  WifiSync clear
#
# Nécessite la fonction globale pi(cmd) qui envoie une ligne au Pi.

import json
import string
import persist

class WifiSync
  var state        # idle check same diff set ok fail noconf ap stale apply restart wait
  var set_sent     # anti-boucle : un seul WIFI_SET par READY
  var on_change    # callback optionnel f(state) pour l'écran
  var pending      # [ssid, psk] en cours d'application depuis la page, ou nil
  var pi_ssid      # SSID configuré sur le Pi (WIFI_CRED)
  var pi_link      # SSID auquel le Pi est connecté, "" si aucun (WIFI_OK / WIFI_NONE)
  var last_error   # message d'erreur pour la page web
  var wait_link    # READY reçu : on attend que le Pi annonce son état Wi-Fi

  def init()
    self.state = persist.find("wifi_ssid") ? "idle" : "noconf"
    self.set_sent = false
    self.on_change = nil
    self.pending = nil
    self.pi_ssid = nil
    self.pi_link = nil
    self.last_error = nil
    self.wait_link = false
    tasmota.add_cmd("WifiSync", / cmd, idx, payload -> self.cmd_wifisync(cmd, idx, payload))
    tasmota.add_rule("Wifi#Connected", / -> self.check())   # retour du mode AP
  end

  def set_state(s)
    if s == self.state return end
    self.state = s
    print("WIFISYNC: " + s)
    if self.on_change != nil self.on_change(s) end
  end

  # SSID auquel l'ESP est réellement connecté, ou nil (mode AP / pas de réseau)
  def esp_ssid()
    var w = tasmota.wifi()
    if w == nil || !w.find("up", false) return nil end
    try
      return tasmota.cmd("Status 11", true)["StatusSTS"]["Wifi"]["SSId"]
    except .. as e
      return nil
    end
  end

  def creds_json()
    return json.dump({"ssid": persist.find("wifi_ssid", ""),
                      "psk":  persist.find("wifi_psk", "")})
  end

  # ---------- contrôle automatique ----------

  def check()
    if self.pending != nil || self.state == "restart" return end   # changement en cours
    if !persist.find("wifi_ssid")
      self.set_state("noconf")
      return
    end
    var cur = self.esp_ssid()
    if cur == nil
      self.set_state("ap")      # ESP sans réseau : on ne touche pas au Pi
      return
    end
    if cur != persist.find("wifi_ssid")
      self.set_state("stale")   # ESP changé de réseau sans passer par /wsync
      return
    end
    self.set_sent = false
    self.set_state("check")
    pi("WIFI_CHECK " + self.creds_json())
  end

  # à appeler pour chaque ligne reçue du Pi ; renvoie true si traitée
  def on_line(line)
    if string.find(line, "WIFI_CRED ") == 0
      var c = json.load(line[10..])
      if c != nil self.pi_ssid = c.find("ssid") end
      return false
    elif string.find(line, "WIFI_OK ") == 0 || line == "WIFI_NONE"
      self.pi_link = (line == "WIFI_NONE") ? "" : line[8..]
      if self.wait_link         # le Wi-Fi du Pi est stabilisé : on peut comparer
        self.wait_link = false
        tasmota.remove_timer("wifisync")
        tasmota.set_timer(500, / -> self.check(), "wifisync")
      end
      return false
    elif line == "READY"
      # au démarrage du Pi, son Wi-Fi n'est pas encore prêt : on attend WIFI_OK /
      # WIFI_NONE (au plus 30 s côté Pi), avec un filet de sécurité à 45 s
      self.wait_link = true
      tasmota.remove_timer("wifisync")
      tasmota.set_timer(45000, def () self.wait_link = false self.check() end, "wifisync")
      return false              # READY reste utile au reste du programme
    elif line == "WIFI_WAIT"
      self.set_state("wait")
      tasmota.remove_timer("wifisync")
      tasmota.set_timer(15000, / -> self.check(), "wifisync")
    elif line == "WIFI_SAME"
      self.set_state("same")
    elif line == "WIFI_DIFF"
      if self.set_sent
        self.set_state("fail")  # déjà tenté : on ne boucle pas
      else
        self.set_sent = true
        self.set_state("diff")
        pi("WIFI_SET " + self.creds_json())
      end
    elif line == "WIFI_SET_START"
      self.set_state(self.pending != nil ? "apply" : "set")
    elif line == "WIFI_SET_OK"
      if self.pending != nil
        self.finish_apply()
      else
        self.set_state("ok")
      end
    elif line == "WIFI_SET_FAIL" || line == "ERR WIFI_SET" || line == "ERR WIFI_CHECK"
      if self.pending != nil
        self.pending = nil
        tasmota.remove_timer("wifisync_to")
        self.last_error = "Wrong SSID or password. Nothing changed."
      end
      self.set_state("fail")
    else
      return false
    end
    return true
  end

  # ---------- changement de réseau (page /wsync) ----------

  # Renvoie nil, ou un message d'erreur.
  def apply(ssid, psk)
    if ssid == nil ssid = "" end
    if psk == nil psk = "" end
    if self.pending != nil return "Change already in progress." end
    if size(ssid) == 0 || size(ssid) > 32 || ssid == "1" return "Invalid SSID." end
    if size(psk) < 8 || size(psk) > 63 return "Password: 8 to 63 characters." end
    self.last_error = nil
    self.pending = [ssid, psk]
    self.set_state("apply")
    pi("WIFI_SET " + json.dump({"ssid": ssid, "psk": psk}))
    tasmota.remove_timer("wifisync_to")
    tasmota.set_timer(90000, / -> self.apply_timeout(), "wifisync_to")
    return nil
  end

  def apply_timeout()
    if self.pending == nil return end
    self.pending = nil
    self.last_error = "No reply from streamer. Nothing changed."
    self.set_state("fail")
  end

  def finish_apply()
    var ssid = self.pending[0]
    var psk = self.pending[1]
    self.pending = nil
    tasmota.remove_timer("wifisync_to")
    persist.wifi_ssid = ssid
    persist.wifi_psk = psk
    persist.save()
    self.set_state("restart")
    # petit délai pour que la page web affiche le résultat avant le redémarrage
    tasmota.set_timer(4000, def ()
      tasmota.cmd("SSId1 " + ssid, true)
      tasmota.cmd("Password1 " + psk, true)      # Tasmota redémarre ensuite
      # appliqué depuis le point d'accès : on revient aussi au défaut WifiConfig 4,
      # dans le même redémarrage (voir settings_ui.be)
      if persist.find("ap_mode")
        tasmota.cmd("WifiConfig 4", true)
        persist.remove("ap_mode")               # redémarrage vers le nouveau réseau, pas vers l'AP
        persist.save()
      end
    end, "wifisync_rs")
  end

  # ---------- commande console (secours) ----------
  #   WifiSync ssid|motdepasse  -> mémorise la copie (réseau actuel de l'ESP) et contrôle
  #   WifiSync                  -> relance le contrôle
  #   WifiSync clear            -> efface la copie
  def cmd_wifisync(cmd, idx, payload)
    if payload == nil || payload == ""
      self.check()
    elif payload == "clear"
      persist.remove("wifi_ssid")
      persist.remove("wifi_psk")
      persist.save()
      self.set_state("noconf")
    else
      var i = string.find(payload, "|")
      if i <= 0
        tasmota.resp_cmnd_error()
        return
      end
      var ssid = payload[0 .. i - 1]
      var psk = payload[i + 1 ..]
      if size(ssid) > 32 || (size(psk) > 0 && size(psk) < 8) || size(psk) > 64
        tasmota.resp_cmnd_error()
        return
      end
      persist.wifi_ssid = ssid
      persist.wifi_psk = psk
      persist.save()
      self.check()
    end
    # réponse sans le mot de passe (la console web est lisible sur le réseau)
    tasmota.resp_cmnd(json.dump({"WifiSync": self.state,
                                 "SSID": persist.find("wifi_ssid", "")}))
  end
end

wifisync = WifiSync()
