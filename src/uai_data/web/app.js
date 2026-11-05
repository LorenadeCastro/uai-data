// Uai Data — aplicação do navegador. Sem framework e sem etapa de build: o que está aqui é o que roda.
import { authFileName, decrypt, decryptJson, fromB64u, toB64u, unlockPrivateKey, unwrapKey } from './crypto.js';
import { aggregate, distinctValues, makeFormatter, toCsv } from './data.js';
import { CHART_VIZ, esc, readTheme, render } from './viz.js';

const app = document.getElementById('app');
const state = { cfg: null, fmt: null, session: null, next: null, keys: new Map(), view: null };

// ------------------------------------------------------------------ utilidades
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* modo privado */ } },
};

function applyTheme(mode) {
  if (mode === 'light' || mode === 'dark') document.documentElement.dataset.theme = mode;
  else delete document.documentElement.dataset.theme;
}
const currentTheme = () => document.documentElement.dataset.theme
  || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');

function toast(msg) {
  const el = document.createElement('div');
  el.className = 'toast'; el.setAttribute('role', 'status'); el.textContent = msg;
  document.body.append(el);
  setTimeout(() => el.remove(), 2600);
}

async function getBuffer(url) {
  const res = await fetch(url, { cache: 'no-cache' });
  if (!res.ok) throw new Error(`HTTP ${res.status} em ${url}`);
  return res.arrayBuffer();
}

function download(blob, filename) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = filename;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

const slug = (s) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'painel';
const when = (iso) => new Date(iso).toLocaleString(state.cfg.locale || 'pt-BR', { dateStyle: 'short', timeStyle: 'short' });
const repoOk = () => state.cfg.repo && state.cfg.repo.includes('/') && state.cfg.repo !== 'dono/repositorio';
const ghUrl = (kind, path, query = '') => `https://github.com/${state.cfg.repo}/${kind}/${state.cfg.branch}/${path}${query}`;

