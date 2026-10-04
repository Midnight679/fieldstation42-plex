// News42: a headline news channel page. Settings come from the address, e.g.
//   news.html?config=runtime/news_config.json&lat=40.71&lon=-74.01&name=New%20York&units=f
//   config    a JSON file under the FieldStation42 folder listing the sections and their feeds (see docs/NEWS.md);
//             without it, a few general public feeds are used
//   lat, lon  optional: show the current temperature in the bottom bar   name  place name for it
//   units     f (default) or c      rotate  seconds per story (default 14)
//   music     a folder of audio files under the FieldStation42 folder    volume  music volume 0 to 1 (default 0.25)
// Feeds are read through the FieldStation42 server (/news/feed), because a page cannot read another site's feed itself.
const params = new URLSearchParams(window.location.search);
const CONFIG_PATH = params.get('config');
const LAT = parseFloat(params.get('lat'));
const LON = parseFloat(params.get('lon'));
const PLACE = params.get('name') || '';
const FAHRENHEIT = (params.get('units') || 'f').toLowerCase() !== 'c';
const STORY_MS = (parseFloat(params.get('rotate')) || 14) * 1000;
const MUSIC_DIR = params.get('music');
const MUSIC_VOLUME = Math.min(1, Math.max(0, parseFloat(params.get('volume')) || 0.25));
const REFRESH_MS = 10 * 60 * 1000;

const DEFAULT_CONFIG = {
  sections: [
    { title: 'Top Stories', count: 6, feeds: ['https://feeds.npr.org/1001/rss.xml', 'https://www.cbsnews.com/latest/rss/main', 'https://feeds.nbcnews.com/nbcnews/public/news'] },
    { title: 'World', count: 6, feeds: ['https://feeds.bbci.co.uk/news/world/rss.xml', 'https://www.theguardian.com/world/rss'] },
    { title: 'United States', count: 6, feeds: ['https://www.pbs.org/newshour/feeds/rss/headlines', 'https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml'] },
  ],
};

let config = DEFAULT_CONFIG;
let sections = [];      // [{title, items: [{title, summary, source, published}]}] with data
let sectionIndex = 0;
let itemIndex = 0;
let rotateTimer = null;
const stage = document.getElementById('stage');

// ---- loading headlines
async function loadConfig() {
  if (!CONFIG_PATH) return;
  try {
    const resp = await fetch('/media/json?path=' + encodeURIComponent(CONFIG_PATH));
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    if (data && Array.isArray(data.sections) && data.sections.length) config = data;
  } catch (e) {
    console.warn('using the default feeds:', e.message);
  }
}

async function fetchFeed(url, limit) {
  const resp = await fetch('/news/feed?limit=' + limit + '&u=' + encodeURIComponent(url));
  if (!resp.ok) throw new Error('HTTP ' + resp.status);
  const data = await resp.json();
  return data.items.map((i) => ({ ...i, source: data.source }));
}

// one story from each feed in turn, so no single outlet fills the section; repeated headlines are dropped
function interleave(lists, count) {
  const out = [], seen = new Set();
  for (let n = 0; out.length < count && lists.some((l) => n < l.length); n++) {
    for (const l of lists) {
      if (n >= l.length || out.length >= count) continue;
      const key = l[n].title.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(l[n]);
    }
  }
  return out;
}

async function refreshNews() {
  const fresh = [];
  for (const sec of config.sections) {
    const count = sec.count || 6;
    const results = await Promise.allSettled(sec.feeds.map((u) => fetchFeed(u, count + 2)));
    const lists = results.filter((r) => r.status === 'fulfilled').map((r) => r.value);
    const items = interleave(lists, count);
    if (items.length) fresh.push({ title: sec.title, items });
  }
  if (!fresh.length) {           // keep showing what we had; only show the error if there is nothing at all
    stage.classList.toggle('no-data', !sections.length);
    return;
  }
  const first = !sections.length;
  const current = sections[sectionIndex] && sections[sectionIndex].title;
  sections = fresh;
  const keep = sections.findIndex((s) => s.title === current);
  if (!first && keep >= 0) sectionIndex = keep;
  stage.classList.remove('no-data');
  buildTicker();
  if (first) { sectionIndex = 0; itemIndex = 0; showStory(true); scheduleRotation(); }
}

// ---- drawing the screen
function ago(published) {
  const t = Date.parse(published);
  if (isNaN(t)) return '';
  const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (mins < 2) return 'Just now';
  if (mins < 60) return mins + ' minutes ago';
  const hrs = Math.round(mins / 60);
  if (hrs < 36) return hrs + (hrs === 1 ? ' hour ago' : ' hours ago');
  return Math.round(hrs / 24) + ' days ago';
}

