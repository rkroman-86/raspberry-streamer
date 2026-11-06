/* AndroRadio web — interface du Raspberry Streamer, servie par l'ESP32 (Tasmota) sur /ui.
 * Copie de l'appli Android AndroRadio. Le navigateur fait le travail lourd
 * (Radio Browser, pochettes, tuner) ; l'ESP ne sert que l'état, les favoris et les commandes. */
'use strict';

/* ---------------- outils ---------------- */
const $ = (s, r = document) => r.querySelector(s);
function h(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
}
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* stockage indisponible */ } },
};
const shuffle = a => { a = a.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };

/* Icônes Material (Apache 2.0) */
const ICON = {
  play: 'M8 5v14l11-7z',
  stop: 'M6 6h12v12H6z',
  search: 'M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z',
  fav: 'M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z',
  favb: 'M16.5 3c-1.74 0-3.41.81-4.5 2.09C10.91 3.81 9.24 3 7.5 3 4.42 3 2 5.42 2 8.5c0 3.78 3.4 6.86 8.55 11.54L12 21.35l1.45-1.32C18.6 15.36 22 12.28 22 8.5 22 5.42 19.58 3 16.5 3zm-4.4 15.55l-.1.1-.1-.1C7.14 14.24 4 11.39 4 8.5 4 6.5 5.5 5 7.5 5c1.54 0 3.04.99 3.57 2.36h1.87C13.46 5.99 14.96 5 16.5 5c2 0 3.5 1.5 3.5 3.5 0 2.89-3.14 5.74-7.9 10.05z',
  globe: 'M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z',
  refresh: 'M17.65 6.35A7.958 7.958 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z',
  close: 'M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z',
  del: 'M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z',
  save: 'M17 3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V7l-4-4zm-5 16c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3zm3-10H5V5h10v4z',
  volUp: 'M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z',
  volDown: 'M18.5 12c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM5 9v6h4l5 5V4L9 9H5z',
  volOff: 'M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51A8.796 8.796 0 0 0 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06a8.99 8.99 0 0 0 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z',
  radio: 'M3.24 6.15C2.51 6.43 2 7.17 2 8v12a2 2 0 0 0 2 2h16c1.11 0 2-.89 2-2V8c0-1.11-.89-2-2-2H8.3l8.26-3.34L15.88 1 3.24 6.15zM7 20c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3zm13-8h-2v-2h-2v2H4V8h16v4z',
  eq: 'M7 18h2V6H7v12zm4 4h2V2h-2v20zm-8-8h2v-4H3v4zm12 4h2V6h-2v12zm4-8v4h2v-4h-2z',
  gear: 'M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 0 0 .12-.61l-1.92-3.32a.488.488 0 0 0-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54a.484.484 0 0 0-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58a.49.49 0 0 0-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z',
  drop: 'M7 10l5 5 5-5z',
};
const svg = (n, cls = 'i') => `<svg class="${cls}" viewBox="0 0 24 24"><path d="${ICON[n]}"/></svg>`;

/* ---------------- données ---------------- */
const SOURCES = ['webradio', 'spotify', 'airplay', 'dlna', 'bluetooth'];
const SRC_LABEL = { webradio: 'Web radio', spotify: 'Spotify', airplay: 'AirPlay', dlna: 'DLNA', bluetooth: 'Bluetooth' };
const RENDERERS = ['airplay', 'spotify', 'bluetooth'];
const NB_FAV = 20, LOCAL_COUNT = 10, LOCAL_POOL = 60;

const S = {
  st: null, src: 'webradio', ps: 'stop', cur: null, last: null, rev: -1,
  fav: Array(NB_FAV).fill(null), rec: [],
  local: 'loading', localPool: [],
  optimistic: null, optimisticTs: 0,   // station lancée depuis la page, en attendant l'ESP
  volLocalTs: 0, volDrag: false, volBefore: 50,
  trackArt: null, artKey: '',
};

const normUrl = u => String(u || '').trim().replace(/\/+$/, '').toLowerCase();
const same = (a, b) => !!a && !!b && ((a.uuid && a.uuid === b.uuid) || normUrl(a.url) === normUrl(b.url));
const details = s => {
  if (!s) return '';
  const fmt = [s.codec && s.codec !== 'UNKNOWN' ? s.codec : '', s.bitrate > 0 ? s.bitrate + ' kbps' : ''].filter(Boolean).join(' ');
  return [String(s.country || '').trim(), fmt].filter(Boolean).join(' · ');
};

/** « Artiste - Titre » ; sans séparateur, tout devient le titre. */
function parseTrack(raw) {
  const text = String(raw || '').trim();
  if (!text || text === '-') return null;
  const sep = [' - ', ' – ', ' — '].find(x => text.includes(x));
  if (!sep) return { artist: null, title: text };
  const i = text.indexOf(sep);
  const artist = text.slice(0, i).trim(), title = text.slice(i + sep.length).trim();
  if (!artist && !title) return null;
  if (!artist) return { artist: null, title };
  if (!title) return { artist: null, title: artist };
  return { artist, title };
}

/* ---------------- ESP (API du driver ui.be) ---------------- */
async function api(a, params = {}) {
  const r = await fetch('/ui/api?' + new URLSearchParams({ a, ...params }), { cache: 'no-store' });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}
function stationParams(s) {
  const p = {};
  for (const k of ['uuid', 'name', 'url', 'favicon', 'country', 'codec']) if (s[k]) p[k] = String(s[k]).slice(0, 400);
  if (s.bitrate > 0) p.bitrate = s.bitrate;
  return p;
}

