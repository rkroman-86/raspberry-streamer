/* WebRadio UI (Radio-Browser -> Tasmota I2S) */

const els = {
  searchInput: document.getElementById("searchInput"),
  searchBtn:   document.getElementById("searchBtn"),
  status:      document.getElementById("status"),
  results:     document.getElementById("results"),
  volInput:    document.getElementById("volInput"),
  volValue:    document.getElementById("volValue"),
  stopBtn:     document.getElementById("stopBtn"),
  playBtn:     document.getElementById("playBtn"),
  npStation:   document.getElementById("npStation"),
  npTrack:     document.getElementById("npTrack"),
  favBtn:      document.getElementById("favBtn"),
  modeBtn:     document.getElementById("modeBtn"),
};

const CFG = {
  RADIO_BROWSER_BYNAME: "https://de1.api.radio-browser.info/json/stations/byname/",
  LIMIT: 50,
  TITLE_POLL_MS: 10000,
  COOLDOWN_MS: 5000,
  VOLUME_DEBOUNCE_MS: 200,
  LOGO_SIZE_PX: 80,
  SCROLL_PX_PER_SEC: 45,
  SCROLL_MIN_S: 8,
  SCROLL_MAX_S: 24,
};

let isBusy = false;
let volTimer = null;
let titleTimer = null;

let currentStationName = "";
let currentStreamUrl = "";
let lastTrack = "";

// Modes: one, loop_one, all, loop_all, shuffle
const PLAY_MODES = [
  { id: "one",       icon: "①",  label: "Lire un" },
  { id: "all",       icon: "▶≡", label: "Lire tout" },
  { id: "loop_one",  icon: "🔂", label: "Boucle un" },
  { id: "loop_all",  icon: "🔁", label: "Boucle tout" },
  { id: "shuffle",   icon: "🔀", label: "Aléatoire" },
];
let playModeIndex = 0; // index dans PLAY_MODES

/* ---------------- Utils ---------------- */

function setStatus(msg, isError = false) {
  els.status.textContent = msg;
  els.status.style.color = isError ? "red" : "#333";
}

function baseUrl() {
  return window.location.protocol + "//" + window.location.host;
}

async function tasmotaCmd(cmd) {
  const url = `${baseUrl()}/cm?cmnd=${encodeURIComponent(cmd)}`;
  const resp = await fetch(url);
  return await resp.text();
}

function setButtonsEnabled(enabled) {
  document.querySelectorAll(".play-btn").forEach((btn) => {
    btn.disabled = !enabled;
  });
  els.stopBtn.disabled = !enabled;
}

/* ---------------- Mode de lecture ---------------- */

function updateModeBtn() {
  const m = PLAY_MODES[playModeIndex];
  if (els.modeBtn) {
    els.modeBtn.textContent = m.icon;
    els.modeBtn.title = m.label;
  }
}

function cyclePlayMode() {
  playModeIndex = (playModeIndex + 1) % PLAY_MODES.length;
  updateModeBtn();
  setStatus("Mode : " + PLAY_MODES[playModeIndex].label);
}

function currentMode() {
  return PLAY_MODES[playModeIndex].id;
}

/* ---------------- Playlist DLNA ---------------- */

async function sendPlaylist(items, startIndex) {
  if (!items || items.length === 0) return;
  const mode = currentMode();
  let payload = `mode=${mode}||index=${startIndex}`;
  items.forEach(item => {
    payload += `||url=${item.url}`;
  });
  try {
    await tasmotaCmd(`setplaylist ${payload}`);
    setStatus(`▶ ${items[startIndex].title}`);
    currentStationName = items[startIndex].title;
    currentStreamUrl   = items[startIndex].url;
    refreshNowPlaying();
  } catch(err) {
    setStatus("Erreur playlist : " + err.message, true);
  }
}

/* ---------------- Now Playing (Status 8) + Marquee ---------------- */

