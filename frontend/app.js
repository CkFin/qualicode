/* QualiCode - Frontend
 * IMPORTANTE: ocultar pestañas/botones aquí es solo comodidad visual.
 * Toda la autorización real ocurre en el servidor (api/security/permissions.py).
 * Todo texto de datos se inserta con textContent (nunca innerHTML) para evitar XSS.
 */
'use strict';

const state = { me: null, tab: null, timer: null, result: null };

const TABS = [
    { id: 'mine', label: 'Mis trabajos', perm: 'jobs:create', load: loadMine },
    { id: 'review', label: 'Revisión QA', perm: 'jobs:read_all', load: loadReview },
    { id: 'users', label: 'Usuarios y roles', perm: 'users:manage', load: loadUsers },
    { id: 'audit', label: 'Auditoría', perm: 'audit:read', load: loadAudit },
    { id: 'system', label: 'Sistema', perm: 'system:status', load: loadSystem },
];

const STATUS_LABEL = { pendiente: 'Pendiente', en_ejecucion: 'En ejecución', completado: 'Completado', fallido: 'Fallido' };

// ---------------------------------------------------------------- utilidades
const $ = (id) => document.getElementById(id);

function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
        if (k === 'class') node.className = v;
        else if (k === 'on') Object.entries(v).forEach(([evt, fn]) => node.addEventListener(evt, fn));
        else if (k === 'title') node.title = v;
        else node.setAttribute(k, v);
    }
    for (const c of children.flat()) {
        if (c === null || c === undefined || c === false) continue;
        node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return node;
}

function fmtDate(v) { return v ? new Date(v).toLocaleString('es-CO') : '—'; }
function fmtBytes(n) {
    if (n === null || n === undefined) return '—';
    const u = ['B', 'KiB', 'MiB', 'GiB']; let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}
function badge(text, cls) { return el('span', { class: `badge ${cls}` }, text); }
function can(perm) { return state.me && state.me.permissions.includes(perm); }

function toast(msg, kind = 'ok') {
    const t = $('toast');
    t.textContent = msg;
    t.className = `toast ${kind}`;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => t.classList.add('hidden'), 5000);
}

async function api(path, opts = {}) {
    const headers = { ...(opts.headers || {}) };
    if (opts.json !== undefined) {
        headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(opts.json);
    }
    const res = await fetch(path, { credentials: 'same-origin', ...opts, headers });
    const ct = res.headers.get('content-type') || '';
    const data = ct.includes('application/json') ? await res.json() : await res.text();
    if (!res.ok) {
        if (res.status === 401 && state.me && !path.endsWith('/login')) {
            showLogin('Tu sesión expiró o fue revocada. Ingresa de nuevo.');
        }
        let detail = data && data.detail !== undefined ? data.detail : res.statusText;
        if (typeof detail !== 'string') detail = JSON.stringify(detail);
        const err = new Error(`${res.status} · ${detail}`);
        err.status = res.status;
        throw err;
    }
    return data;
}

function table(target, headers, rows, emptyMsg = 'Sin registros') {
    const t = $(target);
    t.replaceChildren(el('thead', {}, el('tr', {}, headers.map((h) => el('th', {}, h)))));
    const body = el('tbody');
    if (!rows.length) body.append(el('tr', {}, el('td', { colspan: headers.length, class: 'muted' }, emptyMsg)));
    rows.forEach((cells) => body.append(el('tr', {}, cells.map((c) => (c instanceof Node && c.tagName === 'TD') ? c : el('td', {}, c)))));
    t.append(body);
}

// ------------------------------------------------------------------- sesión
function showLogin(msg = '') {
    state.me = null;
    clearInterval(state.timer);
    $('view-app').classList.add('hidden');
    $('session-box').classList.add('hidden');
    $('view-login').classList.remove('hidden');
    $('login-error').textContent = msg;
}