/* ---------------- Radio Browser ---------------- */
const RB = {
  servers: null,
  FALLBACK: ['de1.api.radio-browser.info', 'de2.api.radio-browser.info', 'fi1.api.radio-browser.info',
    'nl1.api.radio-browser.info', 'at1.api.radio-browser.info'],
  async get(url, ms = 15000) {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), ms);
    try {
      const r = await fetch(url, { signal: ctl.signal });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return await r.json();
    } finally { clearTimeout(t); }
  },
  async hosts() {
    if (this.servers) return this.servers;
    let list = [];
    try {
      list = (await this.get('https://all.api.radio-browser.info/json/servers', 8000))
        .map(s => String(s.name || '').trim()).filter(n => n.endsWith('.radio-browser.info'));
    } catch (e) { /* repli ci-dessous */ }
    list = [...new Set(list)];
    return (this.servers = shuffle(list.length ? list : this.FALLBACK));
  },
  /** Essaie chaque serveur ; celui qui répond passe en tête. */
  async request(path, params = {}) {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== '')).toString();
    for (let round = 0; round < 2; round++) {
      const hosts = await this.hosts();
      for (const host of hosts) {
        try {
          const data = await this.get(`https://${host}${path}${q ? '?' + q : ''}`);
          if (hosts[0] !== host) this.servers = [host, ...hosts.filter(x => x !== host)];
          return data;
        } catch (e) { /* serveur suivant */ }
      }
      this.servers = null;
      await new Promise(r => setTimeout(r, 1500));
    }
    throw new Error('Radio Browser unreachable');
  },
  station(j) {
    return {
      uuid: j.stationuuid || '', name: String(j.name || '').trim(), url: String(j.url_resolved || j.url || '').trim(),
      favicon: j.favicon || '', country: j.country || '', countrycode: j.countrycode || '', state: j.state || '',
      language: j.language || '', codec: j.codec || '', bitrate: j.bitrate || 0, tags: j.tags || '',
    };
  },
  async stations(path, limit) {
    const list = await this.request(path, { order: 'clickcount', reverse: 'true', hidebroken: 'true', limit });
    return list.map(j => this.station(j)).filter(s => s.name && /^https?:/i.test(s.url));
  },
  async popular(cc, limit) {
    const n = limit * 3;
    const list = cc ? await this.stations('/json/stations/bycountrycodeexact/' + cc.toUpperCase(), n)
      : await this.stations('/json/stations/topclick/' + n, n);
    return dedupe(list).slice(0, limit);
  },
  click(uuid) { if (uuid) this.request('/json/url/' + uuid).catch(() => {}); },
};

/** Doublons : même identifiant, même flux, ou même nom dans le même pays. */
function dedupe(list) {
  const seen = new Set();
  return list.filter(s => {
    const name = s.name.trim().toLowerCase().replace(/\s+/g, ' ');
    const keys = ['id:' + s.uuid, 'url:' + normUrl(s.url), 'name:' + name + '|' + String(s.countrycode || '').toUpperCase()];
    const isNew = !keys.some(k => (k !== 'id:' && seen.has(k)));
    keys.forEach(k => seen.add(k));
    return isNew;
  });
}

/* ---------------- pochette du morceau (MusicBrainz + Cover Art Archive, sinon iTunes) ---------------- */
const artCache = new Map();
const normTxt = s => String(s || '').toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
const imgExists = url => new Promise(res => { const i = new Image(); i.onload = () => res(true); i.onerror = () => res(false); i.src = url; });
function itunes(artist, title) {
  return new Promise(res => {
    const cb = 'itc' + Date.now() + Math.floor(Math.random() * 1000);
    const sc = document.createElement('script');
    const done = v => { delete window[cb]; sc.remove(); res(v); };
    const timer = setTimeout(() => done(null), 8000);
    window[cb] = d => {
      clearTimeout(timer);
      const want = normTxt(artist);
      const hit = (d.results || []).find(r => { const n = normTxt(r.artistName); return n && (n.includes(want) || want.includes(n)); });
      done(hit && hit.artworkUrl100 ? hit.artworkUrl100.replace('100x100bb', '600x600bb') : null);
    };
    sc.onerror = () => { clearTimeout(timer); done(null); };
    sc.src = 'https://itunes.apple.com/search?' + new URLSearchParams({ term: artist + ' ' + title, media: 'music', entity: 'song', limit: 5, callback: cb });
    document.head.appendChild(sc);
  });
}
async function musicbrainz(artist, title) {
  const q = `recording:"${title.replace(/"/g, '\\"')}" AND artist:"${artist.replace(/"/g, '\\"')}"`;
  const d = await RB.get('https://musicbrainz.org/ws/2/recording?' + new URLSearchParams({ query: q, fmt: 'json', limit: 10 }), 10000);
  const want = normTxt(artist);
  const rel = (d.recordings || []).filter(r => r.score >= 80).filter(r => {
    const c = normTxt((r['artist-credit'] || []).map(a => a.name).join(' '));
    return c && (c.includes(want) || want.includes(c));
  }).flatMap(r => r.releases || []);
  const rank = r => {
    const g = r['release-group'] || {};
    return (String(r.status).toLowerCase() === 'official' ? 0 : 2) + ((g['secondary-types'] || []).length ? 4 : 0)
      + (['Album', 'Single', 'EP'].includes(g['primary-type']) ? 0 : 1);
  };
  rel.sort((a, b) => rank(a) - rank(b));
  const cands = [...new Set(rel.map(r => (r['release-group'] || {}).id).filter(Boolean))].slice(0, 4)
    .map(id => `https://coverartarchive.org/release-group/${id}/front-500`)
    .concat([...new Set(rel.map(r => r.id).filter(Boolean))].slice(0, 2).map(id => `https://coverartarchive.org/release/${id}/front-500`));
  for (const u of cands) if (await imgExists(u)) return u;
  return null;
}
async function findArt(track) {
  if (!track || !track.artist) return null;
  const key = (track.artist + '|' + track.title).toLowerCase();
  if (artCache.has(key)) return artCache.get(key);
  let url = null;
  try { url = await musicbrainz(track.artist, track.title); } catch (e) { /* iTunes ensuite */ }
  if (!url) url = await itunes(track.artist, track.title);
  artCache.set(key, url);
  return url;
}

/* ---------------- éléments communs ---------------- */
function artEl(url, cls = '') {
  const a = h('div', 'art ' + cls, svg('radio', ''));
  setArt(a, url);
  return a;
}
function setArt(a, url) {
  url = url || '';
  if (a.dataset.url === url) return;
  a.dataset.url = url;
  const old = a.querySelector('img');
  if (old) old.remove();
  if (!url) return;
  const img = h('img');
  img.alt = '';
  img.referrerPolicy = 'no-referrer';
  img.onload = () => img.classList.add('ok');
  img.onerror = () => img.remove();
  img.src = url;
  a.appendChild(img);
}