function setNowPlayingLine(elLine, labelText, valueText) {
  if (!elLine) return;

  const label   = elLine.querySelector(".np-label");
  const marquee = elLine.querySelector(".np-marquee");
  const textEl  = elLine.querySelector(".np-text");
  if (!label || !marquee || !textEl) return;

  const v = valueText || "";

  if (elLine.dataset.value === v && label.textContent === labelText) return;
  elLine.dataset.value = v;

  label.textContent = labelText;
  textEl.textContent = v;
  elLine.title = v;

  const apply = () => {
    marquee.classList.remove("is-scroll");
    marquee.style.removeProperty("--dx");
    marquee.style.removeProperty("--dur");

    textEl.style.transform = "translateX(0)";

    const boxW = marquee.clientWidth;
    const textW = textEl.scrollWidth;
    const overflow = textW - boxW;

    if (overflow > 2) {
      marquee.style.setProperty("--dx", `${-overflow}px`);

      const seconds = Math.max(
        CFG.SCROLL_MIN_S,
        Math.min(CFG.SCROLL_MAX_S, overflow / CFG.SCROLL_PX_PER_SEC)
      );

      marquee.style.setProperty("--dur", `${seconds}s`);
      marquee.classList.add("is-scroll");
    }
  };

  requestAnimationFrame(apply);
  setTimeout(() => requestAnimationFrame(apply), 150);
}

async function refreshNowPlaying() {
  try {
    const txt = await tasmotaCmd("Status 8");

    let obj = null;
    try { obj = JSON.parse(txt); } catch { obj = null; }

    const audio = (obj && obj.StatusSNS && obj.StatusSNS.Audio) ? obj.StatusSNS.Audio : {};
    const track = (audio && audio.Title) ? String(audio.Title) : "";

    const station = currentStationName ? currentStationName : "(aucune)";
    setNowPlayingLine(els.npStation, "Station :", station);

    if (track && track !== lastTrack) {
      lastTrack = track;
      setNowPlayingLine(els.npTrack, "Titre :", track);
    } else if (!track && lastTrack !== "") {
      lastTrack = "";
      setNowPlayingLine(els.npTrack, "Titre :", "(aucun)");
    }
  } catch (err) {
    console.error("refreshNowPlaying error:", err);
    setNowPlayingLine(els.npTrack, "Titre :", "(erreur de lecture)");
  }
}

function startNowPlayingPolling() {
  if (titleTimer) return;
  refreshNowPlaying();
  titleTimer = setInterval(refreshNowPlaying, CFG.TITLE_POLL_MS);
}

/* ---------------- Radio Browser Search ---------------- */

async function searchStations() {
  const q = els.searchInput.value.trim();
  els.results.innerHTML = "";

  if (!q) {
    setStatus("Tape un nom ou un mot-clé pour rechercher.");
    return;
  }

  setStatus("Recherche en cours...");
  try {
    const url =
      CFG.RADIO_BROWSER_BYNAME +
      encodeURIComponent(q) +
      `?hidebroken=true&limit=${CFG.LIMIT}`;

    const resp = await fetch(url);
    if (!resp.ok) throw new Error("HTTP " + resp.status);

    const data = await resp.json();

    const mp3Stations = data.filter(
      (st) => (st.codec || "").toString().toLowerCase() === "mp3"
    );

    if (mp3Stations.length === 0) {
      setStatus("Aucune station MP3 trouvée pour cette recherche.");
      return;
    }

    setStatus(mp3Stations.length + " station(s) MP3 trouvée(s).");
    renderResults(mp3Stations);
  } catch (err) {
    console.error(err);
    setStatus("Erreur lors de la recherche : " + err.message, true);
  }
}

/* ---------------- Render Stations ---------------- */

function mkStationLogo(st) {
  const img = document.createElement("img");

  img.style.setProperty("width",  CFG.LOGO_SIZE_PX + "px", "important");
  img.style.setProperty("height", CFG.LOGO_SIZE_PX + "px", "important");
  img.style.setProperty("max-width",  CFG.LOGO_SIZE_PX + "px", "important");
  img.style.setProperty("max-height", CFG.LOGO_SIZE_PX + "px", "important");
  img.style.setProperty("object-fit", "contain", "important");
  img.style.setProperty("display", "block", "important");

  img.setAttribute("width",  String(CFG.LOGO_SIZE_PX));
  img.setAttribute("height", String(CFG.LOGO_SIZE_PX));

  img.src = st.favicon || "";
  img.alt = "logo";
  img.onerror = () => { img.style.visibility = "hidden"; };

  return img;
}

