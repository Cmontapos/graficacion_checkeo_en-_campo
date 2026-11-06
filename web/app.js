// GasLab 2.0 · página principal. Los datos vienen de gaslab_web.py ya reducidos al ancho de cada gráfica.
'use strict';

const PALETTE = ['#007f86', '#d95f02', '#7570b3', '#e7298a', '#66a61e', '#e6ab02', '#a6761d', '#1f78b4', '#b2182b', '#8c564b'];
const $ = (id) => document.getElementById(id);
const state = { id: null, info: null, zone: 'UTC', selected: [], range: null, route: null, zones: new Set(['UTC']),
  step: 1, bounds: {}, shown: null, range2: null,
  heat: { name: null, view: '2d', data: null, fitted: null }, terrain: { data: null, fitted: null } }; // bounds: { variable: { min, max } } con el texto tal como se escribió
const charts = new Map(); // variable -> div
const config = { displaylogo: false, responsive: true, scrollZoom: true, modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'] };

// ---------- utilidades ----------
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const fmt = (n) => n.toLocaleString('es');
const colorOf = (name) => PALETTE[Math.max(state.info.variables.indexOf(name), 0) % PALETTE.length];

function toast(message, error = false) {
  const box = $('toast');
  box.textContent = message;
  box.className = 'toast' + (error ? ' error' : '');
  box.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { box.hidden = true; }, error ? 7000 : 3500);
}

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || response.statusText);
  return body;
}

// Plotly interpreta los números de fecha en la zona del navegador, pero los textos 'AAAA-MM-DD HH:MM:SS' tal cual:
// por eso los ms "de reloj" que manda el servidor se le pasan siempre como texto.
const wall = (ms) => new Date(ms).toISOString().slice(0, 23).replace('T', ' ');

// Plotly devuelve el rango como texto 'AAAA-MM-DD HH:MM:SS.sss' en hora "de reloj"; el servidor usa ms de reloj.
function toMs(value) {
  if (typeof value === 'number') return value;
  const text = value.includes(' ') ? value.replace(' ', 'T') : value.includes('T') ? value : value + 'T00:00:00';
  return Date.parse(text + 'Z');
}

function baseLayout() {
  const text = css('--text'), line = css('--line');
  return {
    margin: { l: 56, r: 12, t: 6, b: 30 },
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    // Como en la versión anterior: arrastrar desplaza y la rueda hace zoom (el recuadro de zoom sigue en la barra).
    font: { color: text, size: 12 }, hovermode: 'x', showlegend: false, dragmode: 'pan',
    hoverlabel: { bgcolor: css('--card'), bordercolor: line, font: { color: text } },
  };
}

function timeAxis(range = state.range) {
  const axis = {
    type: 'date', gridcolor: css('--line'), zeroline: false, hoverformat: '%d/%m/%Y %H:%M:%S',
    tickformatstops: [
      { dtickrange: [null, 60000], value: '%H:%M:%S' },
      { dtickrange: [60000, 86400000], value: '%H:%M' },
      { dtickrange: [86400000, null], value: '%d/%m' },
    ],
  };
  if (range) axis.range = range.map(wall);
  else axis.autorange = true;
  return axis;
}

// Rango que se le pide al servidor: el visible más un ancho a cada lado, para poder desplazar sin ver huecos.
function fetchWindow(query, range, width) {
  if (range) {
    const span = range[1] - range[0];
    query.set('start', range[0] - span);
    query.set('end', range[1] + span);
  }
  query.set('width', range ? width * 3 : width);
}

// Eje Y ajustado a lo que se ve (como el visor anterior), no a todo lo descargado.
function yRange(xs, lines, range) {
  let lo = Infinity, hi = -Infinity;
  for (const ys of lines) {
    for (let i = 0; i < xs.length; i++) {
      const x = xs[i], y = ys[i];
      if (x === null || y === null || (range && (x < range[0] || x > range[1]))) continue;
      if (y < lo) lo = y;
      if (y > hi) hi = y;
    }
  }
  if (lo === Infinity) return null;
  const pad = (hi - lo) * 0.06 || Math.abs(hi) * 0.02 || 1;
  return [lo - pad, hi + pad];
}

function yAxis(range) {
  const axis = { gridcolor: css('--line'), zeroline: false, fixedrange: true, automargin: true };
  if (range) axis.range = range;
  else axis.autorange = true;
  return axis;
}

// ---------- abrir archivo ----------
// sheet: hoja de Excel elegida en el selector; sin ella el servidor abre 'Datos' o la hoja más grande.
async function openFile(file, sheet) {
  if (!file) return;
  $('fileinfo').textContent = `Cargando ${file.name}${sheet ? ` (hoja ${sheet})` : ''}…`;
  try {
    const headers = { 'X-Filename': encodeURIComponent(file.name) };
    if (sheet) headers['X-Sheet'] = encodeURIComponent(sheet);
    const info = await api('/api/upload', { method: 'POST', body: file, headers });
    state.file = file;
    showSheets(info);
    $('calbox').hidden = !info.cal_id;
    $('gpsbox').hidden = !info.drone;
    state.id = currentId(info);
    state.info = info;
    state.range = state.range2 = state.shown = null;
    state.tramo = null;
    showTramo();
    state.bounds = {};
    state.selected = info.defaults.length ? [...info.defaults] : info.variables.filter((v) => v !== info.altitude).slice(0, 1);
    $('fileinfo').textContent = fileText(info);
    $('empty').hidden = true;
    $('workspace').hidden = false;
    $('filter').value = '';
    $('note').textContent = info.missing_gases.length ? `${info.missing_gases.join(' y ')} no ${info.missing_gases.length > 1 ? 'están' : 'está'} en este archivo` : '';
    $('alttitle').textContent = info.altitude ? `Altura (${info.altitude})` : 'Altura';
    renderVariables();
    for (const div of charts.values()) { Plotly.purge(div); div.closest('.card').remove(); }
    charts.clear();
    for (const tab of document.querySelectorAll('.tab')) tab.disabled = false;
    state.heat.name = state.heat.fitted = state.terrain.fitted = null;
    showStep(state.step);
    await Promise.all([loadTramos(), loadRoute(), refresh()]);
  } catch (error) {
    $('fileinfo').textContent = state.info ? fileText(state.info) : 'Ningún archivo abierto';
    if (state.info) showSheets(state.info); // el selector vuelve a la hoja que sigue abierta
    toast(error.message, true);
  }
}

// Original / Calibrado / Comparación: si el archivo trae columnas '_cal', el servidor guarda las dos versiones con
// los mismos nombres de variables y la página solo cambia de id; la selección, los límites y la vista se conservan.
// En Comparación las gráficas piden también la versión original (compare=) y los mapas usan la calibrada.
const CAL_KEY = 'gaslab.calibrado';
const CAL_MODES = { original: 'Usando las columnas originales.', cal: 'Usando las columnas calibradas (_cal).',
  compare: 'Comparación: las gráficas muestran calibrado y sin calibrar (gris punteado); los mapas usan el calibrado.' };
let calMode = 'original';
try { calMode = { 1: 'cal', 0: 'original' }[localStorage.getItem(CAL_KEY)] || localStorage.getItem(CAL_KEY) || 'original'; } catch (error) { /* sin almacenamiento */ }
if (!CAL_MODES[calMode]) calMode = 'original';
const currentId = (info) => (calMode !== 'original' && info.cal_id) || info.id;
const compareId = () => (calMode === 'compare' && state.info && state.info.cal_id ? state.info.id : null);
const showCalMode = () => { for (const b of document.querySelectorAll('[data-cal]')) b.classList.toggle('on', b.dataset.cal === calMode); };
showCalMode();
$('calbox').addEventListener('click', (event) => {
  const mode = event.target.dataset && event.target.dataset.cal;
  if (!mode || mode === calMode) return;
  calMode = mode;
  showCalMode();
  try { localStorage.setItem(CAL_KEY, mode); } catch (error) { /* no se recuerda, pero funciona */ }
  if (!state.info || !state.info.cal_id) return;
  state.id = currentId(state.info);
  loadRoute();
  refresh();
  if (state.step === 2) refreshBig();
  if (state.step === 3) refreshHeat();
  if (state.step === 4) refreshTerrain();
  if (state.step === 5) enterExcel();
  toast(CAL_MODES[mode]);
});
// Líneas que cuentan para el rango del eje Y: la serie, y en Comparación también la otra versión.
const linesOf = (series, ...extra) => [series.y, ...extra, ...(series.compare ? [series.compare] : [])];
const diffText = (d) => (d ? ` · calibrado − sin calibrar: promedio ${num(d.mean)}, máx ${num(d.max)}` : '');

// GPS sensor / Dron / Ambos: si el archivo trae también la posición del dron (latitud_dron, drone_lat...), los mapas
// pueden usar esa. En Ambos la ruta muestra las dos (la del sensor en gris punteado) y los mapas usan la del dron.
const GPS_KEY = 'gaslab.gps';
const GPS_MODES = { sensor: 'Mapas con el GPS del sensor.', dron: 'Mapas con el GPS del dron (las filas sin posición del dron quedan sin punto).',
  both: 'Ruta con los dos GPS (sensor en gris punteado); los mapas de calor y terreno usan el del dron.' };
let gpsMode = 'sensor';
try { gpsMode = localStorage.getItem(GPS_KEY) || 'sensor'; } catch (error) { /* sin almacenamiento */ }
if (!GPS_MODES[gpsMode]) gpsMode = 'sensor';
const mapGps = () => (gpsMode !== 'sensor' && state.info && state.info.drone ? 'dron' : 'sensor');
const bothGps = () => gpsMode === 'both' && state.info && state.info.drone;
const showGpsMode = () => { for (const b of document.querySelectorAll('[data-gps]')) b.classList.toggle('on', b.dataset.gps === gpsMode); };
showGpsMode();
$('gpsbox').addEventListener('click', (event) => {
  const mode = event.target.dataset && event.target.dataset.gps;
  if (!mode || mode === gpsMode) return;
  gpsMode = mode;
  showGpsMode();
  try { localStorage.setItem(GPS_KEY, mode); } catch (error) { /* no se recuerda, pero funciona */ }
  if (!state.info || !state.info.drone) return;
  loadRoute();
  if (state.step === 3) refreshHeat();
  if (state.step === 4) refreshTerrain();
  if (state.step === 5) enterExcel();
  toast(GPS_MODES[mode]);
});
const meters = (v) => `${num(v)} m`;

const fileText = (info) => `${info.name} · ${fmt(info.rows)} filas · tiempo: ${info.time_column}`;

function showSheets(info) {
  $('sheetbox').hidden = info.sheets.length < 2;
  $('sheet').replaceChildren(...info.sheets.map((name) => new Option(`Hoja: ${name}`, name, false, name === info.sheet)));
}
$('sheet').addEventListener('change', () => openFile(state.file, $('sheet').value));

$('file').addEventListener('change', (event) => { openFile(event.target.files[0]); event.target.value = ''; });
document.addEventListener('dragover', (event) => { event.preventDefault(); document.body.classList.add('dragging'); });
document.addEventListener('dragleave', (event) => { if (!event.relatedTarget) document.body.classList.remove('dragging'); });
document.addEventListener('drop', (event) => {
  event.preventDefault();
  document.body.classList.remove('dragging');
  openFile(event.dataTransfer.files[0]);
});