function showApp() {
    $('view-login').classList.add('hidden');
    $('view-app').classList.remove('hidden');
    $('session-box').classList.remove('hidden');
    $('session-user').textContent = state.me.username;
    $('session-role').textContent = state.me.role_label;

    const tabs = TABS.filter((t) => can(t.perm));
    $('tabs').replaceChildren(...tabs.map((t) =>
        el('button', { 'data-tab': t.id, on: { click: () => selectTab(t.id) } }, t.label)));
    selectTab(tabs.length ? tabs[0].id : null);

    clearInterval(state.timer);
    state.timer = setInterval(() => refresh(true), 4000);
}

function selectTab(id) {
    state.tab = id;
    document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === id));
    document.querySelectorAll('.tab-panel').forEach((p) => p.classList.toggle('hidden', p.dataset.tab !== id));
    refresh(false);
}

async function refresh(silent) {
    const tab = TABS.find((t) => t.id === state.tab);
    if (!tab || !state.me) return;
    try { await tab.load(); } catch (e) { if (!silent) toast(e.message, 'err'); }
}

$('login-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    $('login-error').textContent = '';
    try {
        state.me = await api('/api/auth/login', { method: 'POST', json: { username: $('login-user').value, password: $('login-pass').value } });
        $('login-pass').value = '';
        showApp();
    } catch (e) {
        $('login-error').textContent = e.message;
    }
});

$('btn-logout').addEventListener('click', async () => {
    try { await api('/api/auth/logout', { method: 'POST' }); } catch (_) { /* ya expirada */ }
    showLogin('Sesión cerrada.');
});

// ------------------------------------------------------------- mis trabajos
function jobActions(job, { review = false } = {}) {
    const isOwner = job.owner_id === state.me.id;
    const actions = [];
    if (job.status === 'completado') {
        actions.push(el('button', { class: 'btn-secondary btn-sm', on: { click: () => viewResult(job) } }, 'Ver resultado'));
    }
    if (review && can('jobs:release') && job.status === 'completado' && !job.released) {
        actions.push(el('button', { class: 'btn-primary btn-sm', on: { click: () => releaseJob(job) } }, 'Liberar'));
    }
    if (review && can('jobs:retry') && job.status === 'fallido') {
        actions.push(el('button', { class: 'btn-warning btn-sm', on: { click: () => jobAction(job, 'retry', 'Trabajo reencolado') } }, 'Reintentar'));
    }
    if (review && can('audit:read')) {
        actions.push(el('button', { class: 'btn-secondary btn-sm', on: { click: () => traceJob(job) } }, 'Trazabilidad'));
    }
    if (job.status !== 'en_ejecucion' && ((isOwner && can('jobs:delete_own')) || can('jobs:delete_any'))) {
        actions.push(el('button', { class: 'btn-danger btn-sm', on: { click: () => deleteJob(job) } }, 'Eliminar'));
    }
    actions.push(el('button', { class: 'btn-secondary btn-sm', title: 'Copiar ID', on: { click: () => copyId(job.id) } }, 'ID'));
    return el('td', {}, actions);
}

function jobRow(job, opts = {}) {
    const status = el('td', {}, badge(STATUS_LABEL[job.status] || job.status, `st-${job.status}`),
        job.error ? el('div', { class: 'muted', title: job.error }, job.error.slice(0, 80)) : null);
    const released = job.status !== 'completado' ? '—'
        : badge(job.released ? `Liberado (${job.released_by})` : 'Pendiente de liberación', job.released ? 'rel-si' : 'rel-no');
    const cells = [job.original_name, job.file_type.toUpperCase(), fmtBytes(job.size_bytes), status, released,
        fmtDate(job.created_at), jobActions(job, opts)];
    if (opts.review) cells.splice(0, 0, job.owner);
    return cells;
}

async function loadMine() {
    const jobs = await api('/api/jobs?scope=mine');
    table('tbl-mine', ['Archivo', 'Tipo', 'Tamaño', 'Estado', 'Liberación', 'Creado', 'Acciones'], jobs.map((j) => jobRow(j)),
        'Aún no has cargado archivos');
}

$('upload-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const file = $('upload-file').files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    try {
        const job = await api('/api/jobs', { method: 'POST', body: fd });
        toast(`Archivo encolado. ID: ${job.id}`);
        $('upload-file').value = '';
        loadMine();
    } catch (e) { toast(e.message, 'err'); }
});

