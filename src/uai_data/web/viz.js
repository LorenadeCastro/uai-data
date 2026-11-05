// Visualizações. Cada função desenha a tabela já agregada (data.js) dentro de `el`.
// Gráficos usam Plotly; tabela, tabela dinâmica e números são HTML puro.
import { compare, niceTicks } from './data.js';

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** Lê as cores do tema atual (variáveis CSS), para que claro/escuro sirvam aos gráficos também. */
export function readTheme() {
  const css = getComputedStyle(document.documentElement);
  const v = (n) => css.getPropertyValue(n).trim();
  return {
    series: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => v(`--s${i}`)),
    other: v('--other'), ink: v('--ink'), ink2: v('--ink-2'), grid: v('--grid'), surface: v('--surface'),
    seq: [100, 150, 200, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700].map((n) => v(`--q${n}`)),
    font: v('--font'),
    dark: matchMedia('(prefers-color-scheme: dark)').matches && document.documentElement.dataset.theme !== 'light'
      || document.documentElement.dataset.theme === 'dark',
  };
}

const measuresOf = (t) => t.columns.filter((c) => c.kind === 'measure');
const dimsOf = (t) => t.columns.filter((c) => c.kind === 'dim');
const colIndex = (t, name) => t.columns.findIndex((c) => c.name === name);

function empty(el) {
  el.innerHTML = '<div class="empty">Nenhum dado para os filtros selecionados.</div>';
}

function baseLayout(T) {
  const axis = { gridcolor: T.grid, zerolinecolor: T.grid, linecolor: T.grid, tickfont: { color: T.ink2, size: 11 }, automargin: true, fixedrange: true };
  return {
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', separators: ',.',
    font: { family: T.font, size: 12, color: T.ink2 }, margin: { l: 16, r: 12, t: 6, b: 6 },
    xaxis: { ...axis }, yaxis: { ...axis },
    legend: { orientation: 'h', yanchor: 'bottom', y: 1.02, x: 0, font: { color: T.ink2, size: 11 } },
    hoverlabel: { bgcolor: T.surface, bordercolor: T.grid, font: { color: T.ink, family: T.font, size: 12 } },
  };
}

function draw(el, traces, layout, after) {
  el.innerHTML = '';
  const config = { responsive: true, displayModeBar: false, displaylogo: false, scrollZoom: false };
  return Plotly.newPlot(el, traces, layout, config).then((gd) => { after?.(gd); return gd; });
}

/** Troca os rótulos do eixo de valores por marcas "redondas" em formato compacto (12 mi, 1,2 bi). */
function compactAxis(gd, axis, ctx, format) {
  try {
    const key = `${axis}axis`;
    const range = gd._fullLayout[key].range;
    const ticks = niceTicks(Math.min(...range), Math.max(...range));
    if (ticks.length) Plotly.relayout(gd, { [`${key}.tickmode`]: 'array', [`${key}.tickvals`]: ticks, [`${key}.ticktext`]: ticks.map((t) => ctx.fmt.compact(t, format)) });
  } catch { /* o Plotly escolhe as marcas sozinho */ }
}

/** Séries de cores: até 8 identidades; o excedente vira "Outros" (nunca uma 9ª cor inventada). */
function foldSeries(totals, T) {
  const order = [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([k]) => k);
  const keep = order.length > 8 ? order.slice(0, 7) : order;
  const colors = new Map(keep.map((k, i) => [k, T.series[i]]));
  return { keep: new Set(keep), colors, folded: order.length > 8 };
}

