/* Panel de "planos": pestañas de obras, ficha, látigo, cuadrilla y bitácora.
   Conecta la caseta con el servidor (SSE + POST con token) o con la demostración. */
'use strict';
(function () {
  const $ = (s, el) => (el || document).querySelector(s);
  const recordar = (k, v) => { try { localStorage.setItem('latigo.' + k, v); } catch (e) { /* sin almacenamiento */ } };
  const recuerdo = (k) => { try { return localStorage.getItem('latigo.' + k); } catch (e) { return null; } };
  const olvidar = (k) => { try { localStorage.removeItem('latigo.' + k); } catch (e) { /* sin almacenamiento */ } };

  // La llave de la oficina (su token) nunca viaja en la URL: la ventana se abre con un boleto
  // de un solo uso (#p=…) que aquí se canjea por la llave. La llave se guarda en este navegador
  // y el boleto se quita de la barra de direcciones.
  const esLlave = (t) => /^[0-9a-f]{32,}$/.test(t || '');
  async function obtenerLlave() {
    const h = new URLSearchParams(location.hash.slice(1));
    const boleto = h.get('p') || '';
    const directa = h.get('t') || '';
    if (h.has('p') || h.has('t')) {
      try { history.replaceState(null, '', location.pathname + location.search); } catch (e) { /* sin historial */ }
    }
    if (esLlave(directa)) { recordar('llave', directa); return directa; }
    if (boleto) {
      try {
        const r = await fetch('api/canjear', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ boleto }),
        });
        const d = r.ok ? await r.json() : {};
        if (esLlave(d.token)) { recordar('llave', d.token); return d.token; }
      } catch (e) { /* la oficina no respondió: se usa la guardada, si hay */ }
    }
    const guardada = recuerdo('llave') || '';
    return esLlave(guardada) ? guardada : '';
  }
  const DEMO = new URLSearchParams(location.search).has('demo');
  let TOKEN = '';
  let sinLlave = false;
  const compacto = new Intl.NumberFormat('es-MX', { notation: 'compact', maximumFractionDigits: 1 });

  let snap = null;
  let seleccion = recuerdo('sesion');
  let abierto = null;
  let pip = null;
  let ultimaBitacora = '';

  const Motor = window.OficinaIso || window.Oficina;
  const oficina = new Motor($('.marco'), { onLatigazo: latigazo, onSeleccion: abrirAgente });
  new ResizeObserver(() => oficina.ajustar()).observe($('.lienzo'));

  // ------------------------------------------------------------ conexión

  let fuente = null;

  function conectar() {
    // Primero se prueba la llave: EventSource no deja ver si el servidor contestó 403.
    fetch('api/estado', { headers: { 'X-Latigo-Token': TOKEN }, cache: 'no-store' }).then((r) => {
      if (r.status === 403) { perderLlave(); return; }
      abrirEventos();
    }).catch(() => { $('.conexion').hidden = false; setTimeout(conectar, 3000); });
  }

  function abrirEventos() {
    if (fuente) fuente.close();
    const es = new EventSource('api/eventos?t=' + encodeURIComponent(TOKEN));
    fuente = es;
    let espera = null;
    let fallas = 0;
    es.addEventListener('estado', (e) => { clearTimeout(espera); fallas = 0; $('.conexion').hidden = true; aplicar(JSON.parse(e.data)); });
    es.addEventListener('efecto', (e) => efecto(JSON.parse(e.data)));
    es.onopen = () => { clearTimeout(espera); $('.conexion').hidden = true; };
    es.onerror = () => {
      clearTimeout(espera);
      espera = setTimeout(() => { $('.conexion').hidden = false; }, 2500);
      // EventSource se rinde solo si el servidor contesta con error (p. ej. otra llave): se vuelve a probar.
      if (es.readyState === EventSource.CLOSED) { fallas += 1; setTimeout(conectar, Math.min(15000, 1500 * fallas)); }
    };
  }

  function perderLlave() {
    olvidar('llave');
    TOKEN = '';
    sinLlave = true;
    if (fuente) { fuente.close(); fuente = null; }
    $('.conexion').hidden = true;
    aplicar({ sesiones: [], config: {} });
  }

  function api(ruta, datos) {
    if (DEMO) return Demo.api(ruta, datos);
    if (sinLlave) { avisar('Abre la caseta con «latigo abrir» para conectarla'); return Promise.reject(new Error('sin llave')); }
    return fetch(ruta, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Latigo-Token': TOKEN },
      body: JSON.stringify(datos || {}),
    }).then((r) => {
      if (r.status === 403) { perderLlave(); throw new Error('sin llave'); }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).catch((e) => {
      if (e.message !== 'sin llave') avisar('La caseta no responde');
      throw e;
    });
  }

  // Para acciones que no esperan respuesta: el aviso ya lo dio api().
  const enviar = (ruta, datos) => api(ruta, datos).catch(() => null);

  // ------------------------------------------------------------ utilidades de formato

  const ahora = () => Date.now() / 1000;

  function duracion(seg) {
    seg = Math.max(0, Math.floor(seg));
    if (seg < 60) return seg + ' s';
    if (seg < 600) return Math.floor(seg / 60) + ' min ' + String(seg % 60).padStart(2, '0') + ' s';
    if (seg < 3600) return Math.floor(seg / 60) + ' min';
    return Math.floor(seg / 3600) + ' h ' + String(Math.floor((seg % 3600) / 60)).padStart(2, '0') + ' min';
  }

  function hora(t) {
    return new Date(t * 1000).toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  }

  function nombreModelo(m) {
    if (!m) return '—';
    const r = /claude-(opus|sonnet|haiku|fable|mythos)-(\d+)(?:-(\d{1,2})(?!\d))?/i.exec(m);
    if (r) return r[1][0].toUpperCase() + r[1].slice(1) + ' ' + r[2] + (r[3] ? '.' + r[3] : '');
    return m.replace(/^claude-/, '');
  }

  const MODOS = { default: 'Manual', acceptEdits: 'Aceptar ediciones', auto: 'Automático', plan: 'Plan',
    bypassPermissions: 'Sin permisos', dontAsk: 'No preguntar' };

  const TIPOS = { peon: 'Peón', 'peon-libre': 'Peón sin worktree', Explore: 'Explora el código', Plan: 'Planea',
    'general-purpose': 'Ayudante general', fork: 'Copia del capataz', principal: 'Sesión principal' };

  function el(tag, clase, texto) {
    const e = document.createElement(tag);
    if (clase) e.className = clase;
    if (texto !== undefined && texto !== null) e.textContent = texto;
    return e;
  }

  const atencion = (a) => a.cat === 'permiso' || a.cat === 'pregunta' || a.cat === 'plan';

  // ------------------------------------------------------------ estado

  function sesionActual() {
    if (!snap || !snap.sesiones.length) return null;
    return snap.sesiones.find((s) => s.id === seleccion) || snap.sesiones.find((s) => s.estado === 'activa') || snap.sesiones[0];
  }

  function aplicar(nuevo) {
    snap = nuevo;
    const ses = sesionActual();
    pintarPestanas(ses);
    pintarFicha(ses);
    pintarLatigo(ses);
    pintarCuadrilla(ses);
    pintarBitacora(ses);
    pintarAjustes();
    oficina.actualizar(ses);
    const bocina = $('#btn-sonido');
    const mudo = !!(snap.config && snap.config.silencio);
    bocina.setAttribute('aria-pressed', mudo ? 'false' : 'true');
    bocina.textContent = mudo ? '🔇' : '🔊';
  }

  function efecto(ef) {
    oficina.efecto(ef);
    const ses = sesionActual();
    if (!ses || ef.sesion !== ses.id) return;
    if (ef.tipo === 'latigazo' && ef.objetivo === 'capataz') avisar(ef.texto || '¡Chas!');
    else if (ef.tipo === 'latigazo_entregado') avisar('El capataz recibió el latigazo');
    else if (ef.tipo === 'latigazo_perdido') avisar('El latigazo no llegó a tiempo');
  }

  let timerAviso = null;
  function avisar(texto) {
    const a = $('.aviso');
    a.textContent = texto;
    a.classList.add('visible');
    clearTimeout(timerAviso);
    timerAviso = setTimeout(() => a.classList.remove('visible'), 2600);
  }

  // ------------------------------------------------------------ pestañas

  function pintarPestanas(actual) {
    const nav = $('.obras');
    const existentes = new Map([...nav.children].map((b) => [b.dataset.id, b]));
    for (const s of snap.sesiones) {
      let b = existentes.get(s.id);
      if (!b) {
        b = el('button', 'pestana');
        b.type = 'button';
        b.setAttribute('role', 'tab');
        b.dataset.id = s.id;
        b.append(el('span', 'luz'), el('span', 'nombre'), el('span', 'sub'));
        b.addEventListener('click', () => { seleccion = s.id; recordar('sesion', s.id); abierto = null; aplicar(snap); });
      }
      existentes.delete(s.id);
      const cap = s.agentes.find((a) => a.rol === 'capataz') || {};
      b.className = 'pestana cat-' + (cap.cat || 'esperando') + (s.agentes.some(atencion) ? ' atencion' : '') + (s.estado !== 'activa' ? ' terminada' : '');
      b.setAttribute('aria-selected', actual && actual.id === s.id ? 'true' : 'false');
      $('.nombre', b).textContent = s.proyecto;
      $('.sub', b).textContent = s.demo ? 'Demostración' : (s.titulo || '');
      b.title = (s.titulo ? s.titulo + '\n' : '') + (s.cwd || '');
      nav.appendChild(b);
    }
    for (const b of existentes.values()) b.remove();
  }

  // ------------------------------------------------------------ ficha de la obra

  function pintarFicha(ses) {
    const f = $('.ficha');
    f.textContent = '';
    if (!ses) {
      f.className = 'ficha vacio';
      if (sinLlave) {
        f.append(el('h2', null, 'Esta caseta no está conectada'));
        f.append(el('p', null, 'Ábrela desde la terminal con «latigo abrir» (o deja que Claude Code la abra al arrancar): así trae la llave de tu oficina.'));
      } else {
        f.append(el('h2', null, 'Todavía no hay obras'));
        f.append(el('p', null, 'Abre Claude Code en cualquier proyecto y aquí aparece la cuadrilla trabajando.'));
        f.append(el('p', null, 'Si Claude Code ya estaba abierto antes de instalar el látigo, ciérralo y vuelve a abrirlo.'));
      }
      if (!DEMO) {
        const b = el('button', 'boton-texto', 'Ver la demostración');
        b.type = 'button';
        b.addEventListener('click', () => { location.search = '?demo'; });
        f.append(b);
      }
      return;
    }
    f.className = 'ficha';
    f.append(el('h1', 'obra-nombre', ses.proyecto));
    f.append(el('p', 'obra-titulo', ses.demo ? 'Demostración: ' + (ses.titulo || '') : (ses.titulo || ses.cwd || '')));
    const dl = el('dl', 'obra-datos');
    const fila = (dt, dd, clase, attrs) => {
      const d = el('dd', clase, dd);
      if (attrs) for (const k in attrs) d.dataset[k] = attrs[k];
      dl.append(el('dt', null, dt), d);
    };
    if (ses.encargo) fila('Encargo', '«' + ses.encargo + '»', 'encargo');
    fila('Modelo', nombreModelo(ses.modelo));
    if (ses.modo) fila('Permisos', MODOS[ses.modo] || ses.modo);
    const cap = ses.agentes.find((a) => a.rol === 'capataz') || {};
    const trabajando = cap.cat && !['esperando', 'durmiendo'].includes(cap.cat) && ses.turno_inicio;
    if (trabajando) fila('Turno', duracion(ahora() - ses.turno_inicio), null, { desde: ses.turno_inicio });
    fila('Escrito', compacto.format(ses.tokens_salida || 0) + ' tokens');
    if (ses.cwd && !ses.demo) fila('Carpeta', ses.cwd);
    if (!ses.con_hooks && !ses.demo) fila('Ojo', 'Esta sesión se ve solo por su transcript: reiníciala para ver todo en vivo.');
    f.append(dl);
  }

  // ------------------------------------------------------------ látigo

  function pintarLatigo(ses) {
    const lat = (ses && ses.latigo) || {};
    const cfg = (snap && snap.config) || {};
    const tope = cfg.tope_peones || 5;
    const enObra = ses ? ses.agentes.filter((a) => a.rol === 'peon' && a.visible && a.cat !== 'terminado' && a.cat !== 'saliendo').length : 0;
    const activos = Math.max(lat.peones_activos || 0, enObra);
    const techo = lat.techo || 0;
    const cascos = $('.cascos');
    cascos.textContent = '';
    for (let i = 0; i < tope; i++) {
      cascos.append(el('span', 'casco ' + (i < activos ? 'trabajando' : i < techo ? 'disponible' : 'fuera')));
    }
    cascos.setAttribute('aria-label', activos + ' peones trabajando, techo de ' + techo + ' de ' + tope);
    const est = $('.latigo-estado');
    est.textContent = '';
    if (lat.nivel) {
      est.append(el('strong', null, 'Latigazo ' + lat.nivel + ' de esta tarea.'), document.createTextNode(' Techo: ' + techo + ' peones.'));
    } else {
      est.append(document.createTextNode(lat.latigazos ? 'Latigazos que solo sonaron: ' + lat.latigazos + '.' : 'Sin latigazos en esta tarea.'));
    }
    $('#btn-latigo').disabled = false;  // sin obra también truena (por el meme)
    const cap = ses ? ses.agentes.find((a) => a.rol === 'capataz') || {} : {};
    const nota = $('.latigo-nota');
    nota.classList.toggle('pendiente', !!lat.pendiente);
    if (!ses) nota.textContent = '';
    else if (lat.pendiente) nota.textContent = 'Latigazo en camino: le llega en cuanto termine la herramienta que está usando.';
    else if (activos > 0) nota.textContent = 'Con peones trabajando, otro latigazo solo suena.';
    else if (cap.cat === 'esperando' || cap.cat === 'durmiendo') nota.textContent = 'El capataz está esperando tus instrucciones: un latigazo solo sonaría.';
    else nota.textContent = 'El capataz decide cuántos peones manda, hasta el techo.';
    refrescarEnfriamiento();
  }

  function refrescarEnfriamiento() {
    const ses = sesionActual();
    const lat = (ses && ses.latigo) || {};
    const total = (snap && snap.config && snap.config.enfriamiento_segundos) || 60;
    const resta = (lat.enfriamiento_hasta || 0) - ahora();
    const caja = $('.enfriamiento');
    caja.hidden = !(resta > 0);
    if (resta > 0) {
      $('.medidor span', caja).style.width = Math.min(100, resta / total * 100) + '%';
      $('.enfriamiento-texto', caja).textContent = 'Calma: ' + Math.ceil(resta) + ' s';
    }
  }

  // ------------------------------------------------------------ cuadrilla

  function filaAgente(a) {
    const li = el('li');
    li.dataset.id = a.id;
    li.tabIndex = 0;
    const retrato = el('canvas', 'retrato');
    retrato.width = window.RetratoIso ? 64 : 16; retrato.height = window.RetratoIso ? 80 : 20;
    const cuerpo = el('div', 'miembro-cuerpo');
    const nombre = el('p', 'miembro-nombre');
    nombre.append(el('strong'), el('span', 'miembro-tarea'));
    const accion = el('p', 'miembro-accion');
    accion.append(el('span', 'icono'), el('span', 'texto'));
    const metaP = el('p', 'miembro-meta');
    metaP.append(el('span', 'tiempo'), el('span', 'contexto'), el('span', 'salida'), el('span', 'rama'));
    cuerpo.append(nombre, accion, metaP);
    const detalle = el('div', 'miembro-detalle');
    detalle.hidden = true;
    li.append(retrato, cuerpo, detalle);
    const alternar = () => { abierto = abierto === a.id ? null : a.id; aplicar(snap); };
    li.addEventListener('click', alternar);
    li.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); alternar(); } });
    return li;
  }

  function pintarCuadrilla(ses) {
    const ol = $('.lista-cuadrilla');
    const ahoraS = ahora();
    const agentes = ses ? ses.agentes.filter((a) => a.visible || (a.fin && ahoraS - a.fin < 900)) : [];
    const existentes = new Map([...ol.children].map((li) => [li.dataset.id, li]));
    for (const a of agentes) {
      let li = existentes.get(a.id);
      if (!li) li = filaAgente(a);
      existentes.delete(a.id);
      li.className = 'miembro cat-' + a.cat + (atencion(a) ? ' atencion' : '') + (!a.visible ? ' fuera' : '') + (abierto === a.id ? ' abierto' : '');
      li.setAttribute('aria-expanded', abierto === a.id ? 'true' : 'false');
      const claveRetrato = a.id + ':' + (a.cat === 'permiso' || a.cat === 'terminado' ? a.cat : '');
      const canvas = $('.retrato', li);
      if (canvas.dataset.clave !== claveRetrato) { canvas.dataset.clave = claveRetrato; (window.RetratoIso || window.Sprites.retrato)(canvas, a, a.cat); }
      $('.miembro-nombre strong', li).textContent = a.nombre;
      $('.miembro-tarea', li).textContent = a.tarea || TIPOS[a.tipo] || a.tipo || '';
      $('.miembro-accion .icono', li).textContent = a.icono;
      $('.miembro-accion .texto', li).textContent = a.texto;
      $('.miembro-accion', li).title = a.detalle || a.texto;
      const t = $('.tiempo', li);
      t.dataset.desde = a.desde;
      t.textContent = duracion(ahoraS - a.desde) + ' en esto';
      $('.contexto', li).textContent = a.tokens.contexto ? 'contexto ' + compacto.format(a.tokens.contexto) : '';
      $('.salida', li).textContent = a.tokens.salida ? 'escribió ' + compacto.format(a.tokens.salida) : '';
      $('.rama', li).textContent = a.rama ? 'rama ' + a.rama : '';
      const det = $('.miembro-detalle', li);
      det.hidden = abierto !== a.id;
      if (abierto === a.id) pintarDetalle(det, a);
      ol.appendChild(li);
    }
    for (const li of existentes.values()) li.remove();
    if (!agentes.length && ses) {
      ol.textContent = '';
    }
  }

  function pintarDetalle(det, a) {
    det.textContent = '';
    if (a.detalle && a.detalle !== a.texto) det.append(el('p', 'resultado', a.detalle));
    if (a.resultado) det.append(el('p', 'resultado', a.resultado));
    const datos = [];
    if (a.modelo) datos.push('Modelo ' + nombreModelo(a.modelo));
    if (a.herramientas) datos.push(a.herramientas + ' herramientas');
    if (a.errores) datos.push(a.errores + ' fallas');
    if (datos.length) det.append(el('p', null, datos.join(', ')));
    const ol = el('ol', 'historial');
    for (const h of [...(a.historial || [])].reverse()) {
      const li = el('li');
      li.append(el('time', null, hora(h.t)), el('span', null, h.icono), el('span', 'que', h.texto));
      ol.append(li);
    }
    det.append(ol);
  }

  function abrirAgente(id) {
    abierto = id;
    aplicar(snap);
    const li = $('.lista-cuadrilla li[data-id="' + CSS.escape(id) + '"]');
    if (li) li.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  // ------------------------------------------------------------ bitácora

  function pintarBitacora(ses) {
    const ol = $('.lista-bitacora');
    const entradas = ses ? ses.bitacora : [];
    const ult = entradas.length ? entradas[entradas.length - 1] : null;
    const clave = (ses ? ses.id : '') + ':' + entradas.length + ':' + (ult ? ult.t + ult.texto : '');
    if (clave === ultimaBitacora) return;
    ultimaBitacora = clave;
    ol.textContent = '';
    for (const e of [...entradas].reverse()) {
      const li = el('li');
      const que = el('span', 'que');
      que.append(el('span', 'quien rol-' + (e.rol || ''), e.quien || ''), document.createTextNode(e.icono + ' ' + e.texto));
      li.append(el('time', null, hora(e.t)), que);
      ol.append(li);
    }
  }

  // ------------------------------------------------------------ látigo: acciones

  // Sonido del latigazo en la propia caseta: precargado y arrancado justo antes del impacto
  // (el archivo empieza con 0.22 s de silbido). Así suena al instante, sin esperar la ida y
  // vuelta a la oficina ni a que arranque afplay. Si no se pudo cargar, lo toca la oficina.
  const IMPACTO = 0.22;
  let ctxAudio = null;
  let chas = null;
  function prepararSonido() {
    try {
      ctxAudio = ctxAudio || new (window.AudioContext || window.webkitAudioContext)();
      if (!chas) {
        chas = 'cargando';
        fetch('sonidos/latigazo.wav').then((r) => (r.ok ? r.arrayBuffer() : Promise.reject()))
          .then((b) => ctxAudio.decodeAudioData(b)).then((b) => { chas = b; }).catch(() => { chas = null; });
      }
    } catch (e) { /* sin audio */ }
  }
  const despertarAudio = () => { prepararSonido(); try { if (ctxAudio && ctxAudio.state !== 'running') ctxAudio.resume(); } catch (e) { /* nada */ } };
  prepararSonido();
  document.addEventListener('pointerdown', despertarAudio, true);
  document.addEventListener('keydown', despertarAudio, true);

  function tronar() {
    const cfg = (snap && snap.config) || {};
    if (cfg.silencio || (cfg.sonidos && cfg.sonidos.latigazo === false)) return true;  // apagado a propósito
    if (!ctxAudio || !chas || chas === 'cargando') return false;
    try {
      const s = ctxAudio.createBufferSource();
      s.buffer = chas;
      s.connect(ctxAudio.destination);  // el volumen ya viene en el archivo
      s.start(0, IMPACTO - 0.02);
      return true;
    } catch (e) { return false; }
  }

  function latigazo(objetivo, agenteId) {
    const sonado = tronar();
    const ses = sesionActual();
    if (!ses) {  // sin obra también truena, por el meme: la oficina toca el sonido
      if (!sinLlave && !DEMO) enviar('api/latigo', { sesion: '', objetivo, sonado });
      avisar('¡Chas! No hay obra abierta');
      return;
    }
    enviar('api/latigo', { sesion: ses.id, objetivo, agente: agenteId, sonado });
  }

  $('#btn-latigo').addEventListener('click', () => oficina.latigazoAuto());

  // ------------------------------------------------------------ ajustes y sonido

  function pintarAjustes() {
    const cfg = (snap && snap.config) || {};
    const dlg = $('.ajustes');
    if (dlg.open && dlg.contains(document.activeElement)) return;
    for (const c of dlg.querySelectorAll('[data-sonido]')) c.checked = !!(cfg.sonidos || {})[c.dataset.sonido];
    $('#ajuste-volumen').value = Math.round((cfg.volumen === undefined ? 0.7 : cfg.volumen) * 100);
    $('#ajuste-abrir').checked = cfg.abrir_oficina_al_iniciar !== false;
  }

  $('#btn-ajustes').addEventListener('click', () => { pintarAjustes(); $('.ajustes').showModal(); });
  $('#btn-cerrar-ajustes').addEventListener('click', () => $('.ajustes').close());
  for (const c of document.querySelectorAll('[data-sonido]')) {
    c.addEventListener('change', () => enviar('api/config', { sonidos: { [c.dataset.sonido]: c.checked } }));
  }
  for (const b of document.querySelectorAll('[data-probar]')) {
    b.addEventListener('click', () => enviar('api/sonar', { nombre: b.dataset.probar }));
  }
  $('#ajuste-volumen').addEventListener('change', (e) => enviar('api/config', { volumen: Number(e.target.value) / 100 }));
  $('#ajuste-abrir').addEventListener('change', (e) => enviar('api/config', { abrir_oficina_al_iniciar: e.target.checked }));
  $('#btn-sonido').addEventListener('click', () => {
    const mudo = !!(snap && snap.config && snap.config.silencio);
    api('api/config', { silencio: !mudo }).then(() => avisar(mudo ? 'Sonido encendido' : 'Silencio'), () => null);
  });

  // ------------------------------------------------------------ ventana flotante (siempre visible)

  async function flotante() {
    if (pip) { pip.close(); return; }
    if (!('documentPictureInPicture' in window)) { avisar('La ventana flotante funciona en Chrome o Edge'); return; }
    const esc = $('.escenario');
    try {
      pip = await documentPictureInPicture.requestWindow({ width: 660, height: 420 });
    } catch (e) { avisar('No se pudo abrir la ventana flotante'); return; }
    for (const link of document.querySelectorAll('link[rel="stylesheet"]')) {
      const l = pip.document.createElement('link');
      l.rel = 'stylesheet'; l.href = link.href;
      pip.document.head.appendChild(l);
    }
    pip.document.title = 'La caseta';
    pip.document.body.classList.add('flotante');
    const marcador = document.createElement('div');
    esc.before(marcador);
    pip.document.body.appendChild(esc);
    oficina.usarVentana(pip);
    pip.document.addEventListener('keydown', teclas);
    pip.document.addEventListener('pointerdown', despertarAudio, true);  // L, S, F y 1-9 también con la flotante enfocada
    pip.addEventListener('resize', () => oficina.ajustar());
    pip.addEventListener('pagehide', () => {
      marcador.replaceWith(esc);
      pip = null;
      oficina.usarVentana(window);
      setTimeout(() => oficina.ajustar(), 30);
    });
    setTimeout(() => oficina.ajustar(), 60);
  }

  $('#btn-flotante').addEventListener('click', flotante);
  if (!('documentPictureInPicture' in window)) $('#btn-flotante').title = 'Disponible en Chrome o Edge';

  // ------------------------------------------------------------ teclado y relojes

  function teclas(e) {
    const objetivo = e.target && e.target.closest ? e.target : null;
    if ((objetivo && objetivo.closest('input, textarea, select, dialog')) || e.metaKey || e.ctrlKey || e.altKey) return;
    const k = (e.key || '').toLowerCase();
    if (k === 'l') { oficina.latigazoAuto(); e.preventDefault(); }
    else if (k === 's') { $('#btn-sonido').click(); }
    else if (k === 'f') { flotante(); }
    else if (/^[1-9]$/.test(k) && snap && snap.sesiones[Number(k) - 1]) {
      seleccion = snap.sesiones[Number(k) - 1].id; recordar('sesion', seleccion); abierto = null; aplicar(snap);
    }
  }
  document.addEventListener('keydown', teclas);

  setInterval(() => {
    const s = ahora();
    for (const n of document.querySelectorAll('[data-desde]')) {
      const d = Number(n.dataset.desde);
      if (!d) continue;
      n.textContent = duracion(s - d) + (n.classList.contains('tiempo') ? ' en esto' : '');
    }
    refrescarEnfriamiento();
  }, 1000);

  // ------------------------------------------------------------ arranque

  if (DEMO) {
    document.title = 'La caseta (demostración)';
    obtenerLlave();  // también aquí: la URL queda limpia y la llave guardada para la caseta real
    Demo.iniciar({ onEstado: aplicar, onEfecto: efecto });
  } else {
    aplicar({ sesiones: [], config: {} });
    obtenerLlave().then((t) => {
      TOKEN = t;
      sinLlave = !t;
      if (sinLlave) aplicar({ sesiones: [], config: {} });
      else conectar();
    });
  }
})();