/** Appui long (vignettes, lignes) : n'interfère pas avec le défilement. */
function onLongPress(el, fn) {
  let t = null, x = 0, y = 0, fired = false;
  el.addEventListener('pointerdown', e => {
    fired = false; x = e.clientX; y = e.clientY;
    clearTimeout(t);
    t = setTimeout(() => { fired = true; fn(); }, 500);
  });
  const cancel = () => clearTimeout(t);
  el.addEventListener('pointermove', e => { if (Math.abs(e.clientX - x) > 10 || Math.abs(e.clientY - y) > 10) cancel(); });
  el.addEventListener('pointerup', cancel);
  el.addEventListener('pointercancel', cancel);
  el.addEventListener('pointerleave', cancel);
  el.addEventListener('contextmenu', e => e.preventDefault());
  el.addEventListener('click', e => { if (fired) { e.stopImmediatePropagation(); e.preventDefault(); } }, true);
}

/** Texte qui défile s'il est trop long (artiste, titre). */
function setMarquee(el, text, dim) {
  const span = el.firstElementChild;
  el.classList.toggle('dim', !!dim);
  if (span.textContent === text) return;
  span.textContent = text;
  el.classList.remove('run');
  requestAnimationFrame(() => {
    const over = span.scrollWidth - el.clientWidth;
    if (over > 2) {
      el.style.setProperty('--mq-d', -(over + 48) + 'px');
      el.style.setProperty('--mq-t', Math.max(6, (over + 48) / 30) + 's');
      el.classList.add('run');
    }
  });
}

/* ---------------- pages flottantes ---------------- */
function openPage(title, { small = false, actions = null, onClose = null } = {}) {
  const scrim = h('div', 'scrim');
  const page = h('div', 'page' + (small ? ' small' : ''));
  const head = h('div', 'page-head', `<div class="page-title">${esc(title)}</div>`);
  if (actions) head.appendChild(actions);
  const x = h('button', 'icon-btn', svg('close'));
  x.setAttribute('aria-label', 'Close');
  head.appendChild(x);
  page.appendChild(head);
  scrim.appendChild(page);
  document.body.appendChild(scrim);
  const close = () => { scrim.remove(); if (onClose) onClose(); };
  x.onclick = close;
  scrim.addEventListener('click', e => { if (e.target === scrim) close(); });
  return { scrim, page, close };
}

/* ---------------- écran principal ---------------- */
function currentStation() {
  if (S.optimistic && Date.now() - S.optimisticTs < 6000) return S.optimistic;
  if (S.cur && S.cur.url) return S.cur;
  const st = S.st;
  if (st && st.source === 'webradio' && st.file) return { name: st.station || 'web', url: st.file, favicon: /^http/.test(st.cover || '') ? st.cover : '' };
  if (S.last && S.last.url) return S.rec.find(r => same(r, S.last)) || { name: S.last.name, url: S.last.url };
  return S.rec[0] || null;
}
const isActive = () => S.ps === 'play';
const isWeb = () => !S.src || S.src === 'webradio';
const playingUrl = () => (isActive() && isWeb() && S.st && S.st.file) ? S.st.file : null;

function renderNow() {
  const st = S.st || {};
  const active = isActive();
  const nameEl = $('#now-name'), statusEl = $('#now-status'), detEl = $('#now-details');
  let name, status = '', det = '', track = null, art = null, busy = false, err = false;
  if (isWeb()) {
    const cur = currentStation();
    name = cur ? cur.name : 'No station selected';
    if (cur) {
      const connecting = active && st.source === 'webradio' && !st.title && !st.elapsed;
      if (S.optimistic && Date.now() - S.optimisticTs < 6000 && !active) { status = 'Connecting…'; busy = true; }
      else if (connecting) { status = 'Connecting…'; busy = true; }
      else status = active ? 'Live' : 'Stopped';
      det = details(cur) || (active && st.format ? st.format : '');
    }
    if (active) track = parseTrack(st.title);
    art = (track && S.trackArt) || (cur && cur.favicon) || (/^http/.test(st.cover || '') ? st.cover : null);
  } else {
    name = SRC_LABEL[S.src] || S.src;
    status = st.state === 'play' ? 'Playing' : st.state === 'pause' ? 'Paused'
      : RENDERERS.includes(S.src) ? 'Start playback from your phone' : 'Stopped';
    det = S.src === 'bluetooth' ? (st.station || '') : (st.album || '');
    if (st.title || st.artist) track = { artist: st.artist || null, title: st.title || '' };
    art = /^http/.test(st.cover || '') ? st.cover : null;
  }
  nameEl.textContent = name;
  statusEl.textContent = status;
  statusEl.classList.toggle('err', err);
  detEl.textContent = det;
  $('#now-busy').classList.toggle('hidden', !busy);
  setArt($('#now-art'), art);
  setMarquee($('#now-artist'), (track && track.artist) || '—', !(track && track.artist));
  setMarquee($('#now-title'), (track && track.title) || '—', !track);
  const icon = '/ui/f?n=A/src_' + (SOURCES.includes(S.src) ? S.src : 'webradio') + '.png';
  const img = $('#src-btn img');
  if (img.getAttribute('src') !== icon) img.setAttribute('src', icon);
  if (isWeb()) updateTrackArt(track);
}

async function updateTrackArt(track) {
  const key = track && track.artist ? (track.artist + '|' + track.title) : '';
  if (key === S.artKey) return;
  S.artKey = key;
  S.trackArt = null;
  if (!key) return;
  const url = await findArt(track);
  if (S.artKey === key) { S.trackArt = url; renderNow(); }
}

/** Bande de stations (récents, favoris, locales). */
const bandSig = {};
const stSig = s => s ? [s.name, s.url, s.favicon].join('\u0001') : '-';
function renderBand(id, title, slots, { numbered = false, empty = '', trailing = null, loading = false, error = false } = {}) {
  const band = $(id);
  const cur = currentStation(), playing = playingUrl();
  const sig = [title, loading, error, slots.map(stSig).join('\u0002'), cur ? normUrl(cur.url) : '', playing || ''].join('|');
  if (bandSig[id] === sig) return;
  bandSig[id] = sig;
  const keepScroll = band.querySelector('.strip') ? band.querySelector('.strip').scrollLeft : 0;
  band.innerHTML = '';
  const head = h('div', 'band-head', `<div class="band-title">${esc(title)}</div>`);
  if (trailing) head.appendChild(trailing);
  band.appendChild(head);
  if (loading || error) {
    band.appendChild(h('div', 'strip-msg', error ? 'Could not load stations.' : '<div class="spinner"></div>'));
    return;
  }
  if (!slots.length) { band.appendChild(h('div', 'strip-msg', esc(empty))); return; }
  const strip = h('div', 'strip');
  slots.forEach((s, i) => {
    const isCur = !!s && !!cur && same(s, cur);
    const t = h('div', 'tile' + (isCur ? ' cur' : '') + (s ? '' : ' void'));
    const box = h('div', 'box'), sq = h('div', 'sq');
    sq.appendChild(s ? artEl(s.favicon) : h('div', 'art empty'));
    if (numbered) sq.appendChild(h('div', 'num', String(i + 1)));
    if (isCur && playing && normUrl(playing) === normUrl(s.url)) sq.appendChild(h('div', 'eq', svg('eq', '')));
    box.appendChild(sq);
    t.appendChild(box);
    t.appendChild(h('div', 'nm', esc(s ? s.name : 'Empty')));
    if (s) {
      t.onclick = () => play(s);
      onLongPress(t, () => openFavorites(s));
    }
    strip.appendChild(t);
  });
  band.appendChild(strip);
  strip.scrollLeft = keepScroll;
}