// ---------------------------------------------------------------- gráficos cartesianos
function cartesian(el, card, table, ctx) {
  const { T, fmt } = ctx;
  const meas = measuresOf(table);
  const dims = dimsOf(table);
  const xName = card.x || dims[0]?.name;
  const xi = colIndex(table, xName);
  const yNames = card.y?.length ? card.y : [meas[0].name];
  const horizontal = card.viz === 'hbar';
  const stackLike = card.viz === 'stacked_bar';
  const isLine = card.viz === 'line' || card.viz === 'area';
  const traces = [];
  let format = meas[0].format;

  const mk = (name, xs, ys, color, fmtName) => {
    const custom = ys.map((v) => fmt.full(v, fmtName));
    const common = { name, customdata: custom, hovertemplate: `%{${horizontal ? 'y' : 'x'}}<br>%{customdata}<extra>${esc(name)}</extra>` };
    if (isLine) {
      return { ...common, type: 'scatter', mode: 'lines+markers', x: xs, y: ys, line: { color, width: 2 }, marker: { color, size: 8, line: { color: T.surface, width: 2 } },
        ...(card.viz === 'area' ? { stackgroup: 'one', fill: 'tonexty', mode: 'lines', line: { color, width: 2 }, fillcolor: color + 'cc' } : {}) };
    }
    return { ...common, type: 'bar', orientation: horizontal ? 'h' : 'v', x: horizontal ? ys : xs, y: horizontal ? xs : ys,
      marker: { color, line: { color: T.surface, width: 2 } } };
  };

  if (card.series) {
    const si = colIndex(table, card.series);
    const yi = colIndex(table, yNames[0]);
    format = table.columns[yi].format;
    const catTotals = new Map();
    const serTotals = new Map();
    for (const r of table.rows) {
      catTotals.set(r[xi], (catTotals.get(r[xi]) || 0) + (r[yi] || 0));
      serTotals.set(r[si], (serTotals.get(r[si]) || 0) + (r[yi] || 0));
    }
    let cats = [...catTotals.keys()];
    if (card.sort?.length) {
      const sign = card.sort[0].dir === 'asc' ? 1 : -1;
      cats.sort((a, b) => sign * (catTotals.get(a) - catTotals.get(b)));
    }
    if (card.top) cats = cats.slice(0, card.top);
    const { keep, colors, folded } = foldSeries(serTotals, T);
    const cell = new Map();
    for (const r of table.rows) {
      const s = keep.has(r[si]) ? r[si] : 'Outros';
      const key = `${r[xi]}\u0000${s}`;
      cell.set(key, (cell.get(key) || 0) + (r[yi] || 0));
    }
    const names = [...keep, ...(folded ? ['Outros'] : [])];
    names.sort((a, b) => (serTotals.get(b) || 0) - (serTotals.get(a) || 0));
    for (const s of names) {
      const ys = cats.map((c) => cell.get(`${c}\u0000${s}`) ?? null);
      traces.push(mk(String(s), cats, ys, s === 'Outros' ? T.other : colors.get(s), format));
    }
  } else {
    let cats = table.rows.map((r) => r[xi]);
    yNames.forEach((yn, k) => {
      const yi = colIndex(table, yn);
      const col = table.columns[yi];
      format = col.format;
      traces.push(mk(col.label, cats, table.rows.map((r) => r[yi]), T.series[k % 8], col.format));
    });
  }

  const layout = baseLayout(T);
  layout.showlegend = traces.length > 1;
  if (layout.showlegend) layout.margin.t = 30;
  layout.hovermode = isLine ? 'x unified' : 'closest';
  if (stackLike) layout.barmode = 'stack';
  else if (card.viz === 'bar' || horizontal) layout.barmode = 'group';
  const cat = { type: 'category' };
  if (horizontal) { layout.yaxis = { ...layout.yaxis, ...cat, autorange: 'reversed' }; layout.margin.l = 8; }
  else {
    layout.xaxis = { ...layout.xaxis, ...cat };
    const cats = traces[0]?.x || [];
    if (cats.length > 12) {                      // poucos rótulos legíveis em vez de todos inclinados
      const step = Math.ceil(cats.length / 10);
      layout.xaxis.tickmode = 'array';
      layout.xaxis.tickvals = cats.filter((_, i) => i % step === 0);
      layout.xaxis.tickangle = 0;
    }
  }
  const valueAxis = horizontal ? 'x' : 'y';
  draw(el, traces, layout, (gd) => compactAxis(gd, valueAxis, ctx, format));
}

