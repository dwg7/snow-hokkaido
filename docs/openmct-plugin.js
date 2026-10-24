/*
 * openmct-plugin.js — snow-hokkaido instruments for Open MCT.
 *
 * Structure follows dwg7/cafebabe's Open MCT notes and tabularmaps/do:
 *   objects.addProvider + composition.addProvider + objectViews.addProvider only;
 *   no Telemetry API, no Plot, no Display Layout. Each view fetches static JSON itself.
 *
 * Tree:  root (snow.instrument, kind 'root')
 *          ├─ maplibre            MapLibre map: per-date raster PMTiles (last known / observed) under the basemap's line work
 *          ├─ tabular:snow_rate   tabularmaps cells coloured by a series
 *          ├─ tabular:cloud_rate
 *          ├─ tabular:visible_rate
 *          ├─ tabular:scan_rate
 *          ├─ tabular:snow_rate_last
 *          ├─ tabular:freshness
 *          └─ about               text page: the algorithm explanation (about-algorithm.html)
 *
 * Data (all under dataUrl): stage1.json, view/dates.json + view/{obs,state}-<date>.pmtiles,
 *   series/<key>.json ({label, unit, asOf, min, max, values:{code:number}, notes:{code:string}}),
 *   layout-v08.json, municipalities.json, sapporo-wards.json (tabularmaps/do).
 */