// ---------- lista de variables ----------
function renderVariables() {
  const list = $('varlist');
  const filter = $('filter').value.trim().toLowerCase();
  list.replaceChildren();
  for (const name of state.info.variables) {
    if (filter && !name.toLowerCase().includes(filter)) continue;
    const on = state.selected.includes(name);
    const chip = document.createElement('label');
    chip.className = 'chip' + (on ? ' on' : '');
    chip.innerHTML = `<input type="checkbox"${on ? ' checked' : ''}><i></i><span></span>`;
    chip.querySelector('span').textContent = name;
    chip.querySelector('i').style.background = colorOf(name);
    chip.querySelector('input').addEventListener('change', (event) => toggle(name, event.target.checked));
    list.append(chip);
  }
}

// La selección es una sola para todas las pestañas: las filas de límites del paso 2 son estas mismas variables.
function setSelected(names) {
  state.selected = state.info.variables.filter((v) => names.includes(v));
}

function toggle(name, on) {
  setSelected(on ? [...state.selected, name] : state.selected.filter((v) => v !== name));
  renderVariables();
  refresh();
}

$('filter').addEventListener('input', renderVariables);
$('all').addEventListener('click', () => { setSelected(state.info.variables); renderVariables(); refresh(); });
$('none').addEventListener('click', () => { setSelected([]); renderVariables(); refresh(); });
$('gases').addEventListener('click', () => {
  if (!state.info.defaults.length) return toast('Este archivo no tiene columnas de CO₂, SO₂ ni H₂S.', true);
  setSelected(state.info.defaults);
  renderVariables();
  refresh();
});

// ---------- zona horaria ----------
api('/api/zones').then((zones) => {
  state.zones = new Set(zones);
  $('zones').replaceChildren(...zones.map((z) => Object.assign(document.createElement('option'), { value: z })));
}).catch(() => {});

$('zone').addEventListener('change', () => {
  const zone = $('zone').value.trim();
  $('zone').classList.toggle('bad', !state.zones.has(zone));
  if (!state.zones.has(zone)) return toast(`Zona desconocida: «${zone}». Usa un nombre IANA, p. ej. UTC o America/Costa_Rica.`, true);
  state.zone = zone;
  state.range = state.range2 = null; // el rango estaba en la hora de la zona anterior
  if (state.tramo) { resetTramoBoxes(); state.tramo = null; showTramo(); } // y el tramo también
  if (state.id) { loadTramos(); loadRoute(); refresh(); if (state.step === 2) refreshBig(); if (state.step >= 3) showStep(state.step); }
});

// ---------- tramos (como la versión 1) ----------
// Inactividad > N s + Tramo (tramos continuos), o Día de … a …; Todo quita el límite. El tramo vale para todas las
// pestañas: el servidor recibe w0/w1 (ms 'de reloj' de la zona) y solo usa esas muestras en gráficas, mapas y Excel.
state.tramo = null; // { w: [inicio, fin], tag (para el nombre del Excel), text }
let tramoData = null;
const two = (n) => String(n).padStart(2, '0');
const clock = (ms) => wall(ms).slice(11, 19);
const dayText = (ms) => { const d = new Date(ms); return `${two(d.getUTCDate())}/${two(d.getUTCMonth() + 1)}`; };
const durText = (s) => (s >= 3600 ? `${Math.floor(s / 3600)} h ${two(Math.floor((s % 3600) / 60))} min` : `${Math.floor(s / 60)} min ${two(Math.floor(s % 60))} s`);
const withTramo = (query) => { if (state.tramo) { query.set('w0', state.tramo.w[0]); query.set('w1', state.tramo.w[1]); } return query; };

// Rango del paso 1 dentro del tramo: no se puede ver fuera de él (null = el tramo completo).
function keepInside(range) {
  if (!state.tramo || !range) return range;
  const [a, b] = state.tramo.w;
  if (range[1] - range[0] >= b - a) return null;
  let [lo, hi] = range;
  if (lo < a) { hi += a - lo; lo = a; }
  if (hi > b) { lo -= hi - b; hi = b; }
  return lo === range[0] && hi === range[1] ? range : [lo, hi];
}

async function loadTramos() {
  try {
    tramoData = await api(`/api/tramos?id=${state.id}&zone=${encodeURIComponent(state.zone)}&gap=${Number($('gap').value) || 1200}`);
  } catch (error) {
    return toast(error.message, true);
  }
  const list = tramoData.tramos;
  $('tramo').replaceChildren(new Option(`Todo · ${list.length} tramo${list.length > 1 ? 's' : ''}`, ''), ...list.map((x, k) => {
    const end = dayText(x.t0) === dayText(x.t1) ? clock(x.t1) : `${dayText(x.t1)} ${clock(x.t1)}`;
    return new Option(`${k + 1} · ${dayText(x.t0)} ${clock(x.t0)} → ${end} · ${durText(x.seconds)} · ${fmt(x.rows)} muestras`, k);
  }));
  $('day').replaceChildren(new Option('—', ''), ...tramoData.days.map((d, k) => new Option(dayText(d.t0), k)));
  fillHours();
}

function fillHours() {
  const day = tramoData && tramoData.days[$('day').value];
  for (const id of ['hfrom', 'hto']) {
    $(id).replaceChildren(...(day ? day.hours.map((h) => new Option(`${two(h)}:00`, h)) : [new Option('--:--', '')]));
    $(id).disabled = !day;
  }
  if (day) $('hto').value = day.hours[day.hours.length - 1]; // por defecto, todo el día
}

function resetTramoBoxes() {
  $('tramo').value = '';
  $('day').value = '';
  fillHours();
}

function showTramo() {
  $('tramoinfo').textContent = state.tramo ? `Gráficas, mapas y Excel solo con ${state.tramo.text}. «Todo» quita el límite.` : '';
  $('alltime').disabled = !state.tramo;
}

function setTramo(tramo) {
  state.tramo = tramo;
  state.range = state.range2 = null;
  state.heat.fitted = state.terrain.fitted = null; // los mapas se encuadran en el tramo
  showTramo();
  if (!state.id) return;
  loadRoute();
  refresh();
  if (state.step === 2) refreshBig();
  if (state.step === 3) refreshHeat();
  if (state.step === 4) refreshTerrain();
  if (state.step === 5) enterExcel();
}

$('gap').addEventListener('change', async () => {
  if (!state.id) return;
  const wasList = state.tramo && state.tramo.kind === 'tramo';
  await loadTramos();
  if (wasList) setTramo(null); // los tramos cambiaron: se vuelve a Todo
  else if (state.tramo) $('day').value = state.tramo.day;
});
$('tramo').addEventListener('change', () => {
  const k = $('tramo').value;
  $('day').value = '';
  fillHours();
  if (k === '') return setTramo(null);
  const x = tramoData.tramos[k];
  setTramo({ kind: 'tramo', w: [x.t0, x.t1], tag: `tramo${Number(k) + 1}`, text: `el tramo ${Number(k) + 1} (${dayText(x.t0)} ${clock(x.t0)} → ${clock(x.t1)}, ${fmt(x.rows)} muestras)` });
});
function applyHours() {
  const k = $('day').value, day = tramoData.days[k];
  let from = Number($('hfrom').value), to = Number($('hto').value);
  if (to < from) { [from, to] = [to, from]; $('hfrom').value = from; $('hto').value = to; } // el fin no puede quedar antes del inicio
  setTramo({ kind: 'day', day: k, w: [day.t0 + from * 3600000, day.t0 + (to + 1) * 3600000 - 1], tag: `${dayText(day.t0).replace('/', '')}_${two(from)}-${two(to + 1)}h`,
    text: `el día ${dayText(day.t0)} de ${two(from)}:00 a ${two(to + 1)}:00` });
}
$('day').addEventListener('change', () => {
  $('tramo').value = '';
  fillHours();
  if ($('day').value === '') setTramo(null);
  else applyHours();
});
for (const id of ['hfrom', 'hto']) $(id).addEventListener('change', applyHours);
$('alltime').addEventListener('click', () => { resetTramoBoxes(); setTramo(null); });
showTramo();

// ---------- gráficas contra el tiempo ----------
function syncCards() {
  const box = $('charts');
  for (const [name, div] of charts) {
    if (!state.selected.includes(name)) { Plotly.purge(div); div.closest('.card').remove(); charts.delete(name); }
  }
  for (const name of state.selected) {
    if (charts.has(name)) continue;
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = '<div class="card-head"><h3></h3><span class="muted"></span></div><div class="plot chart"></div>';
    card.querySelector('h3').textContent = name;
    charts.set(name, card.querySelector('.plot'));
  }
  // Mismo orden que la lista de variables.
  box.replaceChildren(...state.selected.map((name) => charts.get(name).closest('.card')));
  if (!state.selected.length) box.innerHTML = '<div class="empty-note">Marca una o más variables arriba para graficarlas.</div>';
}

let pending = 0;
async function refresh() {
  if (!state.id) return;
  syncCards();
  $('zonelabel').textContent = `(${state.zone})`;
  const altitude = state.info.altitude;
  const names = [...state.selected, ...(altitude ? [altitude] : [])];
  if (!names.length) return;
  const width = Math.round(($('charts').clientWidth || $('alt').clientWidth || 1200) * (window.devicePixelRatio || 1));
  const query = withTramo(new URLSearchParams({ id: state.id, zone: state.zone, vars: names.join(',') }));
  if (compareId()) query.set('compare', compareId());
  fetchWindow(query, state.range, width);
  const ticket = ++pending;
  let data;
  try {
    data = await api('/api/series?' + query);
  } catch (error) {
    return toast(error.message, true);
  }
  if (ticket !== pending) return; // llegó otra petición más nueva mientras tanto
  for (const name of state.selected) if (data[name]) draw(charts.get(name), name, data[name], colorOf(name));
  if (altitude && data[altitude]) draw($('alt'), altitude, data[altitude], css('--accent'));
  else Plotly.react($('alt'), [], { ...baseLayout(), annotations: [{ text: 'Este archivo no tiene columna de altura', showarrow: false, xref: 'paper', yref: 'paper', x: .5, y: .5, font: { color: css('--muted') } }], xaxis: { visible: false }, yaxis: { visible: false } }, config);
}

function draw(div, name, series, color) {
  const x = series.x.map((ms) => (ms === null ? null : wall(ms)));
  const trace = { type: 'scatter', mode: 'lines', x, y: series.y, line: { color, width: 1.4 }, connectgaps: false, name, hovertemplate: (series.compare ? 'Calibrado: ' : '') + '%{y:.4~g}<extra></extra>' };
  const traces = series.compare ? [{ type: 'scatter', mode: 'lines', x, y: series.compare, line: { color: css('--muted'), width: 1.2, dash: 'dot' }, connectgaps: false, name: 'Sin calibrar', hovertemplate: 'Sin calibrar: %{y:.4~g}<extra></extra>' }, trace] : [trace];
  div._series = series;
  const layout = { ...baseLayout(), xaxis: timeAxis(), yaxis: yAxis(yRange(series.x, linesOf(series), state.range)), shapes: div._cursor || [] };
  Plotly.react(div, traces, layout, config);
  const info = div.closest('.card').querySelector('.card-head .muted');
  info.textContent = (series.shown < series.total ? `${fmt(series.shown)} de ${fmt(series.total)} puntos (acerca para más detalle)` : `${fmt(series.total)} puntos`) + diffText(series.diff);
  if (!div._wired) wire(div);
}

// Zoom y desplazamiento sincronizados: mientras se arrastra o se gira la rueda las demás gráficas siguen en vivo;
// al soltar se pide el tramo con más detalle y se ajusta el eje Y a lo visible.
const plots1 = () => [...charts.values(), $('alt')].filter((div) => div._wired);