function setView(html, { shell = true, nav = '' } = {}) {
  state.view = null;
  if (!shell) { app.innerHTML = html; return; }
  const s = state.session;
  const link = (href, label, key) => `<a href="${href}" ${nav === key ? 'aria-current="page"' : ''}>${label}</a>`;
  const orgs = s ? s.me.orgs : [];
  const catalogOrg = orgs.find((o) => o.catalog);
  const adminOrgs = orgs.filter((o) => o.admin);
  app.innerHTML = `
    <header class="top"><div class="top-in">
      <a href="#/" aria-label="Uai Data — página inicial"><img src="assets/logo.png" alt="Uai Data" width="127" height="40"></a>
      <nav aria-label="Principal">
        ${s ? link('#/', 'Painéis', 'home') : ''}
        ${catalogOrg ? link(`#/explore/${catalogOrg.id}`, 'Explorar dados', 'explore') : ''}
        ${adminOrgs.map((o) => link(`#/org/${o.id}`, `Pessoas · ${esc(o.name)}`, `org-${o.id}`)).join('')}
      </nav>
      <div class="who">
        <button class="icon-btn" id="theme" type="button" aria-label="Alternar entre tema claro e escuro">${currentTheme() === 'dark' ? 'Tema claro' : 'Tema escuro'}</button>
        ${s ? `<span title="${esc(s.me.user.name)}">${esc(s.me.user.name)}</span><button class="icon-btn" id="logout" type="button">Sair</button>` : ''}
      </div>
    </div></header>
    <main id="main" tabindex="-1">${html}</main>`;
  document.getElementById('theme').onclick = () => {
    const next = currentTheme() === 'dark' ? 'light' : 'dark';
    applyTheme(next); store.set('uai-theme', next);
    document.getElementById('theme').textContent = next === 'dark' ? 'Tema claro' : 'Tema escuro';
    state.view?.refresh?.();
  };
  const out = document.getElementById('logout');
  if (out) out.onclick = () => { state.session = null; state.keys.clear(); location.hash = '#/'; route(); };
}

function failure(err, message = 'Não foi possível abrir esta página.') {
  console.error(err);
  setView(`<div class="panel"><h1>${esc(message)}</h1>
    <p>Isso costuma acontecer quando o acesso foi removido ou o painel ainda não foi publicado.
    Volte para a lista de painéis e, se o problema continuar, fale com o administrador da sua organização.</p>
    <p><a class="btn primary" href="#/">Ver meus painéis</a></p></div>`, { shell: !!state.session });
}

// ------------------------------------------------------------------ login
function showLogin(message = '') {
  setView(`
    <div class="login-wrap"><form class="login" id="login" novalidate>
      <img src="assets/logo.png" alt="${esc(state.cfg.name)} — ${esc(state.cfg.tagline)}">
      <h1>Entrar</h1><p class="lead">Use o usuário e a senha que o administrador da sua organização criou.</p>
      <div class="field"><label for="u">Usuário</label><input id="u" name="u" autocomplete="username" autocapitalize="none" spellcheck="false" required></div>
      <div class="field"><label for="p">Senha</label><input id="p" name="p" type="password" autocomplete="current-password" required></div>
      <p class="err" id="err" role="alert">${esc(message)}</p>
      <button class="btn primary" id="go" type="submit" style="width:100%;justify-content:center">Entrar</button>
      <p class="fine">Os dados dos painéis ficam cifrados. A senha abre a sua chave aqui no navegador e nunca é enviada a lugar nenhum.</p>
    </form></div>`, { shell: false });
  const form = document.getElementById('login');
  document.getElementById('u').focus();
  form.onsubmit = async (e) => {
    e.preventDefault();
    const user = form.u.value.trim(); const pass = form.p.value;
    const err = document.getElementById('err'); const go = document.getElementById('go');
    if (!user || !pass) { err.textContent = 'Informe o usuário e a senha.'; return; }
    go.disabled = true; go.textContent = 'Entrando…'; err.textContent = '';
    try {
      await login(user, pass);
      const next = state.next; state.next = null;
      location.hash = next && next !== '#/login' ? next : '#/';
      route();
    } catch (ex) {
      console.error(ex);
      err.textContent = 'Usuário ou senha incorretos.';
      go.disabled = false; go.textContent = 'Entrar'; form.p.select();
    }
  };
}

async function login(user, password) {
  const name = await authFileName(state.cfg.salt, user);
  const auth = await (await fetch(`auth/${name}.json`, { cache: 'no-cache' })).json();   // 404 => erro => "usuário ou senha"
  const priv = await unlockPrivateKey(auth, password);                                  // senha errada => erro
  const meKey = await unwrapKey(priv, auth.keys['@me']);
  const me = await decryptJson(meKey, await getBuffer(`auth/${name}.me.bin`));
  state.keys.clear();
  state.session = { login: user, priv, auth, me };
}

/** Chave (32 bytes) de um painel/catálogo para o usuário logado. */
async function keyFor(id) {
  if (state.keys.has(id)) return state.keys.get(id);
  const wrapped = state.session.auth.keys[id];
  if (!wrapped) throw new Error('sem acesso a ' + id);
  const raw = await unwrapKey(state.session.priv, wrapped);
  state.keys.set(id, raw);
  return raw;
}

// ------------------------------------------------------------------ início
function showHome() {
  const { me } = state.session;
  const q = { text: '' };
  const byOrg = (text) => me.orgs.map((o) => ({
    org: o,
    items: me.dashboards.filter((d) => d.organization === o.id && (!text || `${d.title} ${d.description || ''} ${(d.tags || []).join(' ')}`.toLowerCase().includes(text))),
  })).filter((g) => g.items.length || (!text && g.org.perms.includes('create')));

  const body = (text) => {
    const groups = byOrg(text);
    if (!groups.length) return '<div class="empty">Nenhum painel encontrado.</div>';
    return groups.map(({ org, items }) => `
      <section class="org-block" aria-labelledby="o-${esc(org.id)}">
        <h2 id="o-${esc(org.id)}">${esc(org.name)} <span class="chip">${org.admin ? 'administrador' : esc(org.profile)}</span>
          ${org.perms.includes('create') && repoOk() ? `<a class="btn small" href="#/explore/${esc(org.id)}">Novo painel</a>` : ''}</h2>
        ${items.length ? `<div class="tiles">${items.map((d) => `
          <a class="tile" href="#/d/${d.id}"><h3>${esc(d.title)}</h3>
            ${d.description ? `<p>${esc(d.description)}</p>` : ''}
            <div class="chips">${(d.tags || []).map((t) => `<span class="chip">${esc(t)}</span>`).join('')}</div></a>`).join('')}</div>`
    : '<p class="muted">Ainda não há painéis nesta organização.</p>'}
      </section>`).join('');
  };
  setView(`
    <div class="page-head"><div><h1>Painéis</h1><p>Olá, ${esc(me.user.name.split(' ')[0])}. Escolha um painel para explorar.</p></div>
      <div><label class="sr" for="q">Buscar painéis</label><input id="q" class="search" type="search" placeholder="Buscar painéis" style="min-width:260px"></div></div>
    <div id="list">${body('')}</div>`, { nav: 'home' });
  document.getElementById('q').oninput = (e) => {
    q.text = e.target.value.trim().toLowerCase();
    document.getElementById('list').innerHTML = body(q.text);
  };
}

// ------------------------------------------------------------------ painel
async function loadDashboard(id, rawKey, exportKey) {
  const spec = await decryptJson(rawKey, await getBuffer(`d/${id}/spec.bin`));
  const payloads = {};
  await Promise.all(spec.cards.map(async (c) => {
    payloads[c.id] = await decryptJson(rawKey, await getBuffer(`c/${id}/${c.id}.bin`));
  }));
  return { spec, payloads, id, rawKey, exportKey };
}

async function showDashboard(id) {
  setView('<div class="spinner">Abrindo painel…</div>', { nav: 'home' });
  const entry = state.session.me.dashboards.find((d) => d.id === id);
  if (!entry) throw new Error('painel não autorizado');
  const rawKey = await keyFor(id);
  const exportKey = entry.perms.includes('download') ? await keyFor(`${id}x`).catch(() => null) : null;
  const dash = await loadDashboard(id, rawKey, exportKey);
  mountDashboard(dash, { perms: entry.perms, shared: false });
}

async function showShared(id, keyText) {
  setView('<div class="spinner">Abrindo painel compartilhado…</div>', { shell: false });
  const rawKey = fromB64u(keyText);
  const dash = await loadDashboard(id, rawKey, null);
  setView('', { shell: true });
  document.querySelector('.top nav').innerHTML = '<span style="padding:8px 12px;color:#c3d0ec">Painel compartilhado · somente leitura</span>';
  mountDashboard(dash, { perms: ['view'], shared: true });
}

function mountDashboard(dash, { perms, shared }) {
  const { spec, payloads } = dash;
  const filters = {};                       // coluna -> Set | {text}
  const tableMode = new Set();               // cards mostrados como tabela
  const last = {};                           // id -> última tabela agregada (para CSV)
  const can = (p) => perms.includes(p);
  document.title = `${spec.title} · ${state.cfg.name}`;

  const editUrl = repoOk() && can('edit') ? ghUrl('edit', spec.edit_path) : null;
  const html = `
    <div class="dash-head"><div>
      <h1>${esc(spec.title)}</h1>
      ${spec.description ? `<p>${esc(spec.description)}</p>` : ''}
      <div class="meta">${esc(spec.organization)} · dados de ${esc(when(spec.updated))}</div></div>
      <div class="actions no-print">
        ${can('share') && !shared ? '<button class="btn" id="share" type="button">Compartilhar</button>' : ''}
        <details class="menu" id="export"><summary class="btn" role="button">Baixar ▾</summary><div class="menu-pop">
          ${can('download') && dash.exportKey ? `<button type="button" data-x="xlsx">Excel (.xlsx)<small>todos os cards, sem filtros de tela</small></button>
            <button type="button" data-x="pdf">PDF (.pdf)<small>resumo do painel, sem filtros de tela</small></button>` : ''}
          <button type="button" data-x="print">Imprimir ou salvar PDF da tela<small>com os filtros que você escolheu</small></button>
          ${can('download') || shared ? '<button type="button" data-x="csv-all">CSV de todos os cards (.csv)<small>com os filtros que você escolheu</small></button>' : ''}
        </div></details>
        ${editUrl ? `<a class="btn" href="${esc(editUrl)}" target="_blank" rel="noopener">Editar painel</a>` : ''}
      </div></div>
    ${spec.filters.length ? '<section class="filters no-print" id="filters" aria-label="Filtros"></section>' : ''}
    <div class="grid" id="grid">${spec.cards.map((c) => `
      <article class="card" id="card-${esc(c.id)}" style="--w:${c.width};--h:${c.height}px" aria-labelledby="t-${esc(c.id)}">
        <header><h3 id="t-${esc(c.id)}">${esc(c.title)}</h3>
          <div class="tools no-print">
            ${c.viz !== 'table' && c.viz !== 'pivot' ? `<button class="tool" type="button" data-a="table" aria-pressed="false">Ver tabela</button>` : ''}
            ${can('download') || shared ? '<button class="tool" type="button" data-a="csv">CSV</button>' : ''}
            ${(can('download') || shared) && CHART_VIZ.has(c.viz) ? '<button class="tool" type="button" data-a="png">PNG</button>' : ''}
          </div></header>
        ${c.description ? `<p class="desc">${esc(c.description)}</p>` : ''}
        <div class="body" data-card="${esc(c.id)}"></div></article>`).join('')}</div>`;
  if (shared) document.getElementById('main').innerHTML = html; else setView(html, { nav: 'home' });

  // ---- filtros
  const cardsByFilter = (col) => spec.cards.filter((c) => c.filters !== 'none' && payloads[c.id].columns.some((k) => k.name === col && k.kind === 'dim'));
  const box = document.getElementById('filters');
  const clearBtn = () => `<button class="btn small" type="button" id="clear">Limpar filtros</button>`;
  const drawFilters = () => {
    if (!box) return;
    const open = box.querySelector('details[open]')?.dataset.col;
    box.innerHTML = spec.filters.map((f) => {
      const label = f.label || f.column;
      if (f.type === 'text') return `<label class="sr" for="f-${esc(f.column)}">${esc(label)}</label><input class="flt-text" id="f-${esc(f.column)}" data-text="${esc(f.column)}" placeholder="${esc(label)}…" value="${esc(filters[f.column]?.text || '')}">`;
      const opts = distinctValues(cardsByFilter(f.column).map((c) => payloads[c.id]), f.column);
      const sel = filters[f.column] || new Set();
      return `<details class="flt" data-col="${esc(f.column)}" ${open === f.column ? 'open' : ''}><summary>${esc(label)}${sel.size ? ` <span class="badge">${sel.size}</span>` : ''}</summary>
        <div class="flt-pop">${opts.length > 8 ? `<input class="search" type="search" placeholder="Buscar" aria-label="Buscar em ${esc(label)}">` : ''}
        ${opts.map((v) => `<label><input type="checkbox" value="${esc(v)}" ${sel.has(v) ? 'checked' : ''}> ${esc(v)}</label>`).join('') || '<span class="muted">Sem valores</span>'}</div></details>`;
    }).join('') + (Object.values(filters).some((f) => (f instanceof Set ? f.size : f?.text)) ? clearBtn() : '');
    box.querySelectorAll('details.flt').forEach((d) => {
      const col = d.dataset.col;
      d.querySelectorAll('input[type=checkbox]').forEach((cb) => cb.onchange = () => {
        const set = filters[col] || (filters[col] = new Set());
        cb.checked ? set.add(cb.value) : set.delete(cb.value);
        refreshAll(); drawFilters();
      });
      const s = d.querySelector('.search');
      if (s) s.oninput = () => d.querySelectorAll('.flt-pop label').forEach((l) => { l.hidden = !l.textContent.toLowerCase().includes(s.value.toLowerCase()); });
    });
    box.querySelectorAll('[data-text]').forEach((i) => i.oninput = () => { filters[i.dataset.text] = { text: i.value }; refreshAll(); });
    const c = box.querySelector('#clear');
    if (c) c.onclick = () => { for (const k of Object.keys(filters)) delete filters[k]; refreshAll(); drawFilters(); };
  };

  const closePops = (e) => {
    if (!box?.isConnected) { document.removeEventListener('click', closePops); document.removeEventListener('keydown', closePops); return; }
    if (e.type === 'keydown' ? e.key !== 'Escape' : box.contains(e.target)) return;
    box.querySelectorAll('details[open]').forEach((d) => { d.open = false; });
  };
  document.addEventListener('click', closePops); document.addEventListener('keydown', closePops);

  // ---- cards
  const fmt = state.fmt;
  const tableOf = (card) => aggregate(payloads[card.id], card, filters);
  const draw = (card) => {
    const el = document.querySelector(`.body[data-card="${CSS.escape(card.id)}"]`);
    const table = tableOf(card);
    last[card.id] = table;
    const view = tableMode.has(card.id) ? { ...card, viz: 'table' } : card;
    render(el, view, table, { T: readTheme(), fmt });
  };
  const refreshAll = () => spec.cards.forEach(draw);
  state.view = { refresh: refreshAll };
  drawFilters();
  // desenha depois do layout para o Plotly medir a largura certa
  requestAnimationFrame(() => refreshAll());

  // ---- ações dos cards
  document.getElementById('grid').onclick = (e) => {
    const btn = e.target.closest('button[data-a]');
    if (!btn) return;
    const cardEl = btn.closest('.card');
    const card = spec.cards.find((c) => `card-${c.id}` === cardEl.id);
    const a = btn.dataset.a;
    if (a === 'table') {
      tableMode.has(card.id) ? tableMode.delete(card.id) : tableMode.add(card.id);
      btn.setAttribute('aria-pressed', String(tableMode.has(card.id)));
      btn.textContent = tableMode.has(card.id) ? 'Ver gráfico' : 'Ver tabela';
      draw(card);
    } else if (a === 'csv') {
      download(new Blob([toCsv(last[card.id], state.cfg)], { type: 'text/csv;charset=utf-8' }), `${slug(spec.title)}-${card.id}.csv`);
    } else if (a === 'png') {
      const gd = cardEl.querySelector('.js-plotly-plot');
      if (gd) Plotly.downloadImage(gd, { format: 'png', width: 1400, height: 800, scale: 2, filename: `${slug(spec.title)}-${card.id}` });
    }
  };

  // ---- baixar
  const menu = document.getElementById('export');
  menu.addEventListener('click', async (e) => {
    const b = e.target.closest('button[data-x]');
    if (!b) return;
    menu.open = false;
    const kind = b.dataset.x;
    try {
      if (kind === 'print') window.print();
      else if (kind === 'csv-all') {
        spec.cards.forEach((c, i) => setTimeout(() => download(new Blob([toCsv(last[c.id], state.cfg)], { type: 'text/csv;charset=utf-8' }), `${slug(spec.title)}-${c.id}.csv`), i * 250));
      } else {
        toast('Preparando o arquivo…');
        const bytes = await decrypt(dash.exportKey, await getBuffer(`x/${dash.id}/dashboard.${kind}.bin`));
        const type = kind === 'xlsx' ? 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' : 'application/pdf';
        download(new Blob([bytes], { type }), `${slug(spec.title)}.${kind}`);
      }
    } catch (ex) { console.error(ex); toast('Não foi possível baixar o arquivo.'); }
  });
  const closeMenu = (e) => { if (!menu.isConnected) document.removeEventListener('click', closeMenu); else if (!menu.contains(e.target)) menu.open = false; };
  document.addEventListener('click', closeMenu);

  // ---- compartilhar
  const share = document.getElementById('share');
  if (share) share.onclick = () => openShare(dash, spec);
}

function openShare(dash, spec) {
  const link = `${location.origin}${location.pathname}#/s/${dash.id}/${toB64u(dash.rawKey)}`;
  const dlg = document.createElement('dialog');
  dlg.innerHTML = `<h2>Compartilhar “${esc(spec.title)}”</h2>
    <p><strong>Quem tiver este link abre o painel, sem usuário e sem senha, somente para ver.</strong> A chave está no próprio link, então envie só para quem você confia.</p>
    <div class="copy-row"><input id="lnk" readonly value="${esc(link)}" aria-label="Link do painel"><button class="btn primary" id="cp" type="button">Copiar</button></div>
    <p class="muted" style="font-size:13px">Para desativar links já enviados, o administrador aumenta <code>share_epoch</code> no arquivo do painel. Para entregar o painel com download, envie o Excel ou o PDF.</p>
    <div class="dlg-actions"><button class="btn" id="close" type="button">Fechar</button></div>`;
  document.body.append(dlg); dlg.showModal();
  const input = dlg.querySelector('#lnk'); input.select();
  dlg.querySelector('#cp').onclick = async () => {
    try { await navigator.clipboard.writeText(link); toast('Link copiado.'); } catch { input.select(); toast('Selecione e copie o link (Ctrl+C).'); }
  };
  dlg.querySelector('#close').onclick = () => dlg.close();
  dlg.addEventListener('close', () => dlg.remove());
}

