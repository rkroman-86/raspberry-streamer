# main_prog.be — interface ESP du Raspberry Streamer
# Prerequis : pizero_uart.be charge AVANT ce fichier (fournit pi())
#   autoexec.be :  load("pizero_uart.be")
#                  load("main_prog.be")
# Charge aussi wifi_sync.be (synchro Wi-Fi ESP <-> Pi) et web_ui.be
# (pages web /wsync et /player), a placer a cote sur le systeme de fichiers.

import persist
import string
import json
import haspmota

# global.xxx partout : ces objets n'existent qu'apres load(), et un module en
# erreur ne doit pas empecher l'ecran de fonctionner
try load("wifi_sync.be") except .. as e, m print("wifi_sync.be :", e, m) end
try load("web_ui.be")    except .. as e, m print("web_ui.be :", e, m)    end
try load("settings_ui.be") except .. as e, m print("settings_ui.be :", e, m) end   # objet global settings_ui
try load("boot_ui.be")     except .. as e, m print("boot_ui.be :", e, m)     end   # objet global boot_ui

try
  var top = lv.layer_top()
  top.clear_flag(lv.OBJ_FLAG_SCROLLABLE)
  top.clear_flag(lv.OBJ_FLAG_SCROLL_ELASTIC)
except .. as e, m
  print("scroll fix:", e, m)
end

# ---------------------------------------------------------------
# Donnees persistantes
# ---------------------------------------------------------------
var NB_FAV     = 10
var fav_list   = persist.find("Fav", [])
var last_radio = persist.find("LastRadio", {"name":"", "url":""})
var NB_RECENT  = 3
var recent     = persist.find("Recent", [])     # [{"name","url","thumb"}], la plus recente en tete
if size(recent) == 0 && last_radio["url"] != ""
  recent.push({"name":last_radio["name"], "url":last_radio["url"], "thumb":""})
end
while size(recent) > NB_RECENT  recent.pop()  end

# garantit NB_FAV emplacements (SaveFav ecrit dans un emplacement existant)
while size(fav_list) < NB_FAV
  fav_list.push({"name":"", "url":""})
end

def save_data()
  persist.Fav = fav_list
  persist.LastRadio = last_radio
  persist.Recent = recent
  persist.save()
end

# ---------------------------------------------------------------
# Telechargement d'images (pochette, vignettes des stations)
# ---------------------------------------------------------------
import path

var COVER_DIR     = "/A/"                 # meme dossier que les icones
var COVER_DEFAULT = "A/cover_default.png" # 200x200

# nom de fichier unique par image (hash du Pi dans l'URL) : LVGL garde les images
# decodees en cache par chemin, reutiliser un meme nom afficherait l'ancienne
def img_name(prefix, url)
  return prefix + string.split(url, "/").pop()
end

# Reseau pret : Wi-Fi connecte depuis au moins 10 s. Avant, aucun telechargement
# (pochette DLNA au demarrage, Wi-Fi pas encore stable -> plantage de l'ESP)
var NET_DELAY = 10000
var net_up_ms = 0         # instant de la connexion Wi-Fi (0 = pas connecte)
def net_ready()
  var up = tasmota.wifi().find("up", false)
  if !up  net_up_ms = 0  return false  end
  if net_up_ms == 0  net_up_ms = tasmota.millis()  end
  return tasmota.millis() - net_up_ms >= NET_DELAY
end

# telecharge url dans COVER_DIR + name ; renvoie true si le fichier est ecrit
def img_download(url, name)
  if string.find(url, "http://") != 0  return false  end   # chemin relatif (Pi sans IP au demarrage)
  var cl = webclient()
  cl.set_timeouts(2000, 3000)
  cl.begin(url)
  var r = cl.GET()
  var ok = false
  if r == 200
    ok = cl.write_file(COVER_DIR + name) > 0
  end
  cl.close()
  if !ok  print("image: failed " + str(r) + " " + url)  end
  return ok
end