function rangeFrom(event) {
  if (event['xaxis.autorange']) return null;
  if (event['xaxis.range[0]'] !== undefined) return [toMs(event['xaxis.range[0]']), toMs(event['xaxis.range[1]'])];
  if (event['xaxis.range']) return event['xaxis.range'].map(toMs);
  return undefined; // el evento no cambió el eje X (p. ej. el cursor)
}

let zoomTimer = null, followFrame = null;
function follow(source) {
  cancelAnimationFrame(followFrame);
  followFrame = requestAnimationFrame(() => {
    for (const other of plots1()) if (other !== source) Plotly.relayout(other, { xaxis: timeAxis() });
    highlightRoute();
  });
}

function wire(div) {
  div._wired = true;
  div.on('plotly_relayouting', (event) => {
    const range = rangeFrom(event);
    if (range === undefined) return;
    state.range = range;
    follow(div);
  });
  div.on('plotly_relayout', (event) => {
    const range = rangeFrom(event);
    if (range === undefined) return;
    // Con un tramo elegido las gráficas quedan encerradas en él (como en la versión 1).
    const kept = keepInside(range);
    const moved = (kept === null) !== (range === null) || (kept && (kept[0] !== range[0] || kept[1] !== range[1]));
    state.range = kept;
    if (moved) {
      for (const other of plots1()) Plotly.relayout(other, { xaxis: timeAxis() });
      highlightRoute();
    } else follow(div);
    // Ajuste inmediato del eje Y con lo ya descargado; los datos con más detalle llegan al detenerse.
    for (const other of plots1()) if (other._series) Plotly.relayout(other, { yaxis: yAxis(yRange(other._series.x, linesOf(other._series), state.range)) });
    clearTimeout(zoomTimer);
    zoomTimer = setTimeout(refresh, 150);
  });
  div.on('plotly_hover', (event) => cursor(toMs(event.points[0].x)));
  div.on('plotly_unhover', () => cursor(null));
  pinchZoom(div, ['x']);
}

// Tableta: pellizcar con dos dedos acerca o aleja (Plotly solo hace zoom con la rueda). Con un dedo sigue
// desplazando Plotly; el segundo dedo no le llega, así no lo toma como doble toque (que reinicia la vista).
// El rango nuevo pasa por Plotly.relayout, así que las demás gráficas siguen igual que con la rueda.
function pinchZoom(div, axes) {
  let start = null, last = null, frame = null;
  const fingers = (touches) => {
    const [a, b] = touches;
    return { x: (a.clientX + b.clientX) / 2, y: (a.clientY + b.clientY) / 2, d: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY) };
  };
  const pixel = (ax, letter, at) => {
    const box = div.getBoundingClientRect();
    return (letter === 'x' ? at.x - box.left : at.y - box.top) - ax._offset;
  };
  div.addEventListener('touchstart', (event) => {
    if (event.touches.length < 2 || !div._fullLayout) return;
    event.stopPropagation();
    const at = fingers(event.touches);
    start = { at, axes: axes.map((letter) => {
      const ax = div._fullLayout[letter + 'axis'];
      const [r0, r1] = ax.range.map(ax.r2l);
      return { letter, ax, center: ax.p2l(pixel(ax, letter, at)), perPixel: Math.abs(r1 - r0) / ax._length };
    }) };
  }, { capture: true, passive: false });
  div.addEventListener('touchmove', (event) => {
    if (!start) return;
    event.stopPropagation();
    event.preventDefault(); // sin esto el navegador agranda toda la página
    if (event.touches.length < 2) return;
    const at = fingers(event.touches), scale = start.at.d / Math.max(at.d, 1);
    last = {};
    for (const { letter, ax, center, perPixel } of start.axes) {
      const step = perPixel * scale, p = pixel(ax, letter, at);
      const ends = letter === 'x' ? [center - step * p, center + step * (ax._length - p)] : [center - step * (ax._length - p), center + step * p];
      last[letter + 'axis.range'] = ends.map(ax.l2r);
    }
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => Plotly.relayout(div, last));
  }, { capture: true, passive: false });
  div.addEventListener('touchend', (event) => {
    if (!start || event.touches.length >= 2) return;
    start = null;
    // Plotly termina aquí el arrastre del primer dedo y puede volver al rango de antes: se reaplica el pellizco.
    const range = last;
    last = null;
    if (range) requestAnimationFrame(() => Plotly.relayout(div, range));
  }, { capture: true });
}

// ---------- paso 5: Excel (como la versión 1) ----------
// Variables marcadas, versión en uso (original o calibrada), GPS elegido y todo el archivo o el tramo visible del paso 1.
// La vista previa muestra las mismas hojas que tendrá el libro: Resumen, Datos, Gráficas y Ruta.
state.excel = { range: null, sheet: 'Resumen', data: null };
const SHEETS = ['Resumen', 'Datos', 'Gráficas', 'Ruta'];
const excelRange = () => (state.excel.range === 'visible' && state.range ? state.range : state.excel.range !== 'all' && state.tramo ? state.tramo.w : null);

function excelQuery() {
  const query = new URLSearchParams({ id: state.id, zone: state.zone, vars: state.selected.join(','), gps: bothGps() ? 'ambos' : mapGps(),
    limits: JSON.stringify(limitsMap()) });
  const range = excelRange();
  if (range) { query.set('start', range[0]); query.set('end', range[1]); }
  if (state.excel.range !== 'all' && state.tramo) query.set('tag', state.tramo.tag);
  return query;
}

function enterExcel() {
  const usable = { all: true, tramo: Boolean(state.tramo), visible: Boolean(state.range) };
  if (!usable[state.excel.range]) state.excel.range = state.range ? 'visible' : state.tramo ? 'tramo' : 'all';
  for (const b of $('xrange').children) {
    b.classList.toggle('on', b.dataset.range === state.excel.range);
    b.disabled = !usable[b.dataset.range];
  }
  const range = excelRange();
  $('xnote').textContent = range ? `${wall(range[0]).slice(0, 19)} → ${wall(range[1]).slice(0, 19)} (${state.zone})`
    : 'Para exportar solo una parte, elige un tramo o acércate a ella en las gráficas del paso 1.';
  const gps = !state.info.gps && !state.info.drone ? 'sin GPS' : bothGps() ? 'sensor y dron (la hoja Ruta usa el del dron)' : mapGps() === 'dron' ? 'del dron' : 'del sensor';
  const version = state.info.cal_id ? ` · ${calMode === 'original' ? 'columnas originales' : 'columnas calibradas'}` : '';
  $('xwhat').innerHTML = '<b></b> <span class="muted"></span>';
  $('xwhat').querySelector('b').textContent = state.selected.length ? `${state.selected.length} variable${state.selected.length > 1 ? 's' : ''}: ${state.selected.join(', ')}` : 'Ninguna variable marcada';
  const limited = Object.keys(limitsMap());
  const bounds = limited.length ? ` · con los límites del paso 2 en ${limited.join(', ')}` : '';
  $('xwhat').querySelector('span').textContent = ` · GPS ${gps}${version}${bounds} · hora de ${state.zone}. Se cambian en los pasos 1 y 2 y en la barra de arriba.`;
  refreshExcel();
}

$('xrange').addEventListener('click', (event) => {
  const b = event.target.closest('button');
  if (!b || b.disabled || b.dataset.range === state.excel.range) return;
  state.excel.range = b.dataset.range;
  enterExcel();
});

let excelTicket = 0;
async function refreshExcel() {
  if (!state.id || state.step !== 5) return;
  const box = $('xlsheet');
  if (!state.selected.length) {
    state.excel.data = null;
    $('xltabs').replaceChildren();
    $('xfile').textContent = '';
    box.innerHTML = '<div class="empty-note">Marca una o más variables en el paso 1 para armar el Excel.</div>';
    return;
  }
  const ticket = ++excelTicket;
  let data;
  try {
    data = await api('/api/excel/preview?' + excelQuery());
  } catch (error) {
    box.replaceChildren(Object.assign(document.createElement('div'), { className: 'empty-note', textContent: error.message }));
    return;
  }
  if (ticket !== excelTicket) return;
  state.excel.data = data;
  $('xfile').textContent = `${data.filename} · ${fmt(data.rows)} filas`;
  renderExcelSheet();
}

const cell = (v) => (v === null ? '' : typeof v === 'number' ? v.toLocaleString('es', { maximumFractionDigits: 6 }) : v);
function tableOf(className, headers, rows) {
  const table = Object.assign(document.createElement('table'), { className });
  if (headers) table.createTHead().insertRow().append(...headers.map((h) => Object.assign(document.createElement('th'), { textContent: h })));
  const body = table.createTBody();
  for (const row of rows) {
    const tr = body.insertRow();
    if (row.more) { Object.assign(tr.insertCell(), { colSpan: headers.length, textContent: row.more }); tr.className = 'more'; continue; }
    for (const v of row) tr.insertCell().textContent = cell(v);
  }
  return table;
}

function renderExcelSheet() {
  const data = state.excel.data, box = $('xlsheet');
  const sheets = SHEETS.filter((s) => s !== 'Ruta' || data.route);
  if (!sheets.includes(state.excel.sheet)) state.excel.sheet = 'Resumen';
  $('xltabs').replaceChildren(...sheets.map((name) => {
    const b = Object.assign(document.createElement('button'), { textContent: name, className: name === state.excel.sheet ? 'on' : '' });
    b.addEventListener('click', () => { state.excel.sheet = name; renderExcelSheet(); });
    return b;
  }));
  for (const div of box.querySelectorAll('.js-plotly-plot')) Plotly.purge(div);
  box.replaceChildren();
  const sheet = state.excel.sheet;
  if (sheet === 'Resumen') {
    box.append(Object.assign(document.createElement('p'), { className: 'xltitle', textContent: data.title }),
      tableOf('xltable xlinfo', null, [['Desde', data.from], ['Hasta', data.to], ['Duración', data.duration], ['Zona horaria', data.zone], ['Muestras', data.rows]]),
      tableOf('xltable', ['Variable', 'Mínimo', 'Promedio', 'Máximo', 'Muestras válidas'],
        data.stats.map((s) => [s.name, ...[s.min, s.mean, s.max].map((v) => (v === null ? null : Number(v.toFixed(3)))), s.count])));
  } else if (sheet === 'Datos') {
    const hidden = data.rows - data.first.length - data.last.length;
    const rows = hidden > 0 ? [...data.first, { more: `⋯ ${fmt(hidden)} filas más en el Excel ⋯` }, ...data.last] : [...data.first, ...data.last];
    box.append(tableOf('xltable', data.headers, rows));
  } else if (sheet === 'Gráficas') {
    const grid = Object.assign(document.createElement('div'), { className: 'xlcharts' });
    box.append(grid);
    for (const [name, series] of Object.entries(data.charts)) {
      const div = Object.assign(document.createElement('div'), { className: 'xlchart' });
      grid.append(div);
      Plotly.newPlot(div, [{ type: 'scatter', mode: 'lines', x: series.x.map((ms) => (ms === null ? null : wall(ms))), y: series.y, line: { color: PALETTE[Math.max(data.headers.indexOf(name) - 2, 0) % PALETTE.length], width: 1.25 }, connectgaps: false, hovertemplate: '%{y:.4~g}<extra></extra>' }],
        { ...baseLayout(), margin: { l: 56, r: 12, t: 30, b: 36 }, title: { text: name, font: { size: 13 } }, xaxis: timeAxis(null), yaxis: yAxis(null) },
        { ...config, displayModeBar: false, scrollZoom: false, staticPlot: false });
    }
  } else {
    const div = Object.assign(document.createElement('div'), { className: 'xlroute' });
    box.append(div);
    const lat0 = data.route.lat.find((v) => v !== null) || 0;
    const axis = { showgrid: true, gridcolor: css('--line'), zeroline: false, tickformat: '.4f', automargin: true };
    Plotly.newPlot(div, [{ type: 'scatter', mode: 'lines+markers', x: data.route.lon, y: data.route.lat, line: { color: css('--accent'), width: 1.5 }, marker: { size: 3, color: css('--accent') }, hovertemplate: 'Lat %{y:.6f} · Lon %{x:.6f}<extra></extra>' }],
      { ...baseLayout(), hovermode: 'closest', margin: { l: 70, r: 12, t: 30, b: 40 }, title: { text: `${data.route.name} (sin fondo de mapa)`, font: { size: 13 } },
        xaxis: { ...axis, title: { text: 'Longitud', font: { size: 11 } } }, yaxis: { ...axis, title: { text: 'Latitud', font: { size: 11 } }, scaleanchor: 'x', scaleratio: 1 / Math.cos(lat0 * Math.PI / 180) } },
      { ...config, displayModeBar: false });
  }
}

