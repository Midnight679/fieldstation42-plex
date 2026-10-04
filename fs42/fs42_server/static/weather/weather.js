// Weather42: a local weather channel page. Settings come from the address, e.g.
//   weather.html?lat=40.71&lon=-74.01&name=New%20York&units=f&rotate=14
//   lat, lon  location (required)        name    place name shown on screen
//   units     f (default) or c            rotate  seconds per screen (default 14)
//   bg        comma-separated image names in the bg/ folder (default: scenes for the time of day and weather)
//   music     a folder of audio files under the FieldStation42 folder, e.g. runtime/weather_music
//   volume    music volume from 0 to 1 (default 0.3)
// Data comes from Open-Meteo (https://open-meteo.com): free, no account or key.
const params = new URLSearchParams(window.location.search);
const LAT = parseFloat(params.get('lat'));
const LON = parseFloat(params.get('lon'));
const PLACE = params.get('name') || 'Your Area';
const FAHRENHEIT = (params.get('units') || 'f').toLowerCase() !== 'c';
const ROTATE_MS = (parseFloat(params.get('rotate')) || 14) * 1000;
const REFRESH_MS = 15 * 60 * 1000;
const BG_FIXED = (params.get('bg') || '').split(',').map((s) => s.trim()).filter(Boolean);
const MUSIC_DIR = params.get('music');
const MUSIC_VOLUME = Math.min(1, Math.max(0, parseFloat(params.get('volume')) || 0.3));
const SCREENS = ['screen-now', 'screen-hourly', 'screen-daily', 'screen-almanac'];
const TITLES = ['Current Conditions', 'Next 12 Hours', '5-Day Forecast', 'Sun and Almanac'];

let weather = null;
let screenIndex = 0;
let rotateTimer = null;

// ---- weather codes (WMO) -> words and an icon kind
function describe(code) {
  if (code === 0) return ['Clear', 'sun'];
  if (code === 1) return ['Mostly Clear', 'sun'];
  if (code === 2) return ['Partly Cloudy', 'partly'];
  if (code === 3) return ['Overcast', 'cloud'];
  if (code === 45 || code === 48) return ['Fog', 'fog'];
  if (code >= 51 && code <= 57) return ['Drizzle', 'rain'];
  if (code >= 61 && code <= 65) return ['Rain', 'rain'];
  if (code === 66 || code === 67) return ['Freezing Rain', 'rain'];
  if (code >= 71 && code <= 77) return ['Snow', 'snow'];
  if (code >= 80 && code <= 82) return ['Showers', 'rain'];
  if (code === 85 || code === 86) return ['Snow Showers', 'snow'];
  if (code >= 95) return ['Thunderstorms', 'storm'];
  return ['Unknown', 'cloud'];
}

// ---- simple vector icons (no emoji fonts needed)
const CLOUD = '<path d="M20 46h26a11 11 0 0 0 1.5-21.9A15 15 0 0 0 18.6 28 9 9 0 0 0 20 46z" fill="#e8f1ff" stroke="#9db8e6" stroke-width="1.5"/>';
const GREYCLOUD = '<path d="M20 46h26a11 11 0 0 0 1.5-21.9A15 15 0 0 0 18.6 28 9 9 0 0 0 20 46z" fill="#9aa9c4" stroke="#6f7f9d" stroke-width="1.5"/>';
function sunSvg(cx, cy, r) {
  let rays = '';
  for (let i = 0; i < 8; i++) {
    const a = (i * Math.PI) / 4, x1 = cx + Math.cos(a) * (r + 4), y1 = cy + Math.sin(a) * (r + 4);
    const x2 = cx + Math.cos(a) * (r + 10), y2 = cy + Math.sin(a) * (r + 10);
    rays += `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="#ffd23f" stroke-width="3" stroke-linecap="round"/>`;
  }
  return rays + `<circle cx="${cx}" cy="${cy}" r="${r}" fill="#ffd23f" stroke="#ffb400" stroke-width="1.5"/>`;
}
function icon(kind, isDay = true) {
  let body = '';
  switch (kind) {
    case 'sun': body = isDay ? sunSvg(32, 32, 12) : '<circle cx="32" cy="32" r="14" fill="#dfe8ff"/><circle cx="38" cy="28" r="12" fill="#10306e"/>'; break;
    case 'partly': body = (isDay ? sunSvg(24, 24, 9) : '<circle cx="24" cy="24" r="10" fill="#dfe8ff"/>') + CLOUD; break;
    case 'cloud': body = CLOUD; break;
    case 'fog': body = CLOUD + '<g stroke="#cfe0ff" stroke-width="3" stroke-linecap="round"><line x1="14" y1="52" x2="50" y2="52"/><line x1="18" y1="58" x2="46" y2="58"/></g>'; break;
    case 'rain': body = GREYCLOUD + '<g stroke="#4aa3ff" stroke-width="3" stroke-linecap="round"><line x1="24" y1="50" x2="21" y2="58"/><line x1="33" y1="50" x2="30" y2="58"/><line x1="42" y1="50" x2="39" y2="58"/></g>'; break;
    case 'snow': body = GREYCLOUD + '<g fill="#ffffff"><circle cx="23" cy="53" r="2.6"/><circle cx="33" cy="57" r="2.6"/><circle cx="43" cy="53" r="2.6"/></g>'; break;
    case 'storm': body = GREYCLOUD + '<polygon points="34,44 26,56 32,56 29,64 41,50 34,50 38,44" fill="#ffd23f" stroke="#ffb400" stroke-width="1"/>'; break;
    default: body = CLOUD;
  }
  return `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">${body}</svg>`;
}