function normalizeStreamUrl(st) {
  let streamUrl = st.url || st.url_resolved || "";
  if (!streamUrl) return "";

  if (streamUrl.startsWith("https://")) {
    streamUrl = "http://" + streamUrl.slice(8);
  }

  const qIndex = streamUrl.indexOf("?");
  if (qIndex !== -1) streamUrl = streamUrl.slice(0, qIndex);

  return streamUrl;
}

function renderResults(stations) {
  els.results.innerHTML = "";

  stations.forEach((st) => {
    const streamUrl = normalizeStreamUrl(st);
    if (!streamUrl) return;

    const card = document.createElement("div");
    card.className = "station";

    const top = document.createElement("div");
    top.className = "station-top";

    const img = mkStationLogo(st);

    const actions = document.createElement("div");
    actions.className = "station-actions-col";

    const playBtn = document.createElement("button");
    playBtn.className = "play-btn";
    playBtn.title = "Lire sur ESP";
    const playIcon = document.createElement("span");
    playIcon.className = "icon-play";
    playBtn.appendChild(playIcon);

    playBtn.addEventListener("click", () => {
      sendToTasmota(streamUrl, st.name || "");
    });

    const favBtn = document.createElement("button");
    favBtn.className = "fav-btn";
    favBtn.title = "Ajouter aux favoris";
    favBtn.textContent = "⭐";
    favBtn.style.fontSize = "16px";

    favBtn.addEventListener("click", () => {
      loadFavList();
    });

    actions.appendChild(playBtn);
    actions.appendChild(favBtn);

    top.appendChild(img);
    top.appendChild(actions);

    const info = document.createElement("div");
    info.className = "station-info";

    const nameEl = document.createElement("div");
    nameEl.className = "station-name";
    nameEl.textContent = st.name || "(sans nom)";

    const urlEl = document.createElement("div");
    urlEl.className = "station-url";
    urlEl.textContent = streamUrl;

    const bitrateEl = document.createElement("div");
    bitrateEl.className = "station-bitrate";
    bitrateEl.textContent = `bitrate: ${st.bitrate} kbps`;

    info.appendChild(nameEl);
    info.appendChild(urlEl);
    info.appendChild(bitrateEl);

    card.appendChild(top);
    card.appendChild(info);

    els.results.appendChild(card);
  });
}

/* ---------------- Controls (Play/Stop/Volume) ---------------- */

async function sendToTasmota(streamUrl, stationName) {
  currentStationName = stationName || "";
  currentStreamUrl = streamUrl || "";
  if (!streamUrl) {
    alert("URL de flux vide ou invalide.");
    return;
  }
  if (isBusy) return;
  isBusy = true;
  setButtonsEnabled(false);
  setStatus("Envoi de la commande à l'ESP...");
  try {
    const payload = `${stationName}||u=${streamUrl}`;
    const txt = await tasmotaCmd(`playurl ${payload}`);
    console.log("Réponse Tasmota:", txt);
    setStatus("Commande envoyée.");
    refreshNowPlaying();
  } catch (err) {
    console.error(err);
    setStatus("Erreur en envoyant la commande à l'ESP : " + err.message, true);
  } finally {
    setTimeout(() => {
      isBusy = false;
      setButtonsEnabled(true);
    }, CFG.COOLDOWN_MS);
  }
}

async function stopOnTasmota() {
  if (isBusy) return;
  isBusy = true;
  setButtonsEnabled(false);
  setStatus("Stop...");

  try {
    const txt = await tasmotaCmd("stop");
    console.log("Réponse Tasmota:", txt);
    setStatus("Lecture arrêtée.");

    currentStationName = "";
    currentStreamUrl = "";
    lastTrack = "";

    setNowPlayingLine(els.npStation, "Station :", "(aucune)");
    setNowPlayingLine(els.npTrack, "Titre :", "(aucun)");
  } catch (err) {
    console.error(err);
    setStatus("Erreur STOP : " + err.message, true);
  } finally {
    setTimeout(() => {
      isBusy = false;
      setButtonsEnabled(true);
    }, CFG.COOLDOWN_MS);
  }
}