$('lookup-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const id = $('lookup-id').value.trim();
    try {
        const job = await api(`/api/jobs/${encodeURIComponent(id)}`);
        $('lookup-out').textContent = JSON.stringify(job, null, 2);
    } catch (e) { $('lookup-out').textContent = `DENEGADO / ERROR\n${e.message}`; }
});

$('lookup-download').addEventListener('click', async () => {
    const id = $('lookup-id').value.trim();
    if (!id) return;
    try {
        const data = await api(`/api/jobs/${encodeURIComponent(id)}/result`);
        $('lookup-out').textContent = JSON.stringify(data, null, 2);
    } catch (e) { $('lookup-out').textContent = `DENEGADO / ERROR\n${e.message}`; }
});

async function copyId(id) {
    try { await navigator.clipboard.writeText(id); toast(`ID copiado: ${id}`); }
    catch (_) { toast(id); }
}

async function jobAction(job, action, okMsg) {
    try { await api(`/api/jobs/${job.id}/${action}`, { method: 'POST' }); toast(okMsg); refresh(false); }
    catch (e) { toast(e.message, 'err'); }
}

function releaseJob(job) { return jobAction(job, 'release', `Resultado liberado a ${job.owner}`); }

async function deleteJob(job) {
    if (!confirm(`¿Eliminar el trabajo "${job.original_name}"?`)) return;
    try { await api(`/api/jobs/${job.id}`, { method: 'DELETE' }); toast('Trabajo eliminado'); refresh(false); }
    catch (e) { toast(e.message, 'err'); }
}

// ---------------------------------------------------------- visor resultado
async function viewResult(job) {
    try {
        const data = await api(`/api/jobs/${job.id}/result`);
        state.result = { job, data };
        renderResult(job, data);
    } catch (e) { toast(e.message, 'err'); }
}

const ESTADO = { optimo: ['Óptimo', 'sem-ok'], atencion: ['Atención', 'sem-warn'], critico: ['Crítico', 'sem-bad'] };
const NIVEL = { optimo: 'sem-ok', bajo: 'sem-warn', alto: 'sem-warn', critico: 'sem-bad' };
const TENDENCIA = { descendente: '↘ en descenso', ascendente: '↗ en aumento', estable: '→ estable', 'sin datos': '—' };
const CATEGORIA = { seguridad: 'Seguridad', errores: 'Errores', rendimiento: 'Rendimiento', pruebas: 'Pruebas', mantenibilidad: 'Mantenibilidad' };
const ROLE_LABEL = { productor: 'Desarrollador', tecnico: 'Revisor QA', admin: 'Administrador', sistema: 'Sistema' };
function roleLabel(r) { return ROLE_LABEL[r] || r || '—'; }

function statCard(label, value, sub = '', cls = '') {
    return el('div', { class: `stat ${cls}` }, el('div', { class: 'label' }, label), el('div', { class: 'value' }, value),
        sub ? el('div', { class: 'sub' }, sub) : null);
}

function reportHeader(job, data, kind) {
    const meta = data._metadatos || {};
    const code = `QC-${String(job.id).slice(0, 8).toUpperCase()}`;
    const release = job.released
        ? badge(`Liberado por ${job.released_by}`, 'rel-si')
        : badge('BORRADOR · pendiente de revisión QA', 'rel-no');
    const p = data.periodo || {};
    return el('div', { class: 'report-head' },
        el('div', {},
            el('div', { class: 'report-lab' }, 'QUALICODE · Aseguramiento de calidad de software'),
            el('h3', {}, kind),
            el('div', { class: 'muted' }, `Informe ${code} · Archivo ${job.original_name}` + (job.owner ? ` · Desarrollador ${job.owner}` : ''))),
        el('div', { class: 'report-meta' }, release,
            el('div', { class: 'muted' }, `Periodo ${p.desde || '?'} a ${p.hasta || '?'}`),
            el('div', { class: 'muted' }, `Procesado ${fmtDate(meta.fecha)} en ${meta.duracion_ms ?? '?'} ms`)));
}