// ------------------------------------------------------------------ organização (administrador)
const PERM_LABEL = { view: 'Ver', download: 'Baixar', share: 'Compartilhar', create: 'Criar', edit: 'Editar' };
function showOrg(orgId) {
  const org = state.session.me.orgs.find((o) => o.id === orgId && o.admin);
  if (!org) throw new Error('sem acesso');
  const perms = Object.keys(PERM_LABEL);
  const editLink = repoOk() ? ghUrl('edit', `access/${org.id}.yml`) : null;
  setView(`
    <div class="page-head"><div><h1>Pessoas e permissões</h1><p>${esc(org.name)} — você é administrador. O que cada pessoa pode fazer é decidido pelo perfil dela.</p></div>
      ${editLink ? `<a class="btn primary" href="${esc(editLink)}" target="_blank" rel="noopener">Editar permissões no GitHub</a>` : ''}</div>
    <div class="panel"><h2 style="margin-bottom:10px;font-size:16px">Perfis</h2>
      <table class="perm-grid"><thead><tr><th>Perfil</th>${perms.map((p) => `<th>${PERM_LABEL[p]}</th>`).join('')}</tr></thead><tbody>
        ${Object.entries(org.profiles).map(([name, ps]) => `<tr><td><strong>${esc(name)}</strong></td>${perms.map((p) => `<td>${ps.includes(p) ? '<span class="yes" aria-label="sim">✓</span>' : '<span class="no" aria-label="não">–</span>'}</td>`).join('')}</tr>`).join('')}
      </tbody></table></div>
    <div class="two-col">
      <div class="panel"><h2>Pessoas (${org.members.length})</h2>
        <table class="perm-grid"><thead><tr><th>Nome</th><th>Login</th><th>Perfil</th></tr></thead><tbody>
          ${org.members.map((m) => `<tr><td>${esc(m.name)}</td><td>${esc(m.id)}</td><td>${m.profile === 'admin' ? '<span class="chip">administrador</span>' : esc(m.profile)}</td></tr>`).join('')}
        </tbody></table></div>
      <div class="panel"><h2>Como alterar</h2>
        <p>Dar ou tirar acesso é um pull request no repositório. Quem pode aprovar é você, administrador desta organização. Pelo terminal:</p>
        <div class="code">uai user add maria --name "Maria Souza" --github maria-souza
uai org member ${esc(org.id)} maria analyst
uai org profile ${esc(org.id)} auditor --perm view --perm download
uai org remove ${esc(org.id)} joao</div>
        <p class="muted" style="font-size:13px">Quando alguém perde o acesso, a chave do painel é trocada no próximo build: o que a pessoa guardou deixa de abrir os dados novos.</p></div>
    </div>`, { nav: `org-${org.id}` });
}

