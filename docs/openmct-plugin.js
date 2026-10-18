/*
 * openmct-plugin.js — snow-hokkaido instruments for Open MCT.
 *
 * Structure follows dwg7/cafebabe's Open MCT notes and tabularmaps/do:
 *   objects.addProvider + composition.addProvider + objectViews.addProvider only;
 *   no Telemetry API, no Plot, no Display Layout. Each view fetches static JSON itself.
 *
 * Tree:  root (snow.instrument, kind 'root')
 *          ├─ maplibre            MapLibre map: obs classes (image overlay) + municipality outlines
 *          ├─ tabular:snow_rate   tabularmaps cells coloured by a series
 *          ├─ tabular:cloud_rate
 *          └─ tabular:visible_rate
 *
 * Data (all under dataUrl): stage1.json, obs-class.png, muni-stage1.geojson,
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
    { key: 'visible_rate', name: '見えた割合 (tabular map)' }
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

  function rootView(host) {
    host.appendChild(el('h2', 'sh-h', 'snow-hokkaido'));
    host.appendChild(el('p', 'sh-p', '北海道の積雪を、雲で見えなかったことも含めて記録する台帳の計器盤。左のツリーから計器を選んでください。'));
    host.appendChild(el('p', 'sh-p', '現在は段階1 (XYZタイル 9/459/186、大雪山系を含む約56 km四方) の1シーンのみ。ほかの市町村は「無データ」です。'));
    fetchJson('stage1.json').then((m) => {
      host.appendChild(el('p', 'sh-p sh-muted', '観測: ' + m.asOf + ' / ' + m.scene + ' / ' + m.algo_version + ' (暫定の判定規則)'));
    }).catch(() => {});
  }

  function mapView(host, state) {
    const wrap = el('div', 'sh-map');
    host.appendChild(wrap);
    Promise.all([fetchJson('stage1.json'), fetchJson('muni-stage1.geojson'), fetchJson('series/snow_rate.json')]).then(([meta, muni, snow]) => {
      if (state.disposed) return;
      const map = state.map = new maplibregl.Map({
        container: wrap,
        style: STYLE_URL,
        bounds: [[meta.bbox[0], meta.bbox[1]], [meta.bbox[2], meta.bbox[3]]],
        fitBoundsOptions: { padding: 20 },
        maxZoom: 17
      });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
      map.on('style.load', () => {
        // Put overlays under the basemap's labels so place names stay readable.
        const firstSymbol = (map.getStyle().layers.find((l) => l.type === 'symbol') || {}).id;
        // 'raster-resampling': 'nearest' rendered the layer black in the embedded browser (cause unconfirmed;
        // other browsers not checked), so the overlay uses 'linear'.
        map.addSource('obs', { type: 'image', url: dataUrl + 'obs-class.png', coordinates: meta.coordinates });
        map.addLayer({ id: 'obs', type: 'raster', source: 'obs', paint: { 'raster-resampling': 'linear' } }, firstSymbol);
        map.addSource('muni', { type: 'geojson', data: muni });
        map.addLayer({ id: 'muni-fill', type: 'fill', source: 'muni', paint: { 'fill-color': '#000000', 'fill-opacity': 0 } }, firstSymbol);
        map.addLayer({ id: 'muni-line', type: 'line', source: 'muni', paint: { 'line-color': '#444444', 'line-width': 1.2, 'line-dasharray': [3, 2] } }, firstSymbol);
        map.on('click', 'muni-fill', (e) => {
          const p = e.features[0].properties;
          const v = snow.values[p.code];
          const html = '<b>' + p.name + '</b> (' + p.code + ')<br>' + (v == null ? '積雪率: 無データ' : '積雪率: ' + v + '%<br>' + (snow.notes[p.code] || ''));
          new maplibregl.Popup({ closeButton: true }).setLngLat(e.lngLat).setHTML(html).addTo(map);
        });
        map.on('mouseenter', 'muni-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', 'muni-fill', () => { map.getCanvas().style.cursor = ''; });
      });
      const legend = el('div', 'sh-legend');
      legend.appendChild(el('div', 'sh-legend-t', meta.asOf));
      for (const k of ['4', '3', '2', '1']) {
        const row = el('div', 'sh-legend-r');
        const sw = el('i'); sw.style.background = meta.colors[k];
        row.appendChild(sw); row.appendChild(document.createTextNode(meta.classes[k]));
        legend.appendChild(row);
      }
      legend.appendChild(el('div', 'sh-legend-n', '112 m セル / 透明 = 走査外'));
      const tg = el('label', 'sh-legend-n'); const cb = document.createElement('input');
      cb.type = 'checkbox'; cb.checked = true;
      cb.addEventListener('change', () => { if (state.map && state.map.getLayer('obs')) state.map.setLayoutProperty('obs', 'visibility', cb.checked ? 'visible' : 'none'); });
      tg.appendChild(cb); tg.appendChild(document.createTextNode(' セルを表示'));
      legend.appendChild(tg);
      wrap.appendChild(legend);
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
      const note = el('div', 'sh-tabular-note', '値があるのは段階1の範囲に入る市町村だけです (それ以外は無データ)。範囲が一部だけの市町村は、範囲内のセルだけの値です。');
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