// En la APK de Android (WebView) no se pueden bajar enlaces blob:. La app expone window.GasLabAndroid: saveUrl()
// descarga la URL del servidor local y la guarda en Descargas (avisa al terminar con gaslabSaved), y saveBase64()
// guarda bytes ya hechos (el PNG del mapa). Devuelve '' o el mensaje de error.
const android = window.GasLabAndroid || null;
const androidWaits = {};
window.gaslabSaved = (id, error, name) => {
  const wait = androidWaits[id];
  delete androidWaits[id];
  if (wait) error ? wait.fail(new Error(error)) : wait.ok(name);
};
const androidSaveUrl = (url, fallback) => new Promise((ok, fail) => {
  const id = `${Date.now()}-${Math.random()}`;
  androidWaits[id] = { ok, fail };
  android.saveUrl(id, new URL(url, location.href).href, fallback);
});

// Descarga con fetch + blob: si el servidor responde un error se muestra como aviso, en lugar de bajar un archivo
// con el error o dejar la página. El nombre lo da el servidor (Content-Disposition, con acentos).
async function saveFrom(button, url, what, fallback) {
  button.disabled = true;
  toast(`Preparando ${what}…`);
  try {
    if (android) return toast(`Guardado en Descargas: ${await androidSaveUrl(url, fallback)}`);
    const response = await fetch(url);
    if (!response.ok) throw new Error((await response.json()).error || response.statusText);
    const match = /filename\*=UTF-8''([^;]+)/.exec(response.headers.get('Content-Disposition') || '');
    const link = Object.assign(document.createElement('a'), { href: URL.createObjectURL(await response.blob()), download: match ? decodeURIComponent(match[1]) : fallback });
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 2000);
    toast(`Guardado en Descargas: ${link.download}`);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

$('excel').addEventListener('click', () => {
  if (!state.id) return;
  if (!state.selected.length) return toast('Marca al menos una variable para exportar (paso 1).', true);
  saveFrom($('excel'), '/api/excel?' + excelQuery(), 'el Excel', `${state.info.name}.xlsx`);
});

// ---------- Google Earth (.kmz): todo lo que tiene mapa, con el tramo, el GPS, la señal y la escala elegidos ----------
// En «Ambos» la ruta lleva los dos GPS y las muestras usan el del dron, igual que los mapas.
function kmzQuery(kind, base) {
  const query = base || withTramo(new URLSearchParams({ id: state.id, zone: state.zone }));
  query.set('kind', kind);
  query.set('gps', bothGps() ? 'ambos' : mapGps());
  if (state.tramo) query.set('tag', state.tramo.tag);
  return query;
}
$('routekmz').addEventListener('click', () => {
  if (!state.id) return;
  if (!state.route) return toast('Este archivo no tiene posiciones GPS válidas.', true);
  saveFrom($('routekmz'), '/api/kmz?' + kmzQuery('route'), 'la ruta para Google Earth', `${state.info.name}_ruta.kmz`);
});

$('reset').addEventListener('click', () => { state.range = null; highlightRoute(); refresh(); });

// ---------- cursor compartido ----------
let cursorFrame = null;
function cursor(ms) {
  cancelAnimationFrame(cursorFrame);
  cursorFrame = requestAnimationFrame(() => {
    const shapes = ms === null ? [] : [{ type: 'line', xref: 'x', yref: 'paper', x0: wall(ms), x1: wall(ms), y0: 0, y1: 1, line: { color: css('--muted'), width: 1, dash: 'dot' } }];
    for (const div of plots1()) {
      div._cursor = shapes;
      Plotly.relayout(div, { shapes });
    }
    markOnMap(ms);
  });
}

// ---------- mapa (solo la ruta, sin fondo) ----------
async function loadRoute() {
  const map = $('map');
  const url = (gps) => '/api/route?' + withTramo(new URLSearchParams({ id: state.id, zone: state.zone, gps }));
  let route, other;
  try {
    [route, other] = await Promise.all([api(url(mapGps())), bothGps() ? api(url('sensor')) : null]);
  } catch (error) {
    return toast(error.message, true);
  }
  state.route = route;
  state.routeOther = other; // en Ambos: la ruta del sensor, dibujada primero (debajo)
  if (!route) {
    $('routeinfo').textContent = '';
    return Plotly.react(map, [], { ...baseLayout(), xaxis: { visible: false }, yaxis: { visible: false }, annotations: [{ text: state.info.gps ? 'No hay coordenadas GPS válidas' : 'Este archivo no tiene columnas de latitud/longitud', showarrow: false, xref: 'paper', yref: 'paper', x: .5, y: .5, font: { color: css('--muted') } }] }, config);
  }
  // Índices con punto (sin los cortes) ordenados por tiempo, para encontrar el más cercano a una hora.
  route.points = route.t.map((t, i) => (t === null ? -1 : i)).filter((i) => i >= 0);
  const first = route.points[0], last = route.points[route.points.length - 1];
  const hoverOf = (r, label) => label + (r.alt ? '%{customdata[0]}<br>Lat %{y:.6f} · Lon %{x:.6f}<br>Altura %{customdata[1]:.1f} m<extra></extra>' : '%{customdata[0]}<br>Lat %{y:.6f} · Lon %{x:.6f}<extra></extra>');
  const dataOf = (r) => r.t.map((t, i) => [t === null ? '' : wall(t).slice(0, 19), r.alt ? r.alt[i] : null]);
  const both = Boolean(other);
  const traces = [
    ...(both ? [{ type: 'scatter', mode: 'lines', x: other.lon, y: other.lat, customdata: dataOf(other), line: { color: css('--muted'), width: 1.5, dash: 'dot' }, hovertemplate: hoverOf(other, 'GPS sensor<br>') }] : []),
    { type: 'scatter', mode: 'lines', x: route.lon, y: route.lat, customdata: dataOf(route), line: { color: css('--route'), width: 2 }, hovertemplate: hoverOf(route, both ? 'GPS dron<br>' : '') },
    { type: 'scatter', mode: 'lines', x: [], y: [], line: { color: css('--accent'), width: 3 }, hoverinfo: 'skip' },
    { type: 'scatter', mode: 'markers+text', x: [route.lon[first], route.lon[last]], y: [route.lat[first], route.lat[last]], text: ['Inicio', 'Fin'], textposition: 'top center', marker: { size: 9, color: ['#1a9850', '#d73027'], line: { color: '#fff', width: 1.5 } }, hoverinfo: 'skip' },
    { type: 'scatter', mode: 'markers', x: [], y: [], marker: { size: 13, color: 'rgba(0,0,0,0)', line: { color: css('--text'), width: 2.5 } }, hoverinfo: 'skip' },
  ];
  const axis = { showgrid: true, gridcolor: css('--line'), zeroline: false, tickformat: '.4f', automargin: true };
  const layout = {
    ...baseLayout(), hovermode: 'closest', margin: { l: 70, r: 12, t: 6, b: 36 },
    xaxis: { ...axis, title: { text: 'Longitud', font: { size: 11 } } },
    // Misma escala en metros en ambos ejes: un grado de longitud mide cos(latitud) veces un grado de latitud.
    yaxis: { ...axis, title: { text: 'Latitud', font: { size: 11 } }, scaleanchor: 'x', scaleratio: 1 / Math.cos(route.lat0 * Math.PI / 180) },
  };
  state.routeBase = both ? 1 : 0; // índice de la ruta principal; después van el tramo resaltado, Inicio/Fin y el cursor
  await Plotly.react(map, traces, layout, config);
  const gap = state.info.drone && state.info.drone.gap;
  $('routeinfo').textContent = `${fmt(route.points.length)} puntos GPS${mapGps() === 'dron' ? ' del dron' : ''}`
    + (both && gap ? ` · distancia sensor–dron: mediana ${meters(gap.median)}, promedio ${meters(gap.mean)}, máx ${meters(gap.max)}` : '');
  highlightRoute();
  if (!map._wired) {
    map._wired = 'map';
    map.on('plotly_hover', (event) => {
      const point = event.points[0], r = point.curveNumber === state.routeBase ? state.route : state.routeOther;
      const t = r && point.curveNumber <= state.routeBase && r.t[point.pointIndex];
      if (t !== null && t !== undefined && t !== false) cursor(t);
    });
    map.on('plotly_unhover', () => cursor(null));
    pinchZoom(map, ['x', 'y']);
  }
}

// Tramo con zoom resaltado en la ruta.
function highlightRoute() {
  const route = state.route;
  if (!route || !route.points) return;
  const inside = (t) => t !== null && (!state.range || (t >= state.range[0] && t <= state.range[1]));
  const lon = route.lon.map((v, i) => (inside(route.t[i]) ? v : null));
  const lat = route.lat.map((v, i) => (inside(route.t[i]) ? v : null));
  Plotly.restyle($('map'), { x: [lon], y: [lat] }, [state.routeBase + 1]);
}

function markOnMap(ms) {
  const route = state.route;
  if (!route || !route.points.length) return;
  if (ms === null) return Plotly.restyle($('map'), { x: [[]], y: [[]] }, [state.routeBase + 3]);
  // Búsqueda binaria del punto GPS más cercano a esa hora.
  const points = route.points;
  let lo = 0, hi = points.length - 1;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (route.t[points[mid]] < ms) lo = mid + 1; else hi = mid; }
  if (lo > 0 && Math.abs(route.t[points[lo - 1]] - ms) < Math.abs(route.t[points[lo]] - ms)) lo -= 1;
  const i = points[lo];
  Plotly.restyle($('map'), { x: [[route.lon[i]]], y: [[route.lat[i]]] }, [state.routeBase + 3]);
}