function sendVolume(level) {
  tasmotaCmd(`vol ${level}`).catch((err) => {
    console.error(err);
    setStatus("Erreur en envoyant le volume : " + err.message, true);
  });
}

/* ---------------- Favoris ---------------- */

function renderFavList(favs) {
  els.results.innerHTML = "";
  favs.forEach((fav) => {
    const card = document.createElement("div");
    card.className = "station";

    const info = document.createElement("div");
    info.className = "station-info";

    const nameEl = document.createElement("div");
    nameEl.className = "station-name";
    nameEl.textContent = fav.num + ". " + (fav.name || "(vide)");

    const urlEl = document.createElement("div");
    urlEl.className = "station-url";
    urlEl.textContent = fav.url || "(aucune url)";

    const actions = document.createElement("div");
    actions.className = "station-actions-col";
    actions.style.flexDirection = "row";
    actions.style.gap = "20px";

    const playBtn = document.createElement("button");
    playBtn.className = "play-btn";
    playBtn.title = "Lire";
    const playIcon = document.createElement("span");
    playIcon.className = "icon-play";
    playBtn.appendChild(playIcon);
    playBtn.disabled = !fav.url;
    playBtn.addEventListener("click", () => {
      if (fav.url) sendToTasmota(fav.url, fav.name);
    });

    const saveBtn = document.createElement("button");
    saveBtn.className = "play-btn";
    saveBtn.title = "Sauvegarder station courante ici";
    saveBtn.textContent = "💾";
    saveBtn.style.fontSize = "16px";
    saveBtn.addEventListener("click", () => {
      if (!currentStreamUrl) {
        setStatus("Aucune station en cours.", true);
        return;
      }
      const cmd = `savefav num=${fav.num}||name=${currentStationName}||url=${currentStreamUrl}`;
      tasmotaCmd(cmd)
        .then(() => {
          setStatus(`Fav ${fav.num} sauvegardé : ${currentStationName}`);
          loadFavList();
        })
        .catch(err => setStatus("Erreur save fav : " + err.message, true));
    });

    const delBtn = document.createElement("button");
    delBtn.className = "play-btn";
    delBtn.title = "Supprimer ce favori";
    delBtn.textContent = "🗑️";
    delBtn.style.fontSize = "16px";
    delBtn.disabled = !fav.url;
    delBtn.addEventListener("click", () => {
      const cmd = `savefav num=${fav.num}||name=||url=`;
      tasmotaCmd(cmd)
        .then(() => {
          setStatus(`Fav ${fav.num} supprimé.`);
          loadFavList();
        })
        .catch(err => setStatus("Erreur suppression : " + err.message, true));
    });

    actions.appendChild(playBtn);
    actions.appendChild(saveBtn);
    actions.appendChild(delBtn);
    info.appendChild(nameEl);
    info.appendChild(urlEl);
    card.appendChild(actions);
    card.appendChild(info);
    els.results.appendChild(card);
  });
}

async function loadFavList() {
  try {
    const txt = await tasmotaCmd("getfav");
    console.log("getfav raw:", txt);
    const obj = JSON.parse(txt);
    let favs = [];
    if (obj.Command) {
      favs = JSON.parse(obj.Command);
    } else if (Array.isArray(obj)) {
      favs = obj;
    } else {
      const val = Object.values(obj).find(v => typeof v === "string");
      if (val) favs = JSON.parse(val);
    }
    renderFavList(favs);
  } catch (err) {
    console.error("loadFavList error:", err);
    setStatus("Erreur chargement favoris : " + err.message, true);
  }
}

/* ---------------- DLNA / UPnP Browser ---------------- */

const DLNA = {
  SOAP_URL: "/dlna",
  PAGE_SIZE: 20,   // 20 items/page : garde la réponse SOAP sous le plafond ~32 Ko de get_string() côté Berry
};

let dlnaNavStack = [{ id: "0", title: "🏠 Racine" }];
let dlnaCurrentId = "0";
let dlnaCurrentStart = 0;
let dlnaTotal = 0;
let dlnaCurrentItems = [];

let dlnaServers = [];        // [{name, url}, ...] découverts
let dlnaActiveCtrl = "";     // control URL du serveur actif

