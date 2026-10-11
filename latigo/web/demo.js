/* Demostración sin servidor: una obra inventada que se repite sola, con el mismo formato
   que manda el servidor. Se abre con ?demo o cuando la página no viene del servidor. */
'use strict';
(function (global) {
  const SID = 'demo-tienda';
  const MODULOS = ['pagos', 'envios', 'facturas'];
  const TAREAS = ['Armar el módulo de pagos', 'Armar el módulo de envíos', 'Armar el módulo de facturas'];
  const ACCIONES_PEON = [
    ['leyendo', '📖', 'Leyendo src/features/{m}/index.ts'],
    ['escribiendo', '✏️', 'Editando src/features/{m}/servicio.ts (+18 −7)'],
    ['pensando', '🧠', 'Pensando…'],
    ['escribiendo', '✏️', 'Editando src/features/{m}/rutas.ts (+31 −0)'],
    ['buscando', '🔎', 'Buscando «carrito» en src/features/{m}'],
    ['terminal', '💻', 'Corre las pruebas de {m}'],
  ];
  const ACCIONES_CAPATAZ = [
    ['pensando', '🧠', 'Pensando…'],
    ['leyendo', '📖', 'Leyendo src/app.ts'],
    ['buscando', '🔎', 'Buscando «checkout» en src/'],
    ['escribiendo', '✏️', 'Editando src/features/carrito/servicio.ts (+24 −10)'],
    ['terminal', '💻', 'Corre las pruebas del carrito'],
    ['pensando', '🧠', 'Pensando…'],
  ];

  const ahora = () => Date.now() / 1000;
  let ses, fase, faseDesde, onEstado, onEfecto, intervalo, config, audio = null, chasquido = null;

  function agente(id, rol, tipo, nombre, silla, tarea) {
    const t = ahora();
    return {
      id, rol, tipo, nombre, silla, tarea: tarea || '', cat: rol === 'capataz' ? 'esperando' : 'arrancando',
      icono: '🚪', texto: 'Llegando a su escritorio', detalle: '', desde: t, inicio: t, fin: null, visible: true,
      tokens: { salida: 0, contexto: 0, entrada: 0 }, herramientas: 0, errores: 0, modelo: 'claude-opus-5-5',
      rama: null, resultado: '', globo: null, historial: [], paralelas: 1,
    };
  }

  function nuevaSesion() {
    const t = ahora();
    return {
      id: SID, proyecto: 'tienda-en-linea', titulo: 'Pagos, envíos y facturas', cwd: '~/proyectos/tienda-en-linea',
      estado: 'activa', actividad: t, creada: t, modelo: 'claude-opus-5-5', modo: 'acceptEdits',
      encargo: 'Agrega pagos, envíos y facturas a la tienda y que pasen las pruebas',
      turno_inicio: t, demo: true, con_hooks: true,
      latigo: { nivel: 0, techo: 0, latigazos: 0, peones_activos: 0, enfriamiento_hasta: 0, pendiente: null },
      agentes: [agente('main', 'capataz', 'principal', 'Capataz', null, '')], bitacora: [], tokens_salida: 0,
    };
  }

  function buscar(id) { return ses.agentes.find((a) => a.id === id); }

  function anotar(ag, icono, texto) {
    const t = ahora();
    ses.bitacora.push({ t, quien: ag.nombre, rol: ag.rol, icono, texto });
    if (ses.bitacora.length > 50) ses.bitacora.shift();
    ag.historial.push({ t, icono, texto });
    if (ag.historial.length > 14) ag.historial.shift();
  }

  function hacer(ag, cat, icono, texto, sinBitacora) {
    if (!ag) return;
    ag.cat = cat; ag.icono = icono; ag.texto = texto; ag.desde = ahora(); ag.globo = null;
    if (cat !== 'pensando') ag.herramientas += 1;
    if (!sinBitacora) anotar(ag, icono, texto);
  }

  function decir(ag, texto) {
    ag.globo = { tipo: 'dijo', texto };
    ag.cat = 'pensando'; ag.icono = '🧠'; ag.texto = 'Pensando…'; ag.desde = ahora();
    anotar(ag, '💬', texto);
  }

  function cambiarFase(f) { fase = f; faseDesde = ahora(); }

  function iniciar(callbacks) {
    onEstado = callbacks.onEstado;
    onEfecto = callbacks.onEfecto;
    config = { sonidos: { latigazo: true, peon_listo: true, permiso: true, listo: true, error: true }, tope_peones: 5,
      techo_por_nivel: [3, 5], enfriamiento_segundos: 60, abrir_oficina_al_iniciar: true, silencio: false, volumen: 0.7 };
    ses = nuevaSesion();
    cambiarFase('solo');
    anotar(buscar('main'), '📝', 'Encargo: ' + ses.encargo);
    const prender = () => {
      try {
        audio = audio || new (global.AudioContext || global.webkitAudioContext)();
        audio.resume();
        if (!chasquido) {  // el mismo latigazo que toca la oficina; si no carga, se sintetiza aquí
          chasquido = 'cargando';
          fetch('sonidos/latigazo.wav').then((r) => (r.ok ? r.arrayBuffer() : Promise.reject()))
            .then((b) => audio.decodeAudioData(b)).then((buf) => { chasquido = buf; }).catch(() => { chasquido = null; });
        }
      } catch (e) { /* sin audio */ }
    };
    global.addEventListener('pointerdown', prender, { once: true });
    global.addEventListener('keydown', prender, { once: true });
    tick();
    intervalo = setInterval(tick, 600);
  }

  function emitir() {
    const cap = buscar('main');
    ses.actividad = ahora();
    ses.tokens_salida = ses.agentes.reduce((n, a) => n + a.tokens.salida, 0);
    for (const a of ses.agentes) a.paralelas = 1;
    const snap = { v: Date.now(), ahora: ahora(), version: 'demo', config: JSON.parse(JSON.stringify(config)),
      sesiones: [JSON.parse(JSON.stringify(ses))] };
    if (cap) onEstado(snap);
  }

  function tokens(ag, mucho) {
    if (ag.cat === 'esperando' || ag.cat === 'durmiendo' || ag.cat === 'terminado') return;
    ag.tokens.salida += Math.floor((mucho ? 90 : 40) + Math.random() * 60);
    ag.tokens.contexto = Math.min(190000, (ag.tokens.contexto || (ag.rol === 'capataz' ? 38000 : 14000)) + Math.floor(Math.random() * 900));
  }

  function tick() {
    const t = ahora() - faseDesde;
    const cap = buscar('main');
    for (const a of ses.agentes) tokens(a, a.cat === 'escribiendo');
    if (fase === 'solo') {
      const i = Math.floor(t / 2.6);
      if (i === 3 && cap.cat !== 'pensando' && !cap.globo && t % 2.6 < 0.7) decir(cap, 'Son 3 módulos que no dependen entre sí. Voy con el primero…');
      else if (i !== 3) {
        const [cat, ic, tx] = ACCIONES_CAPATAZ[i % ACCIONES_CAPATAZ.length];
        if (cap.texto !== tx) hacer(cap, cat, ic, tx);
      }
      if (t > 17 && !ses.latigo.nivel) latigazo('capataz', null, true);
    } else if (fase === 'entrega') {
      if (t > 1.4 && !ses.latigo._entregado) {
        ses.latigo._entregado = true; ses.latigo.pendiente = null;
        anotar(cap, '📨', 'El capataz recibió el latigazo');
        onEfecto({ tipo: 'latigazo_entregado', sesion: SID, t: ahora() });
      }
      if (t > 3.2) { cambiarFase('reparto'); }
    } else if (fase === 'reparto') {
      const n = Math.min(3, Math.floor(t / 1.1) + 1);
      for (let k = 0; k < n; k++) {
        const id = 'peon-' + k;
        if (!buscar(id)) {
          hacer(cap, 'delegando', '👷', 'Mandando peón: ' + TAREAS[k]);
          const p = agente(id, 'peon', 'peon', 'Peón ' + (k + 1), k, TAREAS[k]);
          p.rama = 'worktree-agent-' + (1000 + k * 37).toString(16);
          ses.agentes.push(p);
          anotar(p, '🚪', 'Llegó ' + p.nombre + ': ' + p.tarea);
          ses.latigo.peones_activos = k + 1;
        }
      }
      if (t > 4.2) { hacer(cap, 'esperando_peones', '👀', 'Vigilando a los peones'); cambiarFase('cuadrilla'); }
    } else if (fase === 'cuadrilla') {
      const fines = [19, 24, 29];
      for (let k = 0; k < 3; k++) {
        const p = buscar('peon-' + k);
        if (!p) continue;
        if (p.cat === 'terminado' || p.cat === 'saliendo') {
          if (p.cat === 'terminado' && ahora() - p.fin > 6) { p.cat = 'saliendo'; p.icono = '👋'; p.texto = 'Ya se va'; p.desde = ahora(); }
          else if (p.cat === 'saliendo' && ahora() - p.desde > 5) { p.visible = false; p.silla = null; }
          continue;
        }
        if (t > fines[k]) {
          p.fin = ahora(); p.resultado = 'Listo: armé ' + MODULOS[k] + ' (4 archivos) y las pruebas pasan. Commit en ' + p.rama + '.';
          hacer(p, 'terminado', '✅', '¡Terminé!');
          anotar(p, '✅', p.nombre + ' terminó: ' + p.resultado);
          ses.latigo.peones_activos = Math.max(0, ses.latigo.peones_activos - 1);
          sonar('peon_listo');
          continue;
        }
        if (k === 1 && t > 9 && t < 13.5) {
          if (p.cat !== 'permiso') { hacer(p, 'permiso', '🙋', 'Pide permiso: $ npm install zod'); sonar('permiso'); }
          continue;
        }
        const idx = Math.floor((t + k * 1.7) / 2.4) % ACCIONES_PEON.length;
        const [cat, ic, tx] = ACCIONES_PEON[idx];
        const texto = tx.split('{m}').join(MODULOS[k]);
        if (p.texto !== texto && t > 2.5) hacer(p, cat, ic, texto);
        else if (t <= 2.5 && p.cat === 'arrancando' && t > 1.2) hacer(p, 'pensando', '🧠', 'Pensando…', true);
      }
      // el Topógrafo (Explore) pasa a revisar las pruebas
      if (t > 5 && t < 15 && !buscar('topo')) {
        const g = agente('topo', 'ayudante', 'Explore', 'Topógrafo', 0, 'Ubicar las pruebas del checkout');
        ses.agentes.push(g); anotar(g, '🚪', 'Llegó Topógrafo: ' + g.tarea);
      }
      const g = buscar('topo');
      if (g && g.visible) {
        if (t > 15 && g.cat !== 'terminado' && g.cat !== 'saliendo') { g.fin = ahora(); g.resultado = 'Hay 9 archivos de pruebas que tocan el checkout.'; hacer(g, 'terminado', '✅', '¡Terminé!'); }
        else if (g.cat === 'terminado' && ahora() - g.fin > 5) { g.cat = 'saliendo'; g.desde = ahora(); }
        else if (g.cat === 'saliendo' && ahora() - g.desde > 5) { g.visible = false; g.silla = null; }
        else if (t > 6.5 && t <= 15 && g.cat !== 'terminado') {
          const tx = Math.floor(t) % 2 ? 'Buscando archivos **/*.test.ts' : 'Leyendo src/features/carrito/carrito.test.ts';
          if (g.texto !== tx) hacer(g, Math.floor(t) % 2 ? 'buscando' : 'leyendo', Math.floor(t) % 2 ? '🗂️' : '📖', tx);
        }
      }
      if (t > 12 && t < 12.7 && !cap.globo) decir(cap, 'Van bien. Mientras, reviso las rutas.');
      if (t > 13 && t < 18 && cap.cat !== 'leyendo') hacer(cap, 'leyendo', '📖', 'Leyendo src/rutas.ts');
      if (t > 18 && cap.cat === 'leyendo') hacer(cap, 'esperando_peones', '👀', 'Vigilando a los peones');
      if (t > 41) cambiarFase('integrar');
    } else if (fase === 'integrar') {
      const pasos = [
        [0, 'terminal', '💻', '$ git merge --no-ff worktree-agent-3e8'],
        [3, 'terminal', '💻', '$ git merge --no-ff worktree-agent-40d'],
        [6, 'escribiendo', '✏️', 'Editando src/app.ts (+3 −8)'],
        [9, 'terminal', '💻', 'Corre el build completo'],
      ];
      for (const [seg, cat, ic, tx] of pasos) if (t >= seg && t < seg + 0.7 && cap.texto !== tx) hacer(cap, cat, ic, tx);
      if (t > 13) {
        decir(cap, 'Quedaron pagos, envíos y facturas: 3 peones, 41 pruebas en verde.');
        cap.cat = 'esperando'; cap.icono = '☕'; cap.texto = 'Esperando tus instrucciones';
        anotar(cap, '🏁', 'Terminó el turno (1 min 32 s)');
        sonar('listo');
        ses.latigo.nivel = 0; ses.latigo.techo = 0; ses.latigo.latigazos = 0;
        cambiarFase('fin');
      }
    } else if (fase === 'fin') {
      if (t > 9 && cap.cat === 'esperando') { cap.globo = null; cap.cat = 'durmiendo'; cap.icono = '😴'; cap.texto = 'Zzz… te está esperando'; }
      if (t > 16) {
        ses = nuevaSesion();
        anotar(buscar('main'), '📝', 'Encargo: ' + ses.encargo);
        cambiarFase('solo');
      }
    }
    // los globos de "dijo" se apagan solos
    for (const a of ses.agentes) if (a.globo && ahora() - a.desde > 6) a.globo = null;
    emitir();
  }

  function latigazo(objetivo, agenteId, automatico, sonado) {
    const cap = buscar('main');
    const lat = ses.latigo;
    let res;
    if (!sonado) sonar('latigazo');
    if (objetivo !== 'capataz') {
      res = { efectivo: false, motivo: 'meme' };
      onEfecto({ tipo: 'latigazo', sesion: SID, objetivo, agente: agenteId, res, texto: '¡Ay!', t: ahora() });
      return { ok: true, res, texto: '¡Ay!' };
    }
    lat.latigazos += 1;
    const enfriando = lat.enfriamiento_hasta > ahora();
    if (fase === 'fin') res = { efectivo: false, motivo: 'capataz_esperando' };
    else if (lat.peones_activos > 0) res = { efectivo: false, motivo: 'peones_trabajando', peones_activos: lat.peones_activos };
    else if (enfriando) res = { efectivo: false, motivo: 'enfriamiento', restante: Math.ceil(lat.enfriamiento_hasta - ahora()) };
    else {
      lat.nivel += 1; lat.techo = lat.nivel === 1 ? 3 : 5; lat.enfriamiento_hasta = ahora() + 60;
      res = { efectivo: true, nivel: lat.nivel, techo: lat.techo, origen: 'oficina' };
    }
    const texto = res.efectivo ? '¡Latigazo #' + res.nivel + '! Techo: ' + res.techo + ' peones'
      : res.motivo === 'peones_trabajando' ? 'Ya hay ' + res.peones_activos + ' peones chambeando'
        : res.motivo === 'enfriamiento' ? 'Calma: faltan ' + res.restante + ' s' : 'El capataz te está esperando';
    anotar(cap, '🪢', (automatico ? 'Latigazo de la demostración: ' : 'Latigazo desde la oficina: ') + texto);
    onEfecto({ tipo: 'latigazo', sesion: SID, objetivo: 'capataz', res, texto, t: ahora() });
    if (res.efectivo && fase === 'solo') {
      lat.pendiente = { creado: ahora(), expira: ahora() + 300 };
      lat._entregado = false;
      cambiarFase('entrega');
    } else if (res.efectivo && fase === 'integrar') {
      setTimeout(() => decir(cap, 'Esto ya no se paraleliza: falta integrar y probar. Sigo yo.'), 1200);
    }
    emitir();
    return { ok: true, res, texto };
  }

  function sonar(nombre, forzar) {
    if (!audio || (!forzar && (config.silencio || !config.sonidos[nombre]))) return;
    const ctx = audio, t0 = ctx.currentTime, vol = config.volumen;
    const salida = ctx.createGain(); salida.gain.value = vol; salida.connect(ctx.destination);
    if (nombre === 'latigazo' && chasquido && chasquido !== 'cargando') {
      const s = ctx.createBufferSource(); s.buffer = chasquido; s.connect(ctx.destination); s.start(t0, 0.2);  // directo al impacto  // el volumen ya viene en el archivo
      return;
    }
    if (nombre === 'latigazo') {
      const largo = Math.floor(ctx.sampleRate * 0.26);
      const buf = ctx.createBuffer(1, largo, ctx.sampleRate), d = buf.getChannelData(0);
      const corte = Math.floor(ctx.sampleRate * 0.17);
      let y = 0;
      for (let i = 0; i < largo; i++) {
        const r = Math.random() * 2 - 1;
        if (i < corte) { const x = i / corte; y += (0.02 + 0.35 * x * x) * (r - y); d[i] = y * 0.5 * Math.pow(x, 2.2); }
        else { const t = (i - corte) / ctx.sampleRate; d[i] = r * Math.exp(-t / 0.01) + Math.sin(2 * Math.PI * 2600 * t) * Math.exp(-t / 0.004) * 0.6; }
      }
      const s = ctx.createBufferSource(); s.buffer = buf; s.connect(salida); s.start(t0);
      return;
    }
    const notas = { peon_listo: [[1318.5, 0.07], [1760, 0.2]], permiso: [[784, 0.1], [0, 0.07], [784, 0.1]],
      listo: [[523.25, 0.085], [659.25, 0.085], [783.99, 0.085], [1046.5, 0.3]], error: [[196, 0.3]] }[nombre] || [];
    let t = t0;
    for (const [f, d] of notas) {
      if (f) {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = nombre === 'error' ? 'square' : nombre === 'listo' ? 'triangle' : 'sine';
        o.frequency.value = f;
        g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.4, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + d);
        o.connect(g); g.connect(salida); o.start(t); o.stop(t + d + 0.02);
      }
      t += d;
    }
  }

  function api(ruta, datos) {
    datos = datos || {};
    if (ruta.endsWith('latigo')) return Promise.resolve(latigazo(datos.objetivo, datos.agente, false, datos.sonado));
    if (ruta.endsWith('config')) {
      if (datos.sonidos) Object.assign(config.sonidos, datos.sonidos);
      if (typeof datos.silencio === 'boolean') config.silencio = datos.silencio;
      if (typeof datos.volumen === 'number') config.volumen = datos.volumen;
      if (typeof datos.abrir_oficina_al_iniciar === 'boolean') config.abrir_oficina_al_iniciar = datos.abrir_oficina_al_iniciar;
      emitir();
      return Promise.resolve({ ok: true });
    }
    if (ruta.endsWith('sonar')) { sonar(datos.nombre, true); return Promise.resolve({ ok: true }); }
    return Promise.resolve({ ok: false });
  }

  global.Demo = { iniciar, api };
})(window);