// ---------- pestañas (pasos del análisis) ----------
function showStep(step) {
  state.step = step;
  for (const tab of document.querySelectorAll('.tab')) tab.classList.toggle('on', Number(tab.dataset.step) === step);
  $('step1').hidden = step !== 1;
  $('step2').hidden = step !== 2;
  $('step3').hidden = step !== 3;
  $('step4').hidden = step !== 4;
  $('step5').hidden = step !== 5;
  if (step === 1) {
    // La selección pudo cambiar en el paso 2; las gráficas dibujadas con la pestaña oculta quedaron sin tamaño.
    renderVariables();
    for (const div of [...charts.values(), $('alt'), $('map')]) if (div._wired) Plotly.Plots.resize(div);
    refresh();
  } else if (step === 2) {
    renderLimits();
    refreshBig();
  } else if (step === 3) {
    enterHeat();
  } else if (step === 4) {
    enterTerrain();
  } else if (step === 5) {
    enterExcel();
  }
}

$('tabs').addEventListener('click', (event) => {
  const tab = event.target.closest('.tab');
  if (tab && !tab.disabled) showStep(Number(tab.dataset.step));
});

// ---------- paso 2: límites (saturación) ----------
// Texto del campo -> número; '' = sin límite; acepta coma decimal. NaN si no es un número.
const parseLimit = (text) => (text.trim() === '' ? null : Number(text.trim().replace(',', '.')));

const boundsOf = (name) => (state.bounds[name] ||= { min: '', max: '' });

function limitError(row) {
  const low = parseLimit(row.min), high = parseLimit(row.max);
  if (Number.isNaN(high)) return 'El máximo no es un número.';
  if (Number.isNaN(low)) return 'El mínimo no es un número.';
  if (low !== null && high !== null && low > high) return 'El mínimo es mayor que el máximo.';
  return '';
}

// Límites válidos para el servidor: { variable: [mínimo, máximo] }. Las filas con error no se aplican.
function limitsMap() {
  const map = {};
  for (const name of state.selected) {
    const row = boundsOf(name);
    if (limitError(row)) continue;
    const low = parseLimit(row.min), high = parseLimit(row.max);
    if (low !== null || high !== null) map[name] = [low, high];
  }
  return map;
}

function renderLimits() {
  const box = $('limitrows');
  box.replaceChildren();
  // Una fila por cada variable seleccionada (en el paso 1 o con + Agregar límite); los valores se recuerdan por variable.
  if (!state.selected.length) {
    box.innerHTML = '<div class="empty-note">No hay variables seleccionadas. Márcalas en el paso 1 o usa <b>+ Agregar límite</b>.</div>';
  }
  state.selected.forEach((current) => {
    const row = boundsOf(current);
    const line = document.createElement('div');
    line.className = 'limit-row';
    line.innerHTML = '<label>Dato: <select></select></label><span class="sep">|</span>'
      + '<label>Máximo: <input inputmode="decimal" placeholder="sin límite"></label><span class="sep">|</span>'
      + '<label>Mínimo: <input inputmode="decimal" placeholder="sin límite"></label>'
      + '<button class="remove" title="Quitar este límite">✕</button><span class="msg"></span>';
    const [select] = line.getElementsByTagName('select');
    const [maxInput, minInput] = line.getElementsByTagName('input');
    const used = new Set(state.selected.filter((name) => name !== current));
    for (const name of state.info.variables) {
      select.append(Object.assign(document.createElement('option'), { value: name, textContent: name, disabled: used.has(name) }));
    }
    select.value = current;
    maxInput.value = row.max;
    minInput.value = row.min;
    const check = () => {
      const error = limitError(row);
      line.querySelector('.msg').textContent = error;
      maxInput.classList.toggle('bad', /máximo/.test(error));
      minInput.classList.toggle('bad', /mínimo/.test(error));
    };
    check();
    select.addEventListener('change', () => {
      if (state.shown === current) state.shown = select.value;
      setSelected([...state.selected.filter((name) => name !== current), select.value]);
      renderLimits();
      refreshBig();
    });
    for (const [input, key] of [[maxInput, 'max'], [minInput, 'min']]) {
      input.addEventListener('input', () => { row[key] = input.value; check(); scheduleBig(); });
    }
    line.querySelector('.remove').addEventListener('click', () => {
      setSelected(state.selected.filter((name) => name !== current));
      renderLimits();
      refreshBig();
    });
    box.append(line);
  });
  renderPick();
}

$('addlimit').addEventListener('click', () => {
  const free = state.info.variables.find((name) => !state.selected.includes(name));
  if (!free) return toast('Todas las variables ya tienen una fila de límites.');
  setSelected([...state.selected, free]);
  state.shown = free;
  renderLimits();
  refreshBig();
});

// Botones para elegir qué variable se ve en la gráfica grande.
function renderPick() {
  const names = state.selected;
  if (!names.includes(state.shown)) state.shown = names[0] || null;
  $('pick').replaceChildren(...names.map((name) => {
    const button = Object.assign(document.createElement('button'), { className: 'button' + (name === state.shown ? ' on' : ''), textContent: name });
    button.addEventListener('click', () => { state.shown = name; state.range2 = null; renderPick(); refreshBig(); });
    return button;
  }));
}

let bigTimer = null;
const scheduleBig = () => { clearTimeout(bigTimer); bigTimer = setTimeout(refreshBig, 250); };

let bigPending = 0;
async function refreshBig() {
  const div = $('big'), name = state.shown;
  if (!state.id || state.step !== 2) return;
  if (!name) {
    Plotly.purge(div);
    $('biginfo').textContent = $('bigstats').textContent = '';
    return;
  }
  const limits = limitsMap();
  const query = withTramo(new URLSearchParams({ id: state.id, zone: state.zone, vars: name, limits: JSON.stringify(limits), original: $('compare').checked ? '1' : '0' }));
  if (compareId()) query.set('compare', compareId());
  fetchWindow(query, state.range2, Math.round((div.clientWidth || 1200) * (window.devicePixelRatio || 1)));
  const ticket = ++bigPending;
  let data;
  try {
    data = (await api('/api/series?' + query))[name];
  } catch (error) {
    return toast(error.message, true);
  }
  if (ticket !== bigPending || !data) return;
  const x = data.x.map((ms) => (ms === null ? null : wall(ms)));
  const traces = [];
  if (data.compare) traces.push({ type: 'scatter', mode: 'lines', x, y: data.compare, name: 'Sin calibrar', line: { color: css('--muted'), width: 1.2, dash: 'dot' }, hovertemplate: 'Sin calibrar: %{y:.4~g}<extra></extra>' });
  if (data.original) traces.push({ type: 'scatter', mode: 'lines', x, y: data.original, name: 'Original', line: { color: css('--route'), width: 1.4 }, hovertemplate: 'Original: %{y:.4~g}<extra></extra>' });
  traces.push({ type: 'scatter', mode: 'lines', x, y: data.y, name: data.limits ? 'Ajustada' : data.compare ? 'Calibrado' : name, line: { color: colorOf(name), width: 1.6 }, hovertemplate: (data.limits ? 'Ajustada: ' : '') + '%{y:.4~g}<extra></extra>' });
  // Líneas punteadas en los límites.
  const shapes = [], annotations = [];
  (data.limits || []).forEach((value, i) => {
    if (value === null) return;
    const label = i ? 'Máximo' : 'Mínimo';
    shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: value, y1: value, line: { color: css('--error'), width: 1, dash: 'dash' } });
    annotations.push({ xref: 'paper', x: 1, y: value, text: `${label} ${value.toLocaleString('es')}`, showarrow: false, xanchor: 'right', yanchor: i ? 'bottom' : 'top', font: { size: 11, color: css('--error') } });
  });
  const layout = { ...baseLayout(), margin: { l: 64, r: 12, t: 8, b: 34 }, showlegend: traces.length > 1, legend: { orientation: 'h', x: 0, y: 1.06 },
    xaxis: timeAxis(state.range2), yaxis: yAxis(yRange(data.x, linesOf(data, ...(data.original ? [data.original] : [])), state.range2)), shapes, annotations };
  div._series = data;
  await Plotly.react(div, traces, layout, config);
  $('biginfo').textContent = `${data.shown < data.total ? `${fmt(data.shown)} de ${fmt(data.total)}` : fmt(data.total)} puntos · hora del día (${state.zone})${diffText(data.diff)}`;
  $('bigstats').textContent = data.limits
    ? `Ajustadas: ${fmt(data.above)} al máximo y ${fmt(data.below)} al mínimo, de ${fmt(data.valid)} muestras (${((data.above + data.below) / Math.max(data.valid, 1) * 100).toLocaleString('es', { maximumFractionDigits: 1 })} %).`
    : 'Sin límites para esta variable: se muestra el dato original.';
  if (!div._wired) {
    div._wired = 'big';
    div.on('plotly_relayout', (event) => {
      const range = rangeFrom(event);
      if (range === undefined) return;
      state.range2 = range;
      const data = div._series;
      if (data) Plotly.relayout(div, { yaxis: yAxis(yRange(data.x, linesOf(data, ...(data.original ? [data.original] : [])), range)) });
      scheduleBig();
    });
    pinchZoom(div, ['x']);
  }
}

$('compare').addEventListener('change', refreshBig);

// Pantalla completa: la del navegador si existe (Esc la cierra solo); si no, la clase .full y Esc a mano.
$('full').addEventListener('click', () => {
  const card = $('bigcard');
  if (document.fullscreenElement) return document.exitFullscreen();
  if (card.classList.contains('full')) return setFallbackFull(false);
  if (card.requestFullscreen) card.requestFullscreen().catch(() => setFallbackFull(true));
  else setFallbackFull(true);
});
function setFallbackFull(on) {
  $('bigcard').classList.toggle('full', on);
  $('full').textContent = on ? 'Salir (Esc)' : 'Pantalla completa';
  Plotly.Plots.resize($('big'));
}
document.addEventListener('fullscreenchange', () => {
  $('full').textContent = document.fullscreenElement ? 'Salir (Esc)' : 'Pantalla completa';
  Plotly.Plots.resize($('big'));
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && $('bigcard').classList.contains('full')) setFallbackFull(false);
});

// Valor al pasar el mouse: a lo sumo una consulta por cuadro y ninguna mientras el mapa se mueve o gira (consultar
// miles de prismas en cada movimiento del mouse es lo que más trababa el 3D). Un toque (tableta) llega como 'click'.
function hoverValues(map, show, hide) {
  let frame = null, last = null;
  map.on('mousemove', (event) => {
    last = event;
    if (frame || map.isMoving()) return;
    frame = requestAnimationFrame(() => { frame = null; show(last); });
  });
  map.on('click', show);
  map.on('mouseout', () => { cancelAnimationFrame(frame); frame = null; hide(); });
  map.on('movestart', hide);
}

// Cambiar una altura que depende de cada prisma obliga a MapLibre a reprocesar todos (cientos de ms con miles). Al
// arrastrar un deslizador esos cambios se encolaban y la vista quedaba trabada. Con esto, mientras el mapa procesa
// un cambio los siguientes se juntan y solo se aplica el último cuando termina.
function latestOnly(map) {
  let busy = false, next = null;
  const run = (fn) => {
    if (busy) { next = fn; return; }
    busy = true;
    fn();
    let finished = false;
    const done = () => {
      if (finished) return;
      finished = true;
      busy = false;
      if (next) { const again = next; next = null; run(again); }
    };
    map.once('idle', done);
    setTimeout(done, 1500); // por si el mapa no queda quieto (teselas cargando)
  };
  return run;
}

// ---------- paso 3: mapa de calor (una sola señal) ----------
const SATELLITE = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
let hmap = null, hpopup = null;
const num = (v) => Number(v).toLocaleString('es', { maximumFractionDigits: Math.abs(v) >= 100 ? 1 : Math.abs(v) >= 1 ? 2 : 4 });