function moduleCard(p) {
    const [label, cls] = ESTADO[p.estado] || [p.estado, ''];
    const i = p.interpretacion;
    const row = (name, unit, x) => el('tr', {},
        el('td', {}, name), el('td', { class: 'num' }, `${x.valor}${unit}`),
        el('td', {}, el('span', { class: `dot ${NIVEL[x.nivel] || ''}` }), x.texto));
    const recs = p.recomendaciones.length
        ? el('ul', { class: 'recs' }, p.recomendaciones.map((r) => el('li', {},
            el('b', {}, r.area), r.dosis !== '—' ? el('span', { class: 'dose' }, r.dosis) : null, el('div', { class: 'muted' }, r.accion))))
        : el('p', { class: 'ok-text' }, 'Sin acciones: mantener las prácticas actuales.');
    return el('div', { class: `plot ${cls}` },
        el('div', { class: 'plot-head' }, el('div', {}, el('b', {}, p.modulo), ` · ${p.lenguaje}`), badge(label, cls)),
        el('table', { class: 'plot-table' }, row('Cobertura', ' %', i.cobertura), row('Complejidad', '', i.complejidad), row('Defectos', ' /KLOC', i.defectos)),
        el('div', { class: 'muted' }, `${p.mediciones} mediciones · cobertura ${TENDENCIA[p.tendencia_cobertura.direccion] || '—'}`
            + ` (${p.tendencia_cobertura.cambio > 0 ? '+' : ''}${p.tendencia_cobertura.cambio}) · σ complejidad ${p.variabilidad_complejidad}`),
        el('div', { class: 'recs-title' }, 'Recomendaciones'), recs);
}

function renderQuality(job, data, body) {
    body.append(reportHeader(job, data, 'Informe de calidad de código'));
    if (!data.resumen) {  // resultados de una version anterior del informe
        body.append(el('p', {}, el('b', {}, data.diagnostico)));
        return;
    }
    const r = data.resumen;
    body.append(el('div', { class: 'stats' },
        statCard('Módulos', r.modulos, `${data.filas} mediciones`),
        statCard('Óptimas', r.optimo, 'sin acciones', 'sem-ok'),
        statCard('Atención', r.atencion, 'requieren manejo', 'sem-warn'),
        statCard('Críticas', r.critico, 'acción inmediata', 'sem-bad')));
    if (data.prioridades.length) {
        body.append(el('div', { class: 'priorities' }, el('b', {}, 'Prioridades de mejora'),
            el('ol', {}, data.prioridades.map((x) => el('li', {}, x)))));
    }
    body.append(el('div', { class: 'plots' }, data.modulos.map(moduleCard)));
    const s = data.estadisticas;
    body.append(el('p', { class: 'muted' },
        `Repositorio completo · cobertura ${s.cobertura.promedio} % (${s.cobertura.min}–${s.cobertura.max}) · complejidad ${s.complejidad.promedio} · defectos ${s.defectos.promedio} /KLOC. ${data.metodo}`));
    body.append(el('p', { class: 'disclaimer' }, data.advertencia));
}

function logModuleCard(p) {
    const [label, cls] = ESTADO[p.estado] || [p.estado, ''];
    const nivel = (n, grave) => (n === 0 ? 'sem-ok' : (n >= grave ? 'sem-bad' : 'sem-warn'));
    const row = (name, n, texto, grave) => el('tr', {},
        el('td', {}, name), el('td', { class: 'num' }, String(n)),
        el('td', {}, el('span', { class: `dot ${nivel(n, grave)}` }), texto));
    const recs = p.recomendaciones.length
        ? el('ul', { class: 'recs' }, p.recomendaciones.map((r) => el('li', {},
            el('b', {}, r.area), el('span', { class: 'dose' }, r.dosis), el('div', { class: 'muted' }, r.accion))))
        : el('p', { class: 'ok-text' }, 'Sin hallazgos: mantener las prácticas actuales.');
    return el('div', { class: `plot ${cls}` },
        el('div', { class: 'plot-head' }, el('div', {}, el('b', {}, p.modulo), ' · bitácora'), badge(label, cls)),
        el('table', { class: 'plot-table' },
            row('Seguridad', p.seguridad, p.seguridad ? 'Hallazgos de seguridad reportados' : 'Sin hallazgos', 3),
            row('Errores', p.errores, p.errores ? `Problema principal: ${p.problema_principal || 'error'}` : 'Sin errores reportados', 3),
            row('Rendimiento', p.rendimiento, p.rendimiento ? 'Consultas o procesos lentos' : 'Sin reportes', 5)),
        el('div', { class: 'muted' }, `${p.menciones} menciones en la bitácora · builds fallidos ${p.builds_fallidos}`),
        el('div', { class: 'recs-title' }, 'Recomendaciones'), recs);
}