window.SnowHokkaidoPlugin = function SnowHokkaidoPlugin(options) {
  'use strict';
  const NS = 'snow';
  const dataUrl = (options && options.dataUrl) || './data/';
  // Where the per-date raster PMTiles and view/dates.json live. The published copy is on Source Cooperative; the local
  // copy under dataUrl is the fallback. Override with ?viewbase=<url ending in /> (e.g. ./data/view/ for local work).
  const viewBases = (() => {
    const q = new URLSearchParams(location.search).get('viewbase');
    return [q || (options && options.viewUrl), dataUrl + 'view/'].filter(Boolean);
  })();
  // Basemap: bvmap-starlight (GSI optimized vector tiles), served by stars.optgeo.org (CORS allowed).
  const STYLE_URL = (options && options.styleUrl) || 'https://stars.optgeo.org/style/bvmap-starlight.json';
  const TABULAR = [
    { key: 'snow_rate', name: '積雪率 (tabular map)' },
    { key: 'cloud_rate', name: '雲の割合 (tabular map)' },
    { key: 'visible_rate', name: '見えた割合 (tabular map)' },
    { key: 'scan_rate', name: '走査できた割合 (tabular map)' },
    { key: 'snow_rate_last', name: '積雪率・最終既知 (tabular map)' },
    { key: 'freshness', name: '鮮度・7日以内に見えた割合 (tabular map)' }
  ];

  const fetchJson = (p) => fetch(dataUrl + p, { cache: 'no-store' }).then((r) => {
    if (!r.ok) throw new Error(p + ' ' + r.status);
    return r.json();
  });
  let layoutPromise = null;
  const loadLayout = () => layoutPromise || (layoutPromise = Promise.all([
    fetchJson('layout-v08.json'), fetchJson('municipalities.json'), fetchJson('sapporo-wards.json')
  ]).then(([layout, municipalities, wards]) => ({ layout, municipalities, wards })));

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }

  const ATTRIBUTION = 'Contains modified Copernicus Sentinel data 2026 / 「国土数値情報(行政区域データ)」(国土交通省)をもとに作成(国が作成したものではありません) / 背景地図: 国土地理院最適化ベクトルタイルをもとにしたスタイル(bvmap-starlight) / データ: CC BY 4.0';

  function rootView(host) {
    host.appendChild(el('h2', 'sh-h', 'snow-hokkaido'));
    host.appendChild(el('p', 'sh-p', '北海道の積雪を、雲で見えなかったことも含めて記録する台帳の計器盤。左のツリーから計器を選んでください。'));
    host.appendChild(el('p', 'sh-p sh-muted', ATTRIBUTION));
    host.appendChild(el('p', 'sh-p', '現在は2026-10-18の1パス(北海道の広い範囲を1回で撮影した1回分)の集計です。写真に写らなかった市町村は「無データ」です。地図の計器は、セルの色の上に、背景地図の線画(海岸・川・道路・行政界)と地名を重ねて表示します。'));
    fetchJson('stage1.json').then((m) => {
      host.appendChild(el('p', 'sh-p sh-muted', '観測: ' + m.asOf + ' / ' + m.scene + ' / ' + m.algo_version + ' (暫定の判定規則)'));
    }).catch(() => {});
  }

  function initialView() {
    const q = new URLSearchParams(location.search);
    const c = (q.get('center') || '').split(',').map(Number);
    const z = Number(q.get('zoom'));
    return c.length === 2 && c.every(Number.isFinite) && Number.isFinite(z) && q.get('zoom') ? { center: c, zoom: z } : null;
  }

  function ensurePmtiles() {
    if (!window.__pmtilesProtocol) {
      window.__pmtilesProtocol = new pmtiles.Protocol();
      maplibregl.addProtocol('pmtiles', window.__pmtilesProtocol.tile);
    }
  }

  // Try each base in turn (remote first, then the local copy); remember which one answered.
  function loadViewIndex() {
    const tryBase = (i) => fetch(new URL(viewBases[i] + 'dates.json', document.baseURI).href, { cache: 'no-store' })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((j) => Object.assign(j, { base: viewBases[i] }))
      .catch((err) => { if (i + 1 < viewBases.length) return tryBase(i + 1); throw err; });
    return tryBase(0);
  }

  const AGE_LABELS = ['〜1', '2–3', '4–7', '8–14', '15〜'];  // days since the cell was last seen clear (bucket edges: pixel.AGE_BUCKETS)

  function mapView(host, state) {
    ensurePmtiles();
    const wrap = el('div', 'sh-map');
    host.appendChild(wrap);
    Promise.all([fetchJson('stage1.json'), loadViewIndex()]).then(([meta, view]) => {
      if (state.disposed) return;
      const map = state.map = new maplibregl.Map({
        container: wrap,
        style: STYLE_URL,
        // ?center=lon,lat&zoom=z opens at that view (for links); otherwise fit all of Hokkaido
        ...(initialView() || { bounds: [[view.bbox[0], view.bbox[1]], [view.bbox[2], view.bbox[3]]], fitBoundsOptions: { padding: 20 } }),
        maxZoom: 17
      });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');

      // View state: which display layer (mode) and which date. "state" = last known state with age; "obs" = observed that day.
      const mode = { value: view.state.length ? 'state' : 'obs', index: 0 };
      const dates = () => view[mode.value];
      mode.index = dates().length - 1;
      let rasterBefore;

      // The raster goes under the basemap's water fill and every line layer (coast, rivers, boundaries, roads), so line
      // work and labels stay on top; the basemap already draws prefecture / subprefecture / municipality boundaries for
      // the whole region. 'nearest' keeps cell edges crisp; it rendered black for an image source in the embedded
      // browser (cause unconfirmed), so check other browsers too.
      function showLayer() {
        if (map.getLayer('obs')) map.removeLayer('obs');
        if (map.getSource('obs')) map.removeSource('obs');
        const file = view.templates[mode.value].replace('{date}', dates()[mode.index]);
        const url = new URL(view.base + file, document.baseURI).href;
        map.addSource('obs', { type: 'raster', url: 'pmtiles://' + url, tileSize: 256 });
        map.addLayer({ id: 'obs', type: 'raster', source: 'obs', paint: { 'raster-resampling': 'nearest' } }, rasterBefore);
        if (cb && !cb.checked) map.setLayoutProperty('obs', 'visibility', 'none');
        renderLegend();
      }

      map.on('style.load', () => {
        const layers = map.getStyle().layers;
        rasterBefore = (layers.find((l) => l.type === 'fill' && l['source-layer'] === 'WA') || layers.find((l) => l.type === 'line') || {}).id;
        // The basemap's topographic area fill (TpgphArea: wetland 7401, perennial snow 7402, gravel 7403) would show
        // light-gray "snow" patches that readers could take for our data. Drop perennial snow (7402) and draw the rest
        // below the cell raster, so the cells are never covered by it.
        const tp = layers.find((l) => l.type === 'fill' && l['source-layer'] === 'TpgphArea');
        if (tp) {
          map.setFilter(tp.id, ['all', map.getFilter(tp.id), ['!=', ['get', 'vt_code'], 7402]]);
          map.moveLayer(tp.id, rasterBefore);
        }
        showLayer();
      });

      const legend = el('div', 'sh-legend');
      const legendBody = el('div');
      const controls = el('div', 'sh-legend-n');
      const cb = document.createElement('input');
      cb.type = 'checkbox'; cb.checked = true;
      cb.addEventListener('change', () => { if (map.getLayer('obs')) map.setLayoutProperty('obs', 'visibility', cb.checked ? 'visible' : 'none'); });
      const picker = datePicker((i) => { mode.index = i; showLayer(); });

      function renderLegend() {
        legendBody.textContent = '';
        legendBody.appendChild(el('div', 'sh-legend-t', dates()[mode.index] + ' (JST)'));
        if (mode.value === 'obs') {
          for (const k of ['4', '3', '2', '1']) {
            const r = el('div', 'sh-legend-r');
            const sw = el('i'); sw.style.background = view.palette.obs[+k];
            r.appendChild(sw); r.appendChild(document.createTextNode(meta.classes[k]));
            legendBody.appendChild(r);
          }
          legendBody.appendChild(el('div', 'sh-legend-n', 'その日に撮れた場所だけ。透明 = 走査外'));
        } else {
          const r0 = el('div', 'sh-legend-r sh-legend-head');
          r0.appendChild(el('span', 'sh-legend-lab', '見えてから(日)'));
          for (const l of AGE_LABELS) r0.appendChild(el('span', 'sh-legend-cell', l));
          legendBody.appendChild(r0);
          for (const [name, off] of [['雪', 6], ['緑 (雪なし)', 1]]) {
            const r = el('div', 'sh-legend-r');
            r.appendChild(el('span', 'sh-legend-lab', name));
            for (let i = 0; i < 5; i++) { const sw = el('i', 'sh-legend-cell'); sw.style.background = view.palette.state[off + i]; r.appendChild(sw); }
            legendBody.appendChild(r);
          }
          legendBody.appendChild(el('div', 'sh-legend-n', '最後に晴れて見えた状態。色が薄いほど古い。透明 = まだ一度も見えていない'));
        }
        picker.set(dates(), mode.index);
      }

      const modes = el('div', 'sh-legend-n');
      for (const [val, label] of [['state', '最終既知'], ['obs', '観測値']]) {
        if (!view[val].length) continue;
        const lab = el('label', 'sh-mode'); const rb = document.createElement('input');
        rb.type = 'radio'; rb.name = 'sh-mode'; rb.checked = mode.value === val;
        rb.addEventListener('change', () => { mode.value = val; mode.index = dates().length - 1; showLayer(); });
        lab.appendChild(rb); lab.appendChild(document.createTextNode(' ' + label + ' '));
        modes.appendChild(lab);
      }
      controls.appendChild(modes);
      const sliderRow = el('div'); sliderRow.appendChild(picker.el);
      controls.appendChild(sliderRow);
      const tg = el('div'); const tgl = el('label');
      tgl.appendChild(cb); tgl.appendChild(document.createTextNode(' セルを表示'));
      tg.appendChild(tgl);
      controls.appendChild(tg);
      legend.appendChild(legendBody);
      legend.appendChild(controls);
      legend.appendChild(el('div', 'sh-legend-n sh-attr', 'Contains modified Copernicus Sentinel data 2026 / 国土数値情報(行政区域データ)(国土交通省)をもとに作成 / 国土地理院'));
      wrap.appendChild(legend);
      renderLegend();
    }).catch((err) => { host.appendChild(el('p', 'sh-p', '読み込みに失敗: ' + err.message)); });
  }

  // Text page: the algorithm explanation lives in docs/about-algorithm.html (a trusted same-origin fragment).
  function aboutView(host, state) {
    const box = el('div', 'sh-about');
    host.appendChild(box);
    fetch(new URL('about-algorithm.html', document.baseURI).href, { cache: 'no-store' }).then((r) => {
      if (!r.ok) throw new Error('about-algorithm.html ' + r.status);
      return r.text();
    }).then((html) => {
      if (state.disposed) return;
      box.innerHTML = html;
      box.appendChild(el('p', 'sh-p sh-muted', ATTRIBUTION));
    }).catch((err) => { box.appendChild(el('p', 'sh-p', '読み込みに失敗: ' + err.message)); });
  }

  const TS_KEYS = ['snow_rate', 'cloud_rate', 'visible_rate', 'scan_rate', 'snow_rate_last', 'freshness'];  // these have a per-day series (series/<key>_ts.json)
  const LAST_KNOWN = ['snow_rate_last', 'freshness'];  // calendar-day series (every day, ages advance); the others are observed days only

  // Date picker in the manner of the Copernicus Browser: previous / next *available* date, a calendar in which only
  // dates with data can be chosen, and a jump to the latest. `dates` are ascending 'YYYY-MM-DD' strings.
  const WEEK = ['日', '月', '火', '水', '木', '金', '土'];
  const pad = (n) => String(n).padStart(2, '0');
  function datePicker(onPick) {
    const root = el('div', 'sh-dp'); root.tabIndex = 0;
    const mkBtn = (text, title, cls) => { const b = el('button', 'sh-dp-b ' + (cls || ''), text); b.type = 'button'; b.title = title; return b; };
    const prev = mkBtn('◀', '前の観測日'), next = mkBtn('▶', '次の観測日');
    const label = mkBtn('', 'カレンダーを開く', 'sh-dp-date'), latest = mkBtn('最新', '最新の日へ');
    const pop = el('div', 'sh-dp-pop'); pop.hidden = true;
    let dates = [], idx = 0, ym = [2000, 1];
    const wd = (iso) => WEEK[new Date(iso + 'T00:00:00Z').getUTCDay()];
    function pick(i) { if (i < 0 || i >= dates.length || i === idx) return; idx = i; onPick(i); update(); }
    function renderPop() {
      pop.textContent = '';
      const first = dates[0].slice(0, 7), last = dates[dates.length - 1].slice(0, 7);
      const cur = ym[0] + '-' + pad(ym[1]);
      const head = el('div', 'sh-dp-head');
      const mp = mkBtn('◀', '前の月'), mn = mkBtn('▶', '次の月');
      mp.disabled = cur <= first; mn.disabled = cur >= last;
      const shift = (d) => { const t = new Date(Date.UTC(ym[0], ym[1] - 1 + d, 1)); ym = [t.getUTCFullYear(), t.getUTCMonth() + 1]; renderPop(); };
      mp.addEventListener('click', () => shift(-1)); mn.addEventListener('click', () => shift(1));
      head.appendChild(mp); head.appendChild(el('span', 'sh-dp-month', ym[0] + '年' + ym[1] + '月')); head.appendChild(mn);
      pop.appendChild(head);
      const grid = el('div', 'sh-dp-grid');
      for (const w of WEEK) grid.appendChild(el('span', 'sh-dp-wd', w));
      const dow = new Date(Date.UTC(ym[0], ym[1] - 1, 1)).getUTCDay();
      for (let i = 0; i < dow; i++) grid.appendChild(el('span'));
      const days = new Date(Date.UTC(ym[0], ym[1], 0)).getUTCDate();
      const at = new Map(dates.map((d, i) => [d, i]));
      for (let d = 1; d <= days; d++) {
        const iso = ym[0] + '-' + pad(ym[1]) + '-' + pad(d);
        const c = mkBtn(String(d), at.has(iso) ? iso + ' を表示' : 'この日のデータはありません', 'sh-dp-day');
        if (!at.has(iso)) c.disabled = true;
        else {
          if (at.get(iso) === idx) c.classList.add('sh-dp-sel');
          c.addEventListener('click', () => { pick(at.get(iso)); pop.hidden = true; });
        }
        grid.appendChild(c);
      }
      pop.appendChild(grid);
      pop.appendChild(el('div', 'sh-dp-n', '色のついた日だけ選べます (データのある日)'));
    }
    function update() {
      label.textContent = dates.length ? dates[idx] + ' (' + wd(dates[idx]) + ')' : '日付なし';
      prev.disabled = idx <= 0; next.disabled = idx >= dates.length - 1; latest.disabled = idx >= dates.length - 1;
      if (!pop.hidden) { ym = dates[idx].slice(0, 7).split('-').map(Number); renderPop(); }
    }
    label.addEventListener('click', () => {
      pop.hidden = !pop.hidden;
      if (!pop.hidden) { ym = dates[idx].slice(0, 7).split('-').map(Number); renderPop(); }
    });
    prev.addEventListener('click', () => pick(idx - 1)); next.addEventListener('click', () => pick(idx + 1));
    latest.addEventListener('click', () => pick(dates.length - 1));
    root.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowLeft') { pick(idx - 1); e.preventDefault(); }
      else if (e.key === 'ArrowRight') { pick(idx + 1); e.preventDefault(); }
      else if (e.key === 'Escape') pop.hidden = true;
    });
    document.addEventListener('mousedown', (e) => { if (!pop.hidden && root.isConnected && !root.contains(e.target)) pop.hidden = true; });
    const bar = el('div', 'sh-dp-bar');
    for (const n of [prev, label, next, latest]) bar.appendChild(n);
    root.appendChild(bar); root.appendChild(pop);
    return {
      el: root, get index() { return idx; },
      set(newDates, newIdx) { dates = newDates; idx = Math.min(Math.max(newIdx, 0), Math.max(dates.length - 1, 0)); update(); }
    };
  }

  function tabularView(host, state, key, name) {
    const hasTs = TS_KEYS.includes(key);
    Promise.all([loadLayout(), fetchJson('series/' + key + '.json'), hasTs ? fetchJson('series/' + key + '_ts.json') : Promise.resolve(null)]).then(([data, latest, ts]) => {
      if (state.disposed) return;
      state.map = window.TabularMap.create(host, {
        layout: data.layout, municipalities: data.municipalities, wards: data.wards,
        mode: 'region', title: name, includeNorthernTerritoriesVillages: true
      });
      let noteText = '';
      if (ts) {
        // one value per observed day: a slider steps through the days; municipalities not scanned that day show no data
        const seriesAt = (i) => {
          const values = {};
          for (const [code, arr] of Object.entries(ts.values)) if (arr[i] != null) values[code] = arr[i];
          return { label: ts.label, unit: ts.unit, min: ts.min, max: ts.max, values, asOf: ts.dates[i] + (LAST_KNOWN.includes(key) ? ' 時点' : ' (日本時間の1日分)') };
        };
        let idx = ts.dates.length - 1;
        state.map.setSeries(seriesAt(idx));
        const row = el('div', 'sh-ts-row');
        const picker = datePicker((i) => { idx = i; state.map.setSeries(seriesAt(idx)); });
        picker.set(ts.dates, idx);
        row.appendChild(picker.el);
        host.appendChild(row);
        noteText = LAST_KNOWN.includes(key)
          ? ATTRIBUTION + '。日付は、◀ ▶ かカレンダーで選べます。その日までに最後に晴れて見えた状態で数えた値で、観測のない日も、古さだけが進みます。一度も見えていない場所は数に入りません。'
          : ATTRIBUTION + '。日付は、◀ ▶ かカレンダーで選べます (その日に撮れた観測だけの値。同じ日に複数回撮れた場所は、最後に晴れて見えた観測を使います)。写らなかった市町村は無データです。「見えた割合」と「走査できた割合」は、市町村全体に対する割合なので、一部しか写らなかった日は小さくなります。積雪率と雲の割合は、写った範囲だけの割合です。';
      } else {
        state.map.setSeries(latest);
        noteText = ATTRIBUTION + '。最新の日の値です (日付は上の見出し)。最終既知の計算は、雲で見えなかった場所に、最後に見えた状態を使います。';
      }
      host.appendChild(el('div', 'sh-tabular-note', noteText));
    }).catch((err) => { host.appendChild(el('p', 'sh-p', '読み込みに失敗: ' + err.message)); });
  }

  return function install(openmct) {
    openmct.types.addType('snow.instrument', {
      name: 'snow-hokkaido instrument',
      description: 'snow-hokkaido 計器',
      creatable: false
    });

    const objects = new Map();
    const add = (key, name, kind, extra) => {
      objects.set(key, Object.assign({ identifier: { namespace: NS, key }, name, type: 'snow.instrument', snow: Object.assign({ kind }, extra) },
        key === 'root' ? { location: 'ROOT' } : {}));
    };
    add('root', 'snow-hokkaido', 'root');
    add('maplibre', '地図 (MapLibre)', 'maplibre');
    add('about', 'アルゴリズムの説明', 'about');
    for (const t of TABULAR) add('tabular:' + t.key, t.name, 'tabular', { series: t.key });
    const children = [{ namespace: NS, key: 'maplibre' }, ...TABULAR.map((t) => ({ namespace: NS, key: 'tabular:' + t.key })), { namespace: NS, key: 'about' }];

    openmct.objects.addRoot({ namespace: NS, key: 'root' });
    openmct.objects.addProvider(NS, {
      get(identifier) {
        const o = objects.get(identifier.key);
        return o ? Promise.resolve(o) : Promise.reject(new Error('Unknown object ' + identifier.key));
      }
    });
    openmct.composition.addProvider({
      appliesTo: (d) => d.identifier.namespace === NS && d.identifier.key === 'root',
      load: () => Promise.resolve(children)
    });
    openmct.objectViews.addProvider({
      key: 'snow.view',
      name: 'snow-hokkaido',
      canView: (d) => d.identifier.namespace === NS && d.type === 'snow.instrument',
      view(domainObject) {
        const state = { disposed: false, map: null };
        let host = null;
        return {
          show(element) {
            host = el('div', 'sh-host');
            element.appendChild(host);
            const kind = domainObject.snow.kind;
            if (kind === 'root') rootView(host);
            else if (kind === 'maplibre') mapView(host, state);
            else if (kind === 'about') aboutView(host, state);
            else tabularView(host, state, domainObject.snow.series, domainObject.name);
          },
          destroy() {
            state.disposed = true;
            if (state.map) {
              // MapLibre: remove() frees the WebGL context; TabularMap: destroy()
              if (typeof state.map.remove === 'function') state.map.remove();
              else if (typeof state.map.destroy === 'function') state.map.destroy();
            }
            if (host && host.parentNode) host.parentNode.removeChild(host);
          }
        };
      }
    });
  };
};