// Escala (divisiones) y apariencia de la nube; la imagen se pide solo para la zona visible del mapa.
const heatSpacing = () => $('hspacing').querySelector('.on')?.dataset.spacing || 'original';
// Al elegir una escala, el % mínimo vuelve a su valor inicial: 5 % en «Original» (igual que antes), 0 % en las demás.
const syncMinPct = () => { $('hmin').value = heatSpacing() === 'original' ? 5 : 0; };
syncMinPct();
function heatQuery(look = false) {
  const query = new URLSearchParams({ id: state.id, var: state.heat.name, limits: JSON.stringify(limitsMap()), bins: $('hbins').value || 20, minpct: $('hmin').value || 0, spacing: heatSpacing(), gps: mapGps(), zone: state.zone });
  withTramo(query);
  if (look) { query.set('size', $('hsize').value); query.set('opacity', $('hop').value / 100); query.set('cool', $('hcool').value); query.set('reach', $('hreach').value / $('hsize').value); } // alcance en veces el tamaño
  return query;
}

// Solo una señal a la vez (pasos 3 y 4, la misma), elegida entre las variables seleccionadas en los pasos 1 y 2.
function fillSignal(select) {
  const options = state.selected;
  if (!options.includes(state.heat.name)) {
    state.heat.name = options.includes(state.shown) ? state.shown : (state.info.defaults.find((v) => options.includes(v)) || options[0] || null);
  }
  select.replaceChildren(...options.map((name) => Object.assign(document.createElement('option'), { value: name, textContent: name })));
  select.value = state.heat.name || '';
  select.disabled = !options.length;
  return options;
}

function enterHeat() {
  const options = fillSignal($('hvar'));
  $('hnote').textContent = !options.length ? 'No hay variables seleccionadas: márcalas en el paso 1.'
    : !state.info.gps ? 'Este archivo no tiene GPS: no se puede hacer el mapa de calor.' : '';
  showOutputs();
  if (!hmap) createHeatMap();
  else hmap.resize();
  refreshHeat();
}

function showOutputs() {
  $('hsize').nextElementSibling.textContent = `${num($('hsize').value)} m`;
  $('hop').nextElementSibling.textContent = `${$('hop').value} %`;
  $('hcool').nextElementSibling.textContent = Number($('hcool').value) ? num($('hcool').value) : 'no';
  $('hreach').nextElementSibling.textContent = `${num($('hreach').value)} m (${num($('hreach').value / $('hsize').value)}×)`;
  $('hheight').nextElementSibling.textContent = `${$('hheight').value} m`;
  $('hwidth').nextElementSibling.textContent = `${num($('hwidth').value)} m`;
}

function createHeatMap() {
  hmap = new maplibregl.Map({
    container: 'hmap', preserveDrawingBuffer: true, maxZoom: 21, center: [0, 0], zoom: 1, attributionControl: { compact: true },
    style: {
      version: 8,
      sources: { sat: { type: 'raster', tiles: [SATELLITE], tileSize: 256, maxzoom: 19, attribution: 'Imagen © Esri, Maxar, Earthstar Geographics' } },
      layers: [{ id: 'fondo', type: 'background', paint: { 'background-color': '#1b2229' } }, { id: 'sat', type: 'raster', source: 'sat' }],
    },
  });
  hmap._ready = new Promise((done) => hmap.once('load', done));
  hmap.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
  hmap.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right');
  hmap.on('error', (event) => {
    if (event.sourceId === 'sat' && !hmap._offline) { hmap._offline = true; toast('No se pudo cargar la imagen satelital (¿sin internet?). El mapa de calor se ve igual, sin fondo.', true); }
  });
  hpopup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10 });
  // Al pasar el mouse, o al tocar la muestra en una tableta (un toque llega como 'click').
  const showValue = (event) => {
    const layer = state.heat.view === '2d' ? 'muestras' : 'barras';
    const feature = hmap.getLayer(layer) && hmap.queryRenderedFeatures(event.point, { layers: [layer] })[0];
    if (!feature) return hpopup.remove();
    const { v, k } = feature.properties, c = state.heat.data.classes[k];
    hpopup.setLngLat(event.lngLat).setHTML(`<b>${num(v)}</b> ${state.heat.name}<br><i style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${c.color}"></i> división ${num(c.lo)} – ${num(c.hi)}`).addTo(hmap);
  };
  hoverValues(hmap, showValue, () => hpopup.remove());
  hmap.on('moveend', () => { if (state.heat.view === '2d') scheduleCloud(); });
}

let heatTimer = null, heatTicket = 0, cloudTimer = null, cloudTicket = 0;
const scheduleHeat = () => { clearTimeout(heatTimer); heatTimer = setTimeout(refreshHeat, 250); };
const scheduleCloud = () => { clearTimeout(cloudTimer); cloudTimer = setTimeout(refreshCloud, 150); };

// Nube solo de lo que se ve, a la resolución de la pantalla: con nubes de 0,1–2 m sigue nítida al acercar.
async function refreshCloud() {
  const data = state.heat.data;
  if (!data || state.heat.view !== '2d' || state.step !== 3) return;
  const b = hmap.getBounds(), query = heatQuery(true);
  query.set('bbox', [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].join(','));
  query.set('zoom', hmap.getZoom());
  query.set('dpr', window.devicePixelRatio || 1);
  const ticket = ++cloudTicket;
  let image;
  try {
    image = await api('/api/heat/image?' + query);
  } catch (error) {
    return toast(error.message, true);
  }
  if (ticket !== cloudTicket) return;
  if (hmap.getSource('nube')) hmap.getSource('nube').updateImage({ url: image.image, coordinates: image.corners });
  else {
    hmap.addSource('nube', { type: 'image', url: image.image, coordinates: image.corners });
    hmap.addLayer({ id: 'nube', type: 'raster', source: 'nube', paint: { 'raster-fade-duration': 0, 'raster-resampling': 'linear' } }, hmap.getLayer('muestras') ? 'muestras' : undefined);
  }
}

async function refreshHeat() {
  if (!state.id || state.step !== 3 || !state.heat.name || !state.info.gps) return;
  const ticket = ++heatTicket;
  let data;
  try {
    data = await api('/api/heat?' + heatQuery());
  } catch (error) {
    return toast(error.message, true);
  }
  if (ticket !== heatTicket) return;
  state.heat.data = data;
  renderHeatTable(data);
  await hmap._ready;
  drawHeat(data);
}

// Rango de valores y tabla de divisiones (porcentaje de muestras en cada una); prefix 'h' = paso 3, 't' = paso 4.
function renderHeatTable(data, prefix = 'h') {
  const $p = (id) => $(prefix + id);
  const limits = data.limits ? ` · ajustado en Límites (${[data.limits[0] !== null ? `mín ${num(data.limits[0])}` : '', data.limits[1] !== null ? `máx ${num(data.limits[1])}` : ''].filter(Boolean).join(', ')})` : '';
  $p('range').innerHTML = `<span class="muted">Valores de <b></b></span><span class="big">${num(data.min)} – ${num(data.max)}</span><span class="muted">${fmt(data.samples)} muestras con GPS · ${data.classes.length} divisiones${limits}</span>`;
  $p('range').querySelector('b').textContent = data.name;
  const top = Math.max(...data.classes.map((c) => c.pct));
  $p('table').replaceChildren(...data.classes.slice().reverse().map((c) => {
    const row = document.createElement('tr');
    row.innerHTML = `<td><i style="background:${c.color}"></i></td><td>${num(c.lo)} – ${num(c.hi)}</td><td>${fmt(c.count)}</td>`
      + `<td class="pct"><span style="width:${(c.pct / top) * 100}%"></span><b>${c.pct.toLocaleString('es', { maximumFractionDigits: 1 })} %</b></td>`;
    return row;
  }));
  $p('legend').innerHTML = '<b></b>' + data.classes.slice().reverse().map((c) => `<div><i style="background:${c.color}"></i>${num(c.lo)} – ${num(c.hi)}</div>`).join('');
  $p('legend').querySelector('b').textContent = data.name;
}

function drawHeat(data) {
  // Muestras (invisibles en 2D): solo para leer el valor con el mouse.
  const points = { type: 'FeatureCollection', features: data.points.v.map((v, i) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [data.points.lon[i], data.points.lat[i]] }, properties: { v, k: classIndex(v, data.classes) } })) };
  if (hmap.getSource('muestras')) hmap.getSource('muestras').setData(points);
  else {
    hmap.addSource('muestras', { type: 'geojson', data: points });
    hmap.addLayer({ id: 'muestras', type: 'circle', source: 'muestras', paint: { 'circle-radius': 6, 'circle-opacity': 0 } });
  }
  drawBars();
  setHeatView(state.heat.view, false);
  const key = `${state.info.id}|${data.name}|${mapGps()}`; // mismo encuadre para original y calibrado
  if (state.heat.fitted !== key) {
    state.heat.fitted = key;
    const [west, south, east, north] = data.bounds;
    hmap.fitBounds([[west, south], [east, north]], { padding: 40, duration: 0 }); // dispara moveend -> nube
  } else refreshCloud();
}

function classIndex(v, classes) {
  let k = 0;
  while (k < classes.length - 1 && v >= classes[k].hi) k++;
  return k;
}

// 3D: una barra por muestra, altura proporcional al valor y color de su división.
// Las barras se arman solo en 3D (en 2D quedan pendientes) y solo cuando cambian los datos o el ancho. La altura
// es una expresión del mapa sobre r (0 a 1): mover «Altura máxima» no rearma nada.
let barsDirty = true;
const barHeight = () => ['+', 0.5, ['*', ['get', 'r'], Number($('hheight').value)]];
function drawBars() {
  const data = state.heat.data;
  if (!data || !hmap.getSource('muestras')) return;
  if (state.heat.view !== '3d') { barsDirty = true; return; }
  barsDirty = false;
  const half = Number($('hwidth').value) / 2, span = data.max - data.min || 1, p = data.points;
  const dy = half / 111320, features = new Array(p.v.length);
  for (let i = 0; i < p.v.length; i++) {
    const v = p.v[i], lon = p.lon[i], lat = p.lat[i], k = classIndex(v, data.classes);
    const dx = half / (111320 * Math.cos(lat * Math.PI / 180));
    features[i] = { type: 'Feature', properties: { v, k, c: data.classes[k].color, r: (v - data.min) / span },
      geometry: { type: 'Polygon', coordinates: [[[lon - dx, lat - dy], [lon + dx, lat - dy], [lon + dx, lat + dy], [lon - dx, lat + dy], [lon - dx, lat - dy]]] } };
  }
  const collection = { type: 'FeatureCollection', features };
  if (hmap.getSource('barras')) hmap.getSource('barras').setData(collection);
  else {
    hmap.addSource('barras', { type: 'geojson', data: collection });
    hmap.addLayer({ id: 'barras', type: 'fill-extrusion', source: 'barras',
      paint: { 'fill-extrusion-color': ['get', 'c'], 'fill-extrusion-height': barHeight(), 'fill-extrusion-opacity': 0.95 } });
  }
}
let barsTimer = null;
const scheduleBars = () => { clearTimeout(barsTimer); barsTimer = setTimeout(drawBars, 120); };