function localInfo() {
  const langs = navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || ''];
  let cc = '';
  for (const l of langs) { const m = /[-_]([A-Za-z]{2})\b/.exec(l); if (m) { cc = m[1].toUpperCase(); break; } }
  let name = '';
  try { if (cc) name = new Intl.DisplayNames(['en'], { type: 'region' }).of(cc); } catch (e) { name = cc; }
  return { cc, name };
}
const LOCAL = localInfo();

function renderBands() {
  renderBand('#b-recent', 'Recently played', S.rec, { empty: 'Stations you play will appear here.' });
  renderBand('#b-fav', 'Favorites', S.fav, { numbered: true });
  const rb = h('button', 'icon-btn sm', svg('refresh'));
  rb.setAttribute('aria-label', 'Show other stations');
  rb.disabled = S.local === 'loading';
  rb.onclick = refreshLocal;
  renderBand('#b-local', LOCAL.name ? 'Local stations · ' + LOCAL.name : 'Popular stations',
    Array.isArray(S.local) ? S.local : [],
    { trailing: rb, loading: S.local === 'loading', error: S.local === 'error', empty: 'No station found.' });
}

async function loadLocal() {
  S.local = 'loading'; renderBands();
  try {
    S.localPool = await RB.popular(LOCAL.cc, LOCAL_POOL);
    S.local = S.localPool.slice(0, LOCAL_COUNT);
  } catch (e) { S.local = 'error'; }
  renderBands();
}
function refreshLocal() {
  const shown = new Set((Array.isArray(S.local) ? S.local : []).map(s => s.uuid));
  if (S.localPool.length <= LOCAL_COUNT) { loadLocal(); return; }
  const fresh = shuffle(S.localPool.filter(s => !shown.has(s.uuid)));
  S.local = fresh.concat(shuffle(S.localPool.filter(s => shown.has(s.uuid)))).slice(0, LOCAL_COUNT);
  renderBands();
}

function renderControls() {
  const active = isActive();
  const btn = $('#play-btn');
  btn.innerHTML = svg(active ? 'stop' : 'play');
  btn.setAttribute('aria-label', active ? 'Stop' : 'Play');
  btn.disabled = !active && (isWeb() ? !currentStation() : RENDERERS.includes(S.src));
  const st = S.st;
  if (st && st.vol != null && !S.volDrag && Date.now() - S.volLocalTs > 1500) $('#vol').value = st.vol;
  renderVolIcon();
}
function renderVolIcon() {
  const v = +$('#vol').value;
  $('#vol-ico').innerHTML = svg(v <= 0 ? 'volOff' : v < 50 ? 'volDown' : 'volUp');
}

function renderAll() { renderNow(); renderBands(); renderControls(); refreshOpenPages(); }

/* ---------------- actions ---------------- */
async function play(s) {
  S.optimistic = s; S.optimisticTs = Date.now();
  S.trackArt = null; S.artKey = '';
  renderAll();
  try { await api('play', stationParams(s)); } catch (e) { console.warn('play', e); }
  RB.click(s.uuid);
  setTimeout(poll, 600);
}
async function togglePlay() {
  if (!isActive() && isWeb() && !(S.st && S.st.file) && !S.last?.url) {
    const c = currentStation();
    if (c) return play(c);
  }
  S.ps = isActive() ? 'stop' : S.ps;
  renderControls();
  try { await api('toggle'); } catch (e) { /* l'état suivant corrigera */ }
  setTimeout(poll, 600);
}
let volTimer = null;
function sendVol(force) {
  const v = +$('#vol').value;
  S.volLocalTs = Date.now();
  renderVolIcon();
  if (volTimer && !force) return;
  clearTimeout(volTimer);
  volTimer = setTimeout(() => { volTimer = null; }, 200);
  api('vol', { v }).catch(() => {});
}

/* ---------------- état de l'ESP ---------------- */
let pollTimer = null, pollBusy = false;
async function poll() {
  clearTimeout(pollTimer);
  if (pollBusy) return;
  pollBusy = true;
  try {
    const d = await api('state');
    S.st = d.st || null;
    S.src = d.src || 'webradio';
    S.ps = d.ps || (S.st && S.st.state) || 'stop';
    S.cur = d.cur || null;
    S.last = d.last || null;
    if (S.optimistic && S.cur && same(S.cur, S.optimistic) && isActive()) S.optimistic = null;
    if (d.rev !== S.rev) await loadLib(d.rev);
    renderAll();
  } catch (e) {
    console.warn('state', e);
  } finally {
    pollBusy = false;
    pollTimer = setTimeout(poll, document.hidden ? 6000 : 1500);
  }
}
async function loadLib(rev) {
  try {
    const d = await api('lib');
    S.fav = (d.fav || []).slice(0, NB_FAV);
    while (S.fav.length < NB_FAV) S.fav.push(null);
    S.rec = d.rec || [];
    S.rev = rev != null ? rev : d.rev;
  } catch (e) { console.warn('lib', e); }
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });

/* ---------------- pages ouvertes : rafraîchies avec l'état ---------------- */
const openPages = new Set();
function refreshOpenPages() { openPages.forEach(fn => fn()); }

/* ---------------- choix de la source ---------------- */
function openSources() {
  const p = openPage('Source', { small: true });
  const grid = h('div', 'src-grid');
  SOURCES.forEach(src => {
    const b = h('button', 'src-tile' + (src === S.src ? ' on' : ''), `<img alt="" src="/ui/f?n=A/src_${src}.png">`);
    b.setAttribute('aria-label', SRC_LABEL[src]);
    b.onclick = async () => {
      p.close();
      S.src = src;
      renderAll();
      try { await api('src', { s: src }); } catch (e) { /* état suivant */ }
      setTimeout(poll, 600);
    };
    grid.appendChild(b);
  });
  const g = h('button', 'src-tile', svg('gear', ''));
  g.setAttribute('aria-label', 'Settings');
  g.onclick = () => { location.href = '/wsync'; };
  grid.appendChild(g);
  p.page.appendChild(grid);
}