// ---------------------------------------------------------------- rosca, funil, árvore, calor, cascata, dispersão
function pie(el, card, table, ctx) {
  const { T, fmt } = ctx;
  const dims = dimsOf(table);
  const xi = colIndex(table, card.x || dims[0].name);
  const yi = colIndex(table, card.y?.[0] || measuresOf(table)[0].name);
  const col = table.columns[yi];
  const totals = new Map();
  table.rows.forEach((r) => totals.set(r[xi], (totals.get(r[xi]) || 0) + (r[yi] || 0)));
  const { keep, colors, folded } = foldSeries(totals, T);
  const labels = [...keep].sort((a, b) => totals.get(b) - totals.get(a));
  const values = labels.map((l) => totals.get(l));
  const palette = labels.map((l) => colors.get(l));
  if (folded) {
    labels.push('Outros'); palette.push(T.other);
    values.push([...totals].filter(([k]) => !keep.has(k)).reduce((s, [, v]) => s + v, 0));
  }
  const short = (l) => (String(l).length > 30 ? `${String(l).slice(0, 28)}…` : String(l));
  const layout = { ...baseLayout(T), showlegend: true, legend: { orientation: 'v', x: 0.62, y: 0.5, font: { color: T.ink2, size: 11 } },
    uniformtext: { minsize: 10, mode: 'hide' } };
  draw(el, [{
    type: 'pie', labels: labels.map(short), hovertext: labels.map(String), values, sort: false, direction: 'clockwise',
    hole: card.viz === 'donut' ? 0.58 : 0, domain: { x: [0, 0.58], y: [0, 1] },
    marker: { colors: palette, line: { color: T.surface, width: 2 } }, textinfo: 'percent', textposition: 'inside',
    customdata: values.map((v) => fmt.full(v, col.format)),
    hovertemplate: '%{hovertext}<br>%{customdata} (%{percent})<extra></extra>',
  }], layout);
}

function funnel(el, card, table, ctx) {
  const { T, fmt } = ctx;
  const dims = dimsOf(table);
  const xi = colIndex(table, card.x || dims[0].name);
  const yi = colIndex(table, card.y?.[0] || measuresOf(table)[0].name);
  const col = table.columns[yi];
  const rows = table.rows.slice(0, 13);
  const ramp = T.dark ? T.seq.slice(2, 11) : T.seq.slice(3);   // etapas ordinais: contraste mínimo 2:1 com o fundo
  const colors = rows.map((_, i) => ramp[Math.min(i * Math.floor(ramp.length / Math.max(rows.length, 1)) || i, ramp.length - 1)]);
  const layout = { ...baseLayout(T), funnelmode: 'stack', showlegend: false };
  layout.yaxis = { ...layout.yaxis, type: 'category' };
  draw(el, [{
    type: 'funnel', y: rows.map((r) => r[xi]), x: rows.map((r) => r[yi]),
    text: rows.map((r) => fmt.full(r[yi], col.format)), textinfo: 'text+percent initial',
    marker: { color: colors, line: { color: T.surface, width: 2 } }, connector: { line: { color: T.grid } },
    customdata: rows.map((r) => fmt.full(r[yi], col.format)), hovertemplate: '%{y}<br>%{customdata}<extra></extra>',
  }], layout);
}

function treemap(el, card, table, ctx) {
  const { T, fmt } = ctx;
  const dims = dimsOf(table).map((d) => colIndex(table, d.name));
  const yi = colIndex(table, card.y?.[0] || measuresOf(table)[0].name);
  const col = table.columns[yi];
  const nodes = new Map();
  const roots = new Map();
  for (const r of table.rows) {
    const v = r[yi] || 0;
    if (v <= 0) continue;
    const path = dims.map((i) => String(r[i]));
    if (!roots.has(path[0])) roots.set(path[0], roots.size);
    path.forEach((_, d) => {
      const id = path.slice(0, d + 1).join('␟');
      const n = nodes.get(id) || { id, parent: d ? path.slice(0, d).join('␟') : '', label: path[d], value: 0, root: path[0] };
      n.value += v; nodes.set(id, n);
    });
  }
  const list = [...nodes.values()];
  if (!list.length) return empty(el);
  const layout = { ...baseLayout(T), margin: { l: 4, r: 4, t: 4, b: 4 } };
  draw(el, [{
    type: 'treemap', ids: list.map((n) => n.id), labels: list.map((n) => n.label), parents: list.map((n) => n.parent),
    values: list.map((n) => n.value), branchvalues: 'total', sort: true,
    marker: { colors: list.map((n) => T.series[roots.get(n.root) % 8]), line: { color: T.surface, width: 2 } },
    customdata: list.map((n) => fmt.full(n.value, col.format)),
    hovertemplate: '%{label}<br>%{customdata}<extra></extra>',
  }], layout);
}