function setHeatView(view, animate = true) {
  state.heat.view = view;
  for (const button of $('hview').children) button.classList.toggle('on', button.dataset.view === view);
  for (const row of document.querySelectorAll('.cfg-row[data-view]')) row.hidden = row.dataset.view !== view;
  if (!hmap || !hmap.getLayer('muestras')) return;
  if (view === '3d' && barsDirty) drawBars();
  // La capa de muestras (invisible) solo sirve para leer valores en 2D; en 3D se apaga para no dibujarla.
  hmap.setLayoutProperty('muestras', 'visibility', view === '2d' ? 'visible' : 'none');
  if (hmap.getLayer('nube')) hmap.setLayoutProperty('nube', 'visibility', view === '2d' ? 'visible' : 'none');
  if (view === '2d' && animate) scheduleCloud();
  if (hmap.getLayer('barras')) hmap.setLayoutProperty('barras', 'visibility', view === '3d' ? 'visible' : 'none');
  const pitch = view === '3d' ? 60 : 0;
  if (hmap.getPitch() !== pitch && animate) hmap.easeTo({ pitch, bearing: view === '3d' ? hmap.getBearing() || -20 : 0, duration: 600 });
}

$('hvar').addEventListener('change', () => { state.heat.name = $('hvar').value; refreshHeat(); });
$('hview').addEventListener('click', (event) => { const b = event.target.closest('button'); if (b) setHeatView(b.dataset.view); });
for (const id of ['hbins', 'hmin']) $(id).addEventListener('input', scheduleHeat);
$('hspacing').addEventListener('click', (event) => {
  const b = event.target.closest('button');
  if (!b || b.classList.contains('on')) return;
  for (const x of $('hspacing').children) x.classList.toggle('on', x === b);
  syncMinPct();
  scheduleHeat();
});
for (const id of ['hsize', 'hop', 'hcool', 'hreach']) $(id).addEventListener('input', () => { showOutputs(); scheduleCloud(); });
let barsPaint = null;
$('hheight').addEventListener('input', () => {
  showOutputs();
  if (!hmap || !hmap.getLayer('barras')) return;
  (barsPaint ||= latestOnly(hmap))(() => hmap.setPaintProperty('barras', 'fill-extrusion-height', barHeight()));
});
$('hwidth').addEventListener('input', () => { showOutputs(); scheduleBars(); });

// Guardar: imagen de lo que se ve (con la leyenda) o carpeta para QGIS.
$('hpng').addEventListener('click', () => {
  const data = state.heat.data;
  if (!hmap || !data) return;
  hmap.once('render', () => {
    const map = hmap.getCanvas(), ratio = map.width / map.clientWidth;
    const canvas = Object.assign(document.createElement('canvas'), { width: map.width, height: map.height });
    const ctx = canvas.getContext('2d');
    ctx.drawImage(map, 0, 0);
    ctx.scale(ratio, ratio);
    const rows = data.classes.slice().reverse(), line = 18, pad = 10;
    ctx.font = '13px system-ui, sans-serif';
    const width = Math.max(ctx.measureText(data.name).width, ...rows.map((c) => ctx.measureText(`${num(c.lo)} – ${num(c.hi)}  ${c.pct.toFixed(1)} %`).width)) + 22 + pad * 2;
    const height = (rows.length + 1) * line + pad * 2, x = 12, y = map.clientHeight - height - 12;
    ctx.fillStyle = 'rgba(20,26,32,.85)';
    ctx.fillRect(x, y, width, height);
    ctx.fillStyle = '#fff';
    ctx.font = 'bold 13px system-ui, sans-serif';
    ctx.fillText(data.name, x + pad, y + pad + 12);
    ctx.font = '13px system-ui, sans-serif';
    rows.forEach((c, i) => {
      const ty = y + pad + (i + 1) * line;
      ctx.fillStyle = c.color;
      ctx.fillRect(x + pad, ty + 3, 14, 14);
      ctx.fillStyle = '#fff';
      ctx.fillText(`${num(c.lo)} – ${num(c.hi)}  ${c.pct.toFixed(1)} %`, x + pad + 22, ty + 15);
    });
    const name = `${state.info.name}_${data.name}_${state.heat.view}.png`;
    if (android) {
      const error = android.saveBase64(name, 'image/png', canvas.toDataURL('image/png').split(',')[1]);
      return error ? toast(error, true) : toast(`Guardado en Descargas: ${name}`);
    }
    canvas.toBlob((blob) => {
      if (!blob) return toast('No se pudo crear la imagen.', true);
      const link = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: name });
      link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 2000);
    }, 'image/png');
  });
  hmap.triggerRepaint();
});

// Lo que se ve: en 2D la nube, en 3D las barras (con su altura máxima y ancho); siempre con la leyenda y la ruta.
$('hkmz').addEventListener('click', () => {
  if (!state.heat.data) return;
  const bars = state.heat.view === '3d';
  const query = kmzQuery(bars ? 'bars' : 'heat', heatQuery(true));
  query.set('barh', $('hheight').value);
  query.set('barw', $('hwidth').value);
  saveFrom($('hkmz'), '/api/kmz?' + query, bars ? 'las barras 3D para Google Earth' : 'la nube para Google Earth',
    `${state.info.name}_${state.heat.name}${bars ? '_barras3d' : ''}.kmz`);
});

$('tkmz').addEventListener('click', () => {
  if (!state.terrain.data) return;
  const query = kmzQuery('terrain', heatQuery());
  query.set('mode', glued() ? 'ground' : 'measured');
  query.set('offset', terrainOffset());
  saveFrom($('tkmz'), '/api/kmz?' + query, 'los puntos 3D para Google Earth', `${state.info.name}_${state.heat.name}_3d.kmz`);
});

$('hzip').addEventListener('click', () => {
  if (!state.heat.data) return;
  Object.assign(document.createElement('a'), { href: '/api/heat.zip?' + heatQuery(true) }).click();
  toast('Preparando GeoTIFF + proyecto QGIS… se descargará como .zip (ábrelo y abre el .qgz).');
});

// Ventanita de ayuda (botones ⓘ).
const INFO = {
  bins: ['Divisiones iniciales', 'El rango entre el valor mínimo y el máximo registrados se parte en esta cantidad de divisiones: del mismo ancho en Lineal, cada vez más anchas en Exponencial. Es el punto de partida de la escala de colores: después se unen las que tengan pocas muestras. Más divisiones iniciales = la escala puede afinar más donde hay muchas muestras.'],
  spacing: ['Original, lineal o exponencial', 'Cómo se parte el rango en divisiones de color. Original (por defecto): la escala de siempre: divisiones del mismo ancho y las que tienen menos del % mínimo de las muestras se unen a su vecina; al elegirla, el % mínimo se pone en 5 %, como antes, y se puede cambiar. Lineal: todas del mismo ancho; al elegirla (o Exponencial), el % mínimo vuelve a 0 %. Exponencial: cada división es más ancha que la anterior por un factor fijo, finas cerca del mínimo y anchas hacia el máximo (la última es 1000 veces más ancha que la primera). Sirve cuando la mayoría de las muestras están cerca del fondo y unas pocas suben mucho: se distinguen mejor las variaciones pequeñas sin perder los picos. Con el % mínimo en 0 % las divisiones se quedan tal cual; con más, se unen las que tengan pocas muestras.'],
  minpct: ['% mínimo por división', 'Cada división debe tener al menos este porcentaje de las muestras para ser relevante. Si tiene menos, se une a su vecina (la que tenga menos muestras), hasta que todas lleguen al mínimo. Así quedan más divisiones, más colores, donde se concentran las muestras y menos donde hay pocas. Con 0 % (el valor por defecto) no se une ninguna: en Lineal todas las divisiones quedan del mismo ancho. La tabla de la derecha muestra el % que quedó en cada división.'],
  cool: ['Enfriamiento', 'Decide el tamaño de la zona de calor. Cada muestra tiene su color real en el centro y se va "enfriando" hacia los lados: su valor baja hacia el mínimo de la escala (azul) según la distancia en metros. Con 1, a 10 m queda a un 60 % de su valor sobre el mínimo y a 25 m casi en el mínimo; más alto = zona de calor más chica (con 4, el 60 % queda a 5 m); más bajo = más grande; 0 = el mismo color hasta el borde. No depende del Alcance. Va de 0 a 10.'],
  reach: ['Alcance', 'Hasta dónde se extiende la nube de cada muestra, en metros (entre paréntesis, en veces el Tamaño). Solo cambia cuánto se extiende: los colores y la opacidad del centro no cambian. La mitad interior es opaca y la exterior se desvanece hasta el borde. Más allá no se pinta nada. Por defecto 30 m; como máximo 50 m.'],
  offset: ['Desfase de altura', 'Metros que se suman a la altura de cada muestra (negativo = se restan). Sirve para corregir un GPS o barómetro que mide con un error fijo, o para separar los puntos del relieve. Con «Pegada al terreno», los puntos van sobre el relieve y el desfase es su altura sobre él. Escribe cualquier valor en el número; la barra lo ajusta ±5 m y al soltarla se recentra en el nuevo valor.'],
};
function closeInfo() {
  $('infopop').hidden = true;
  for (const button of document.querySelectorAll('.info.on')) button.classList.remove('on');
}
document.addEventListener('click', (event) => {
  const button = event.target.closest('.info');
  if (!button) {
    if (!event.target.closest('#infopop') || event.target.closest('.close')) closeInfo();
    return;
  }
  const open = button.classList.contains('on');
  closeInfo();
  if (open) return;
  const [title, text] = INFO[button.dataset.info], pop = $('infopop'), box = button.getBoundingClientRect();
  pop.querySelector('b').textContent = title;
  pop.querySelector('p').textContent = text;
  pop.hidden = false;
  button.classList.add('on');
  const left = Math.min(box.left + window.scrollX, window.scrollX + document.documentElement.clientWidth - pop.offsetWidth - 16);
  pop.style.left = `${Math.max(16, left)}px`;
  pop.style.top = `${box.bottom + window.scrollY + 8}px`;
});
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeInfo(); });

// ---------- paso 4: terreno 3D (relieve real + cada muestra a su altura medida) ----------
const TERRAIN = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png';
let tmap = null, tpopup = null;

function enterTerrain() {
  fillSignal($('tvar'));
  if (!tmap) createTerrainMap();
  else tmap.resize();
  refreshTerrain();
}