/* ---------------- favoris ---------------- */
function openFavorites(target = currentStation()) {
  const p = openPage('Favorites', { onClose: () => openPages.delete(render) });
  const top = h('div', 'fav-target');
  if (target) {
    top.appendChild(artEl(target.favicon));
    top.appendChild(h('div', '', `Save “${esc(target.name)}” to a slot:`));
  } else {
    top.appendChild(h('div', 'r2', 'Play a station first, then save it into a slot.'));
  }
  p.page.appendChild(top);
  p.page.appendChild(h('div', 'hint', 'Hold a row and drag it to change the order.'));
  p.page.appendChild(h('div', 'divider'));
  const body = h('div', 'page-body');
  p.page.appendChild(body);
  let dragging = false;

  let sig = null;
  function render() {
    if (dragging) return;
    const cur = currentStation();
    const nsig = S.fav.map(stSig).join('|') + '#' + (cur ? normUrl(cur.url) : '');
    if (nsig === sig) return;
    sig = nsig;
    const keep = body.scrollTop;
    body.innerHTML = '';
    S.fav.forEach((s, i) => {
      const row = h('div', 'frow' + (s ? '' : ' void'));
      row.dataset.i = i;
      row.appendChild(h('div', 'n', String(i + 1)));
      row.appendChild(s ? artEl(s.favicon) : h('div', 'art empty'));
      const txt = h('div', 'row-txt', `<div class="t1">${esc(s ? s.name : 'Empty')}</div>` +
        (s && details(s) ? `<div class="r2">${esc(details(s))}</div>` : ''));
      row.appendChild(txt);
      if (s && cur && same(s, cur)) { const eq = h('div', '', svg('eq')); eq.style.color = 'var(--primary)'; row.appendChild(eq); }
      const sv = h('button', 'tonal', svg('save'));
      sv.setAttribute('aria-label', 'Save');
      sv.disabled = !target;
      sv.onclick = e => { e.stopPropagation(); saveFav(i, target); };
      const dl = h('button', 'outlined', svg('del'));
      dl.setAttribute('aria-label', 'Delete');
      dl.disabled = !s;
      dl.onclick = e => { e.stopPropagation(); delFav(i); };
      row.appendChild(sv);
      row.appendChild(dl);
      if (s) row.onclick = () => { if (!row.dataset.dragged) { p.close(); play(s); } };
      enableDrag(row, i);
      body.appendChild(row);
    });
    body.scrollTop = keep;
  }

  /** Glisser-déposer : appui long sur une ligne puis déplacement vertical. */
  function enableDrag(row, from) {
    let t = null, startY = 0, active = false, rowH = 0;
    row.addEventListener('pointerdown', e => {
      if (e.target.closest('button')) return;
      startY = e.clientY;
      t = setTimeout(() => {
        active = dragging = true;
        rowH = row.offsetHeight;
        row.classList.add('drag');
        row.setPointerCapture(e.pointerId);
        if (navigator.vibrate) navigator.vibrate(20);
      }, 350);
    });
    row.addEventListener('pointermove', e => {
      if (!active) { if (Math.abs(e.clientY - startY) > 8) clearTimeout(t); return; }
      e.preventDefault();
      row.style.transform = `translateY(${e.clientY - startY}px) scale(1.02)`;
    });
    // une fois la ligne « prise », le doigt ne fait plus défiler la liste
    row.addEventListener('touchmove', e => { if (active) e.preventDefault(); }, { passive: false });
    const end = e => {
      clearTimeout(t);
      if (!active) return;
      active = false;
      const to = Math.max(0, Math.min(NB_FAV - 1, from + Math.round((e.clientY - startY) / rowH)));
      row.dataset.dragged = '1';
      row.classList.remove('drag');
      row.style.transform = '';
      setTimeout(() => { delete row.dataset.dragged; }, 80);
      setTimeout(() => { dragging = false; moveFav(from, to); }, 0);
    };
    row.addEventListener('pointerup', end);
    row.addEventListener('pointercancel', end);
    row.addEventListener('contextmenu', e => e.preventDefault());
  }

  render();
  openPages.add(render);
}
async function saveFav(i, s) {
  if (!s) return;
  S.fav[i] = s; renderAll();
  try { const r = await api('fsave', { slot: i + 1, ...stationParams(s) }); if (r.rev) S.rev = r.rev; } catch (e) { /* */ }
  poll();
}
async function delFav(i) {
  S.fav[i] = null; renderAll();
  try { const r = await api('fdel', { slot: i + 1 }); if (r.rev) S.rev = r.rev; } catch (e) { /* */ }
  poll();
}
async function moveFav(from, to) {
  if (from !== to) { const [s] = S.fav.splice(from, 1); S.fav.splice(to, 0, s); }
  renderAll();
  if (from === to) return;
  try { const r = await api('fmove', { from: from + 1, to: to + 1 }); if (r.rev) S.rev = r.rev; } catch (e) { /* */ }
  poll();
}

/* ---------------- lignes de résultats (recherche, tuner) ---------------- */
function markCurrent(body) {
  const c = currentStation();
  body.querySelectorAll('.row').forEach(r => { const e = r.querySelector('.r1'); if (e) e.classList.toggle('cur', !!(c && r._st && same(r._st, c))); });
}
function resultRow(s, onPlay) {
  const row = h('div', 'row');
  row._st = s;
  row.appendChild(artEl(s.favicon));
  const extra = [s.language, ...String(s.tags || '').split(',').map(x => x.trim()).filter(Boolean).slice(0, 4)].filter(Boolean).join(' · ');
  const cur = currentStation();
  row.appendChild(h('div', 'row-txt', `<div class="r1${cur && same(s, cur) ? ' cur' : ''}">${esc(s.name)}</div>` +
    (details(s) ? `<div class="r2">${esc(details(s))}</div>` : '') + (extra ? `<div class="r3">${esc(extra)}</div>` : '')));
  const fb = h('button', 'icon-btn', svg('favb'));
  fb.setAttribute('aria-label', 'Add to favorites');
  fb.onclick = e => { e.stopPropagation(); openFavorites(s); };
  row.appendChild(fb);
  row.onclick = () => onPlay(s);
  return row;
}