function heatmap(el, card, table, ctx) {
  const { T, fmt } = ctx;
  const dims = dimsOf(table);
  const xi = colIndex(table, card.x || dims[0].name);
  const si = colIndex(table, card.series || dims[1]?.name);
  const yi = colIndex(table, card.y?.[0] || measuresOf(table)[0].name);
  const col = table.columns[yi];
  const xs = [...new Set(table.rows.map((r) => r[xi]))];
  const ys = [...new Set(table.rows.map((r) => r[si]))];
  const z = ys.map(() => xs.map(() => null));
  for (const r of table.rows) {
    const a = ys.indexOf(r[si]); const b = xs.indexOf(r[xi]);
    z[a][b] = (z[a][b] || 0) + (r[yi] || 0);
  }
  const flat = z.flat().filter((v) => v !== null);
  const ticks = niceTicks(Math.min(...flat), Math.max(...flat), 4);
  const scale = T.seq.map((c, i) => [i / (T.seq.length - 1), c]);
  const layout = baseLayout(T);
  layout.xaxis = { ...layout.xaxis, type: 'category' };
  layout.yaxis = { ...layout.yaxis, type: 'category', autorange: 'reversed' };
  draw(el, [{
    type: 'heatmap', x: xs, y: ys, z, colorscale: scale, xgap: 2, ygap: 2, hoverongaps: false,
    customdata: z.map((row) => row.map((v) => fmt.full(v, col.format))),
    hovertemplate: '%{y} · %{x}<br>%{customdata}<extra></extra>',
    colorbar: { thickness: 10, len: 0.9, tickvals: ticks, ticktext: ticks.map((t) => fmt.compact(t, col.format)), tickfont: { color: T.ink2, size: 10 }, outlinewidth: 0 },
  }], layout);
}

function waterfall(el, card, table, ctx) {
  const { T, fmt } = ctx;
  const dims = dimsOf(table);
  const xi = colIndex(table, card.x || dims[0].name);
  const yi = colIndex(table, card.y?.[0] || measuresOf(table)[0].name);
  const col = table.columns[yi];
  const rows = table.rows.filter((r) => r[yi] !== null);
  const xs = [...rows.map((r) => r[xi]), 'Total'];
  const ys = [...rows.map((r) => r[yi]), null];
  const layout = baseLayout(T);
  layout.xaxis = { ...layout.xaxis, type: 'category' };
  layout.showlegend = false;
  draw(el, [{
    type: 'waterfall', x: xs, y: ys, measure: [...rows.map(() => 'relative'), 'total'],
    increasing: { marker: { color: T.series[0], line: { color: T.surface, width: 2 } } },
    decreasing: { marker: { color: T.series[1], line: { color: T.surface, width: 2 } } },
    totals: { marker: { color: T.seq[12], line: { color: T.surface, width: 2 } } },
    connector: { line: { color: T.grid, width: 1 } },
    hovertemplate: `%{x}<br>%{y:,.2f}<extra></extra>`,
  }], layout, (gd) => compactAxis(gd, 'y', ctx, col.format));
}