function createTerrainMap() {
  tmap = new maplibregl.Map({
    // Con relieve, el costo de cada cuadro crece con los píxeles: en pantallas con escala de Windows de 150-200 % se
    // dibujaba 2-4 veces más de lo necesario (medido: 432 ms por cuadro a 2×, 243 ms a 1×). La imagen satelital ya es
    // borrosa de cerca, así que se dibuja a 1×.
    container: 'tmap', maxZoom: 20, maxPitch: 85, center: [0, 0], zoom: 1, attributionControl: { compact: true }, pixelRatio: Math.min(window.devicePixelRatio || 1, 1),
    style: {
      version: 8,
      sources: {
        sat: { type: 'raster', tiles: [SATELLITE], tileSize: 256, maxzoom: 19, attribution: 'Imagen © Esri, Maxar, Earthstar Geographics' },
        // Zoom 13 como en terreno.py: algunas teselas del 14 vienen vacías.
        dem: { type: 'raster-dem', tiles: [TERRAIN], tileSize: 256, maxzoom: 13, encoding: 'terrarium', attribution: 'Relieve: AWS Terrain Tiles' },
      },
      layers: [{ id: 'fondo', type: 'background', paint: { 'background-color': '#1b2229' } }, { id: 'sat', type: 'raster', source: 'sat' }],
      terrain: { source: 'dem', exaggeration: 1 },
    },
  });
  tmap._ready = new Promise((done) => tmap.once('load', done));
  tmap.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
  tmap.on('error', (event) => {
    if ((event.sourceId === 'sat' || event.sourceId === 'dem') && !tmap._offline) { tmap._offline = true; toast('No se pudo cargar la imagen satelital o el relieve (¿sin internet?).', true); }
  });
  tpopup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10 });
  const showValue = (event) => { // al pasar el mouse o al tocar (tableta)
    const feature = tmap.getLayer('puntos3d') && tmap.queryRenderedFeatures(event.point, { layers: ['puntos3d'] })[0];
    if (!feature) return tpopup.remove();
    const p = feature.properties, c = state.terrain.data.classes[p.k], off = terrainOffset();
    const ground = p.ground !== undefined && p.ground !== null ? `<br>Terreno: ${num(p.ground)} m` : '';
    const height = glued() ? `Pegada al terreno${off > 0 ? `, ${num(off)} m sobre él` : ''}${ground}`
      : `Altura${off ? ' (con desfase)' : ' medida'}: ${num(p.alt + off)} m${ground}<br>Sobre el terreno: <b>${num(Math.max(p.alt + off - p.ground, 0))} m</b>`;
    tpopup.setLngLat(event.lngLat).setHTML(`<b>${num(p.v)}</b> ${state.terrain.data.name} <i style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${c.color}"></i><br>${height}`).addTo(tmap);
  };
  hoverValues(tmap, showValue, () => tpopup.remove());
  // Los cubos se ven de un tamaño parecido en pantalla con cualquier zoom: se rearman solo si el zoom cambió medio
  // nivel o más desde la última vez (antes, con cada zoom).
  tmap.on('zoomend', () => { if (Math.abs(tmap.getZoom() - (state.terrain.zoom ?? -99)) >= 0.5) drawPoints3d(); });
}

let terrainTicket = 0;
async function refreshTerrain() {
  const note = $('tnote');
  note.hidden = true;
  if (!state.id || state.step !== 4 || !state.heat.name) {
    note.hidden = false;
    note.textContent = 'No hay variables seleccionadas: márcalas en el paso 1.';
    return;
  }
  const ticket = ++terrainTicket;
  let data;
  try {
    data = await api('/api/terrain?' + heatQuery());
  } catch (error) {
    note.hidden = false;
    note.className = 'tnote warn';
    note.textContent = error.message;
    return;
  }
  if (ticket !== terrainTicket) return;
  state.terrain.data = data;
  renderHeatTable(data, 't');
  showTerrainMode();
  await tmap._ready;
  drawPoints3d();
  const key = `${state.info.id}|${data.name}|${mapGps()}`;
  if (state.terrain.fitted !== key) {
    state.terrain.fitted = key;
    const [west, south, east, north] = data.bounds;
    // Encuadre calculado en plano y luego inclinado: fitBounds con inclinación y relieve deja la cámara en NaN.
    // Se repite cuando el relieve termina de cargar, porque MapLibre reajusta la cámara a la altura del terreno.
    const camera = tmap.cameraForBounds([[west, south], [east, north]], { padding: 60 });
    const frame = () => camera && tmap.jumpTo({ center: camera.center, zoom: camera.zoom - 0.3, pitch: 60, bearing: -20 });
    frame();
    tmap.once('idle', frame);
  }
}

// Altura: Medida (la del archivo más el desfase) o Pegada al terreno (el desfase sobre el relieve). Sin columna de
// altura solo se puede pegar al terreno. Todo se calcula en la página: cambiarlo no vuelve a pedir datos.
state.terrain.mode = 'measured';
const terrainOffset = () => Number(String($('toffset').value).replace(',', '.')) || 0;
const glued = () => state.terrain.mode === 'ground' || !(state.terrain.data && state.terrain.data.altitude);

function showTerrainMode() {
  const data = state.terrain.data;
  if (!data) return;
  for (const b of $('tmode').children) {
    b.classList.toggle('on', b.dataset.mode === (glued() ? 'ground' : 'measured'));
    b.disabled = b.dataset.mode === 'measured' && !data.altitude;
  }
  const off = terrainOffset(), p = data.points, note = $('tnote'), notes = [];
  let under = 0, deepest = 0, noAlt = 0;
  if (glued()) {
    notes.push(!data.altitude ? 'Este archivo no tiene columna de altura: las muestras van pegadas al terreno.' : 'Muestras pegadas al terreno.');
    if (off > 0) notes.push(`Dibujadas ${num(off)} m sobre el relieve.`);
    if (off < 0) notes.push('Pegadas al terreno no pueden ir debajo de él: el desfase negativo no se usa.');
  } else {
    notes.push(`Altura de cada muestra: columna «${data.altitude}» (sobre el nivel del mar)${off ? `, ${off > 0 ? 'más' : 'menos'} ${num(Math.abs(off))} m de desfase` : ''}.`);
    p.v.forEach((v, i) => {
      if (p.alt[i] === null) { noAlt++; return; }
      const above = p.alt[i] + off - p.ground[i];
      if (p.ground[i] !== null && above < 0) { under++; deepest = Math.max(deepest, -above); }
    });
    if (under) notes.push(`${fmt(under)} muestras quedaron hasta ${num(deepest)} m bajo el relieve (precisión del GPS y del relieve, ~30 m); se dibujan sobre el suelo. Un desfase positivo las sube.`);
    if (noAlt) notes.push(`${fmt(noAlt)} muestras sin altura no se dibujan.`);
  }
  note.hidden = false;
  note.className = 'tnote' + (under ? ' warn' : '');
  note.textContent = notes.join(' ');
}

$('tmode').addEventListener('click', (event) => {
  const b = event.target.closest('button');
  if (!b || b.disabled) return;
  state.terrain.mode = b.dataset.mode;
  showTerrainMode();
  terrainPaint();
});
// Desfase: deslizador (−100 a 100 m) y campo para un valor exacto o fuera de ese rango; los dos van juntos.
// El número manda (sin límite); la barra es un ajuste fino de ±5 m alrededor del número y se recentra al soltarla.
const OFFSET_FINE = 5;
function centerOffsetBar() {
  const v = terrainOffset(), bar = $('toffsetr');
  bar.min = v - OFFSET_FINE; bar.max = v + OFFSET_FINE; bar.value = v;
}
$('toffset').addEventListener('input', () => { centerOffsetBar(); showTerrainMode(); terrainPaint(); });
$('toffsetr').addEventListener('input', () => { $('toffset').value = Math.round(Number($('toffsetr').value) * 10) / 10; showTerrainMode(); terrainPaint(); });
$('toffsetr').addEventListener('change', centerOffsetBar);

// Cubos a la altura medida o pegados al relieve (fill-extrusion: base y altura se cuentan desde el relieve).
// La geometría (posición y tamaño) se arma con los datos y al cambiar el zoom; la altura sale de una expresión del
// mapa con el desfase y el modo, así mover el desfase o cambiar de modo no rearma los miles de cubos.
let terrainLatest = null, terrainFilter = null;
function terrainPaint() {
  if (!tmap || !tmap.getLayer('puntos3d')) return;
  (terrainLatest ||= latestOnly(tmap))(() => {
    const off = terrainOffset(), side = state.terrain.side;
    const base = glued() ? Math.max(off, 0) : ['max', ['+', ['-', ['get', 'alt'], ['get', 'ground']], off], 0];
    if (terrainFilter !== glued()) { // el filtro también obliga a reprocesar: solo si cambió el modo
      terrainFilter = glued();
      tmap.setFilter('puntos3d', glued() ? null : ['all', ['has', 'alt'], ['has', 'ground']]); // sin altura no se dibuja
    }
    tmap.setPaintProperty('puntos3d', 'fill-extrusion-base', base);
    tmap.setPaintProperty('puntos3d', 'fill-extrusion-height', glued() ? base + side : ['+', base, side]);
  });
}

function drawPoints3d() {
  const data = state.terrain.data;
  if (!tmap || !data) return;
  const p = data.points, lat0 = (data.bounds[1] + data.bounds[3]) / 2;
  state.terrain.zoom = tmap.getZoom();
  const metersPerPixel = (40075016.7 * Math.cos(lat0 * Math.PI / 180)) / (512 * 2 ** state.terrain.zoom);
  const side = state.terrain.side = Math.max(metersPerPixel * 7, 0.3), half = side / 2, dy = half / 111320;
  const features = new Array(p.v.length);
  for (let i = 0; i < p.v.length; i++) {
    const v = p.v[i], lon = p.lon[i], lat = p.lat[i], k = classIndex(v, data.classes);
    const dx = half / (111320 * Math.cos(lat * Math.PI / 180)), props = { v, k, c: data.classes[k].color };
    if (p.alt[i] !== null) props.alt = p.alt[i];
    if (p.ground[i] !== null) props.ground = p.ground[i];
    features[i] = { type: 'Feature', properties: props,
      geometry: { type: 'Polygon', coordinates: [[[lon - dx, lat - dy], [lon + dx, lat - dy], [lon + dx, lat + dy], [lon - dx, lat + dy], [lon - dx, lat - dy]]] } };
  }
  const collection = { type: 'FeatureCollection', features };
  if (tmap.getSource('puntos3d')) tmap.getSource('puntos3d').setData(collection);
  else {
    tmap.addSource('puntos3d', { type: 'geojson', data: collection });
    tmap.addLayer({ id: 'puntos3d', type: 'fill-extrusion', source: 'puntos3d', paint: { 'fill-extrusion-color': ['get', 'c'], 'fill-extrusion-opacity': 1 } });
    terrainFilter = null;
  }
  terrainPaint();
}

$('tvar').addEventListener('change', () => { state.heat.name = $('tvar').value; refreshTerrain(); });

// ---------- tema: automático (el del sistema), claro u oscuro, como el Modo noche de la versión 1 ----------
// El <head> ya aplica el tema guardado antes de dibujar, para no ver un parpadeo del otro color.
const THEMES = { auto: ['◐', 'Tema automático (sigue al sistema)'], light: ['☀', 'Tema claro'], dark: ['☾', 'Tema oscuro'] };
let theme = 'auto';
try { theme = localStorage.getItem('gaslab.tema') || 'auto'; } catch (error) { /* sin almacenamiento */ }
if (!THEMES[theme]) theme = 'auto';
// Plotly guarda los colores al dibujar: hay que redibujar las gráficas con los colores nuevos.
function redrawAll() {
  if (!state.id) return;
  loadRoute();
  refresh();
  if (state.step === 2) refreshBig();
  if (state.step === 5 && state.excel.data) renderExcelSheet();
}
function applyTheme(redraw) {
  if (theme === 'auto') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  $('theme').textContent = THEMES[theme][0];
  $('theme').title = `${THEMES[theme][1]} · clic para cambiar`;
  if (redraw) redrawAll();
}
applyTheme(false);
$('theme').addEventListener('click', () => {
  theme = { auto: 'light', light: 'dark', dark: 'auto' }[theme];
  try { localStorage.setItem('gaslab.tema', theme); } catch (error) { /* no se recuerda, pero funciona */ }
  applyTheme(true);
  toast(THEMES[theme][1] + '.');
});
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (theme === 'auto') redrawAll(); });

// Avisa al servidor que la página sigue abierta; con --ventana (la app de Windows) GasLab se cierra al cerrarla.
const pageId = Math.random().toString(36).slice(2);
const ping = () => fetch(`/api/ping?page=${pageId}`).catch(() => {});
ping();
setInterval(ping, 30000);
addEventListener('pagehide', () => navigator.sendBeacon(`/api/bye?page=${pageId}`));