/* ---------------- recherche ---------------- */
const SEARCH = { query: '', state: 'idle', results: [], busy: false, token: 0, scroll: 0 };
function openSearch() {
  const p = openPage('Search stations', { onClose: () => { SEARCH.scroll = body.scrollTop; openPages.delete(render); } });
  const box = h('form', 'search-box', `<input type="search" enterkeyhint="search" placeholder="Name, genre, country, language…">`);
  const go = h('button', 'icon-btn', svg('search'));
  go.type = 'submit';
  go.setAttribute('aria-label', 'Search');
  box.appendChild(go);
  const input = box.querySelector('input');
  input.value = SEARCH.query;
  box.onsubmit = e => { e.preventDefault(); input.blur(); runSearch(input.value); };
  p.page.appendChild(box);
  const body = h('div', 'page-body');
  p.page.appendChild(body);

  let sig = null;
  function render() {
    const nsig = [SEARCH.state, SEARCH.busy, SEARCH.results.length, SEARCH.token].join('|');
    if (nsig === sig) { markCurrent(body); return; }
    sig = nsig;
    const keep = body.scrollTop;
    body.innerHTML = '';
    if (SEARCH.state === 'idle') body.appendChild(h('div', 'center-msg', 'Searches name, genre, country, country code, language, region and codec — duplicates are removed.'));
    else if (SEARCH.state === 'loading') body.appendChild(h('div', 'center-msg', '<div class="spinner"></div>'));
    else if (SEARCH.state === 'error') {
      const m = h('div', 'center-msg', 'Could not load stations.');
      const r = h('button', 'text-btn', 'Retry');
      r.onclick = () => runSearch(SEARCH.query);
      m.appendChild(r);
      body.appendChild(m);
    } else if (!SEARCH.results.length) body.appendChild(h('div', 'center-msg', 'No station found.'));
    else {
      if (SEARCH.busy) body.appendChild(h('div', 'progress lin'));
      body.appendChild(h('div', 'count', SEARCH.results.length + ' stations'));
      SEARCH.results.forEach(s => body.appendChild(resultRow(s, st => { p.close(); play(st); })));
    }
    body.scrollTop = keep;
  }
  render();
  body.scrollTop = SEARCH.scroll;
  openPages.add(render);
  if (SEARCH.state === 'idle') setTimeout(() => input.focus(), 50);
}
async function runSearch(text) {
  const q = String(text || '').trim();
  SEARCH.query = q;
  const token = ++SEARCH.token;
  if (!q) { SEARCH.state = 'idle'; refreshOpenPages(); return; }
  SEARCH.state = 'loading'; SEARCH.results = []; SEARCH.busy = true; SEARCH.scroll = 0;
  refreshOpenPages();
  const fields = ['byname', 'bytag', 'bycountry'];
  if (/^[a-z]{2}$/i.test(q)) fields.push('bycountrycodeexact');
  fields.push('bylanguage', 'bystate', 'bycodec');
  const results = new Array(fields.length).fill(null);
  let anyOk = false, next = 0;
  // au plus 2 requêtes à la fois ; résultats affichés au fur et à mesure, dans l'ordre des critères
  const worker = async () => {
    while (next < fields.length) {
      const k = next++, f = fields[k];
      try {
        const term = f === 'bycountrycodeexact' ? q.toUpperCase() : q;
        results[k] = await RB.stations(`/json/stations/${f}/${encodeURIComponent(term)}`, 60);
        anyOk = true;
      } catch (e) { results[k] = []; }
      if (token !== SEARCH.token) return;
      if (anyOk) { SEARCH.state = 'loaded'; SEARCH.results = dedupe(results.filter(Boolean).flat()); refreshOpenPages(); }
    }
  };
  await Promise.all([worker(), worker()]);
  if (token !== SEARCH.token) return;
  SEARCH.busy = false;
  if (!anyOk) SEARCH.state = 'error';
  refreshOpenPages();
}

/* ---------------- tuner « Around the world » ---------------- */
const CONTINENTS = [
  ['Europe', 'AD AL AT AX BA BE BG BY CH CY CZ DE DK EE ES FI FO FR GB GG GI GR HR HU IE IM IS IT JE LI LT LU LV MC MD ME MK MT NL NO PL PT RO RS RU SE SI SJ SK SM UA VA XK'],
  ['Africa', 'AO BF BI BJ BW CD CF CG CI CM CV DJ DZ EG EH ER ET GA GH GM GN GQ GW KE KM LR LS LY MA MG ML MR MU MW MZ NA NE NG RE RW SC SD SH SL SN SO SS ST SZ TD TG TN TZ UG YT ZA ZM ZW'],
  ['Asia', 'AE AF AM AZ BD BH BN BT CN GE HK ID IL IN IQ IR JO JP KG KH KP KR KW KZ LA LB LK MM MN MO MV MY NP OM PH PK PS QA SA SG SY TH TJ TL TM TR TW UZ VN YE'],
  ['North America', 'AG AI AW BB BL BM BQ BS BZ CA CR CU CW DM DO GD GL GP GT HN HT JM KN KY LC MF MQ MS MX NI PA PM PR SV SX TC TT US VC VG VI'],
  ['South America', 'AR BO BR CL CO EC FK GF GY PE PY SR UY VE'],
  ['Oceania', 'AS AU CK FJ FM GU KI MH MP NC NF NR NU NZ PF PG PN PW SB TK TO TV UM VU WF WS'],
].map(([name, codes]) => ({ name, codes: new Set(codes.split(' ')) }));
const continentOf = cc => CONTINENTS.findIndex(c => c.codes.has(String(cc).toUpperCase()));
const regionKey = s => String(s || '').trim().replace(/\s+/g, ' ').toLowerCase();