# ---------------------------------------------------------------
# 3 dernieres stations, page webradio (p1b51..53 = vignettes, p1b61..63 = boutons 60x60 avec cadre)
# Chaque vignette est un objet 200x200 reduit a 60 px (scale 77) et centre
# sur son bouton : LVGL zoome autour du centre de l'objet.
# ---------------------------------------------------------------
var RECENT_SCALE = 77     # 200 px -> 60 px (77/256 x 200)

def recent_show()
  if global.p1b61 == nil
    tasmota.set_timer(1000, recent_show, "recent_show")   # pages pas encore chargees
    return
  end
  for i: 0..NB_RECENT-1
    var img = global.("p1b" + str(51 + i))
    var btn = global.("p1b" + str(61 + i))
    if i < size(recent)
      var th = recent[i].find("thumb", "")
      var name = (th != "") ? img_name("rs_", th) : ""
      img.src = (name != "" && path.exists(COVER_DIR + name)) ? "A/" + name : COVER_DEFAULT
      img.scale = RECENT_SCALE
      img.hidden = false
      btn.hidden = false
    else
      img.hidden = true
      btn.hidden = true
    end
  end
end

# telecharge les vignettes manquantes, supprime celles qui ne servent plus, affiche
def recent_sync()
  if !net_ready()
    tasmota.set_timer(1000, recent_sync, "recent_sync")   # reseau pas encore pret
    return
  end
  var keep = {}
  for r : recent
    var th = r.find("thumb", "")
    if th != ""
      var name = img_name("rs_", th)
      keep[name] = true
      if !path.exists(COVER_DIR + name)  img_download(th, name)  end
    end
  end
  for f : path.listdir(COVER_DIR)
    if string.find(f, "rs_") == 0 && !keep.contains(f)  path.remove(COVER_DIR + f)  end
  end
  recent_show()
end

# place la station en tete de liste (sans doublon), garde les NB_RECENT dernieres
def recent_add(name, url, thumb)
  var nl = [{"name":name, "url":url, "thumb":thumb}]
  for r : recent
    if r["url"] != url && size(nl) < NB_RECENT  nl.push(r)  end
  end
  recent = nl
  tasmota.set_timer(0, recent_sync)
end

# ---------------------------------------------------------------
# Lecture webradio (le Pi decode, l'ESP ne fait que commander)
# ---------------------------------------------------------------
var last_play_url = ""
var last_play_ms = 0

def play_radio(name, url)
  if url == ""  return  end
  # anti-doublon : meme URL demandee 2 fois en moins de 1,5 s (rebond tactile,
  # double evenement) -> un seul PLAY, sinon le Pi relance le flux 2 fois
  var now = tasmota.millis()
  if url == last_play_url && now - last_play_ms < 1500
    print("play ignored (duplicate) " + url)
    return
  end
  last_play_url = url
  last_play_ms = now
  pi("PLAY " + url)
  var skc = global.show_known_cover        # defini plus bas
  if skc != nil  skc(url)  end
  print("play " + name + " " + url)
  # la memorisation se fait a la reception du STATUS (voir track_last_radio),
  # quelle que soit l'origine de la lecture
end

# memorise la station 5 s apres le debut de lecture (derniere + liste des recentes) ;
# le timer nomme est remplace a chaque zapping, seule la derniere station reste
def track_last_radio(st)
  var f = st.find("file", "")
  if st.find("source") != "webradio" || st.find("state") != "play"  return  end
  if f == "" || f == last_radio["url"]  return  end
  var nm = st.find("station", "")
  if nm == ""  nm = "web"  end
  var th = st.find("thumb", "")
  tasmota.set_timer(5000, def ()
    last_radio = {"name":nm, "url":f}
    recent_add(nm, f, th)
    save_data()
    print("last radio -> " + nm)
  end, "save_last_radio")
end

