// Agregação, filtros e formatação — funções puras (sem DOM), testáveis no Node.

/** Colunas que o leitor enxerga (esconde a coluna auxiliar de média ponderada). */
export const visibleColumns = (payload) => payload.columns.filter((c) => c.kind !== 'weight');

/**
 * Aplica filtros e reagrupa pelas dimensões do card.
 *   filters: { coluna: Set(valores) }  ou  { coluna: { text: 'trecho' } }
 * O servidor agrupou por (dimensões + colunas de filtro); aqui somamos de volta o que o leitor escondeu.
 */
export function aggregate(payload, card, filters = {}) {
  const cols = payload.columns;
  const idx = Object.fromEntries(cols.map((c, i) => [c.name, i]));

  const active = Object.entries(filters).filter(([col, f]) =>
    col in idx && (f instanceof Set ? f.size > 0 : f && f.text));
  const rows = payload.rows.filter((r) => active.every(([col, f]) => {
    const v = r[idx[col]];
    return f instanceof Set ? f.has(String(v)) : String(v ?? '').toLowerCase().includes(f.text.toLowerCase());
  }));

  if (card.native && !active.length) return { columns: visibleColumns(payload), rows: payload.rows };
  const dims = cols.filter((c) => c.kind === 'dim');
  const groupDims = card.native
    ? (card.sql_dimensions?.length ? dims.filter((d) => card.sql_dimensions.includes(d.name)) : dims)
    : dims.filter((d) => card.dimensions.includes(d.name));
  const measures = cols.filter((c) => c.kind === 'measure');

  const groups = new Map();
  for (const r of rows) {
    const key = JSON.stringify(groupDims.map((d) => r[idx[d.name]]));
    let g = groups.get(key);
    if (!g) {
      g = { dims: groupDims.map((d) => r[idx[d.name]]), acc: measures.map(() => ({ s: 0, n: 0, min: null, max: null, seen: false })) };
      groups.set(key, g);
    }
    measures.forEach((m, k) => {
      const v = r[idx[m.name]];
      if (v === null || v === undefined) return;
      const a = g.acc[k];
      a.seen = true;
      if (m.agg === 'avg') {
        const w = idx[`${m.name}__n`] !== undefined ? r[idx[`${m.name}__n`]] : 1;
        a.s += v * w; a.n += w;
      } else if (m.agg === 'min') a.min = a.min === null ? v : Math.min(a.min, v);
      else if (m.agg === 'max') a.max = a.max === null ? v : Math.max(a.max, v);
      else a.s += v;
    });
  }

  let out = [...groups.values()].map((g) => [
    ...g.dims,
    ...measures.map((m, k) => {
      const a = g.acc[k];
      if (!a.seen) return null;
      if (m.agg === 'avg') return a.n ? a.s / a.n : null;
      if (m.agg === 'min') return a.min;
      if (m.agg === 'max') return a.max;
      return a.s;
    }),
  ]);
  const columns = [...groupDims, ...measures];

  // sem dimensões e sem linhas: ainda assim existe um "total" (zero) para cartões numéricos
  if (!groupDims.length && !out.length && measures.length) out = [measures.map(() => null)];

  const pos = Object.fromEntries(columns.map((c, i) => [c.name, i]));
  if (!card.sort?.length) {                        // sem ordem pedida: dimensões em ordem natural (2 antes de 10)
    const nd = groupDims.length;
    out.sort((a, b) => { for (let i = 0; i < nd; i++) { const c = compare(a[i], b[i]); if (c) return c; } return 0; });
  }
  for (const s of [...(card.sort || [])].reverse()) {
    const i = pos[s.by];
    if (i === undefined) continue;
    const sign = s.dir === 'asc' ? 1 : -1;
    out.sort((a, b) => sign * compare(a[i], b[i]));
  }
  if (card.top) out = out.slice(0, card.top);
  return { columns, rows: out };
}

export function compare(a, b) {
  if (a === b) return 0;
  if (a === null || a === undefined) return -1;
  if (b === null || b === undefined) return 1;
  return typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b), 'pt-BR', { numeric: true });
}

/** Valores distintos de uma coluna entre os payloads que a possuem (para as opções de filtro). */
export function distinctValues(payloads, column) {
  const set = new Set();
  for (const p of payloads) {
    const i = p.columns.findIndex((c) => c.name === column && c.kind === 'dim');
    if (i >= 0) for (const r of p.rows) if (r[i] !== null) set.add(String(r[i]));
  }
  return [...set].sort((a, b) => a.localeCompare(b, 'pt-BR', { numeric: true }));
}

// ---------------------------------------------------------------- formatação (centavos sempre)
export function makeFormatter(cfg) {
  const locale = cfg.locale || 'pt-BR';
  const nf = {
    currency: new Intl.NumberFormat(locale, { style: 'currency', currency: cfg.currency || 'BRL', minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    number: new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    integer: new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }),
    percent: new Intl.NumberFormat(locale, { style: 'percent', minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    compact: new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }),
  };
  const full = (v, format) => (v === null || v === undefined ? '—'
    : typeof v === 'number' && nf[format] ? nf[format].format(v) : String(v));
  const compact = (v, format) => (typeof v !== 'number' ? String(v)
    : (format === 'currency' ? `${nf.currency.format(0).replace(/[\d.,\s]/g, '')} ` : '') + nf.compact.format(v));
  return { full, compact };
}

/** CSV da visão atual (já filtrada), pronto para o Excel brasileiro: BOM, ';' e vírgula decimal. */
export function toCsv(table, cfg) {
  const sep = cfg.csvSep || ';';
  const dec = cfg.csvDecimal || ',';
  const q = (s) => (/[";\n\r]/.test(s) || s.includes(sep) ? `"${s.replace(/"/g, '""')}"` : s);
  const num = (v, c) => (c.format === 'integer' ? v.toFixed(0) : v.toFixed(2)).replace('.', dec);
  const head = table.columns.map((c) => q(c.label)).join(sep);
  const body = table.rows.map((r) => r.map((v, i) => {
    const c = table.columns[i];
    if (v === null || v === undefined) return '';
    return typeof v === 'number' && c.kind === 'measure' ? num(v, c) : q(String(v));
  }).join(sep));
  return '﻿' + [head, ...body].join('\r\n');
}

/** Valores "redondos" para o eixo (5 marcas), que o chamador formata de forma compacta. */
export function niceTicks(min, max, n = 5) {
  if (!isFinite(min) || !isFinite(max)) return [];
  if (min === max) return [min];
  const span = max - min;
  const raw = span / (n - 1);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const start = Math.ceil(min / step) * step;
  const ticks = [];
  for (let t = start; t <= max + step * 1e-9; t += step) ticks.push(Number(t.toPrecision(12)));
  return ticks;
}