function buildSoapEnvelope(objectId, start, count) {
  // Filter restreint (dc:title,dc:creator,res) au lieu de "*" :
  // réduit fortement la taille de chaque item DIDL renvoyé par Windows Media,
  // ce qui évite la troncature de la réponse côté ESP32.
  return `<?xml version="1.0" encoding="utf-8" standalone="yes"?><s:Envelope s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><u:Browse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1"><ObjectID>${objectId}</ObjectID><BrowseFlag>BrowseDirectChildren</BrowseFlag><Filter>dc:title,dc:creator,res,@childCount</Filter><StartingIndex>${start}</StartingIndex><RequestedCount>${count}</RequestedCount><SortCriteria></SortCriteria></u:Browse></s:Body></s:Envelope>`;
}

async function browseRoot() {
  setStatus("Découverte DLNA...");
  els.results.innerHTML = `<div class="station"><div class="station-info"><div class="station-name">🔍 Recherche des serveurs…</div></div></div>`;
  try {
    const resp = await fetch('/dlna/discover');
    dlnaServers = await resp.json();
  } catch(e) {
    console.warn("discover failed:", e);
    dlnaServers = [];
  }
  renderServerList();
}

function renderServerList() {
  els.results.innerHTML = "";

  const title = document.createElement("div");
  title.className = "dlna-breadcrumb";
  title.textContent = "Serveurs DLNA trouvés :";
  els.results.appendChild(title);

  if (!dlnaServers || dlnaServers.length === 0) {
    const empty = document.createElement("div");
    empty.className = "station";
    empty.innerHTML = `<div class="station-info"><div class="station-name">Aucun serveur trouvé.</div></div>`;
    els.results.appendChild(empty);
    setStatus("Aucun serveur DLNA.", true);
    return;
  }

  setStatus(dlnaServers.length + " serveur(s) trouvé(s).");

  dlnaServers.forEach((srv) => {
    const card = document.createElement("div");
    card.className = "station dlna-folder";
    card.style.cursor = "pointer";

    const info = document.createElement("div");
    info.className = "station-info";

    const nameEl = document.createElement("div");
    nameEl.className = "station-name";
    nameEl.textContent = "🖥️ " + (srv.name || srv.url);

    const urlEl = document.createElement("div");
    urlEl.className = "station-url";
    urlEl.textContent = srv.url;

    info.appendChild(nameEl);
    info.appendChild(urlEl);
    card.appendChild(info);

    card.addEventListener("click", () => {
      dlnaActiveCtrl = srv.url;
      dlnaNavStack = [{ id: "0", title: "🏠 " + (srv.name || "Racine") }];
      dlnaCurrentId = "0";
      dlnaBrowse("0", 0);
    });

    els.results.appendChild(card);
  });
}

async function dlnaBrowse(objectId, startIndex) {
  dlnaCurrentId = objectId;
  dlnaCurrentStart = startIndex;
  els.results.innerHTML = `<div class="station"><div class="station-info"><div class="station-name">⏳ Chargement…</div></div></div>`;
  setStatus("Connexion au serveur DLNA…");

  try {
    const url = DLNA.SOAP_URL + "?ctrl=" + encodeURIComponent(dlnaActiveCtrl);
    const resp = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "text/xml;charset=utf-8",
        "Soapaction": '"urn:schemas-upnp-org:service:ContentDirectory:1#Browse"',
        "User-Agent": "Android/15 UPnP/1.0 BubbleUPnP/4.6.3",
        "Connection": "Keep-Alive"
      },
      body: buildSoapEnvelope(objectId, startIndex, DLNA.PAGE_SIZE)
    });

    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const text = await resp.text();
    dlnaRender(text, objectId, startIndex);

  } catch (err) {
    console.error("DLNA browse error:", err);
    setStatus("Erreur DLNA : " + err.message, true);
    els.results.innerHTML = `<div class="station"><div class="station-info"><div class="station-name" style="color:red">❌ ${err.message}</div></div></div>`;
  }
}