# ---------------------------------------------------------------
# Pochette : meme image et meme case 180x180 en (0,80) sur les pages webradio
# (p1b2), AirPlay (p3b2) et Spotify (p4b2), cadre pb6 par-dessus. Chaque pb2 est
# un objet 200x200 (taille des vignettes du Pi) reduit a 180 px (scale 230)
# et centre sur la case : x=-10, y=70.
# ---------------------------------------------------------------
var COVERS = {"p1b2": 230, "p3b2": 230, "p4b2": 230, "p5b2": 230}   # 200 px -> 180 px
var COVER_KEY = {"webradio": "p1b2", "airplay": "p3b2", "spotify": "p4b2", "dlna": "p5b2"}
var cover_url   = ""   # derniere pochette demandee ("page|url")
var cover_shown = {}   # page -> image affichee (evite de redessiner pour rien)

def cover_set(k, src)
  if cover_shown.find(k) == src  return false  end
  var o = global.(k)
  if o == nil  return false  end
  o.src = src
  o.scale = COVERS[k]                     # vignettes et pochette par defaut font 200x200
  cover_shown[k] = src
  return true
end

# pochette sur la page de la source (key) ; les pages AirPlay / Spotify des autres
# sources repassent a la pochette par defaut. La page webradio garde sa derniere station.
def cover_show(src, key)
  var changed = false
  for k : COVERS.keys()
    if k == key
      if cover_set(k, src)  changed = true  end
    elif k != "p1b2"
      if cover_set(k, COVER_DEFAULT)  changed = true  end
    end
  end
  if !changed  return  end
  # menage : fichiers cv_ qui ne sont plus affiches sur aucune page
  for f : path.listdir(COVER_DIR)
    if string.find(f, "cv_") == 0
      var used = false
      for k : cover_shown.keys()
        if cover_shown[k] == "A/" + f  used = true  end
      end
      if !used  path.remove(COVER_DIR + f)  end
    end
  end
end

def cover_fetch(url, key)
  if key + "|" + url != cover_url  return  end   # une pochette plus recente est deja demandee
  if !net_ready()                                 # reseau pas encore pret : on reessaie
    tasmota.set_timer(1000, def () cover_fetch(url, key) end, "cover_fetch")
    return
  end
  var name = img_name("cv_", url)
  if img_download(url, name)
    cover_show("A/" + name, key)
  else
    cover_show(COVER_DEFAULT, key)
  end
end

# STATUS ampute (octets perdus sur l'UART pendant que l'ESP etait occupe) :
# l'adresse de vignette ne finit plus par une extension d'image
def thumb_ok(url)
  return url == "" || string.find(url, "http://") != 0 ||
         string.endswith(url, ".png") || string.endswith(url, ".jpg")
end

def update_cover(st)
  var url = st.find("thumb", "")
  if !thumb_ok(url)
    print("STATUS incomplet, nouvelle demande")
    tasmota.set_timer(2000, def () pi("STATUS") end, "status_again")
    return
  end
  var src = st.find("source", "")
  var key = COVER_KEY.find(src)
  if key == nil                           # Bluetooth, DLNA... : pas de pochette a suivre
    cover_url = ""
    cover_show(nil, nil)                  # pages AirPlay / Spotify : pochette par defaut
    return
  end
  if key + "|" + url == cover_url  return  end
  cover_url = key + "|" + url
  if string.find(url, "http://") != 0
    cover_show(COVER_DEFAULT, key)        # pas de pochette, chemin relatif
  else
    tasmota.set_timer(0, def () cover_fetch(url, key) end)   # hors de la lecture UART
  end
end

# au lancement d'une radio deja ecoutee : affiche tout de suite sa vignette
# (stations recentes), sans attendre le STATUS du Pi
def show_known_cover(url)
  for r : recent
    if r["url"] == url
      var th = r.find("thumb", "")
      if th != ""
        var name = img_name("rs_", th)
        if path.exists(COVER_DIR + name)  cover_show("A/" + name, "p1b2")  end
      end
      return
    end
  end
end

# menage au demarrage : pochettes laissees par la session precedente
for f : path.listdir(COVER_DIR)
  if string.find(f, "cv_") == 0  path.remove(COVER_DIR + f)  end
end