function scatter(el, card, table, ctx) {
  const { T, fmt } = ctx;
  const meas = measuresOf(table);
  const names = card.y?.length >= 2 ? card.y : meas.slice(0, 2).map((m) => m.name);
  const xi = colIndex(table, names[0]); const yi = colIndex(table, names[1]);
  const cx = table.columns[xi]; const cy = table.columns[yi];
  const label = dimsOf(table)[0] ? colIndex(table, dimsOf(table)[0].name) : -1;
  const layout = baseLayout(T);
  layout.showlegend = false;
  layout.margin.b = 40; layout.margin.l = 40;
  layout.hovermode = 'closest';
  layout.xaxis = { ...layout.xaxis, title: { text: cx.label, font: { color: T.ink2, size: 11 } } };
  layout.yaxis = { ...layout.yaxis, title: { text: cy.label, font: { color: T.ink2, size: 11 } } };
  draw(el, [{
    type: 'scatter', mode: 'markers', x: table.rows.map((r) => r[xi]), y: table.rows.map((r) => r[yi]),
    text: table.rows.map((r) => (label >= 0 ? r[label] : '')),
    marker: { color: T.series[0], size: 10, line: { color: T.surface, width: 2 } },
    customdata: table.rows.map((r) => [fmt.full(r[xi], cx.format), fmt.full(r[yi], cy.format)]),
    hovertemplate: `%{text}<br>${esc(cx.label)}: %{customdata[0]}<br>${esc(cy.label)}: %{customdata[1]}<extra></extra>`,
  }], layout, (gd) => { compactAxis(gd, 'x', ctx, cx.format); compactAxis(gd, 'y', ctx, cy.format); });
}

function gauge(el, card, table, ctx) {
  const { T } = ctx;
  const col = measuresOf(table).find((m) => m.name === card.y?.[0]) || measuresOf(table)[0];
  const value = table.rows[0]?.[colIndex(table, col.name)] ?? 0;
  const max = card.max_value || Math.max(value * 1.25, 1);
  const layout = { ...baseLayout(T), margin: { l: 24, r: 24, t: 8, b: 4 } };
  draw(el, [{
    type: 'indicator', mode: 'gauge+number', value,
    number: { font: { color: T.ink, size: 26, family: T.font }, valueformat: col.format === 'integer' ? ',.0f' : ',.2f', prefix: col.format === 'currency' ? 'R$ ' : '' },
    gauge: {
      axis: { range: [0, max], tickfont: { color: T.ink2, size: 10 }, tickcolor: T.grid }, bar: { color: T.series[0], thickness: 0.6 },
      bgcolor: T.grid, borderwidth: 0,
    },
  }], layout);
}

// ---------------------------------------------------------------- HTML: número, tabela, tabela dinâmica
function number(el, card, table, ctx) {
  const meas = measuresOf(table);
  const col = meas.find((m) => m.name === card.y?.[0]) || meas[0];
  const value = table.rows[0]?.[colIndex(table, col.name)];
  el.innerHTML = `<div class="kpi"><div class="kpi-value">${esc(ctx.fmt.full(value, col.format))}</div><div class="kpi-label">${esc(col.label)}</div></div>`;
}

function tableView(el, card, table, ctx) {
  const state = { sort: -1, dir: 1, page: 0 };
  const per = 50;
  const draw = () => {
    let rows = table.rows;
    if (state.sort >= 0) rows = [...rows].sort((a, b) => state.dir * compare(a[state.sort], b[state.sort]));
    const pages = Math.max(1, Math.ceil(rows.length / per));
    state.page = Math.min(state.page, pages - 1);
    const slice = rows.slice(state.page * per, state.page * per + per);
    const head = table.columns.map((c, i) => `<th class="${c.kind === 'measure' ? 'num' : ''}" data-i="${i}" aria-sort="${state.sort === i ? (state.dir > 0 ? 'ascending' : 'descending') : 'none'}"><button type="button">${esc(c.label)}<span aria-hidden="true">${state.sort === i ? (state.dir > 0 ? ' ▲' : ' ▼') : ''}</span></button></th>`).join('');
    const body = slice.map((r) => `<tr>${r.map((v, i) => `<td class="${table.columns[i].kind === 'measure' ? 'num' : ''}">${esc(ctx.fmt.full(v, table.columns[i].format))}</td>`).join('')}</tr>`).join('');
    el.innerHTML = `<div class="tbl-wrap"><table class="tbl"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`
      + `<div class="tbl-foot"><span>${rows.length.toLocaleString('pt-BR')} linhas</span>${pages > 1 ? `<span><button type="button" data-p="-1" ${state.page === 0 ? 'disabled' : ''}>Anterior</button> ${state.page + 1} de ${pages} <button type="button" data-p="1" ${state.page >= pages - 1 ? 'disabled' : ''}>Próxima</button></span>` : ''}</div>`;
    el.querySelectorAll('th').forEach((th) => th.addEventListener('click', () => {
      const i = Number(th.dataset.i);
      state.dir = state.sort === i ? -state.dir : 1; state.sort = i; draw();
    }));
    el.querySelectorAll('[data-p]').forEach((b) => b.addEventListener('click', () => { state.page += Number(b.dataset.p); draw(); }));
  };
  draw();
}