const GEO = {
  modern: store.get('geo_modern', false),
  all: null, error: false, continent: Math.max(0, continentOf(LOCAL.cc)),
  countries: null, countryIndex: 0, regions: null, regionIndex: 0,
  stations: 'loading', cache: {}, token: 0,
};
function countriesOf(ci) {
  const coll = new Intl.Collator();
  return (GEO.all || []).filter(c => continentOf(c.code) === ci).sort((a, b) => coll.compare(a.name, b.name));
}
async function geoLoadCountries() {
  GEO.countries = null; GEO.error = false; refreshOpenPages();
  try {
    const list = await RB.request('/json/countries', { hidebroken: 'true' });
    let dn = null;
    try { dn = new Intl.DisplayNames(['en'], { type: 'region' }); } catch (e) { /* noms de Radio Browser */ }
    const map = new Map();
    list.filter(c => String(c.iso_3166_1 || '').length === 2 && c.stationcount > 0).forEach(c => {
      const code = c.iso_3166_1.toUpperCase();
      const e = map.get(code) || { code, name: '', stations: 0 };
      e.stations += c.stationcount;
      if (!e.name) { let n = ''; try { n = dn ? dn.of(code) : ''; } catch (x) { /* */ } e.name = n && n !== code ? n : c.name; }
      map.set(code, e);
    });
    GEO.all = [...map.values()];
  } catch (e) { GEO.error = true; refreshOpenPages(); return; }
  geoSelectContinent(GEO.continent, LOCAL.cc);
}
function geoSelectContinent(i, prefer) {
  GEO.continent = i;
  const list = countriesOf(i);
  let ci = list.findIndex(c => c.code === prefer);
  if (ci < 0) ci = list.reduce((best, c, k) => (c.stations > list[best].stations ? k : best), 0);
  GEO.countries = list; GEO.countryIndex = list.length ? ci : 0;
  geoLoadCountry();
}
function geoSelectCountry(i) {
  if (!GEO.countries || !GEO.countries.length || (i === GEO.countryIndex && GEO.regions)) return;
  GEO.countryIndex = i;
  geoLoadCountry();
}
function geoSelectRegion(i) {
  const c = GEO.countries && GEO.countries[GEO.countryIndex];
  const all = c && GEO.cache[c.code];
  if (!all || !GEO.regions || !GEO.regions[i]) return;
  const key = GEO.regions[i].key;
  GEO.regionIndex = i;
  GEO.stations = key == null ? all : all.filter(s => regionKey(s.state) === key);
  refreshOpenPages();
}
async function geoLoadCountry() {
  const token = ++GEO.token;
  const c = GEO.countries && GEO.countries[GEO.countryIndex];
  if (!c) { GEO.regions = []; GEO.regionIndex = 0; GEO.stations = []; refreshOpenPages(); return; }
  if (!GEO.cache[c.code]) {
    GEO.regions = null; GEO.regionIndex = 0; GEO.stations = 'loading'; refreshOpenPages();
    try { GEO.cache[c.code] = dedupe(await RB.stations('/json/stations/bycountrycodeexact/' + c.code, 500)); }
    catch (e) { if (token === GEO.token) { GEO.regions = []; GEO.stations = 'error'; refreshOpenPages(); } return; }
    if (token !== GEO.token) return;
  }
  const all = GEO.cache[c.code];
  const groups = new Map();
  all.forEach(s => {
    const name = String(s.state || '').trim().replace(/\s+/g, ' ');
    if (!name) return;
    const k = regionKey(name);
    const g = groups.get(k) || { key: k, name, stations: 0 };
    g.stations++;
    groups.set(k, g);
  });
  const regions = [...groups.values()].sort((a, b) => b.stations - a.stations || a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
  GEO.regions = [{ key: null, name: 'All', stations: all.length }, ...regions];
  GEO.regionIndex = 0;
  GEO.stations = all;
  refreshOpenPages();
}

/** Cadran rétro : bande à faire glisser sous l'aiguille rouge ; choix validé à l'arrêt. */
function makeDial(label) {
  const wrap = h('div', '', `<div class="dial-lbl">${esc(label)}</div>`);
  const dial = h('div', 'dial');
  wrap.appendChild(dial);
  let items = null, selected = 0, listKey = null, strip = null, tiles = [], onSel = () => {}, settle = null, programmatic = false;

  function centered() {
    if (!strip) return selected;
    const c = strip.scrollLeft + strip.clientWidth / 2;
    let best = 0, bd = 1e9;
    tiles.forEach((e, i) => { const d = Math.abs(e.offsetLeft + e.offsetWidth / 2 - c); if (d < bd) { bd = d; best = i; } });
    return best;
  }
  function paint() {
    if (!strip) return;
    const c = strip.scrollLeft + strip.clientWidth / 2;
    tiles.forEach(e => {
      const d = Math.abs(e.offsetLeft + e.offsetWidth / 2 - c) / e.offsetWidth;
      const f = Math.min(1, Math.max(.55, 1 - d * .35));
      e.style.transform = `scale(${f})`;
      e.style.opacity = Math.min(1, Math.max(.25, 1 - d * .45));
    });
  }
  function scrollTo(i, smooth) {
    const e = strip && tiles[i];
    if (!e) return;
    const left = Math.max(0, Math.round(e.offsetLeft + e.offsetWidth / 2 - strip.clientWidth / 2));
    // déplacement par le code : ne doit pas être pris pour un choix de l'utilisateur
    programmatic = !smooth && Math.abs(strip.scrollLeft - left) > 1;
    strip.scrollTo({ left, behavior: smooth ? 'smooth' : 'auto' });
    paint();
  }
  function build() {
    dial.innerHTML = '';
    strip = null;
    tiles = [];
    if (items == null) dial.appendChild(h('div', 'dial-sweep'));
    else if (!items.length) dial.appendChild(h('div', 'dial-empty', '—'));
    else {
      strip = h('div', 'dial-strip');
      const pad = h('div'); pad.style.cssText = 'flex:none;width:calc(50% - 66px)';
      strip.appendChild(pad.cloneNode());
      items.forEach((it, i) => {
        const e = h('div', 'dial-item', `<b>${esc(it.title)}</b>` + (it.sub ? `<small>${esc(it.sub)}</small>` : ''));
        e.onclick = () => scrollTo(i, true);
        tiles.push(e);
        strip.appendChild(e);
      });
      strip.appendChild(pad);
      strip.addEventListener('scroll', () => {
        requestAnimationFrame(paint);
        clearTimeout(settle);
        settle = setTimeout(() => {
          if (programmatic) { programmatic = false; return; }
          const c = centered();
          if (c !== selected) { selected = c; onSel(c); }
        }, 160);
      }, { passive: true });
      dial.appendChild(strip);
      requestAnimationFrame(() => scrollTo(selected, false));
    }
    dial.appendChild(h('div', 'dial-needle'));
  }
  return {
    el: wrap,
    update(newItems, sel, key, fn) {
      onSel = fn;
      const changed = key !== listKey || (newItems == null) !== (items == null);
      items = newItems; listKey = key;
      if (changed) { selected = sel; build(); }
      else if (sel !== selected && strip) { selected = sel; scrollTo(sel, true); }
    },
  };
}
/** Vue moderne : liste déroulante native avec le nombre de stations. */
function makeSelect(label) {
  const wrap = h('div', '', `<div class="dial-lbl" style="letter-spacing:0;text-transform:none;font-size:12px">${esc(label)}</div>`);
  const box = h('div', 'msel', `<span></span><em></em>${svg('drop')}<select></select>`);
  wrap.appendChild(box);
  const sel = box.querySelector('select');
  let onSel = () => {}, key = null;
  sel.onchange = () => onSel(+sel.value);
  return {
    el: wrap,
    update(items, selected, k, fn) {
      onSel = fn;
      if (items == null) { box.querySelector('span').innerHTML = '<div class="spinner" style="width:18px;height:18px;border-width:2px;margin:0"></div>'; box.querySelector('em').textContent = ''; sel.innerHTML = ''; key = null; return; }
      if (k !== key) {
        sel.innerHTML = items.map((it, i) => `<option value="${i}">${esc(it.title)}${it.sub ? ' (' + esc(it.sub) + ')' : ''}</option>`).join('');
        key = k;
      }
      sel.value = String(selected);
      const cur = items[selected];
      box.querySelector('span').textContent = cur ? cur.title : '—';
      box.querySelector('em').textContent = cur && cur.sub ? cur.sub : '';
    },
  };
}

function openGeo() {
  const knob = h('button', 'knob');
  const p = openPage('Around the world', { actions: knob, onClose: () => openPages.delete(render) });
  const ctl = h('div', 'geo-ctl');
  p.page.appendChild(ctl);
  p.page.appendChild(h('div', 'divider'));
  p.page.style.gap = '0';
  const body = h('div', 'page-body');
  body.style.marginTop = '0';
  p.page.appendChild(body);
  let widgets = null, mode = null, listShown = null;

  function renderKnob() {
    knob.innerHTML = `<span>${GEO.modern ? 'Modern' : 'Retro'}</span><span class="knob-c">` +
      `<i style="left:${24 - 2.2 - 19 * Math.sin(50 * Math.PI / 180)}px;top:${24 - 2.2 - 19 * Math.cos(50 * Math.PI / 180)}px" class="${GEO.modern ? '' : 'on'}"></i>` +
      `<i style="left:${24 - 2.2 + 19 * Math.sin(50 * Math.PI / 180)}px;top:${24 - 2.2 - 19 * Math.cos(50 * Math.PI / 180)}px" class="${GEO.modern ? 'on' : ''}"></i>` +
      `<b style="transform:rotate(${GEO.modern ? 50 : -50}deg)"></b></span>`;
  }
  knob.onclick = () => { GEO.modern = !GEO.modern; store.set('geo_modern', GEO.modern); render(); };
  let kx = 0;
  knob.addEventListener('pointerdown', e => { kx = e.clientX; });
  knob.addEventListener('pointerup', e => {
    const d = e.clientX - kx;
    if (Math.abs(d) > 12 && (d > 0) !== GEO.modern) { GEO.modern = d > 0; store.set('geo_modern', GEO.modern); setTimeout(render, 0); }
  });

  function render() {
    renderKnob();
    const m = GEO.modern ? 'modern' : 'retro';
    if (m !== mode) {
      mode = m;
      ctl.innerHTML = '';
      const mk = GEO.modern ? makeSelect : makeDial;
      widgets = [mk('Continent'), mk('Country'), mk('Region / city')];
      widgets.forEach(w => ctl.appendChild(w.el));
    }
    const continents = CONTINENTS.map(c => ({ title: c.name }));
    const countries = GEO.countries && GEO.countries.map(c => ({ title: c.name, sub: String(c.stations) }));
    const regions = GEO.regions && GEO.regions.map(r => ({ title: r.name, sub: String(r.stations) }));
    const cc = GEO.countries && GEO.countries[GEO.countryIndex];
    widgets[0].update(continents, GEO.continent, 'continents', i => geoSelectContinent(i));
    widgets[1].update(countries, GEO.countryIndex, 'c' + GEO.continent + ':' + (countries ? countries.length : 'x'), geoSelectCountry);
    widgets[2].update(regions, GEO.regionIndex, 'r' + (cc ? cc.code : '') + ':' + (regions ? regions.length : 'x'), geoSelectRegion);

    // liste des stations
    if (GEO.error) { listShown = null; body.innerHTML = ''; body.appendChild(retryMsg()); return; }
    const st = GEO.stations;
    if (st === listShown) { markCurrent(body); return; }   // même liste : seule la station en cours change
    listShown = st;
    body.innerHTML = '';
    body.scrollTop = 0;
    if (st === 'loading') body.appendChild(h('div', 'center-msg', '<div class="spinner"></div>'));
    else if (st === 'error') body.appendChild(retryMsg());
    else if (!st.length) body.appendChild(h('div', 'center-msg', 'No station found.'));
    else st.forEach(s => body.appendChild(resultRow(s, play)));   // la page reste ouverte : on peut zapper
  }
  function retryMsg() {
    const m = h('div', 'center-msg', 'Could not load stations.');
    const r = h('button', 'text-btn', 'Retry');
    r.onclick = () => { if (!GEO.all) geoLoadCountries(); else geoLoadCountry(); };
    m.appendChild(r);
    return m;
  }
  render();
  openPages.add(render);
  if (!GEO.all) geoLoadCountries();
}

/* ---------------- démarrage ---------------- */
$('#fav-btn').innerHTML = svg('fav');
$('#geo-btn').innerHTML = svg('globe');
$('#search-btn').innerHTML = svg('search');
$('#fav-btn').onclick = () => openFavorites();
$('#geo-btn').onclick = openGeo;
$('#search-btn').onclick = openSearch;
$('#src-btn').onclick = openSources;
$('#play-btn').onclick = togglePlay;
const vol = $('#vol');
vol.addEventListener('pointerdown', () => { S.volDrag = true; });
vol.addEventListener('input', () => sendVol(false));
vol.addEventListener('change', () => { S.volDrag = false; sendVol(true); });
vol.addEventListener('pointerup', () => { S.volDrag = false; });
$('#vol-ico').onclick = () => {
  const v = +vol.value;
  if (v > 0) S.volBefore = v;
  vol.value = v > 0 ? 0 : (S.volBefore || 50);
  sendVol(true);
};
renderAll();
poll();
loadLocal();