# ---------------------------------------------------------------
# Volume (p0b5 : slider en bas de l'ecran, 0..100)
# ---------------------------------------------------------------
var vol_dragging = false   # doigt pose sur le slider
var vol_local_ts = 0       # dernier changement de volume fait depuis l'ESP
var vol_sent_ts  = 0       # dernier envoi au Pi (limite le debit pendant le glisser)
var vol_last     = -1      # dernier volume connu du Pi

# envoie le volume au Pi ; pendant le glisser, au plus un envoi toutes les 200 ms
def vol_send(v, force)
  var now = tasmota.millis()
  vol_local_ts = now
  if v == vol_last  return  end
  if !force && now - vol_sent_ts < 200  return  end
  vol_sent_ts = now
  vol_last = v
  pi("VOL " + str(v))
end

# volume venant du Pi (STATUS) : place le slider, sauf si l'utilisateur le manipule
def update_volume(st)
  var v = st.find("vol")
  if v == nil  return  end                                  # renderer : pas de volume MPD
  if vol_dragging  return  end
  if tasmota.millis() - vol_local_ts < 1500  return  end   # evite le rebond pendant que le Pi applique
  vol_last = v
  var s = global.p0b5
  if s != nil && s.val != v
    s.val = v                                               # changement par code : pas d'evenement
  end
end

tasmota.add_rule("hasp#p0b5#event=down", def (value, trigger, msg)
  vol_dragging = true
end)

tasmota.add_rule("hasp#p0b5#event=changed", def (value, trigger, msg)
  vol_send(global.p0b5.val, false)
end)

tasmota.add_rule("hasp#p0b5#event=up", def (value, trigger, msg)
  vol_dragging = false
  vol_send(global.p0b5.val, true)                           # valeur finale, toujours envoyee
end)

# ---------------------------------------------------------------
# Page 0 (toujours visible) :
#   p0b1 = bouton play/stop (reflete l'etat du Pi)   (case du milieu libre)
#   p0b4 = icone 80x80 de la source active, p0b3 = bouton transparent par-dessus
#   p0b5 = slider de volume (bas de l'ecran)
# Une page par source, affichee automatiquement :
#   p1 webradio (pochette p1b2 + 3 dernieres stations)   p2 Bluetooth
#   p3 AirPlay / p4 Spotify (pochette pb2, titre pb10, artiste pb11)   p5 DLNA
# Fenetre des sources (cachee par defaut) :
#   p0b19 = voile plein ecran   p0b20 = panneau   p0b22 = croix de fermeture
#   p0b31..p0b35 = tuiles des sources (icones p0b41..45)   p0b36 = tuile reglages
# ---------------------------------------------------------------
var SOURCES    = ["webradio","spotify","airplay","dlna","bluetooth"]   # ordre des tuiles 31..35
var cur_source = ""
var SRC_PAGE   = {"webradio":1, "bluetooth":2, "airplay":3, "spotify":4, "dlna":5}
var RENDERERS  = ["airplay","spotify","bluetooth"]   # lecture lancee depuis le telephone
var cur_page   = 1
var play_state = "stop"     # dernier etat de lecture du Pi

# les pages 1..5 ne doivent pas defiler (images 200x200 qui depassent la case),
# comme la page 0 (voir le correctif layer_top en debut de fichier)
def pages_no_scroll()
  for n : 1..5
    var scr = nil
    try  scr = global.("p" + str(n) + "b0")._lv_obj  except .. as e  end
    if scr == nil
      try  scr = haspmota.lvh_pages[n].get_scr()  except .. as e  end
    end
    if scr != nil
      scr.clear_flag(lv.OBJ_FLAG_SCROLLABLE)
      scr.clear_flag(lv.OBJ_FLAG_SCROLL_ELASTIC)
    else
      print("no_scroll: page " + str(n) + " introuvable")
    end
  end
end

def page_show(n)
  if n == nil || n == cur_page  return  end
  try
    haspmota.page_show("p" + str(n))
    cur_page = n
  except .. as e, m
    print("page_show:", e, m)
  end
end