function pivot(el, card, table, ctx) {
  const dims = dimsOf(table).map((d) => d.name);
  const rowDims = (card.rows?.length ? card.rows : dims.slice(0, 1)).map((n) => colIndex(table, n));
  const colDims = (card.columns?.length ? card.columns : dims.slice(1, 2)).map((n) => colIndex(table, n));
  const yi = colIndex(table, card.y?.[0] || measuresOf(table)[0].name);
  const col = table.columns[yi];
  const key = (r, ix) => ix.map((i) => String(r[i] ?? '')).join(' › ');
  const rowKeys = []; const colKeys = []; const cell = new Map(); const rt = new Map(); const ct = new Map(); let grand = 0;
  for (const r of table.rows) {
    const rk = key(r, rowDims); const ck = key(r, colDims); const v = r[yi] || 0;
    if (!rowKeys.includes(rk)) rowKeys.push(rk);
    if (!colKeys.includes(ck)) colKeys.push(ck);
    cell.set(rk + '\u0000' + ck, (cell.get(rk + '\u0000' + ck) || 0) + v);
    rt.set(rk, (rt.get(rk) || 0) + v); ct.set(ck, (ct.get(ck) || 0) + v); grand += v;
  }
  colKeys.sort((a, b) => compare(a, b));
  const additive = col.agg === 'sum';                 // totais só fazem sentido para somas/contagens
  const f = (v) => esc(ctx.fmt.full(v, col.format));
  const head = `<tr><th>${esc(rowDims.map((i) => table.columns[i].label).join(' › '))}</th>${colKeys.map((c) => `<th class="num">${esc(c)}</th>`).join('')}${additive ? '<th class="num total">Total</th>' : ''}</tr>`;
  const body = rowKeys.map((rk) => `<tr><th scope="row">${esc(rk)}</th>${colKeys.map((ck) => `<td class="num">${cell.has(rk + '\u0000' + ck) ? f(cell.get(rk + '\u0000' + ck)) : ''}</td>`).join('')}${additive ? `<td class="num total">${f(rt.get(rk))}</td>` : ''}</tr>`).join('');
  const foot = additive ? `<tr class="total"><th scope="row">Total</th>${colKeys.map((ck) => `<td class="num">${f(ct.get(ck))}</td>`).join('')}<td class="num">${f(grand)}</td></tr>` : '';
  el.innerHTML = `<div class="tbl-wrap"><table class="tbl pivot"><thead>${head}</thead><tbody>${body}${foot}</tbody></table></div>`;
}

const RENDERERS = {
  bar: cartesian, hbar: cartesian, stacked_bar: cartesian, line: cartesian, area: cartesian,
  pie, donut: pie, funnel, treemap, heatmap, waterfall, scatter, gauge, number, table: tableView, pivot,
};
export const CHART_VIZ = new Set(['bar', 'hbar', 'stacked_bar', 'line', 'area', 'pie', 'donut', 'funnel', 'treemap', 'heatmap', 'waterfall', 'scatter', 'gauge']);

export function render(el, card, table, ctx) {
  if (!table.rows.length || !table.columns.length) return empty(el);
  try {
    (RENDERERS[card.viz] || tableView)(el, card, table, ctx);
  } catch (err) {
    console.error(card.id, err);
    el.innerHTML = `<div class="empty">Não foi possível desenhar este card (${esc(err.message)}). Confira x, y e series em dashboards/…/${esc(card.id)}.</div>`;
  }
}