function dlnaRender(xmlText, objectId, startIndex) {
  const resultMatch = xmlText.match(/<Result[^>]*>([\s\S]*?)<\/Result>/i);
  if (!resultMatch) {
    setStatus("Réponse DLNA inattendue.", true);
    return;
  }

  const decoded = resultMatch[1]
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&apos;/g, "'");

  const totalMatch = xmlText.match(/<TotalMatches[^>]*>(\d+)<\/TotalMatches>/i);
  const countMatch = xmlText.match(/<NumberReturned[^>]*>(\d+)<\/NumberReturned>/i);
  dlnaTotal = totalMatch ? parseInt(totalMatch[1]) : 0;
  const returned = countMatch ? parseInt(countMatch[1]) : 0;

  setStatus(`${dlnaTotal} élément(s) — ${startIndex + 1}–${startIndex + returned}`);

  els.results.innerHTML = "";

  // Breadcrumb
  const bc = document.createElement("div");
  bc.className = "dlna-breadcrumb";

  // Crumb "Serveurs" -> revient à la liste des serveurs
  const srvCrumb = document.createElement("span");
  srvCrumb.className = "dlna-crumb";
  srvCrumb.textContent = "🖥️ Serveurs";
  srvCrumb.style.cursor = "pointer";
  srvCrumb.addEventListener("click", () => renderServerList());
  bc.appendChild(srvCrumb);

  const srvSep = document.createElement("span");
  srvSep.className = "dlna-sep";
  srvSep.textContent = " › ";
  bc.appendChild(srvSep);

  dlnaNavStack.forEach((item, i) => {
    if (i > 0) {
      const sep = document.createElement("span");
      sep.className = "dlna-sep";
      sep.textContent = " › ";
      bc.appendChild(sep);
    }
    const crumb = document.createElement("span");
    crumb.className = "dlna-crumb" + (i === dlnaNavStack.length - 1 ? " dlna-crumb-active" : "");
    crumb.textContent = item.title;
    if (i < dlnaNavStack.length - 1) {
      crumb.addEventListener("click", () => {
        dlnaNavStack = dlnaNavStack.slice(0, i + 1);
        dlnaBrowse(item.id, 0);
      });
    }
    bc.appendChild(crumb);
  });
  els.results.appendChild(bc);

  // Containers (dossiers)
  const contReg = /<container\b([^>]*)>([\s\S]*?)<\/container>/gi;
  let m;
  while ((m = contReg.exec(decoded)) !== null) {
    const attrs = m[1], inner = m[2];
    const idM = attrs.match(/id="([^"]+)"/);
    const titleM = inner.match(/<dc:title[^>]*>([^<]+)<\/dc:title>/i);
    const childM = attrs.match(/childCount="([^"]+)"/);
    if (!idM || !titleM) continue;

    const id = idM[1];
    const title = dlnaDecodeHtml(titleM[1]);
    const childCount = childM ? childM[1] : "?";

    const card = document.createElement("div");
    card.className = "station dlna-folder";
    card.style.cursor = "pointer";

    const info = document.createElement("div");
    info.className = "station-info";

    const nameEl = document.createElement("div");
    nameEl.className = "station-name";
    nameEl.textContent = "📁 " + title;

    const metaEl = document.createElement("div");
    metaEl.className = "station-url";
    metaEl.textContent = childCount + " éléments";

    info.appendChild(nameEl);
    info.appendChild(metaEl);
    card.appendChild(info);

    card.addEventListener("click", () => {
      dlnaNavStack.push({ id, title: "📁 " + title });
      dlnaBrowse(id, 0);
    });

    els.results.appendChild(card);
  }

  // Items (fichiers)
  dlnaCurrentItems = [];
  const itemReg = /<item\b([^>]*)>([\s\S]*?)<\/item>/gi;
  while ((m = itemReg.exec(decoded)) !== null) {
    const inner = m[2];
    const titleM = inner.match(/<dc:title[^>]*>([^<]+)<\/dc:title>/i);
    const resM   = inner.match(/<res\b[^>]*>([^<]+)<\/res>/i);
    const creatorM  = inner.match(/<dc:creator[^>]*>([^<]+)<\/dc:creator>/i);
    const durationM = inner.match(/duration="([^"]+)"/);
    if (!titleM || !resM) continue;
    if (!resM[1].trim().toLowerCase().includes('.mp3')) continue;

    const title    = dlnaDecodeHtml(titleM[1]);
    const url      = resM[1].trim();
    const creator  = creatorM  ? dlnaDecodeHtml(creatorM[1])  : "";
    const duration = durationM ? durationM[1] : "";

    dlnaCurrentItems.push({ title, url, duration });

    const card = document.createElement("div");
    card.className = "station";

    const top = document.createElement("div");
    top.className = "station-top";

    const actions = document.createElement("div");
    actions.className = "station-actions-col";

    const playBtn = document.createElement("button");
    playBtn.className = "play-btn";
    playBtn.title = "Lire sur ESP";
    const playIcon = document.createElement("span");
    playIcon.className = "icon-play";
    playBtn.appendChild(playIcon);
    playBtn.addEventListener("click", () => {
      const idx = dlnaCurrentItems.findIndex(i => i.url === url);
      sendPlaylist(dlnaCurrentItems, idx >= 0 ? idx : 0);
    });

    actions.appendChild(playBtn);
    top.appendChild(actions);

    const info = document.createElement("div");
    info.className = "station-info";

    const nameEl = document.createElement("div");
    nameEl.className = "station-name";
    nameEl.textContent = "🎵 " + title;

    const metaEl = document.createElement("div");
    metaEl.className = "station-url";
    metaEl.textContent = [creator, duration.substring(0, 5)].filter(Boolean).join(" · ");

    info.appendChild(nameEl);
    info.appendChild(metaEl);
    card.appendChild(top);
    card.appendChild(info);
    els.results.appendChild(card);
  }

  // Pagination
  if (dlnaTotal > DLNA.PAGE_SIZE) {
    const totalPages = Math.ceil(dlnaTotal / DLNA.PAGE_SIZE);
    const curPage = Math.floor(startIndex / DLNA.PAGE_SIZE);

    const pag = document.createElement("div");
    pag.className = "dlna-pagination";

    const prevBtn = document.createElement("button");
    prevBtn.className = "play-btn";
    prevBtn.textContent = "← Préc.";
    prevBtn.disabled = curPage === 0;
    prevBtn.addEventListener("click", () => dlnaBrowse(objectId, (curPage - 1) * DLNA.PAGE_SIZE));

    const pageInfo = document.createElement("span");
    pageInfo.style.fontSize = "0.8rem";
    pageInfo.style.padding = "0 10px";
    pageInfo.textContent = `Page ${curPage + 1} / ${totalPages}`;

    const nextBtn = document.createElement("button");
    nextBtn.className = "play-btn";
    nextBtn.textContent = "Suiv. →";
    nextBtn.disabled = curPage >= totalPages - 1;
    nextBtn.addEventListener("click", () => dlnaBrowse(objectId, (curPage + 1) * DLNA.PAGE_SIZE));

    pag.appendChild(prevBtn);
    pag.appendChild(pageInfo);
    pag.appendChild(nextBtn);
    els.results.appendChild(pag);
  }

  if (returned === 0) {
    const empty = document.createElement("div");
    empty.className = "station";
    empty.innerHTML = `<div class="station-info"><div class="station-name">Dossier vide.</div></div>`;
    els.results.appendChild(empty);
  }
}

function dlnaDecodeHtml(str) {
  return String(str)
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'");
}

/* ---------------- Onglets ---------------- */

function switchTab(tab) {
  if (tab === "dlna") browseRoot();
}

/* ---------------- Init ---------------- */

els.searchBtn.addEventListener("click", searchStations);
els.searchInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") searchStations();
});

els.stopBtn.addEventListener("click", stopOnTasmota);

els.volInput.addEventListener("input", () => {
  const val = els.volInput.value;
  els.volValue.textContent = val + "%";
  if (volTimer) clearTimeout(volTimer);
  volTimer = setTimeout(() => sendVolume(val), CFG.VOLUME_DEBOUNCE_MS);
});

els.playBtn.addEventListener("click", () => {
  tasmotaCmd("play").catch(err => setStatus("Erreur play : " + err.message, true));
});

els.favBtn.addEventListener("click", loadFavList);

if (els.modeBtn) {
  els.modeBtn.addEventListener("click", cyclePlayMode);
  updateModeBtn();
}

startNowPlayingPolling();