function renderNotes(job, data, body) {
    body.append(reportHeader(job, data, 'Resumen de bitácora de revisión de código'));
    const ev = data.eventos_por_categoria || {};
    const t = data.builds && data.builds.duracion_min;
    const incid = (ev.seguridad || 0) + (ev.errores || 0);
    body.append(el('div', { class: 'stats' },
        statCard('Notas', data.notas ?? data.lineas_no_vacias, `${data.palabras} palabras`),
        statCard('Incidencias', incid, 'seguridad y errores', incid ? 'sem-warn' : 'sem-ok'),
        statCard('Builds fallidos', data.builds ? data.builds.fallidos : '—', '', data.builds && data.builds.fallidos ? 'sem-warn' : ''),
        statCard('Duración media del build', t ? `${t.promedio} min` : '—', t ? `${t.min} – ${t.max} min` : '')));
    if (data.alertas && data.alertas.length) {
        body.append(el('div', { class: 'priorities' }, el('b', {}, 'Alertas'), el('ul', {}, data.alertas.map((a) => el('li', {}, a)))));
    }
    if (data.resumen) {
        const r = data.resumen;
        body.append(el('div', { class: 'stats' },
            statCard('Módulos', r.modulos, `${Object.values(ev).reduce((a, b) => a + b, 0)} eventos`),
            statCard('Óptimos', r.optimo, 'sin hallazgos', 'sem-ok'),
            statCard('Atención', r.atencion, 'requieren revisión', 'sem-warn'),
            statCard('Críticos', r.critico, 'acción inmediata', 'sem-bad')));
    }
    if (data.modulos && data.modulos.length && data.modulos[0].estado) {
        body.append(el('div', { class: 'plots' }, data.modulos.map(logModuleCard)));
    }
    const resumenCat = Object.entries(ev).map(([k, v]) => `${CATEGORIA[k] || k}: ${v}`).join(' · ');
    if (resumenCat) body.append(el('p', { class: 'muted' }, `Eventos por categoría · ${resumenCat}`));
    if (data.incidencias && data.incidencias.length) {
        const ti = el('table');
        ti.append(el('tr', {}, ['Fecha', 'Módulo', 'Problema', 'Nota'].map((h) => el('th', {}, h))));
        data.incidencias.slice(-5).reverse().forEach((x) => ti.append(el('tr', {}, el('td', {}, x.fecha || '—'),
            el('td', {}, x.modulos.join(', ') || '—'), el('td', {}, x.problema), el('td', { class: 'muted' }, x.nota))));
        body.append(el('div', { class: 'recs-title' }, 'Últimas incidencias registradas'), el('div', { class: 'table-wrap' }, ti));
    }
    if (data.advertencia) body.append(el('p', { class: 'disclaimer' }, data.advertencia));
}

function renderResult(job, data) {
    $('result-title').textContent = `Resultado · ${job.original_name}`;
    const body = $('result-body');
    body.replaceChildren();
    if (data.tipo === 'calidad_codigo') renderQuality(job, data, body);
    else if (data.tipo === 'bitacora_revision') renderNotes(job, data, body);
    const meta = el('details', { class: 'meta' }, el('summary', {}, 'Metadatos de trazabilidad (SHA-256, worker, duración)'),
        el('pre', { class: 'out' }, JSON.stringify(data._metadatos || {}, null, 2)));
    body.append(meta);
    $('result-viewer').classList.remove('hidden');
    $('result-viewer').scrollIntoView({ behavior: 'smooth' });
}