# bouton play/stop : stop rouge pendant la lecture ; play vert a l'arret,
# gris pour AirPlay / Spotify / Bluetooth (la lecture se lance du telephone)
def play_btn_show()
  var b = global.p0b1
  if b == nil  return  end
  if play_state == "play"
    b.text = "\uf04d"
    b.text_color = "#FF6B6B"
  elif RENDERERS.find(cur_source) != nil
    b.text = "\uf04b"
    b.text_color = "#555555"
  else
    b.text = "\uf04b"
    b.text_color = "#00C853"
  end
end

# Ligne sous la case (pb10), sans defilement : les infos s'affichent a tour de role,
# en commencant par la premiere, puis changent toutes les ROTATE_MS :
#   webradio  : station, titre
#   AirPlay / Spotify : artiste - titre, album
#   Bluetooth : artiste - titre, album, appli   (nom de l'appareil dans la case : p2b11)
var ROTATE_MS = 4000
var LINES  = {}     # "p1b10" -> {"parts": [...], "key": "..."}
var line_i = 0

def set_line(o, t)
  if o != nil && o.text != t  o.text = t  end
end

def set_parts(name, parts)
  var clean = []
  for p : parts
    if p != nil && p != ""  clean.push(p)  end
  end
  var key = clean.concat("\n")
  var cur = LINES.find(name)
  if cur != nil && cur["key"] == key  return  end       # rien de nouveau : on ne coupe pas la rotation
  LINES[name] = {"parts": clean, "key": key}
  set_line(global.(name), size(clean) > 0 ? clean[0] : "")
end

def rotate_lines()
  line_i += 1
  for name : LINES.keys()
    var ps = LINES[name]["parts"]
    if size(ps) > 1  set_line(global.(name), ps[line_i % size(ps)])  end
  end
  tasmota.set_timer(ROTATE_MS, rotate_lines, "rotate_lines")
end
tasmota.set_timer(ROTATE_MS, rotate_lines, "rotate_lines")

def update_track(st)
  var src = st.find("source", "")
  var t = st.find("title", "")
  var a = st.find("artist", "")
  var at = (a != "" && t != "") ? a + " - " + t : a + t
  if src == "webradio"
    set_parts("p1b10", [st.find("station", ""), t])
  elif src == "airplay" || src == "spotify"
    set_parts(src == "airplay" ? "p3b10" : "p4b10", [at, st.find("album", "")])
  elif src == "dlna"
    set_parts("p5b10", (at == "" && st.find("album", "") == "") ? ["DLNA"] : [at, st.find("album", "")])
  elif src == "bluetooth"
    var parts = [at, st.find("album", ""), st.find("app", "")]
    set_parts("p2b10", (at == "" && st.find("album", "") == "" && st.find("app", "") == "") ? ["Bluetooth"] : parts)
    set_line(global.p2b11, st.find("station", ""))
  end
end

# p0b19 (voile opaque) contient le panneau p0b20 : un seul objet a montrer / cacher,
# et rien a redessiner dessous (pochette agrandie) -> affichage d'un coup
def popup_show(visible)
  var v = global.p0b19
  if v == nil || v.hidden == !visible  return  end
  v.hidden = !visible
end

# Pi sans Wi-Fi (WIFI_NONE) ou sans internet stable (NET_KO) : image "Wi-Fi barre"
# (p0b7, page 0) a la place de la pochette, sauf en Bluetooth qui n'a pas besoin du reseau
var pi_wifi = true          # inconnus au demarrage : consideres en ligne
var pi_net  = true
def nowifi_show()
  var o = global.p0b7
  if o != nil  o.hidden = (pi_wifi && pi_net) || cur_source == "bluetooth"  end
end

# Mode de lecture (file MPD : DLNA). Le Pi l'indique dans chaque STATUS ("mode"),
# d'apres les reglages reels de MPD : le bouton suit aussi les changements faits
# depuis le telephone ou moOde. Un appui passe au mode suivant.
var MODES     = ["loop_all", "all_once", "random", "one_loop", "one_once"]
# une ligne, police montserrat-28 (celle du bouton play) : montserrat-20 absente -> plantage
var MODE_TEXT = {"loop_all": "\uf079", "all_once": "\uf00b", "random": "\uf074",
                 "one_loop": "\uf0791", "one_once": "\uf00b1"}