// ------------------------------------------------------------------ explorar dados
async function showExplore(orgId) {
  const org = state.session.me.orgs.find((o) => o.id === orgId && o.catalog);
  if (!org) throw new Error('sem acesso ao catálogo');
  setView('<div class="spinner">Carregando tabelas…</div>', { nav: 'explore' });
  const catalog = await decryptJson(await keyFor(org.catalog), await getBuffer(`k/${org.catalog}.bin`));
  const canCreate = org.perms.includes('create') && repoOk();

  const template = (db, t) => {
    const name = t.schema && t.schema !== 'main' ? `${t.schema}.${t.table}` : t.table;
    const dims = t.columns.filter((c) => !/^(NUMERIC|FLOAT|DOUBLE|REAL|DECIMAL|MONEY|INT|BIGINT|SMALLINT)/i.test(c.type)).slice(0, 3).map((c) => c.name);
    const meas = t.columns.find((c) => /^(NUMERIC|FLOAT|DOUBLE|REAL|DECIMAL|MONEY)/i.test(c.type));
    return `title: ${t.table}\norganization: ${org.id}\ndatabase: ${db}\n\nfilters: []\n\ncards:\n  - id: resumo\n    title: ${t.table}\n    viz: ${meas ? 'bar' : 'table'}\n    source: {table: ${name}}\n    dimensions: [${dims.slice(0, 1).join(', ')}]\n${meas ? `    measures:\n      - {column: ${meas.name}, agg: sum, name: total, format: currency, label: Total}\n    x: ${dims[0] || 'coluna'}\n    y: [total]\n` : ''}`;
  };
  const newUrl = (db, t) => ghUrl('new', `dashboards/${org.id}`, `?filename=${encodeURIComponent(slug(t.table))}.yml&value=${encodeURIComponent(template(db, t))}`);
  const render_ = (text) => Object.entries(catalog).map(([db, tables]) => {
    const shown = tables.filter((t) => !text || `${t.table} ${t.columns.map((c) => c.name).join(' ')}`.toLowerCase().includes(text));
    return `<section class="org-block"><h2>Banco: ${esc(db)} <span class="chip">${shown.length} tabelas</span></h2>${shown.map((t) => `
      <details class="table-item"><summary><span><strong>${esc(t.table)}</strong> <span class="muted">${t.columns.length} colunas</span></span>
        ${canCreate ? `<a class="btn small" href="${esc(newUrl(db, t))}" target="_blank" rel="noopener">Criar painel com esta tabela</a>` : ''}</summary>
        <div class="cols">${t.columns.map((c) => `<div>${esc(c.name)} <small>${esc(c.type)}</small></div>`).join('')}</div></details>`).join('')}</section>`;
  }).join('');
  setView(`
    <div class="page-head"><div><h1>Explorar dados</h1><p>Tabelas e colunas disponíveis para ${esc(org.name)}. Só os nomes aparecem aqui, nunca os dados.</p></div>
      <div><label class="sr" for="q">Buscar tabela ou coluna</label><input id="q" class="search" type="search" placeholder="Buscar tabela ou coluna" style="min-width:280px"></div></div>
    <div id="list">${render_('')}</div>`, { nav: 'explore' });
  document.getElementById('q').oninput = (e) => { document.getElementById('list').innerHTML = render_(e.target.value.trim().toLowerCase()); };
}

// ------------------------------------------------------------------ rotas
async function route() {
  const p = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  document.title = state.cfg.name;
  try {
    if (p[0] === 's' && p[1] && p[2]) return await showShared(p[1], p[2]);
    if (!state.session) { state.next = location.hash; return showLogin(); }
    if (p[0] === 'd' && p[1]) return await showDashboard(p[1]);
    if (p[0] === 'org' && p[1]) return showOrg(p[1]);
    if (p[0] === 'explore' && p[1]) return await showExplore(p[1]);
    return showHome();
  } catch (err) { failure(err); }
}

async function boot() {
  try {
    state.cfg = await (await fetch('config.json', { cache: 'no-cache' })).json();
  } catch {
    app.innerHTML = '<p class="empty">Não encontrei config.json. Rode <code>uai build</code> e abra a pasta <code>site/</code> por um servidor (<code>uai serve</code>).</p>';
    return;
  }
  state.fmt = makeFormatter(state.cfg);
  applyTheme(store.get('uai-theme'));
  addEventListener('hashchange', route);
  route();
}
boot();