$('result-close').addEventListener('click', () => $('result-viewer').classList.add('hidden'));
$('result-print').addEventListener('click', () => window.print());
$('result-download').addEventListener('click', () => {
    if (!state.result) return;
    const blob = new Blob([JSON.stringify(state.result.data, null, 2)], { type: 'application/json' });
    const a = el('a', { href: URL.createObjectURL(blob), download: `resultado_${state.result.job.original_name}.json` });
    document.body.append(a); a.click(); a.remove();
});

// --------------------------------------------------------- revisión QA
async function loadReview() {
    let jobs = await api('/api/jobs?scope=all');
    const f = $('review-filter').value;
    if (f === 'sin_liberar') jobs = jobs.filter((j) => j.status === 'completado' && !j.released);
    else if (f) jobs = jobs.filter((j) => j.status === f);
    table('tbl-review', ['Dueño', 'Archivo', 'Tipo', 'Tamaño', 'Estado', 'Liberación', 'Creado', 'Acciones'],
        jobs.map((j) => jobRow(j, { review: true })));
}
$('review-filter').addEventListener('change', () => refresh(false));

async function traceJob(job) {
    selectTab('audit');
    $('af-user').value = ''; $('af-action').value = ''; $('af-outcome').value = '';
    $('af-resource').value = `job:${job.id}`;
    await loadAuditTable();
    toast('Mostrando la cadena de custodia del trabajo');
}

// ------------------------------------------------------------------ usuarios
async function loadUsers() {
    const [users, roles] = await Promise.all([api('/api/admin/users'), api('/api/admin/roles')]);
    table('tbl-users', ['ID', 'Usuario', 'Rol', 'Estado', 'Trabajos', 'Último login', 'Acciones'], users.map((u) => {
        const roleSel = el('select', { on: { change: (e) => updateUser(u, { role: e.target.value }) } },
            Object.entries(roles.roles).map(([k, label]) => {
                const o = el('option', { value: k }, label); if (k === u.role) o.selected = true; return o;
            }));
        const self = u.id === state.me.id;
        if (self) roleSel.disabled = true;
        return [u.id, u.username, el('td', {}, roleSel), badge(u.active ? 'Activo' : 'Inactivo', u.active ? 'oc-OK' : 'oc-DENEGADO'),
            u.jobs, fmtDate(u.last_login), el('td', {},
                el('button', { class: 'btn-secondary btn-sm', on: { click: () => updateUser(u, { active: !u.active }) }, ...(self ? { disabled: '' } : {}) }, u.active ? 'Desactivar' : 'Activar'),
                el('button', { class: 'btn-secondary btn-sm', on: { click: () => resetPassword(u) } }, 'Restablecer clave'))];
    }));
    const perms = Object.keys(roles.permissions);
    table('tbl-matrix', ['Permiso', ...Object.keys(roles.matrix).map(roleLabel)], perms.map((p) =>
        [el('td', { title: roles.permissions[p] }, el('span', { class: 'mono' }, p)),
        ...Object.keys(roles.matrix).map((r) => roles.matrix[r].includes(p) ? '✔' : '—')]));
}

async function updateUser(u, changes) {
    try { await api(`/api/admin/users/${u.id}`, { method: 'PATCH', json: changes }); toast(`Usuario ${u.username} actualizado`); }
    catch (e) { toast(e.message, 'err'); }
    loadUsers();
}

function resetPassword(u) {
    const pass = prompt(`Nueva contraseña para ${u.username} (mín. 10, letras y números):`);
    if (pass) updateUser(u, { password: pass });
}

$('user-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try {
        await api('/api/admin/users', { method: 'POST', json: { username: $('nu-name').value.trim(), password: $('nu-pass').value, role: $('nu-role').value } });
        toast('Usuario creado');
        ev.target.reset();
        loadUsers();
    } catch (e) { toast(e.message, 'err'); }
});