var play_mode = "loop_all"
var mode_shown = "loop_all"      # texte initial du bouton dans pages.jsonl
# ne lit jamais le texte du bouton (lecture du widget au demarrage -> plantage LVGL) :
# la valeur affichee est gardee ici, le widget n'est touche que si elle change
def mode_show()
  if play_mode == mode_shown || tasmota.millis() < 15000  return  end
  var b = global.p5b72
  if b == nil  return  end
  mode_shown = play_mode
  b.text = MODE_TEXT.find(play_mode, "?")
end

# affiche la source active sur l'icone du bouton du haut
def set_source(src)
  if global.p0b3 == nil  return  end     # pages HASPmota pas encore chargees
  var i = SOURCES.find(src)
  if i == nil  return  end
  cur_source = src
  global.p0b4.src = "A/src_" + src + ".png"
  page_show(SRC_PAGE.find(src))
  play_btn_show()
  nowifi_show()
end

# Changement de source vu dans un STATUS : applique seulement s'il n'est pas
# contredit dans les 2,5 s. Au branchement du Bluetooth, le Pi envoie d'abord
# un STATUS perime (webradio) puis le bon 2 s plus tard : evite un aller-retour.
var src_pending = ""
def src_confirm(src)
  if src == src_pending  return  end
  src_pending = src
  tasmota.remove_timer("src_confirm")
  tasmota.set_timer(2500, def ()
    if src_pending == src && src != cur_source
      print("source detected -> " + src)
      set_source(src)
    end
    src_pending = ""
  end, "src_confirm")
end

def src_cancel()
  if src_pending == ""  return  end
  src_pending = ""
  tasmota.remove_timer("src_confirm")
end

# noms de source du bridge qui ne correspondent pas directement a une tuile
var SRC_ALIAS = {"upnp":"dlna"}
var manual_ts = 0      # instant du dernier choix manuel de source
var got_status = false # un STATUS a-t-il ete affiche depuis le demarrage ?

# appele par pizero_uart.be pour CHAQUE ligne recue du Pi, avant tout autre traitement ;
# renvoie true si la ligne est consommee (lignes WIFI_* de la synchro)
on_pi_line = def (line)
  if line == "ERR DLNA_RESUME"                            # pas de lecture DLNA a reprendre
    set_parts("p5b10", ["Pick music on the phone"])
    return true
  end
  if line == "WIFI_NONE"
    pi_wifi = false
    nowifi_show()
  elif string.find(line, "WIFI_OK ") == 0
    pi_wifi = true
    nowifi_show()
  elif line == "NET_KO" || line == "NET_OK"
    pi_net = (line == "NET_OK")
    nowifi_show()
    return true
  end
  var bu = global.boot_ui
  if bu != nil && bu.on_line(line)  return true  end     # BOOT <pct> : jauge de demarrage
  var ws = global.wifisync
  return ws != nil && ws.on_line(line)
end

# appele par pizero_uart.be a chaque STATUS recu du Pi
on_status = def (st)
  var wu = global.webui
  if wu != nil  wu.status = st  end                       # page /player
  var ud = global.ui_drv
  if ud != nil  ud.on_status(st)  end                     # page /ui (logo, historique)
  if global.p0b3 != nil  got_status = true  end           # ecran pret : etat affiche
  if global.p1b2 != nil  update_cover(st)  end
  update_volume(st)
  update_track(st)
  var md = st.find("mode")
  if md != nil && md != play_mode
    play_mode = md
    mode_show()
  end
  track_last_radio(st)
  play_state = st.find("state", "stop")
  play_btn_show()
  if play_state == "stop"  return  end                    # on ne suit que play / pause
  if tasmota.millis() - manual_ts < 2000  return  end     # laisse le temps au STOP de passer
  var src = st.find("source", "")
  src = SRC_ALIAS.find(src, src)
  if src == cur_source
    src_cancel()                                          # STATUS precedent contredit
  elif SOURCES.find(src) != nil
    src_confirm(src)
  end
