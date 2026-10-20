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
 *          └─ tabular:freshness
 *
 * Data (all under dataUrl): stage1.json, view/dates.json + view/{obs,state}-<date>.pmtiles,
 *   series/<key>.json ({label, unit, asOf, min, max, values:{code:number}, notes:{code:string}}),
 *   layout-v08.json, municipalities.json, sapporo-wards.json (tabularmaps/do).
 */
window.SnowHokkaidoPlugin = function SnowHokkaidoPlugin(options) {
  'use strict';
  const NS = 'snow';
  const dataUrl = (options && options.dataUrl) || './data/';
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

  function ensurePmtiles() {
    if (!window.__pmtilesProtocol) {
      window.__pmtilesProtocol = new pmtiles.Protocol();
      maplibregl.addProtocol('pmtiles', window.__pmtilesProtocol.tile);
    }
  }

  const AGE_LABELS = ['〜1', '2–3', '4–7', '8–14', '15〜'];  // days since the cell was last seen clear (bucket edges: pixel.AGE_BUCKETS)

  function mapView(host, state) {
    ensurePmtiles();
    const wrap = el('div', 'sh-map');
    host.appendChild(wrap);
    Promise.all([fetchJson('stage1.json'), fetchJson('view/dates.json')]).then(([meta, view]) => {
      if (state.disposed) return;
      const map = state.map = new maplibregl.Map({
        container: wrap,
        style: STYLE_URL,
        bounds: [[view.bbox[0], view.bbox[1]], [view.bbox[2], view.bbox[3]]],
        fitBoundsOptions: { padding: 20 },
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
        const url = new URL(dataUrl + 'view/' + file, document.baseURI).href;
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
      const slider = document.createElement('input');
      slider.type = 'range'; slider.className = 'sh-slider';
      slider.addEventListener('input', () => { mode.index = +slider.value; showLayer(); });

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
        slider.min = 0; slider.max = dates().length - 1; slider.value = mode.index;
        slider.disabled = dates().length < 2;
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
      const sliderRow = el('div'); sliderRow.appendChild(slider);
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

  function tabularView(host, state, key, name) {
    Promise.all([loadLayout(), fetchJson('series/' + key + '.json')]).then(([data, series]) => {
      if (state.disposed) return;
      state.map = window.TabularMap.create(host, {
        layout: data.layout, municipalities: data.municipalities, wards: data.wards,
        mode: 'region', title: name, includeNorthernTerritoriesVillages: true
      });
      state.map.setSeries(series);
      const note = el('div', 'sh-tabular-note', ATTRIBUTION + '。値があるのは、この1回の撮影に写った市町村です (写らなかった市町村は無データ)。一部しか写らなかった市町村は、「見えた割合」と「走査できた割合」が市町村全体に対する割合なので小さくなります。積雪率と雲の割合は、写った範囲だけの割合です。');
      host.appendChild(note);
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
    for (const t of TABULAR) add('tabular:' + t.key, t.name, 'tabular', { series: t.key });
    const children = [{ namespace: NS, key: 'maplibre' }, ...TABULAR.map((t) => ({ namespace: NS, key: 'tabular:' + t.key }))];

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