// ----------------------------------------------------------------- auditoría
async function loadAudit() {
    const report = await api('/api/admin/audit/report?hours=24');
    table('tbl-report', ['Usuario', 'Rol', 'Logins', 'Fallidos', 'Cargas', 'Descargas', 'Liberaciones', 'Denegados', 'Última actividad'],
        report.per_user.map((r) => [r.username, roleLabel(r.role), r.logins, r.logins_fallidos, r.cargas, r.descargas, r.liberaciones,
            r.denegados ? badge(r.denegados, 'oc-DENEGADO') : '0', fmtDate(r.ultima_actividad)]));
    await loadAuditTable();
}

async function loadAuditTable() {
    const q = new URLSearchParams({ limit: '200' });
    if ($('af-user').value) q.set('username', $('af-user').value);
    if ($('af-action').value) q.set('action', $('af-action').value.toUpperCase());
    if ($('af-outcome').value) q.set('outcome', $('af-outcome').value);
    if ($('af-resource').value) q.set('resource', $('af-resource').value);
    const rows = await api(`/api/admin/audit?${q}`);
    table('tbl-audit', ['Fecha', 'Usuario', 'Rol', 'Acción', 'Recurso', 'Resultado', 'IP', 'Detalle'], rows.map((r) =>
        [fmtDate(r.ts), r.username || '—', roleLabel(r.role), el('span', { class: 'mono' }, r.action),
        el('span', { class: 'mono' }, r.resource || '—'), badge(r.outcome, `oc-${r.outcome}`), r.ip || '—', r.detail || '']));
}

$('audit-form').addEventListener('submit', (ev) => { ev.preventDefault(); loadAuditTable().catch((e) => toast(e.message, 'err')); });

// ------------------------------------------------------------------- sistema
async function loadSystem() {
    const s = await api('/api/system/status');
    $('env-label').textContent = `entorno: ${s.environment}`;
    const alive = s.workers.filter((w) => w.alive).length;
    const cards = [
        ['Pendientes', s.queue.pendiente, 'en cola'],
        ['En ejecución', s.queue.en_ejecucion, 'procesándose'],
        ['Completados', s.queue.completado, `fallidos: ${s.queue.fallido}`],
        ['Trabajadores vivos', alive, `${s.workers.length} registrados`],
        ['Tiempo medio', s.last_hour.avg_proc_s ?? '—', `seg. proceso · espera ${s.last_hour.avg_wait_s ?? '—'} s`],
        ['Disco libre', fmtBytes(s.storage.disk_free), `de ${fmtBytes(s.storage.disk_total)}`],
        ['Datos usuarios', fmtBytes(s.storage.uploads + s.storage.results), `orig ${fmtBytes(s.storage.uploads)} · res ${fmtBytes(s.storage.results)}`],
        ['Usuarios activos', s.users, ''],
    ];
    $('system-cards').replaceChildren(...cards.map(([l, v, sub]) =>
        el('div', { class: 'stat' }, el('div', { class: 'label' }, l), el('div', { class: 'value' }, v), el('div', { class: 'sub' }, sub))));
    table('tbl-workers', ['Worker (hostname)', 'PID', 'Estado', 'Hechos', 'Fallidos', 'Último latido'], s.workers.map((w) =>
        [el('span', { class: 'mono' }, w.worker_id), w.pid, badge(w.alive ? 'Vivo' : 'Sin latido', w.alive ? 'oc-OK' : 'oc-DENEGADO'),
        w.jobs_done, w.jobs_failed, fmtDate(w.last_seen)]), 'Ningún trabajador ha reportado');
    const a = s.api;
    $('sys-api').textContent =
        `hostname:        ${a.hostname}\npid / uid:       ${a.pid} / ${a.uid}  (uid != 0 -> no es root)\n` +
        `load average:    ${a.load_avg.map((x) => x.toFixed(2)).join(' ')}\n` +
        `memoria usada:   ${fmtBytes(a.cgroup_memory_current)}\nlímite memoria:  ${a.cgroup_memory_max === 'max' ? 'sin límite' : fmtBytes(Number(a.cgroup_memory_max))}\n` +
        `límite CPU:      ${a.cgroup_cpu_max}  (cuota/periodo en µs)`;
}

// ------------------------------------------------------------------- inicio
(async function init() {
    try {
        state.me = await api('/api/auth/me');
        showApp();
    } catch (_) {
        showLogin();
    }
})();