end

# choix d'une source dans la fenetre
def select_source(i)
  popup_show(false)
  var src = SOURCES[i]
  print("source -> " + src)
  manual_ts = tasmota.millis()
  src_cancel()
  if src == "webradio"
    play_radio(last_radio["name"], last_radio["url"])
  elif src == "dlna"
    pi("DLNA_RESUME")             # derniere lecture DLNA (dossier, morceau, position, mode)
  else
    pi("STOP")
  end
  set_source(src)
end

# boutons des stations recentes
def mk_recent(i)
  return def (value, trigger, msg)
    if i >= size(recent)  return  end
    manual_ts = tasmota.millis()
    play_radio(recent[i]["name"], recent[i]["url"])
    set_source("webradio")
  end
end

for i: 0..NB_RECENT-1
  tasmota.add_rule("hasp#p1b" + str(61 + i) + "#event=up", mk_recent(i))
end

def mk_tile(i)
  return def (value, trigger, msg)
    select_source(i)
  end
end

for i: 0..size(SOURCES)-1
  tasmota.add_rule("hasp#p0b" + str(31 + i) + "#event=up", mk_tile(i))
end

# ouverture / fermeture de la fenetre
tasmota.add_rule("hasp#p0b3#event=up",  def (value, trigger, msg) popup_show(true)  end)
tasmota.add_rule("hasp#p0b22#event=up", def (value, trigger, msg) popup_show(false) end)
tasmota.add_rule("hasp#p0b19#event=up", def (value, trigger, msg) popup_show(false) end)   # toucher hors du panneau

# tuile reglages : ferme la fenetre des sources, puis ouvre la fenetre Reglages
tasmota.add_rule("hasp#p0b36#event=up", def (value, trigger, msg)
  popup_show(false)
  var su = global.settings_ui
  if su != nil  su.open()  end
end)

# bouton play/stop :
#   en lecture : STANDBY (coupe aussi AirPlay / Spotify / Bluetooth cote Pi)
#   a l'arret  : webradio -> derniere radio ; DLNA -> reprise de la file MPD ;
#                AirPlay / Spotify / Bluetooth -> rien (lance depuis le telephone)
# L'ecran n'est pas touche : le dimming de pages.jsonl s'en occupe.
tasmota.add_rule("hasp#p0b1#event=up", def (value, trigger, msg)
  if play_state == "play" && cur_source == "dlna"
    pi("PAUSE")                                           # morceaux : pause, Play reprend au meme endroit
    play_state = "pause"
    play_btn_show()
  elif play_state == "play"
    pi("STANDBY")
    play_state = "stop"                                   # retour immediat, le STATUS confirmera
    play_btn_show()
  elif cur_source == "webradio" || cur_source == ""
    manual_ts = tasmota.millis()
    play_radio(last_radio["name"], last_radio["url"])
    set_source("webradio")
  elif cur_source == "dlna"
    pi("DLNA_RESUME")                                     # reprise, ou derniere lecture DLNA
  elif RENDERERS.find(cur_source) == nil
    pi("PLAY")
  end
end)

# page DLNA : precedent / mode / suivant
tasmota.add_rule("hasp#p5b71#event=up", def (value, trigger, msg) pi("PREV") end)
tasmota.add_rule("hasp#p5b73#event=up", def (value, trigger, msg) pi("NEXT") end)
tasmota.add_rule("hasp#p5b72#event=up", def (value, trigger, msg)
  var i = MODES.find(play_mode)
  play_mode = MODES[((i == nil) ? 0 : i + 1) % size(MODES)]
  mode_show()                                             # retour immediat, le STATUS confirmera
  pi("MODE " + play_mode)
end)
tasmota.set_timer(16000, mode_show)                       # mode recu pendant le demarrage

# ---------------------------------------------------------------
# Commandes Tasmota (memes noms qu'avant pour l'interface web)
# ---------------------------------------------------------------
def cmd_play(cmd, idx, payload, raw)
  play_radio(last_radio["name"], last_radio["url"])
  set_source("webradio")
  tasmota.resp_cmnd_done()
