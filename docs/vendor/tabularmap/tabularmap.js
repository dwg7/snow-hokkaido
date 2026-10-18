/*
 * tabularmap.js — 北海道 tabular map の描画コア (依存なし、SVG)。
 *
 *   const map = TabularMap.create(container, { layout, municipalities, wards });
 *   map.setSeries({ label: '人口密度', unit: '人/km²', values: { '01100': 1800, ... } });
 *   // 任意: min/max (値域)、asOf (基準時刻の文字列)、notes: {code: 文字列} (ツールチップと表に出す説明)、
 *   //       scale: {type: 'ordinal', labels: {'0': '発表なし', '2': '注意報', ...}} (順序尺度: 凡例を段階の色見本にする)
 *   //       scale.colors: {'0': '#rrggbb', ...} (任意。段階ごとの塗り色を外から決める。組み込み先の配色に揃える時に使う。
 *   //                     指定の無い段階は既定のランプ。文字のインクを明度から選ぶので #rrggbb 形式で渡す)
 *   map.setMode('value' | 'region');   // データ値の色 / 振興局の色 (無データ時の既定)
 *   map.setExpandSapporo(true | false); // 札幌4×4を10区に展開
 *   map.setIncludeNorthernTerritoriesVillages(true | false); // 北方領土の6村を含める (既定 true。false で179市町村だけ)
 *   map.destroy();
 *
 * 北方領土の6村 (status: 'northern_territories') は、地図としては政府の慣行 (地理院地図・全国市町村要覧の地図・
 * 国土数値情報) に合わせて既定で描く。市町村数の集計 (北海道庁「道内179市町村」・総務省の市町村数) に合わせたい時は
 * false にする。含めない時、その6セルは構造余白と同じ見た目にする (東端の列だけなので凹みは生じない)。
 *
 * 描画方針 (dataviz の規約に従う):
 *   - 値の色は単一色相 (青) の light→dark 逐次ランプ。振興局色は「無データ」の識別用にのみ使う。
 *   - 文字は常にインクの色 (系列色を文字に使わない)。濃いセルでは白インクに切り替える。
 *   - すべてのセルに名前ラベル + ホバーのツールチップ。表ビューを併設して色だけに頼らない。
 *   - セル間は 2 単位の面ギャップ。構造余白はヘアライン枠のみ。
 */