// ---- formatting helpers
const deg = (v) => `${Math.round(v)}°`;
const unitT = () => (FAHRENHEIT ? 'F' : 'C');
const compass = (d) => ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'][Math.round(d / 22.5) % 16];
function hourLabel(iso) {
  const h = new Date(iso).getHours();
  return `${((h + 11) % 12) + 1} ${h < 12 ? 'AM' : 'PM'}`;
}
const dayName = (iso) => new Date(iso + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short' });
function clock12(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

// ---- data
async function loadWeather() {
  if (Number.isNaN(LAT) || Number.isNaN(LON)) throw new Error('Add ?lat=...&lon=... to the address');
  const url = 'https://api.open-meteo.com/v1/forecast'
    + `?latitude=${LAT}&longitude=${LON}`
    + '&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,wind_direction_10m,surface_pressure,is_day'
    + '&hourly=temperature_2m,weather_code,precipitation_probability,is_day'
    + '&daily=weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,precipitation_probability_max'
    + `&temperature_unit=${FAHRENHEIT ? 'fahrenheit' : 'celsius'}&wind_speed_unit=${FAHRENHEIT ? 'mph' : 'kmh'}`
    + '&timezone=auto&forecast_days=7';
  const resp = await fetch(url);
  if (!resp.ok) throw new Error('HTTP ' + resp.status);
  return resp.json();
}

// ---- screens
function renderNow(w) {
  const c = w.current, [cond, kind] = describe(c.weather_code);
  const pressure = FAHRENHEIT ? `${(c.surface_pressure * 0.02953).toFixed(2)} in` : `${Math.round(c.surface_pressure)} hPa`;
  const speed = FAHRENHEIT ? 'mph' : 'km/h';
  document.getElementById('screen-now').innerHTML = `
    <div class="panel now-main">
      <div class="now-icon">${icon(kind, c.is_day === 1)}</div>
      <div><div class="now-temp">${Math.round(c.temperature_2m)}<sup>°${unitT()}</sup></div><div class="now-cond">${cond}</div></div>
    </div>
    <div class="panel now-facts">
      <div class="fact"><span>Feels Like</span><span>${deg(c.apparent_temperature)}</span></div>
      <div class="fact"><span>Humidity</span><span>${Math.round(c.relative_humidity_2m)}%</span></div>
      <div class="fact"><span>Wind</span><span>${compass(c.wind_direction_10m)} ${Math.round(c.wind_speed_10m)} ${speed}</span></div>
      <div class="fact"><span>Pressure</span><span>${pressure}</span></div>
    </div>`;
}

function renderHourly(w) {
  const h = w.hourly;
  let start = h.time.findIndex((t) => new Date(t) >= new Date(w.current.time));
  if (start < 0) start = 0;
  let cols = '';
  for (let i = 0; i < 6; i++) {
    const idx = start + i * 2;
    if (idx >= h.time.length) break;
    const [cond, kind] = describe(h.weather_code[idx]);
    cols += `<div class="panel col"><div class="when">${i === 0 ? 'Now' : hourLabel(h.time[idx])}</div>${icon(kind, h.is_day[idx] === 1)}
      <div class="temp">${deg(h.temperature_2m[idx])}</div><div class="cond">${cond}</div>
      <div class="sub">${h.precipitation_probability[idx] ?? 0}% chance</div></div>`;
  }
  document.getElementById('screen-hourly').innerHTML = `<div class="cols">${cols}</div>`;
}

function renderDaily(w) {
  const d = w.daily;
  let cols = '';
  for (let i = 0; i < 5 && i < d.time.length; i++) {
    const [cond, kind] = describe(d.weather_code[i]);
    cols += `<div class="panel col"><div class="when">${i === 0 ? 'Today' : dayName(d.time[i])}</div>${icon(kind, true)}
      <div class="hilo">${deg(d.temperature_2m_max[i])} <span class="lo">${deg(d.temperature_2m_min[i])}</span></div>
      <div class="cond">${cond}</div><div class="sub">${d.precipitation_probability_max[i] ?? 0}% chance</div></div>`;
  }
  document.getElementById('screen-daily').innerHTML = `<div class="cols">${cols}</div>`;
}

function renderAlmanac(w) {
  const d = w.daily, rise = new Date(d.sunrise[0]), set = new Date(d.sunset[0]);
  const mins = Math.round((set - rise) / 60000);
  document.getElementById('screen-almanac').innerHTML = `
    <div class="panel alm"><div class="label">SUNRISE</div>${icon('sun', true)}<div class="big">${clock12(d.sunrise[0])}</div></div>
    <div class="panel alm"><div class="label">SUNSET</div>${icon('sun', false)}<div class="big">${clock12(d.sunset[0])}</div></div>
    <div class="panel alm"><div class="label">TODAY</div><div class="big">${deg(d.temperature_2m_max[0])} / ${deg(d.temperature_2m_min[0])}</div>
      <div class="small">Daylight: ${Math.floor(mins / 60)} hours ${mins % 60} minutes</div></div>`;
}

function renderTicker(w) {
  const c = w.current, d = w.daily, [cond] = describe(c.weather_code), [todayCond] = describe(d.weather_code[0]);
  const bits = [
    `Currently ${Math.round(c.temperature_2m)}°${unitT()} and ${cond.toLowerCase()} in ${PLACE}.`,
    `Today: ${todayCond.toLowerCase()}, a high of ${Math.round(d.temperature_2m_max[0])}° and a low of ${Math.round(d.temperature_2m_min[0])}°, with a ${d.precipitation_probability_max[0] ?? 0}% chance of precipitation.`,
    `Tomorrow: ${describe(d.weather_code[1])[0].toLowerCase()}, ${Math.round(d.temperature_2m_max[1])}° / ${Math.round(d.temperature_2m_min[1])}°.`,
    'You are watching Weather42.',
  ];
  document.getElementById('ticker-text').textContent = bits.join('      •      ');
}

// ---- background scenes: chosen by time of day and by the weather, two shapes of each that cross-fade
let bgIndex = 0, bgFront = 0, bgTimer = null, bgKey = null;

function dayPhase(w) {
  const now = new Date(w.current.time), rise = new Date(w.daily.sunrise[0]), set = new Date(w.daily.sunset[0]);
  const min = 60000;
  if (now < rise - 30 * min) return 'night';
  if (now < +rise + 60 * min) return 'dawn';
  if (now < set - 90 * min) return 'day';
  if (now < +set + 30 * min) return 'dusk';
  return 'night';
}

function sceneCondition(code) {
  if (code === 45 || code === 48) return 'fog';
  if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82)) return 'rain';
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return 'snow';
  if (code >= 95) return 'storm';
  if (code === 3 || code === 2) return 'cloudy';
  return 'clear';
}