end

def cmd_stop(cmd, idx, payload, raw)
  pi("STOP")
  tasmota.resp_cmnd_done()
end

def cmd_vol(cmd, idx, payload, raw)
  var v = int(payload)
  if v >= 0 && v <= 100
    vol_send(v, true)
    if global.p0b5 != nil  global.p0b5.val = v  end
    tasmota.resp_cmnd_done()
  else
    tasmota.resp_cmnd_error()
  end
end

def cmd_playfav(cmd, idx, payload, raw)
  var i = int(payload) - 1
  if i >= 0 && i < size(fav_list) && fav_list[i]["url"] != ""
    play_radio(fav_list[i]["name"], fav_list[i]["url"])
    set_source("webradio")
    tasmota.resp_cmnd_done()
  else
    tasmota.resp_cmnd_error()
  end
end

# payload : "nom||u=url"  ou  "url" seule
def cmd_playurl(cmd, idx, payload, raw)
  var parts = string.split(payload, "||u=")
  if size(parts) >= 2
    play_radio(parts[0], parts[1])
  else
    play_radio("web", payload)
  end
  set_source("webradio")
  tasmota.resp_cmnd_done()
end

# payload : "num=3||name=FIP||url=http://..." (segments dans n'importe quel ordre,
# les segments inconnus sont ignores ; l'url peut contenir des '=')
def cmd_savefav(cmd, idx, payload, raw)
  var num = 0
  var name = ""
  var url = ""
  for part : string.split(payload, "||")
    if string.startswith(part, "num=")
      num = int(part[4..])
    elif string.startswith(part, "name=")
      name = part[5..]
    elif string.startswith(part, "url=")
      url = part[4..]
    end
  end
  if num >= 1 && num <= size(fav_list) && url != ""
    fav_list[num-1] = {"name":name, "url":url}
    save_data()
    print("fav " + str(num) + " saved: " + name)
    tasmota.resp_cmnd_done()
  else
    tasmota.resp_cmnd_error()
  end
end

def cmd_getfav(cmd, idx, payload, raw)
  var out = []
  for i: 0..size(fav_list)-1
    out.push({"num":i+1, "name":fav_list[i]["name"], "url":fav_list[i]["url"]})
  end
  tasmota.resp_cmnd_str(json.dump(out))
end

tasmota.add_cmd("play",     cmd_play)
tasmota.add_cmd("playlast", cmd_play)
tasmota.add_cmd("stop",     cmd_stop)
tasmota.add_cmd("vol",      cmd_vol)
tasmota.add_cmd("playfav",  cmd_playfav)
tasmota.add_cmd("playurl",  cmd_playurl)
tasmota.add_cmd("savefav",  cmd_savefav)
tasmota.add_cmd("getfav",   cmd_getfav)

print("main_prog loaded: " + str(size(fav_list)) + " favorites, last radio = " + last_radio["name"])

# page web /ui (charge en dernier : utilise les fonctions et variables ci-dessus)
try load("/ui/ui.be") except .. as e, m print("ui/ui.be :", e, m) end

# Au demarrage de l'ESP : demande l'etat courant au Pi toutes les 3 s
# jusqu'a ce qu'un STATUS ait ete recu ET affiche (ecran charge).
# Couvre : Pi deja demarre (reponse immediate), Pi encore en boot
# (reponse des qu'il ecoute), pages HASPmota chargees en retard.
def boot_status()
  if got_status  return  end
  if global.p0b3 != nil
    pi("STATUS")
  end
  tasmota.set_timer(3000, boot_status, "boot_status")
end
tasmota.set_timer(1500, boot_status, "boot_status")
tasmota.set_timer(2000, recent_sync)      # vignettes des stations recentes

# defilement des pages 1..5 coupe des que HASPmota a charge les pages
def no_scroll_boot()
  if global.p1b2 == nil
    tasmota.set_timer(1000, no_scroll_boot, "no_scroll")
    return
  end
  pages_no_scroll()
end
tasmota.set_timer(1000, no_scroll_boot, "no_scroll")