window.TabularMap = (function () {
  'use strict';

  const U = 40;      // 1セルの単位長
  const GAP = 2;     // セル間の面ギャップ
  const SEQ = ['#cde2fb', '#b7d3f6', '#9ec5f4', '#86b6ef', '#6da7ec', '#5598e7', '#3987e5',
               '#2a78d6', '#256abf', '#1c5cab', '#184f95', '#104281', '#0d366b'];
  const REGION = {
    '宗谷': '#b9dcf0', '留萌': '#b0d3ea', '上川': '#bfe3c9', 'オホーツク': '#b5e2df', '空知': '#f1e0a8',
    '石狩': '#f3c5a6', '後志': '#dfcbe8', '胆振': '#f0c1b7', '日高': '#f3ccd0', '十勝': '#d6e6ad',
    '釧路': '#b8d8d6', '根室': '#b0cfcd', '渡島': '#e9c9b1', '檜山': '#dcc2b3'
  };

  function hexToRgb(h) {
    return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
  }
  function rgbToHex(r) {
    return '#' + r.map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('');
  }
  function luminance(hex) {
    const [r, g, b] = hexToRgb(hex).map((v) => {
      v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }
  function ramp(t) {
    t = Math.max(0, Math.min(1, t));
    const p = t * (SEQ.length - 1), i = Math.floor(p), f = p - i;
    if (i >= SEQ.length - 1) return SEQ[SEQ.length - 1];
    const a = hexToRgb(SEQ[i]), b = hexToRgb(SEQ[i + 1]);
    return rgbToHex(a.map((v, k) => v + (b[k] - v) * f));
  }
  function inkFor(fill) {
    return luminance(fill) < 0.3 ? '#ffffff' : '#0b0b0b';
  }
  function ordinalColor(s, v) {
    const c = s && s.scale && s.scale.type === 'ordinal' && s.scale.colors ? s.scale.colors[String(v)] : null;
    return typeof c === 'string' && /^#[0-9a-fA-F]{6}$/.test(c) ? c : null;
  }
  function fmtValue(s, v) {
    if (v == null || Number.isNaN(v)) return '—';
    if (s && s.scale && s.scale.type === 'ordinal' && s.scale.labels && s.scale.labels[String(v)] !== undefined) return s.scale.labels[String(v)];
    return fmt(v, s ? s.unit : '');
  }
  function fmt(v, unit) {
    if (v == null || Number.isNaN(v)) return '—';
    const s = Math.abs(v) >= 100 ? Math.round(v).toLocaleString('ja-JP')
      : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2);
    return unit ? `${s} ${unit}` : s;
  }
  function el(tag, attrs, parent) {
    const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }

  function create(container, opts) {
    const layout = opts.layout;
    const munis = opts.municipalities ? opts.municipalities.municipalities : [];
    const byCode = new Map(munis.map((m) => [m.code, m]));
    const wards = opts.wards || null;
    const N = layout.grid[0];
    const state = { mode: opts.mode || 'region', series: null, expandSapporo: !!opts.expandSapporo, showTable: false,
                    includeNTV: opts.includeNorthernTerritoriesVillages !== false };
    const isNTV = (p) => p.status === 'northern_territories';
    const hasNTV = layout.placements.some(isNTV);

    const root = document.createElement('div');
    root.className = 'tm-root';
    container.appendChild(root);

    // ヘッダー: タイトル・凡例・トグル
    const head = document.createElement('div');
    head.className = 'tm-head';
    root.appendChild(head);
    const titleEl = document.createElement('div');
    titleEl.className = 'tm-title';
    head.appendChild(titleEl);
    const legend = document.createElement('div');
    legend.className = 'tm-legend';
    head.appendChild(legend);
    const controls = document.createElement('div');
    controls.className = 'tm-controls';
    head.appendChild(controls);
    const btnMode = document.createElement('button');
    btnMode.type = 'button'; btnMode.className = 'tm-btn';
    controls.appendChild(btnMode);
    const btnWards = document.createElement('button');
    btnWards.type = 'button'; btnWards.className = 'tm-btn';
    btnWards.hidden = !wards;
    controls.appendChild(btnWards);
    const btnNTV = document.createElement('button');
    btnNTV.type = 'button'; btnNTV.className = 'tm-btn';
    btnNTV.hidden = !hasNTV;
    controls.appendChild(btnNTV);
    const btnTable = document.createElement('button');
    btnTable.type = 'button'; btnTable.className = 'tm-btn';
    controls.appendChild(btnTable);

    const stage = document.createElement('div');
    stage.className = 'tm-stage';
    root.appendChild(stage);
    const svg = el('svg', { viewBox: `0 0 ${N * U} ${N * U}`, class: 'tm-svg', role: 'img' }, stage);
    el('title', {}, svg).textContent = '北海道 tabular map';
    const tip = document.createElement('div');
    tip.className = 'tm-tip'; tip.hidden = true;
    stage.appendChild(tip);
    const tableWrap = document.createElement('div');
    tableWrap.className = 'tm-table'; tableWrap.hidden = true;
    root.appendChild(tableWrap);

    // セルの生成
    const cells = [];   // {code, name, bureau, x, y, w, h, rect, text, isWard}
    function addCell(p, parentOffset, isWard) {
      const ox = parentOffset ? parentOffset.x : 0, oy = parentOffset ? parentOffset.y : 0;
      const g = el('g', { class: 'tm-cell' + (isWard ? ' tm-ward' : '') + (p.w * p.h > 1 ? ' tm-block' : ''),
                          'data-code': p.code }, svg);
      const x = (ox + p.x) * U + GAP / 2, y = (oy + p.y) * U + GAP / 2;
      const w = p.w * U - GAP, h = p.h * U - GAP;
      const rect = el('rect', { x, y, width: w, height: h, rx: p.w * p.h > 1 ? 4 : 3 }, g);
      const name = isWard ? p.short : p.name;
      const size = p.w * p.h >= 16 ? 14 : p.w * p.h >= 4 ? 11 : name.length >= 4 ? 7.4 : name.length === 3 ? 9 : 10;
      const text = el('text', { x: x + w / 2, y: y + h / 2, 'text-anchor': 'middle', 'dominant-baseline': 'central',
                                'font-size': size }, g);
      text.textContent = name;
      const c = { code: p.code, name: isWard ? p.name : (byCode.get(p.code) || {}).fullName || p.name,
                  bureau: p.bureau, x, y, w, h, g, rect, text, isWard: !!isWard, block: p.w * p.h > 1,
                  ntv: !isWard && isNTV(p) };
      if (c.ntv) g.classList.add('tm-ntv');
      cells.push(c);
      g.addEventListener('mousemove', (ev) => showTip(c, ev));
      g.addEventListener('mouseleave', hideTip);
      g.addEventListener('click', () => { if (c.ntv && !state.includeNTV) return; if (opts.onSelect) opts.onSelect(c.code, c); });
      return c;
    }
    for (const s of layout.structural_spaces) {
      el('rect', { x: s[0] * U + GAP / 2, y: s[1] * U + GAP / 2, width: U - GAP, height: U - GAP, rx: 3,
                   class: 'tm-space' }, svg);
    }
    let sapporo = null;
    for (const p of layout.placements) {
      const c = addCell(p, null, false);
      if (p.code === '01100') sapporo = { placement: p, cell: c };
    }
    const wardCells = [];
    if (wards && sapporo) {
      for (const w of wards.wards) {
        const c = addCell({ ...w, bureau: '石狩' }, { x: sapporo.placement.x, y: sapporo.placement.y }, true);
        wardCells.push(c);
      }
    }

    function valueOf(code) {
      const s = state.series;
      if (!s || !s.values) return undefined;
      const v = s.values[code];
      return typeof v === 'number' && !Number.isNaN(v) ? v : undefined;
    }
    function range() {
      const s = state.series;
      if (!s) return [0, 1];
      // 表示中の市町村の値だけで範囲を決める (含めていない6村の値は凡例に影響させない)
      const shown = new Set(layout.placements.filter((p) => state.includeNTV || !isNTV(p)).map((p) => p.code));
      let vals = Object.entries(s.values || {}).filter(([k, v]) => shown.has(k) && typeof v === 'number' && !Number.isNaN(v)).map(([, v]) => v);
      const lo = s.min != null ? s.min : (vals.length ? Math.min(...vals) : 0);
      const hi = s.max != null ? s.max : (vals.length ? Math.max(...vals) : 1);
      return [lo, hi > lo ? hi : lo + 1];
    }

    function paint() {
      const [lo, hi] = range();
      const valueMode = state.mode === 'value' && state.series;
      for (const c of cells) {
        let visible = c.isWard ? state.expandSapporo : !(state.expandSapporo && c.code === '01100');
        if (c.ntv && !state.includeNTV) {
          // 含めない時は構造余白と同じ見た目 (枠線のみ)
          c.g.style.display = '';
          c.g.classList.add('tm-ntv-off');
          c.rect.setAttribute('fill', 'none');
          c.text.textContent = '';
          continue;
        }
        if (c.ntv) { c.g.classList.remove('tm-ntv-off'); c.text.textContent = c.name; }
        c.g.style.display = visible ? '' : 'none';
        let fill;
        if (valueMode) {
          const v = valueOf(c.code);
          fill = v === undefined ? 'var(--tm-nodata)' : (ordinalColor(state.series, v) || ramp((v - lo) / (hi - lo)));
        } else {
          fill = REGION[c.bureau] || 'var(--tm-nodata)';
        }
        c.rect.setAttribute('fill', fill);
        c.text.setAttribute('fill', fill.startsWith('#') ? inkFor(fill) : 'var(--tm-ink)');
      }
      // 凡例
      legend.innerHTML = '';
      const ordinal = valueMode && state.series.scale && state.series.scale.type === 'ordinal' && state.series.scale.labels;
      if (ordinal) {
        // 順序尺度: 段階ごとの色見本 (scale.colors があればその色、無ければ min〜max の位置で同じランプから採る)
        for (const k of Object.keys(ordinal).map(Number).sort((a, b) => a - b)) {
          const sw = document.createElement('span');
          sw.className = 'tm-legend-sw';
          sw.innerHTML = `<i style="background:${ordinalColor(state.series, k) || ramp((k - lo) / (hi - lo))}"></i>${ordinal[k]}`;
          legend.appendChild(sw);
        }
        const nd = document.createElement('span');
        nd.className = 'tm-legend-nodata'; nd.textContent = '無データ';
        legend.appendChild(nd);
      } else if (valueMode) {
        const bar = document.createElement('div');
        bar.className = 'tm-legend-bar';
        bar.style.background = `linear-gradient(90deg, ${SEQ.join(',')})`;
        const lo_ = document.createElement('span'); lo_.textContent = fmt(lo, state.series.unit);
        const hi_ = document.createElement('span'); hi_.textContent = fmt(hi, state.series.unit);
        legend.append(lo_, bar, hi_);
        const nd = document.createElement('span');
        nd.className = 'tm-legend-nodata'; nd.textContent = '無データ';
        legend.appendChild(nd);
      } else {
        for (const b in REGION) {
          const sw = document.createElement('span');
          sw.className = 'tm-legend-sw';
          sw.innerHTML = `<i style="background:${REGION[b]}"></i>${b}`;
          legend.appendChild(sw);
        }
      }
      titleEl.textContent = valueMode
        ? `${state.series.label || ''}${state.series.asOf ? '　' + state.series.asOf : ''}`
        : (opts.title || '北海道');   // 「179市町村 + 6村」のような並列表現は北方領土が北海道の外にあるように読めるので使わない
      btnMode.textContent = state.mode === 'value' ? '振興局の色で見る' : 'データ値の色で見る';
      btnMode.disabled = !state.series;
      btnWards.textContent = state.expandSapporo ? '札幌を1市に畳む' : '札幌を10区に展開';
      btnNTV.textContent = state.includeNTV ? '北方領土の6村を含めない' : '北方領土の6村を含める';
      btnNTV.title = '根室振興局管内の6村 (市町村としての行政の実態がない)。含めない時は北海道庁・総務省の市町村数と同じ179市町村の範囲になる。';
      btnTable.textContent = state.showTable ? '表を隠す' : '表で見る';
      tableWrap.hidden = !state.showTable;
      if (state.showTable) renderTable();
    }

    function renderTable() {
      const s = state.series;
      const rows = layout.placements.filter((p) => state.includeNTV || !isNTV(p))
        .map((p) => ({ code: p.code, name: (byCode.get(p.code) || {}).fullName || p.name,
                       bureau: p.bureau + (isNTV(p) ? ' (北方領土)' : ''), v: valueOf(p.code) }));
      if (s) rows.sort((a, b) => (b.v ?? -Infinity) - (a.v ?? -Infinity));
      const t = document.createElement('table');
      const hasNotes = !!(s && s.notes);
      t.innerHTML = `<thead><tr><th>コード</th><th>市町村</th><th>振興局</th><th>${s ? (s.label || '値') + (s.unit ? ` (${s.unit})` : '') : ''}</th>${hasNotes ? '<th>内容</th>' : ''}</tr></thead>`;
      const tb = document.createElement('tbody');
      for (const r of rows) {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${r.code}</td><td>${r.name}</td><td>${r.bureau}</td><td class="tm-num">${s ? fmtValue(s, r.v) : ''}</td>`
          + (hasNotes ? `<td>${s.notes[r.code] || ''}</td>` : '');
        tb.appendChild(tr);
      }
      t.appendChild(tb);
      tableWrap.innerHTML = '';
      tableWrap.appendChild(t);
    }

    function showTip(c, ev) {
      if (c.ntv && !state.includeNTV) { hideTip(); return; }
      const v = valueOf(c.code);
      const s = state.series;
      tip.innerHTML = `<b>${c.name}</b><span class="tm-tip-sub">${c.isWard ? '札幌市' : c.bureau} · ${c.code}</span>`
        + (c.ntv ? '<span class="tm-tip-sub">北方領土の村。市町村としての行政の実態がない</span>' : '')
        + (s ? `<span class="tm-tip-val">${s.label || ''} ${fmtValue(s, v)}</span>` : '')
        + (s && s.notes && s.notes[c.code] ? `<span class="tm-tip-sub">${s.notes[c.code]}</span>` : '');
      tip.hidden = false;
      const r = stage.getBoundingClientRect();
      let x = ev.clientX - r.left + 12, y = ev.clientY - r.top + 12;
      if (x + tip.offsetWidth > r.width) x = ev.clientX - r.left - tip.offsetWidth - 12;
      if (y + tip.offsetHeight > r.height) y = ev.clientY - r.top - tip.offsetHeight - 12;
      tip.style.left = x + 'px'; tip.style.top = y + 'px';
      for (const o of cells) o.g.classList.toggle('tm-hover', o === c);
    }
    function hideTip() {
      tip.hidden = true;
      for (const o of cells) o.g.classList.remove('tm-hover');
    }

    btnMode.addEventListener('click', () => { state.mode = state.mode === 'value' ? 'region' : 'value'; paint(); });
    btnWards.addEventListener('click', () => { state.expandSapporo = !state.expandSapporo; paint(); });
    btnNTV.addEventListener('click', () => { state.includeNTV = !state.includeNTV; paint(); });
    btnTable.addEventListener('click', () => { state.showTable = !state.showTable; paint(); });

    paint();
    return {
      setSeries(series) { state.series = series || null; if (series) state.mode = 'value'; paint(); },
      setMode(mode) { state.mode = mode; paint(); },
      setExpandSapporo(v) { state.expandSapporo = !!v; paint(); },
      setIncludeNorthernTerritoriesVillages(v) { state.includeNTV = !!v; paint(); },
      highlight(code) { for (const o of cells) o.g.classList.toggle('tm-selected', o.code === code); },
      element: root,
      destroy() { if (root.parentNode) root.parentNode.removeChild(root); }
    };
  }

  return { create, ramp, REGION };
})();