function bgList() {
  if (BG_FIXED.length) return BG_FIXED;
  const [phase, cond] = bgKey.split('_');
  return [`${phase}_${cond}_1.jpg`, `${phase}_${cond}_2.jpg`];
}

function showBackground(step) {
  const list = bgList();
  bgIndex = (bgIndex + step) % list.length;
  const layers = document.querySelectorAll('.bg-layer');
  const next = layers[1 - bgFront], current = layers[bgFront];
  next.style.backgroundImage = `url("bg/${list[bgIndex]}")`;
  next.classList.add('show');
  current.classList.remove('show');
  bgFront = 1 - bgFront;
}

function updateBackground(w) {
  const key = `${dayPhase(w)}_${sceneCondition(w.current.weather_code)}`;
  if (key !== bgKey || !bgTimer) {
    bgKey = key;
    bgIndex = -1;
    showBackground(1);
    clearInterval(bgTimer);
    bgTimer = setInterval(() => showBackground(1), 45000);
  }
}

// ---- music: plays every audio file in a folder, shuffled, quietly in the background
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

// ---- rotation, clock and refresh
function showScreen(i) {
  screenIndex = i % SCREENS.length;
  SCREENS.forEach((id, n) => document.getElementById(id).classList.toggle('active', n === screenIndex));
  document.getElementById('screen-title').textContent = TITLES[screenIndex];
  document.querySelectorAll('#dots i').forEach((dot, n) => dot.classList.toggle('on', n === screenIndex));
}

function showError(message) {
  clearInterval(rotateTimer);
  document.getElementById('error-detail').textContent = message;
  SCREENS.forEach((id) => document.getElementById(id).classList.remove('active'));
  document.getElementById('screen-error').classList.add('active');
  document.getElementById('screen-title').textContent = 'Weather42';
}

function startRotation() {
  clearInterval(rotateTimer);
  document.getElementById('screen-error').classList.remove('active');
  showScreen(screenIndex);
  rotateTimer = setInterval(() => showScreen(screenIndex + 1), ROTATE_MS);
}

function tickClock() {
  const now = new Date();
  document.getElementById('clock').textContent = now.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  document.getElementById('date').textContent = now.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
}

async function refresh() {
  try {
    weather = await loadWeather();
    renderNow(weather); renderHourly(weather); renderDaily(weather); renderAlmanac(weather); renderTicker(weather);
    updateBackground(weather);
    startRotation();
  } catch (e) {
    console.warn('weather unavailable:', e.message);
    if (!weather) showError(e.message);   // keep showing the last good data if a later refresh fails
  }
}

document.getElementById('place').textContent = PLACE;
document.getElementById('dots').innerHTML = SCREENS.map(() => '<i></i>').join('');
tickClock();
setInterval(tickClock, 1000);
refresh();
setInterval(refresh, REFRESH_MS);
startMusic();