function showStory(immediate) {
  const sec = sections[sectionIndex];
  if (!sec) return;
  const story = sec.items[itemIndex];
  const card = document.getElementById('lead-card');
  const draw = () => {
    document.getElementById('section-title').textContent = sec.title;
    document.getElementById('lead-kicker').textContent = sec.title;
    document.getElementById('lead-title').textContent = story.title;
    document.getElementById('lead-summary').textContent = story.summary && story.summary !== story.title ? story.summary : '';
    document.getElementById('lead-meta').textContent = [story.source, ago(story.published)].filter(Boolean).join('  •  ');
    const list = document.getElementById('list');
    list.innerHTML = '';
    sec.items.forEach((it, n) => {
      const row = document.createElement('div');
      row.className = 'list-item' + (n === itemIndex ? ' active' : '');
      const span = document.createElement('span');
      span.textContent = it.title;
      row.appendChild(span);
      list.appendChild(row);
    });
    card.classList.remove('swap');
  };
  if (immediate) return draw();
  card.classList.add('swap');
  setTimeout(draw, 450);
}

function advance() {
  const sec = sections[sectionIndex];
  if (!sec) return;
  itemIndex++;
  if (itemIndex >= sec.items.length) {
    itemIndex = 0;
    sectionIndex = (sectionIndex + 1) % sections.length;
  }
  showStory(false);
}

function scheduleRotation() {
  clearInterval(rotateTimer);
  rotateTimer = setInterval(advance, STORY_MS);
}

function buildTicker() {
  const text = document.getElementById('ticker-text');
  text.innerHTML = '';
  for (const sec of sections) {
    const tag = document.createElement('span');
    tag.className = 'tag';
    tag.textContent = sec.title.toUpperCase();
    text.appendChild(tag);
    text.appendChild(document.createTextNode(sec.items.map((i) => i.title).join('   ◆   ')));
  }
  // about 0.17 seconds per character keeps the speed comfortable at any length
  text.style.animationDuration = Math.max(60, text.textContent.length * 0.17) + 's';
}

// ---- clock
function tickClock() {
  const now = new Date();
  document.getElementById('clock').textContent = now.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  document.getElementById('date').textContent = now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' });
}

// ---- weather box (optional): Open-Meteo, free and keyless
function weatherWord(code) {
  if (code === 0) return 'Clear';
  if (code <= 2) return 'Partly Cloudy';
  if (code === 3) return 'Overcast';
  if (code === 45 || code === 48) return 'Fog';
  if (code >= 51 && code <= 67) return 'Rain';
  if (code >= 71 && code <= 77) return 'Snow';
  if (code >= 80 && code <= 82) return 'Showers';
  if (code === 85 || code === 86) return 'Snow Showers';
  if (code >= 95) return 'Thunderstorms';
  return '';
}

async function refreshWeather() {
  if (isNaN(LAT) || isNaN(LON)) return;
  try {
    const unit = FAHRENHEIT ? '&temperature_unit=fahrenheit' : '';
    const url = 'https://api.open-meteo.com/v1/forecast?latitude=' + LAT + '&longitude=' + LON + '&current=temperature_2m,weather_code' + unit;
    const data = await (await fetch(url)).json();
    const t = Math.round(data.current.temperature_2m);
    const box = document.getElementById('wx');
    box.textContent = (PLACE ? PLACE.toUpperCase() + '  ' : '') + t + '°' + (FAHRENHEIT ? 'F' : 'C');
    const word = weatherWord(data.current.weather_code);
    if (word) { const s = document.createElement('small'); s.textContent = word; box.appendChild(s); }
  } catch (e) {
    console.warn('weather unavailable:', e.message);   // keep whatever was showing
  }
}

// ---- music: every audio file in a folder, shuffled, quietly in the background
async function startMusic() {
  if (!MUSIC_DIR) return;
  try {
    const resp = await fetch('/media/list?path=' + encodeURIComponent(MUSIC_DIR));
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const tracks = (await resp.json()).files || [];
    if (!tracks.length) return;
    for (let i = tracks.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [tracks[i], tracks[j]] = [tracks[j], tracks[i]]; }
    const audio = new Audio();
    audio.volume = MUSIC_VOLUME;
    let n = 0, failures = 0;
    const next = () => { audio.src = tracks[n++ % tracks.length]; audio.play().catch(() => {}); };
    audio.addEventListener('ended', () => { failures = 0; next(); });
    audio.addEventListener('error', () => { if (++failures < tracks.length) next(); });
    next();
  } catch (e) {
    console.warn('no music:', e.message);
  }
}

// ---- start
(async function init() {
  tickClock();
  setInterval(tickClock, 1000);
  await loadConfig();
  await refreshNews();
  if (!sections.length) stage.classList.add('no-data');
  setInterval(refreshNews, REFRESH_MS);
  setInterval(() => { if (!sections.length) refreshNews(); }, 30000);   // retry soon when there was nothing at all
  refreshWeather();
  setInterval(refreshWeather, 15 * 60 * 1000);
  startMusic();
})();
