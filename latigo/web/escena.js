/* La caseta en isométrico: el cuarto de noche, la gente que entra, trabaja y se va,
   los globos y el látigo con física. Interfaz:
   new Oficina(marco, { onLatigazo, onSeleccion }); ajustar(); actualizar(sesion); efecto(ef);
   latigazoAuto(); usarVentana(win). */
'use strict';
(function (global) {
  const { Vista, Caja, Pieza, ordenar, tono, rgba, mezcla } = global.Iso;
  const F = global.Figuras;
  const K = F.COLOR;

  // ---------------------------------------------------------------- medidas

  const ANCHO = 24, FONDO = 14, MURO = 6.4; // cuarto: x, y y altura de muros (unidades)
  const ESC = 30;                            // px lógicos por unidad
  const W = 1060, H = 800;                   // lienzo lógico
  const VISTA = new Vista(ESC, 400, 208);
  const KPX = 2.6;                      // cuánto crece un px de la escena anterior

  const PUERTA = { x: 21.6, y: 0.5 };
  const CARRIL_Y = 2.55;
  const ZT = 0.35;                           // altura de la tarima
  const ASIENTOS = {
    capataz: { x: 3.9, y: 7.1, z: ZT, dir: 0 },
    ayudante: [1.6, 3.5, 10.7, 12.6].map((y) => ({ x: 2.4, y, z: 0, dir: 0 })),
    peon: [0, 1, 2, 3, 4, 5].map((i) => ({ x: i < 3 ? 12.6 : 18.6, y: [4.4, 7.8, 11.2][i % 3], z: 0, dir: 2 })),
  };
  const VELOCIDAD = 3.4; // unidades por segundo

  const P = {
    fondo: '#0C0F16',
    piso: '#19202E',
    pisoLinea: '#202838',
    muroX: '#121824',
    muroY: '#171E2D',
    muroTope: '#283043',
    mueble: '#323C52',
    metal: '#47526A',
    oscuro: '#1C2230',
    madera: '#3A3129',
    tarima: '#2B3346',
    ambar: '#FFB547',
    menta: '#6FE3D0',
    texto: '#EEEAE2',
    tenue: '#8D96A6',
  };

  const POSES = {
    pensando: 'pensar', leyendo: 'leer', escribiendo: 'teclear', terminal: 'teclear', buscando: 'teclear',
    web: 'teclear', delegando: 'teclear', permiso: 'mano', pregunta: 'mano', plan: 'mano', hablando: 'hablar',
    esperando: 'idle', esperando_peones: 'idle', durmiendo: 'dormir', compactando: 'pensar', error: 'idle',
    terminado: 'pulgar', pendientes: 'teclear', skill: 'teclear', mcp: 'teclear', herramienta: 'teclear',
    arrancando: 'idle', saliendo: 'idle',
  };

  const FUENTE = {
    display: "'Archivo Expanded', 'Arial Black', sans-serif",
    semi: "'Archivo SemiExpanded', 'Arial', sans-serif",
    texto: "'Geist', 'Segoe UI', system-ui, sans-serif",
    mono: "'Geist Mono', ui-monospace, Menlo, monospace",
  };

  function asientoDe(ag) {
    if (ag.rol === 'capataz') return ASIENTOS.capataz;
    const lista = ag.rol === 'peon' ? ASIENTOS.peon : ASIENTOS.ayudante;
    return ag.silla === null || ag.silla === undefined ? null : lista[ag.silla] || null;
  }

  function carril(asiento, rol) {
    return rol === 'peon' ? asiento.x + 1.4 : 0.9;
  }

  function ruta(desde, hasta, rol, saliendo) {
    if (!saliendo) {
      const c = carril(hasta, rol);
      return [{ x: PUERTA.x, y: CARRIL_Y }, { x: c, y: CARRIL_Y }, { x: c, y: hasta.y }, { x: hasta.x, y: hasta.y }];
    }
    const c = carril(desde, rol);
    return [{ x: c, y: desde.y }, { x: c, y: CARRIL_Y }, { x: PUERTA.x, y: CARRIL_Y }, { x: PUERTA.x, y: PUERTA.y }];
  }

  // texto dentro de un plano, con la fuente a un tamaño legible
  function textoPlano(ctx, s, u, v, alto, fuente, color, alinear) {
    ctx.save();
    ctx.translate(u, v);
    ctx.scale(alto / 40, alto / 40);
    ctx.font = fuente.replace('{t}', '40px');
    ctx.fillStyle = color;
    ctx.textAlign = alinear || 'left';
    ctx.textBaseline = 'alphabetic';
    ctx.fillText(s, 0, 0);
    ctx.restore();
  }

  // ---------------------------------------------------------------- látigo con física (verlet), en px lógicos

  class Latigo {
    constructor() {
      this.n = 17;
      this.seg = 4.4 * KPX;
      this.p = [];
      this.listo = false;
      this.mango = { x: 0, y: 0, ax: -0.6, ay: -0.8 };
      this.velPunta = 0;
    }
    colocar(x, y) {
      this.p = [];
      for (let i = 0; i < this.n; i++) this.p.push({ x: x - i * 2 * KPX, y: y + i * 3 * KPX, px: x - i * 2 * KPX, py: y + i * 3 * KPX });
      this.listo = true;
    }
    paso(mx, my, vx, vy) {
      if (!this.listo) this.colocar(mx, my);
      const largo = Math.hypot(vx, vy);
      if (largo > 0.6 * KPX) {
        this.mango.ax = this.mango.ax * 0.8 + (vx / largo) * 0.2;
        this.mango.ay = this.mango.ay * 0.8 + (vy / largo) * 0.2;
        const l2 = Math.hypot(this.mango.ax, this.mango.ay) || 1;
        this.mango.ax /= l2; this.mango.ay /= l2;
      }
      this.mango.x = mx; this.mango.y = my;
      const punta = { x: mx + this.mango.ax * 9 * KPX, y: my + this.mango.ay * 9 * KPX };
      const p = this.p;
      p[0].x = punta.x; p[0].y = punta.y; p[0].px = punta.x; p[0].py = punta.y;
      for (let i = 1; i < p.length; i++) {
        const q = p[i];
        const vxq = (q.x - q.px) * 0.975, vyq = (q.y - q.py) * 0.975;
        q.px = q.x; q.py = q.y;
        q.x += vxq; q.y += vyq + 0.12 * KPX;
      }
      for (let k = 0; k < 16; k++) {
        for (let i = 1; i < p.length; i++) {
          const a = p[i - 1], b = p[i];
          const dx = b.x - a.x, dy = b.y - a.y;
          const d = Math.hypot(dx, dy) || 0.0001;
          const dif = (d - this.seg) / d;
          if (i === 1) { b.x -= dx * dif; b.y -= dy * dif; } else {
            a.x += dx * dif * 0.5; a.y += dy * dif * 0.5; b.x -= dx * dif * 0.5; b.y -= dy * dif * 0.5;
          }
        }
        p[0].x = punta.x; p[0].y = punta.y;
      }
      const u = p[p.length - 1];
      this.velPunta = Math.hypot(u.x - u.px, u.y - u.py) / KPX;
      return u;
    }
    punta() { return this.p[this.p.length - 1]; }
    dibujar(ctx) {
      if (!this.listo) return;
      const m = this.mango;
      ctx.save();
      ctx.lineCap = 'round';
      // mango
      ctx.strokeStyle = '#2A1A10'; ctx.lineWidth = 9;
      ctx.beginPath(); ctx.moveTo(m.x - m.ax * 4, m.y - m.ay * 4); ctx.lineTo(m.x + m.ax * 9 * KPX, m.y + m.ay * 9 * KPX); ctx.stroke();
      ctx.strokeStyle = '#7A5230'; ctx.lineWidth = 4;
      ctx.beginPath(); ctx.moveTo(m.x + m.ax * 3, m.y + m.ay * 3); ctx.lineTo(m.x + m.ax * 8 * KPX, m.y + m.ay * 8 * KPX); ctx.stroke();
      // cuerda que se adelgaza hacia la punta
      const p = this.p;
      for (let i = 1; i < p.length; i++) {
        const t = i / (p.length - 1);
        ctx.strokeStyle = t > 0.85 ? '#E8D3A8' : mezcla('#5A3A24', '#C08552', t);
        ctx.lineWidth = 7 - t * 5.4;
        ctx.beginPath(); ctx.moveTo(p[i - 1].x, p[i - 1].y); ctx.lineTo(p[i].x, p[i].y); ctx.stroke();
      }
      ctx.restore();
    }
  }

  // ---------------------------------------------------------------- escena

  class Oficina {
    constructor(marco, opciones) {
      opciones = opciones || {};
      this.marco = marco;
      this.canvas = marco.querySelector('canvas');
      this.capaGlobos = marco.querySelector('.globos');
      this.ctx = this.canvas.getContext('2d');
      this.escala = 1;
      this.dpr = 1;
      this.personajes = new Map();
      this.sesion = null;
      this.cargado = false;
      this.particulas = [];
      this.textos = [];
      this.temblor = 0;
      this.puertaHasta = 0;
      this.latigo = new Latigo();
      this.raton = { x: -100, y: -100, dentro: false, presionado: false, vx: 0, vy: 0, ultimoChas: 0, arrastre: 0 };
      this.auto = null;
      this.chicotazo = null;
      this.onLatigazo = opciones.onLatigazo || null;
      this.onSeleccion = opciones.onSeleccion || null;
      this.hover = null;
      this.reducido = global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches;
      this.fondoCache = document.createElement('canvas');
      this.fondoClave = '';
      this.ultimoCuadro = 0;
      this.vacia = true;
      this.fijos = this._muebles();
      this.polvo = this._polvoInicial();
      this.win = global;
      this.gen = 0;
      this._eventos();
      this.ajustar();
      this._fuentes();
      this._pedirCuadro();
      marco.classList.add('iso');
    }

    _fuentes() {
      if (!document.fonts || !document.fonts.load) return;
      const cargas = ["800 40px 'Archivo Expanded'", "600 40px 'Archivo SemiExpanded'", "400 40px 'Geist'", "500 40px 'Geist'",
        "400 40px 'Geist Mono'", "500 40px 'Geist Mono'"].map((f) => document.fonts.load(f).catch(() => null));
      Promise.all(cargas).then(() => { this.fondoClave = ''; });
    }

    usarVentana(win) {
      this.win = win || global;
      this.gen += 1;
      this._pedirCuadro();
    }

    _pedirCuadro() {
      const gen = this.gen;
      const win = this.win || global;
      try { win.requestAnimationFrame((ms) => this._bucle(ms, gen)); } catch (e) { global.requestAnimationFrame((ms) => this._bucle(ms, gen)); }
    }

    // ------------------------------------------------ tamaño

    ajustar() {
      const caja = this.marco.parentElement.getBoundingClientRect();
      const win = this.marco.ownerDocument.defaultView || global;
      const dpr = Math.min(2, win.devicePixelRatio || 1);
      const anchoDisp = Math.max(240, caja.width - 4), altoDisp = Math.max(180, caja.height - 4);
      const e = Math.min(anchoDisp / W, altoDisp / H);
      this.escala = e;
      this.dpr = dpr;
      const cw = Math.round(W * e), ch = Math.round(H * e);
      this.marco.style.width = cw + 'px';
      this.marco.style.height = ch + 'px';
      this.canvas.style.width = cw + 'px';
      this.canvas.style.height = ch + 'px';
      this.canvas.width = Math.round(cw * dpr);
      this.canvas.height = Math.round(ch * dpr);
      this.fondoCache.width = this.canvas.width;
      this.fondoCache.height = this.canvas.height;
      this.fondoClave = '';
      this.marco.style.setProperty('--escala', e);
      this.marco.classList.toggle('compacto', e < 0.62);
      for (const p of this.personajes.values()) { p._globoClave = ''; p._gx = null; }
    }

    _base(ctx) {
      const k = this.escala * this.dpr;
      ctx.setTransform(k, 0, 0, k, 0, 0);
    }

    // ------------------------------------------------ datos

    actualizar(sesion) {
      this.sesion = sesion;
      this.vacia = !sesion;
      if (!sesion) {
        for (const p of this.personajes.values()) p.globo && p.globo.remove();
        this.personajes.clear();
        this.cargado = false;
        return;
      }
      const ahora = performance.now();
      const vivos = new Set();
      for (const ag of sesion.agentes) {
        if (!ag.visible) continue;
        const asiento = asientoDe(ag);
        if (!asiento) continue;
        vivos.add(ag.id);
        let p = this.personajes.get(ag.id);
        if (!p) {
          p = this._nuevo(ag);
          const entrar = this.cargado && ag.rol !== 'capataz' && ag.cat !== 'saliendo' && ag.cat !== 'terminado';
          if (entrar) {
            p.x = PUERTA.x; p.y = PUERTA.y; p.ruta = ruta(PUERTA, asiento, ag.rol, false); p.sentado = false;
            this.puertaHasta = ahora + 1600;
          } else {
            p.x = asiento.x; p.y = asiento.y; p.sentado = true;
          }
          this.personajes.set(ag.id, p);
        }
        p.agente = ag;
        if (ag.cat === 'saliendo' && !p.saliendo) this._mandarSalir(p, asiento, ahora);
        else if (!p.saliendo && p.sentado && (p.asiento.x !== asiento.x || p.asiento.y !== asiento.y)) {
          p.ruta = ruta(p.asiento, asiento, ag.rol, false); p.sentado = false;
        }
        if (!p.saliendo) p.asiento = asiento;
      }
      for (const p of this.personajes.values()) {
        if (!vivos.has(p.id) && !p.saliendo) this._mandarSalir(p, p.asiento, ahora);
      }
      this.cargado = true;
    }

    _nuevo(ag) {
      const globo = document.createElement('div');
      globo.className = 'globo';
      globo.setAttribute('aria-hidden', 'true');
      this.capaGlobos.appendChild(globo);
      return {
        id: ag.id, rol: ag.rol, look: F.lookPara(ag), x: 0, y: 0, dir: 2, ruta: [], sentado: true, saliendo: false,
        asiento: asientoDe(ag), agente: ag, semilla: F.hash(String(ag.id)) % 997 + 1, reaccion: null,
        parpadeoProx: performance.now() + 1500 + Math.random() * 3000, parpadeoHasta: 0,
        globo, _globoClave: '', fase: Math.random() * 1000,
      };
    }

    _mandarSalir(p, asiento, ahora) {
      p.saliendo = true;
      p.sentado = false;
      p.ruta = ruta(asiento || { x: p.x, y: p.y }, PUERTA, p.rol, true);
      this.puertaHasta = ahora + 4000;
    }

    _cabeza(p) {
      const a = p.sentado ? p.asiento : null;
      const z = (a ? a.z : 0) + F.alturaCabeza(p.sentado) - 0.35;
      return VISTA.p(p.x, p.y, z);
    }

    efecto(ef) {
      if (!this.sesion || ef.sesion !== this.sesion.id) return;
      const ahora = performance.now();
      const cap = [...this.personajes.values()].find((p) => p.rol === 'capataz');
      if (ef.tipo === 'latigazo') {
        if (ef.objetivo !== 'capataz') {
          const p = ef.agente && this.personajes.get(ef.agente);
          if (p) p.reaccion = { pose: 'dolor', hasta: ahora + 700, globo: '¡Ay!' };
          return;
        }
        if (!cap) return;
        const res = ef.res || {};
        if (res.efectivo) {
          cap.reaccion = { pose: 'dolor', hasta: ahora + 450, globo: '¡Ay!',
            siguiente: { pose: 'latigo', hasta: ahora + 1900, globo: '¡A chambear! Techo: ' + (res.techo || '?') + ' peones', grita: true } };
          // el capataz se desquita: chicotazo hacia las filas de los peones
          const a = ASIENTOS.capataz;
          const [x0, y0] = VISTA.p(a.x + 1.2, a.y + 0.5, a.z + 3.1);
          const [x1, y1] = VISTA.p(14.5, 7.8, 2.2);
          this.chicotazo = { t0: ahora + 460, dur: 380, x0, y0, x1, y1, tronido: false };
          setTimeout(() => this._sacudirPeones(), 860);
        } else {
          const motivo = ef.texto || 'Solo sonó';
          cap.reaccion = { pose: 'dolor', hasta: ahora + 450, globo: '¡Ay!',
            siguiente: { pose: 'senalar', hasta: ahora + 2800, globo: motivo } };
        }
      } else if (ef.tipo === 'latigazo_entregado' && cap) {
        cap.reaccion = { pose: 'leer', hasta: ahora + 2200, globo: '📨 Recibido: a repartir el trabajo' };
      } else if (ef.tipo === 'latigazo_perdido' && cap) {
        cap.reaccion = { pose: 'senalar', hasta: ahora + 3200, globo: 'No me llegó el latigazo' };
      }
    }

    _latigoDelCapataz(ctx, ms) {
      const c = this.chicotazo;
      if (!c || ms < c.t0) return;
      const k = Math.min(1, (ms - c.t0) / c.dur);
      const n = 40, hasta = Math.max(2, Math.floor(n * k));
      ctx.save();
      ctx.lineCap = 'round';
      let prev = null;
      for (let i = 0; i <= hasta; i++) {
        const t = i / n;
        const x = c.x0 + (c.x1 - c.x0) * t + Math.sin(t * Math.PI) * 60 * (1 - k * 0.6);
        const y = c.y0 + (c.y1 - c.y0) * t - Math.sin(t * Math.PI) * 120 + Math.sin(t * 9 - ms / 35) * 5 * (1 - t);
        if (prev) {
          ctx.strokeStyle = t > 0.85 ? '#E8D3A8' : mezcla('#5A3A24', '#C08552', t);
          ctx.lineWidth = 7 - t * 5.2;
          ctx.beginPath(); ctx.moveTo(prev[0], prev[1]); ctx.lineTo(x, y); ctx.stroke();
        }
        prev = [x, y];
      }
      ctx.restore();
      if (k >= 1 && !c.tronido) {
        c.tronido = true;
        this.textos.push({ texto: '¡CHAS!', x: c.x1, y: c.y1, vida: 650, total: 650, color: P.ambar });
        for (let i = 0; i < 16; i++) {
          const a = Math.random() * Math.PI * 2, v = (0.5 + Math.random() * 1.4) * KPX;
          this.particulas.push({ x: c.x1, y: c.y1, vx: Math.cos(a) * v, vy: Math.sin(a) * v, vida: 320, color: i % 3 ? '#FFE6B0' : P.ambar });
        }
      }
      if (ms > c.t0 + c.dur + 220) this.chicotazo = null;
    }

    _sacudirPeones() {
      const ahora = performance.now();
      for (const p of this.personajes.values()) {
        if (p.rol === 'peon' && p.sentado && !p.reaccion) p.reaccion = { pose: 'asustado', hasta: ahora + 380 };
      }
      if (!this.reducido) this.temblor = 8;
      for (const a of ASIENTOS.peon) { const [x, y] = VISTA.p(a.x, a.y, 0.2); this._polvo(x, y, 4); }
    }

    // ------------------------------------------------ látigo e interacción

    _eventos() {
      const c = this.canvas;
      const pos = (e) => {
        const r = c.getBoundingClientRect();
        return { x: (e.clientX - r.left) / (r.width / W), y: (e.clientY - r.top) / (r.height / H) };
      };
      c.addEventListener('pointermove', (e) => {
        const p = pos(e);
        this.raton.vx = p.x - this.raton.x; this.raton.vy = p.y - this.raton.y;
        this.raton.x = p.x; this.raton.y = p.y; this.raton.dentro = true;
        if (this.raton.presionado) this.raton.arrastre += Math.hypot(this.raton.vx, this.raton.vy);
        this.hover = this._quienEn(p.x, p.y, 34);
      });
      c.addEventListener('pointerenter', (e) => {
        const p = pos(e);
        this.raton.x = p.x; this.raton.y = p.y; this.raton.dentro = true;
        this.latigo.colocar(p.x, p.y);
      });
      c.addEventListener('pointerleave', () => { this.raton.dentro = false; this.raton.presionado = false; this.hover = null; });
      c.addEventListener('pointerdown', (e) => {
        const p = pos(e);
        this.raton.presionado = true; this.raton.arrastre = 0;
        this.raton.x = p.x; this.raton.y = p.y; this.raton.dentro = true;
        if (!this.latigo.listo) this.latigo.colocar(p.x, p.y);
        try { c.setPointerCapture(e.pointerId); } catch (err) { /* nada */ }
      });
      c.addEventListener('pointerup', (e) => {
        const p = pos(e);
        const fueClic = this.raton.arrastre < 15;
        this.raton.presionado = false;
        if (fueClic) {
          const quien = this._quienEn(p.x, p.y, 40);
          if (quien) {
            if (quien.rol === 'capataz') this.latigazoAuto(quien);
            else if (this.onSeleccion) this.onSeleccion(quien.id);
          }
        }
      });
    }

    _quienEn(x, y, radio) {
      let mejor = null, dist = 1e9;
      for (const p of this.personajes.values()) {
        const [cx, cy0] = this._cabeza(p);
        const cy = cy0 + 18;
        const d = Math.hypot(cx - x, cy - y);
        if (d < radio && d < dist) { mejor = p; dist = d; }
      }
      return mejor;
    }

    latigazoAuto(objetivo) {
      const cap = objetivo || [...this.personajes.values()].find((p) => p.rol === 'capataz');
      let blanco;
      if (cap) { const [x, y] = this._cabeza(cap); blanco = { x, y: y + 26 }; } else blanco = { x: W * 0.4, y: H * 0.35 };
      const inicio = { x: blanco.x - 180, y: blanco.y - 100 };
      this.latigo.colocar(inicio.x, inicio.y);
      this.auto = { t0: performance.now(), dur: 380, inicio, blanco, objetivo: cap, disparado: false };
    }

    _chasquido(x, y, forzado) {
      const ahora = performance.now();
      if (!forzado && ahora - this.raton.ultimoChas < 260) return;
      this.raton.ultimoChas = ahora;
      const quien = this._quienEn(x, y, 44);
      const objetivo = quien ? (quien.rol === 'capataz' ? 'capataz' : quien.rol) : 'aire';
      // Primero el sonido y luego la imagen: el oído perdona menos un sonido tarde que una imagen tarde.
      if (this.onLatigazo) this.onLatigazo(objetivo, quien ? quien.id : null);
      setTimeout(() => {
        this.textos.push({ texto: '¡CHAS!', x, y: y - 16, vida: 700, total: 700, color: P.ambar });
        for (let i = 0; i < 16; i++) {
          const a = Math.random() * Math.PI * 2, v = (0.6 + Math.random() * 1.6) * KPX;
          this.particulas.push({ x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, vida: 260 + Math.random() * 200, color: i % 3 ? '#FFE6B0' : P.ambar });
        }
        if (!this.reducido) this.temblor = Math.max(this.temblor, 5);
        if (quien && quien.rol !== 'capataz') quien.reaccion = { pose: 'dolor', hasta: performance.now() + 600, globo: '¡Ay!' };
      }, 40);
    }

    _polvo(x, y, n) {
      for (let i = 0; i < n; i++) this.particulas.push({ x: x + (Math.random() - 0.5) * 50, y, vx: (Math.random() - 0.5) * 1.5, vy: -0.8 - Math.random(), vida: 500, color: 'rgba(200,190,170,0.6)' });
    }

    // ------------------------------------------------ cuadro

    _bucle(ms, gen) {
      if (gen !== this.gen) return;
      this._pedirCuadro();
      if (ms - this.ultimoCuadro < 30) return;
      const dt = Math.min(100, ms - (this.ultimoCuadro || ms));
      this.ultimoCuadro = ms;
      this._mover(dt, ms);
      this._dibujar(ms);
      this._globos(ms);
    }

    _mover(dt, ms) {
      for (const [id, p] of this.personajes) {
        if (p.ruta.length) {
          const m = p.ruta[0];
          const dx = m.x - p.x, dy = m.y - p.y, d = Math.hypot(dx, dy);
          const paso = VELOCIDAD * dt / 1000;
          if (Math.abs(dx) > Math.abs(dy)) p.dir = dx > 0 ? 0 : 2; else if (d > 0.001) p.dir = dy > 0 ? 1 : 3;
          if (d <= paso) { p.x = m.x; p.y = m.y; p.ruta.shift(); } else { p.x += dx / d * paso; p.y += dy / d * paso; }
          if (!p.ruta.length) {
            if (p.saliendo) { p.globo.remove(); this.personajes.delete(id); continue; }
            p.sentado = true;
          }
        }
        if (ms > p.parpadeoProx) { p.parpadeoHasta = ms + 130; p.parpadeoProx = ms + 2500 + Math.random() * 3500; }
        if (p.reaccion && ms > p.reaccion.hasta) p.reaccion = p.reaccion.siguiente || null;
      }
      if (this.auto) {
        const a = this.auto, k = Math.min(1, (ms - a.t0) / a.dur);
        const e = k * k * (3 - 2 * k);
        const x = a.inicio.x + (a.blanco.x + 20 - a.inicio.x) * e;
        const y = a.inicio.y + (a.blanco.y + 46 - a.inicio.y) * e - Math.sin(e * Math.PI) * 68;
        this._vxAuto = x - (this._xAuto || x); this._vyAuto = y - (this._yAuto || y);
        this._xAuto = x; this._yAuto = y;
        this.latigo.paso(x, y, this._vxAuto, this._vyAuto);
        if (k >= 1 && !a.disparado) {
          a.disparado = true;
          const u = this.latigo.punta();
          let tx = u.x, ty = u.y;
          if (a.objetivo) { const [hx, hy] = this._cabeza(a.objetivo); tx = hx; ty = hy + 18; }
          this._chasquido(tx, ty, true);
          setTimeout(() => { if (this.auto === a) this.auto = null; }, 260);
        }
      } else if (this.raton.dentro) {
        const u = this.latigo.paso(this.raton.x, this.raton.y, this.raton.vx, this.raton.vy);
        this.raton.vx *= 0.5; this.raton.vy *= 0.5;
        if (this.raton.presionado && this.latigo.velPunta > 7.5) this._chasquido(u.x, u.y, false);
      }
      for (const q of this.particulas) { q.x += q.vx; q.y += q.vy; q.vy += 0.08; q.vida -= dt; }
      this.particulas = this.particulas.filter((q) => q.vida > 0);
      for (const t of this.textos) { t.vida -= dt; t.y -= dt * 0.03; }
      this.textos = this.textos.filter((t) => t.vida > 0);
    }

    _pose(p, ms) {
      if (p.reaccion) return p.reaccion.pose;
      if (!p.sentado) return 'caminar';
      const ag = p.agente;
      let pose = POSES[ag.cat] || 'idle';
      const ciclo = Math.floor((ms + p.fase * 7) / 3200) % 3;
      if (pose === 'pensar' && ciclo === 2) pose = 'idle';
      if (pose === 'leer' && ciclo === 1) pose = 'idle';
      if (ag.globo && ag.globo.tipo === 'dijo' && ms % 2400 < 1400) pose = 'hablar';
      if (p.rol === 'capataz' && ag.cat === 'delegando') pose = 'senalar';
      return pose;
    }

    // ------------------------------------------------ muebles fijos

    _muebles() {
      const fijos = [];
      const add = (c) => { fijos.push(c); return c; };
      // tarima del capataz con franjas de precaución
      const franjas = (ctx, u0, u1, v0, v1) => {
        ctx.save(); ctx.beginPath(); ctx.rect(u0, v0, u1 - u0, v1 - v0); ctx.clip();
        ctx.fillStyle = P.ambar;
        for (let u = u0 - 1; u < u1 + 1; u += 0.6) {
          ctx.beginPath(); ctx.moveTo(u, v1); ctx.lineTo(u + 0.3, v1); ctx.lineTo(u + 0.3 + (v1 - v0), v0); ctx.lineTo(u + (v1 - v0), v0); ctx.closePath(); ctx.fill();
        }
        ctx.restore();
      };
      add(new Caja(1.3, 4.7, 0, 5.8, 4.8, ZT, P.tarima, { caras: { top: '#2E374B' }, sobre: { x: franjas, y: franjas } }));
      // escritorio del capataz
      const cz = ZT;
      add(new Caja(4.9, 5.6, cz + 1.52, 1.6, 3.0, 0.12, '#3A4762'));
      for (const [lx, ly] of [[5.0, 5.7], [6.35, 5.7], [5.0, 8.45], [6.35, 8.45]]) add(new Caja(lx, ly, cz, 0.1, 0.1, 1.52, P.metal));
      add(new Caja(4.95, 5.65, cz + 0.2, 0.08, 2.9, 1.1, '#2C3548'));
      // laptop del capataz: la tapa le da la cara a él; atrás brilla el logo
      add(new Caja(5.5, 6.45, cz + 1.64, 0.7, 1.1, 0.05, '#4A5468'));
      add(new Caja(6.15, 6.45, cz + 1.69, 0.07, 1.1, 0.72, '#4A5468', {
        sobre: { x: (ctx, u0, u1, v0, v1) => {
          ctx.fillStyle = rgba(P.ambar, 0.9);
          ctx.beginPath(); ctx.arc((u0 + u1) / 2, (v0 + v1) / 2, 0.11, 0, Math.PI * 2); ctx.fill();
        } },
      }));
      add(new Caja(5.8, 7.9, cz + 1.64, 0.22, 0.22, 0.28, '#E9E4DA'));
      // escritorios de los peones
      ASIENTOS.peon.forEach((a, i) => {
        const x0 = a.x - 2.55, y0 = a.y - 1.15;
        add(new Caja(x0, y0, 1.55, 2.1, 2.3, 0.12, P.mueble));
        for (const [lx, ly] of [[0.06, 0.06], [1.94, 0.06], [0.06, 2.14], [1.94, 2.14]]) add(new Caja(x0 + lx, y0 + ly, 0, 0.1, 0.1, 1.55, P.metal));
        add(new Caja(x0 + 0.2, a.y - 0.12, 1.67, 0.12, 0.24, 0.36, P.metal));
        add(new Caja(x0 + 0.08, a.y - 0.42, 1.67, 0.5, 0.84, 0.04, P.metal));
        add(new Caja(x0 + 1.15, a.y - 0.5, 1.67, 0.42, 1.0, 0.05, '#2B3245'));
        add(new Caja(x0 + 1.5, a.y + 0.62, 1.67, 0.22, 0.22, 0.26, i % 2 ? '#E9E4DA' : P.ambar));
        // silla
        add(new Caja(a.x - 0.42, a.y - 0.42, 0.9, 0.84, 0.84, 0.12, P.oscuro));
        add(new Caja(a.x + 0.42, a.y - 0.42, 1.02, 0.14, 0.84, 0.95, tono(P.oscuro, 1.18)));
        add(new Caja(a.x - 0.07, a.y - 0.07, 0.12, 0.14, 0.14, 0.78, P.metal));
        add(new Caja(a.x - 0.36, a.y - 0.36, 0, 0.72, 0.72, 0.12, P.metal));
      });
      // sillas del capataz y de los ayudantes
      const silla = (x, y, z) => {
        add(new Caja(x - 0.42, y - 0.42, z + 0.9, 0.84, 0.84, 0.12, P.oscuro));
        add(new Caja(x - 0.56, y - 0.42, z + 1.02, 0.14, 0.84, 0.95, tono(P.oscuro, 1.18)));
        add(new Caja(x - 0.07, y - 0.07, z + 0.12, 0.14, 0.14, 0.78, P.metal));
        add(new Caja(x - 0.36, y - 0.36, z, 0.72, 0.72, 0.12, P.metal));
      };
      silla(ASIENTOS.capataz.x, ASIENTOS.capataz.y, ZT);
      // mesas de dibujo de los ayudantes
      for (const a of ASIENTOS.ayudante) {
        silla(a.x, a.y, 0);
        const plano = (ctx, u0, u1, v0, v1) => {
          ctx.fillStyle = '#2F5E9E'; ctx.fillRect(u0 + 0.12, v0 + 0.12, (u1 - u0) * 0.55, (v1 - v0) - 0.24);
          ctx.strokeStyle = '#9FC2EE'; ctx.lineWidth = 0.03;
          ctx.strokeRect(u0 + 0.22, v0 + 0.25, (u1 - u0) * 0.35, (v1 - v0) * 0.35);
        };
        add(new Caja(a.x + 0.95, a.y - 0.85, 1.48, 1.5, 1.7, 0.1, '#3A3F4C', { sobre: { top: plano } }));
        add(new Caja(a.x + 1.0, a.y - 0.8, 0, 0.1, 0.1, 1.48, P.metal));
        add(new Caja(a.x + 2.3, a.y - 0.8, 0, 0.1, 0.1, 1.48, P.metal));
        add(new Caja(a.x + 1.0, a.y + 0.7, 0, 0.1, 0.1, 1.48, P.metal));
        add(new Caja(a.x + 2.3, a.y + 0.7, 0, 0.1, 0.1, 1.48, P.metal));
      }
      // utilería
      // garrafón de agua bajo la ventana
      add(new Caja(6.9, 0.45, 0, 0.8, 0.8, 1.5, '#D6D2C8'));
      add(new Caja(7.0, 0.55, 1.5, 0.6, 0.6, 0.9, '#5DA8D8', { alfa: 0.75 }));
      // archivero
      add(new Caja(16.3, 0.3, 0, 1.4, 1.1, 2.2, '#3A4356', {
        sobre: { y: (ctx, u0, u1, v0, v1) => {
          for (let i = 0; i < 3; i++) {
            ctx.fillStyle = '#2E3546'; ctx.fillRect(u0 + 0.1, v0 + 0.12 + i * 0.7, u1 - u0 - 0.2, 0.58);
            ctx.fillStyle = '#8D96A6'; ctx.fillRect((u0 + u1) / 2 - 0.15, v0 + 0.3 + i * 0.7, 0.3, 0.06);
          }
        } },
      }));
      // planta
      add(new Caja(23.0, 0.5, 0, 0.8, 0.8, 0.8, '#6B4A36'));
      for (const [lx, ly, lz, s] of [[23.05, 0.55, 0.8, 0.7], [23.2, 0.45, 1.4, 0.6], [22.95, 0.75, 1.9, 0.5], [23.25, 0.65, 2.3, 0.42]]) {
        add(new Caja(lx, ly, lz, s, s, s * 0.8, tono('#2F5A4A', 1 + (lz - 0.8) * 0.1)));
      }
      add(new Caja(0.4, 12.9, 0, 0.8, 0.8, 0.8, '#6B4A36'));
      for (const [lx, ly, lz, s] of [[0.45, 12.95, 0.8, 0.7], [0.55, 12.85, 1.4, 0.55], [0.4, 13.1, 1.85, 0.45]]) {
        add(new Caja(lx, ly, lz, s, s, s * 0.8, tono('#2F5A4A', 1 + (lz - 0.8) * 0.1)));
      }
      // costales de cemento y caja de herramientas al frente
      for (const [cx, cy, cz] of [[21.8, 12.4, 0], [22.7, 12.4, 0], [22.2, 12.5, 0.45]]) add(new Caja(cx, cy, cz, 0.85, 1.25, 0.45, '#9C8E74', { caras: { top: '#B5A78A' } }));
      add(new Caja(19.4, 12.9, 0, 1.4, 0.7, 0.6, '#B5473A', { caras: { top: '#C9584A' } }));
      add(new Caja(19.9, 13.15, 0.6, 0.4, 0.2, 0.1, '#2A2622'));
      return fijos;
    }

    _polvoInicial() {
      const lst = [];
      const r = F.aleatorio(5);
      for (let i = 0; i < 18; i++) lst.push({ fase: r() * 9, dur: 6 + r() * 5, lx: r(), ly: r(), lz: r() });
      return lst;
    }

    // ------------------------------------------------ fondo (muros, piso y lo que cuelga)

    _fondo(ctx, fecha, latPiz, op) {
      const v = VISTA;
      ctx.fillStyle = P.fondo;
      ctx.fillRect(0, 0, W, H);
      const halo = ctx.createRadialGradient(W * 0.48, H * 0.5, 40, W * 0.48, H * 0.5, W * 0.62);
      halo.addColorStop(0, '#161D2C'); halo.addColorStop(1, 'rgba(12,15,22,0)');
      ctx.fillStyle = halo; ctx.fillRect(0, 0, W, H);

      // muros y piso
      new Caja(-0.5, 0, -0.5, 0.5, FONDO, MURO + 0.5, P.muroX, { caras: { x: P.muroX, top: P.muroTope, y: tono(P.muroX, 0.75) } }).dibujar(ctx, v);
      new Caja(-0.5, -0.5, -0.5, ANCHO + 0.5, 0.5, MURO + 0.5, P.muroY, { caras: { y: P.muroY, top: P.muroTope, x: tono(P.muroY, 0.75) } }).dibujar(ctx, v);
      new Caja(0, 0, -0.5, ANCHO, FONDO, 0.5, P.piso, { caras: { top: P.piso, x: '#0F131C', y: '#121722' } }).dibujar(ctx, v);

      // piso: retícula, pasillo con cinta y números de lugar
      ctx.save(); v.planoZ(ctx, 0);
      ctx.strokeStyle = P.pisoLinea; ctx.lineWidth = 0.035;
      for (let i = 2; i < ANCHO; i += 2) { ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i, FONDO); ctx.stroke(); }
      for (let j = 2; j < FONDO; j += 2) { ctx.beginPath(); ctx.moveTo(0, j); ctx.lineTo(ANCHO, j); ctx.stroke(); }
      for (const yy of [CARRIL_Y - 0.6, CARRIL_Y + 0.6]) {
        for (let x = 8.2; x < ANCHO - 0.4; x += 0.8) { ctx.fillStyle = rgba(P.ambar, 0.55); ctx.fillRect(x, yy - 0.04, 0.4, 0.08); }
      }
      // charcos de luz
      const charco = (cx, cy, r, a) => {
        const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
        g.addColorStop(0, rgba(P.ambar, a)); g.addColorStop(1, rgba(P.ambar, 0));
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill();
      };
      charco(ASIENTOS.capataz.x + 1.5, ASIENTOS.capataz.y, 3.6, 0.16);
      for (const a of ASIENTOS.peon) charco(a.x - 1.2, a.y, 2.4, 0.1);
      if (op.puertaAbierta) {
        const g = ctx.createLinearGradient(0, 0, 0, 3.4);
        g.addColorStop(0, 'rgba(255,214,150,0.32)'); g.addColorStop(1, 'rgba(255,214,150,0)');
        ctx.fillStyle = g; ctx.beginPath(); ctx.moveTo(20.6, 0); ctx.lineTo(22.6, 0); ctx.lineTo(23.4, 3.4); ctx.lineTo(20.0, 3.4); ctx.closePath(); ctx.fill();
      }
      ASIENTOS.peon.forEach((a, i) => textoPlano(ctx, 'P' + (i + 1), a.x + 0.85, a.y + 0.95, 0.42, '500 {t} ' + FUENTE.mono, rgba(P.tenue, 0.55)));
      ctx.restore();

      // zoclos
      ctx.save(); v.planoY(ctx, 0); ctx.fillStyle = '#1F2738'; ctx.fillRect(0, -0.22, ANCHO, 0.22); ctx.restore();
      ctx.save(); v.planoX(ctx, 0); ctx.fillStyle = '#1A2130'; ctx.fillRect(-FONDO, -0.22, FONDO, 0.22); ctx.restore();

      // muro izquierdo (x = 0): pantalla del capataz y pizarrón
      ctx.save(); v.planoX(ctx, 0);
      // marco de la pantalla grande (el contenido se dibuja vivo)
      ctx.fillStyle = '#0A0D14'; ctx.fillRect(-9.4, -5.55, 4.6, 2.6);
      ctx.strokeStyle = '#2A3245'; ctx.lineWidth = 0.06; ctx.strokeRect(-9.4, -5.55, 4.6, 2.6);
      textoPlano(ctx, 'CAPATAZ', -9.3, -2.65, 0.28, '500 {t} ' + FUENTE.mono, P.tenue);
      // pizarrón
      ctx.fillStyle = '#8D96A6'; ctx.fillRect(-13.75, -5.2, 4.0, 2.7);
      ctx.fillStyle = '#E4E1D8'; ctx.fillRect(-13.65, -5.1, 3.8, 2.5);
      this._pizarron(ctx, -13.45, -4.68, latPiz);
      ctx.fillStyle = '#5A6070'; ctx.fillRect(-13.1, -2.5, 2.9, 0.08);
      ctx.fillStyle = '#2F6FD0'; ctx.fillRect(-12.6, -2.59, 0.4, 0.1);
      ctx.fillStyle = '#C0392B'; ctx.fillRect(-12.0, -2.59, 0.4, 0.1);
      ctx.restore();

      // muro del fondo (y = 0): puerta, perchero, reloj y calendario
      ctx.save(); v.planoY(ctx, 0);
      // puerta
      ctx.fillStyle = '#2A3245'; ctx.fillRect(20.45, -4.55, 2.3, 4.55);
      if (op.puertaAbierta) {
        const g = ctx.createLinearGradient(0, -4.4, 0, 0);
        g.addColorStop(0, '#3A3020'); g.addColorStop(1, '#6A5636');
        ctx.fillStyle = g; ctx.fillRect(20.6, -4.4, 2.0, 4.4);
        ctx.fillStyle = '#3A4458'; ctx.fillRect(20.6, -4.4, 0.35, 4.4);
      } else {
        ctx.fillStyle = '#3A4458'; ctx.fillRect(20.6, -4.4, 2.0, 4.4);
        ctx.fillStyle = '#2E3648'; ctx.fillRect(20.8, -4.2, 1.6, 4.0);
        ctx.fillStyle = '#5E7590'; ctx.fillRect(21.0, -3.9, 1.2, 0.9);
        ctx.fillStyle = '#B8C0CC'; ctx.fillRect(22.2, -2.2, 0.22, 0.1);
      }
      for (let u = 20.6; u < 22.6; u += 0.4) { ctx.fillStyle = P.ambar; ctx.fillRect(u, -0.42, 0.2, 0.42); ctx.fillStyle = '#1A1410'; ctx.fillRect(u + 0.2, -0.42, 0.2, 0.42); }
      // perchero con los cascos que quedan
      ctx.fillStyle = '#5A4632'; ctx.fillRect(16.1, -4.55, 3.5, 0.16);
      for (let i = 0; i < 5; i++) {
        const cu = 16.45 + i * 0.7;
        ctx.fillStyle = '#3A2E22'; ctx.fillRect(cu - 0.03, -4.39, 0.06, 0.2);
        if (i < op.cascos) {
          ctx.fillStyle = '#F2A93B';
          ctx.beginPath(); ctx.ellipse(cu, -3.98, 0.28, 0.22, 0, Math.PI, 0); ctx.fill();
          ctx.fillStyle = '#D18F2B'; ctx.fillRect(cu - 0.34, -3.99, 0.68, 0.07);
        }
      }
      // reloj digital
      ctx.fillStyle = '#0A0D14'; ctx.fillRect(5.2, -6.0, 2.4, 0.9);
      ctx.strokeStyle = '#2A3245'; ctx.lineWidth = 0.05; ctx.strokeRect(5.2, -6.0, 2.4, 0.9);
      const hh = String(fecha.getHours()).padStart(2, '0'), mm = String(fecha.getMinutes()).padStart(2, '0');
      textoPlano(ctx, hh + ':' + mm, 6.4, -5.32, 0.6, '500 {t} ' + FUENTE.mono, P.menta, 'center');
      // calendario
      const MESES = ['ENE', 'FEB', 'MAR', 'ABR', 'MAY', 'JUN', 'JUL', 'AGO', 'SEP', 'OCT', 'NOV', 'DIC'];
      ctx.fillStyle = '#E4E1D8'; ctx.fillRect(3.6, -4.4, 1.05, 1.25);
      ctx.fillStyle = '#C0392B'; ctx.fillRect(3.6, -4.4, 1.05, 0.32);
      textoPlano(ctx, MESES[fecha.getMonth()], 4.12, -4.15, 0.22, '500 {t} ' + FUENTE.mono, '#FFFFFF', 'center');
      textoPlano(ctx, String(fecha.getDate()), 4.12, -3.33, 0.6, '800 {t} ' + FUENTE.display, '#1A1410', 'center');
      ctx.restore();
    }

    _pizarron(ctx, u, v, lat) {
      const azul = '#1F4E9A', rojo = '#B3261E';
      const mono = '500 {t} ' + FUENTE.mono;
      textoPlano(ctx, 'LATIGAZOS', u, v, 0.3, '800 {t} ' + FUENTE.display, azul);
      const n = Math.min(lat.latigazos || 0, 20);
      ctx.strokeStyle = rojo; ctx.lineWidth = 0.05; ctx.lineCap = 'round';
      const ty = v + 0.5;
      for (let i = 0; i < n; i++) {
        const g = Math.floor(i / 5), k = i % 5;
        const bu = u + 0.05 + g * 0.72;
        ctx.beginPath();
        if (k < 4) { ctx.moveTo(bu + k * 0.12, ty - 0.32); ctx.lineTo(bu + k * 0.12, ty + 0.02); } else { ctx.moveTo(bu - 0.08, ty - 0.02); ctx.lineTo(bu + 0.46, ty - 0.3); }
        ctx.stroke();
      }
      if (!n) textoPlano(ctx, 'sin latigazos', u, ty, 0.26, mono, '#8D96A6');
      textoPlano(ctx, 'NIVEL ' + (lat.nivel || 0) + '   TECHO ' + (lat.techo || 0), u, v + 1.02, 0.27, mono, azul);
      textoPlano(ctx, 'PEONES ' + (lat.peones_activos || 0) + '/' + (lat.techo || 0), u, v + 1.47, 0.27, mono, lat.peones_activos ? rojo : azul);
      if (lat.enfriando) textoPlano(ctx, 'CALMA ' + lat.enfriando + ' S', u, v + 1.92, 0.27, mono, '#8A6A00');
      else if (lat.pendiente) textoPlano(ctx, 'EN CAMINO…', u, v + 1.92, 0.27, mono, rojo);
    }

    // ------------------------------------------------ lo vivo de los muros

    _ventana(ctx, fecha, ms) {
      const v = VISTA;
      const hora = fecha.getHours() + fecha.getMinutes() / 60;
      const per = hora >= 7 && hora < 17.5 ? 'dia' : hora >= 17.5 && hora < 19.5 ? 'tarde' : hora >= 5.5 && hora < 7 ? 'amanecer' : 'noche';
      const cielos = { dia: ['#5FA8E0', '#BFE3F7'], tarde: ['#3B2A5C', '#F08A4B'], amanecer: ['#2B2F5C', '#F29E6A'], noche: ['#070A14', '#2A2338'] };
      const [c1, c2] = cielos[per];
      const u0 = 9.5, u1 = 18.5, v0 = -5.9, v1 = -2.4;
      ctx.save(); v.planoY(ctx, 0);
      ctx.translate(8.2, -5.3); ctx.scale(0.8, 0.886); ctx.translate(-9.5, 5.9);
      ctx.beginPath(); ctx.rect(u0, v0, u1 - u0, v1 - v0); ctx.save(); ctx.clip();
      const g = ctx.createLinearGradient(0, v0, 0, v1); g.addColorStop(0, c1); g.addColorStop(1, c2);
      ctx.fillStyle = g; ctx.fillRect(u0, v0, u1 - u0, v1 - v0);
      const r = F.aleatorio(7);
      if (per === 'noche') {
        for (let i = 0; i < 30; i++) {
          const su = u0 + r() * (u1 - u0), sv = v0 + 0.1 + r() * 1.8, rr = 0.02 + r() * 0.035, ff = r() * 6;
          ctx.fillStyle = rgba('#E9E4DA', 0.35 + 0.55 * (0.5 + 0.5 * Math.sin(ms / 900 + ff)));
          ctx.beginPath(); ctx.arc(su, sv, rr, 0, Math.PI * 2); ctx.fill();
        }
        ctx.fillStyle = '#F2EED8'; ctx.beginPath(); ctx.arc(17.4, -5.2, 0.28, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = c1; ctx.beginPath(); ctx.arc(17.52, -5.27, 0.24, 0, Math.PI * 2); ctx.fill();
      } else if (per === 'dia') {
        for (let k = 0; k < 3; k++) {
          const cu = u0 - 1 + (((ms / 2600) + k * 3.4) % (u1 - u0 + 2)), cv = v0 + 0.5 + k * 0.45;
          ctx.fillStyle = 'rgba(245,250,255,0.9)';
          ctx.beginPath(); ctx.ellipse(cu, cv, 0.6, 0.16, 0, 0, Math.PI * 2); ctx.ellipse(cu + 0.25, cv - 0.12, 0.35, 0.14, 0, 0, Math.PI * 2); ctx.fill();
        }
      } else {
        ctx.fillStyle = '#FFD27A'; ctx.beginPath(); ctx.arc(11.2, -3.2, 0.38, 0, Math.PI * 2); ctx.fill();
      }
      // volcán con fumarola
      const volcan = per === 'noche' ? '#1F2436' : per === 'dia' ? '#7E97AD' : '#4A3550';
      ctx.fillStyle = volcan;
      ctx.beginPath(); ctx.moveTo(13.6, v1); ctx.lineTo(15.75, -4.85); ctx.lineTo(16.55, -4.95); ctx.lineTo(18.9, v1); ctx.closePath(); ctx.fill();
      ctx.fillStyle = per === 'noche' ? '#7E869A' : '#F4F6F9';
      ctx.beginPath(); ctx.moveTo(15.45, -4.5); ctx.lineTo(15.75, -4.85); ctx.lineTo(16.55, -4.95); ctx.lineTo(16.9, -4.45); ctx.lineTo(16.45, -4.6); ctx.lineTo(16.05, -4.35); ctx.lineTo(15.75, -4.55); ctx.closePath(); ctx.fill();
      if (!this.reducido) {
        for (let k = 0; k < 4; k++) {
          const t = ((ms / 6000) + k / 4) % 1;
          ctx.fillStyle = rgba('#8D96A6', 0.35 * Math.sin(t * Math.PI));
          ctx.beginPath(); ctx.arc(16.1 + t * 0.9, -5.0 - t * 2.2, 0.15 + t * 0.55, 0, Math.PI * 2); ctx.fill();
        }
      }
      // ciudad
      const lejos = per === 'noche' ? '#10141F' : per === 'dia' ? '#5F7F99' : '#3A2A40';
      const rc = F.aleatorio(11);
      let x = u0 - 0.1;
      while (x < u1) {
        const bw = 0.45 + rc() * 0.55, bh = 0.5 + rc() * 1.7, top = v1 - bh;
        ctx.fillStyle = lejos; ctx.fillRect(x, top, bw, bh);
        for (let wy = 0; wy < Math.floor(bh / 0.22); wy++) {
          for (let wx = 0; wx < Math.floor(bw / 0.18); wx++) {
            const on = rc();
            if (per !== 'dia' && on < 0.22) { ctx.fillStyle = rgba(P.ambar, 0.35 + on * 2.5); ctx.fillRect(x + 0.08 + wx * 0.18, top + 0.12 + wy * 0.22, 0.07, 0.09); }
          }
        }
        x += bw + 0.02 + rc() * 0.1;
      }
      // torre con luz de obstrucción
      ctx.fillStyle = per === 'dia' ? '#4F6A80' : '#121726';
      ctx.fillRect(11.2, -5.0, 0.6, 2.6); ctx.fillRect(11.46, -5.5, 0.08, 0.5);
      if (per !== 'dia' && Math.floor(ms / 800) % 2) { ctx.fillStyle = '#FF5A4F'; ctx.beginPath(); ctx.arc(11.5, -5.55, 0.08, 0, Math.PI * 2); ctx.fill(); }
      ctx.restore();
      // marco
      ctx.strokeStyle = '#2A3245'; ctx.lineWidth = 0.22; ctx.strokeRect(u0, v0, u1 - u0, v1 - v0);
      ctx.fillStyle = '#2A3245'; ctx.fillRect(13.95, v0, 0.12, v1 - v0);
      ctx.fillStyle = '#323B50'; ctx.fillRect(u0 - 0.2, v1, u1 - u0 + 0.4, 0.22);
      ctx.restore();
      return per;
    }

    _neon(ctx, ms) {
      const v = VISTA;
      const t = (ms / 7000) % 1;
      const parpadeo = (t > 0.86 && t < 0.87) || (t > 0.88 && t < 0.885) ? 0.35 : 1;
      ctx.save(); v.planoX(ctx, 0);
      ctx.globalAlpha = parpadeo;
      ctx.shadowColor = P.ambar; ctx.shadowBlur = 18 * this.escala * this.dpr;
      textoPlano(ctx, 'LA CASETA', -4.55, -4.55, 0.82, '800 {t} ' + FUENTE.display, P.ambar);
      ctx.shadowBlur = 0;
      textoPlano(ctx, 'LA CASETA', -4.55, -4.55, 0.82, '800 {t} ' + FUENTE.display, '#FFD9A0');
      ctx.restore();
    }

    _pantallaCapataz(ctx, ms) {
      const v = VISTA;
      const cap = [...this.personajes.values()].find((p) => p.rol === 'capataz');
      const cat = cap ? cap.agente.cat : 'durmiendo';
      ctx.save(); v.planoX(ctx, 0);
      F.pantalla(ctx, -9.3, -4.9, -5.45, -3.05, cat, ms, 17);
      ctx.restore();
    }

    // ------------------------------------------------ dibujo

    _dibujar(ms) {
      const ctx = this.ctx;
      const fecha = new Date();
      const lat = this.sesion ? this.sesion.latigo || {} : {};
      const ahoraSeg = Date.now() / 1000;
      const enfriando = lat.enfriamiento_hasta && lat.enfriamiento_hasta > ahoraSeg ? Math.ceil(lat.enfriamiento_hasta - ahoraSeg) : 0;
      const latPiz = { latigazos: lat.latigazos || 0, nivel: lat.nivel || 0, techo: lat.techo || 0, peones_activos: lat.peones_activos || 0, enfriando, pendiente: !!lat.pendiente };
      const puertaAbierta = ms < this.puertaHasta;
      const peones = [...this.personajes.values()].filter((p) => p.rol === 'peon').length;
      const cascos = Math.max(0, 5 - peones);
      const clave = [fecha.getHours(), fecha.getMinutes(), fecha.getDate(), JSON.stringify(latPiz), puertaAbierta, cascos, this.canvas.width].join('|');
      if (clave !== this.fondoClave) {
        const c2 = this.fondoCache.getContext('2d');
        this._base(c2);
        this._fondo(c2, fecha, latPiz, { puertaAbierta, cascos });
        this.fondoClave = clave;
      }
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      let dx = 0, dy = 0;
      if (this.temblor > 0) {
        dx = Math.round((Math.random() - 0.5) * this.temblor * this.dpr);
        dy = Math.round((Math.random() - 0.5) * this.temblor * this.dpr);
        this.temblor = Math.max(0, this.temblor - 1);
      }
      ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
      ctx.drawImage(this.fondoCache, dx, dy);
      this._base(ctx);
      ctx.translate(dx / (this.escala * this.dpr), dy / (this.escala * this.dpr));

      this._ventana(ctx, fecha, ms);
      this._neon(ctx, ms);
      this._pantallaCapataz(ctx, ms);

      // muebles y gente, ordenados por profundidad
      const piezas = this.fijos.slice();
      const ocupados = new Set();
      for (const p of this.personajes.values()) {
        if (p.sentado && !p.saliendo) ocupados.add(p.asiento);
        this._persona(piezas, p, ms);
      }
      ASIENTOS.peon.forEach((a, i) => piezas.push(this._monitor(a, i, ocupados.has(a) ? this._quienEnAsiento(a) : null, ms)));
      ASIENTOS.ayudante.forEach((a) => piezas.push(this._laptopAyudante(a, ocupados.has(a) ? this._quienEnAsiento(a) : null, ms)));
      for (const pz of ordenar(VISTA, piezas)) pz.dibujar(ctx, VISTA);

      this._lamparas(ctx, ms);
      if (this.vacia) this._letreroVacio(ctx);
      this._latigoDelCapataz(ctx, ms);
      for (const q of this.particulas) { ctx.fillStyle = q.color; ctx.fillRect(q.x - 1.5, q.y - 1.5, 3, 3); }
      for (const t of this.textos) {
        const grande = t.vida > t.total - 120;
        ctx.save();
        ctx.font = '800 ' + (grande ? 34 : 28) + 'px ' + FUENTE.display;
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.lineWidth = 6; ctx.strokeStyle = '#0C0F16'; ctx.lineJoin = 'round';
        ctx.globalAlpha = Math.min(1, t.vida / 200);
        ctx.strokeText(t.texto, t.x, t.y); ctx.fillStyle = t.color; ctx.fillText(t.texto, t.x, t.y);
        ctx.restore();
      }
      if (this.raton.dentro || this.auto) this.latigo.dibujar(ctx);
      if (this.hover && this.raton.dentro && !this.auto) {
        const [hx, hy] = this._cabeza(this.hover);
        ctx.fillStyle = P.ambar;
        ctx.beginPath(); ctx.moveTo(hx - 8, hy - 30); ctx.lineTo(hx + 8, hy - 30); ctx.lineTo(hx, hy - 20); ctx.closePath(); ctx.fill();
      }
    }

    _quienEnAsiento(a) {
      for (const p of this.personajes.values()) if (p.sentado && !p.saliendo && p.asiento === a) return p;
      return null;
    }

    _persona(piezas, p, ms) {
      const pose = this._pose(p, ms);
      const sentado = p.sentado && !p.saliendo;
      const a = sentado ? p.asiento : null;
      const f = Math.floor(ms / (pose === 'teclear' ? 120 : pose === 'caminar' ? 160 : 380));
      let mirar = 0;
      if (p.agente.cat === 'esperando_peones') mirar = Math.floor(ms / 1500) % 2 ? 1 : -1;
      let alfa;
      if (p.saliendo && p.ruta.length === 1) alfa = Math.max(0.15, Math.min(1, Math.hypot(PUERTA.x - p.x, PUERTA.y - p.y) / 1.2));
      const salto = pose === 'dolor' ? (f % 2 ? 0.14 : 0.24) : pose === 'asustado' ? 0.12 : 0;
      const cajas = F.figura(p.look, pose, {
        x: p.x, y: p.y, z: a ? a.z : 0, dir: sentado ? a.dir : p.dir, sentado, f, parpadeo: ms < p.parpadeoHasta, mirar, alfa, salto,
        latigoEnMano: p.rol === 'capataz',
      });
      for (const c of cajas) piezas.push(c);
      // Zzz y lágrima de error, encima de la cabeza
      const cat = p.agente.cat;
      if (sentado && (cat === 'durmiendo' || (cat === 'error' && !p.reaccion))) {
        const zc = (a ? a.z : 0) + F.alturaCabeza(true);
        piezas.push(new Pieza([p.x - 0.3, p.y - 0.3, zc, p.x + 0.3, p.y + 0.3, zc + 0.5], (ctx) => {
          const [hx, hy] = VISTA.p(p.x, p.y, zc);
          ctx.save();
          if (cat === 'durmiendo') {
            const k = (ms / 700) % 3;
            ctx.font = '800 ' + (14 + k * 3) + 'px ' + FUENTE.display; ctx.fillStyle = '#C9D6E8';
            ctx.globalAlpha = 1 - k / 3.2;
            ctx.fillText('Z', hx + 16 + k * 6, hy - 6 - k * 10);
          } else {
            ctx.fillStyle = '#6FC3F3'; ctx.beginPath(); ctx.ellipse(hx + 10, hy + 14, 2.5, 4, 0, 0, Math.PI * 2); ctx.fill();
          }
          ctx.restore();
        }));
      }
    }

    _monitor(a, i, quien, ms) {
      const cat = quien ? quien.agente.cat : 'durmiendo';
      const semilla = quien ? quien.semilla : (i + 1) * 7;
      const x0 = a.x - 2.55;
      return new Caja(x0 + 0.18, a.y - 0.98, 2.02, 0.16, 1.96, 1.18, F.COLOR.oscuro, {
        sobre: { x: (ctx, u0, u1, v0, v1) => {
          F.pantalla(ctx, u0 + 0.07, u1 - 0.07, v0 + 0.07, v1 - 0.07, cat, ms, semilla);
          if (cat === 'permiso' || cat === 'pregunta') { ctx.fillStyle = '#FF5A4F'; ctx.beginPath(); ctx.arc(u1 - 0.14, v1 - 0.12, 0.05, 0, Math.PI * 2); ctx.fill(); }
        } },
      });
    }

    _laptopAyudante(a, quien, ms) {
      const cat = quien ? quien.agente.cat : 'durmiendo';
      const color = quien ? F.colorEstado(cat) : '#1C2230';
      return new Caja(a.x + 1.75, a.y - 0.48, 1.58, 0.07, 0.96, 0.62, '#4A5468', {
        sobre: { x: (ctx, u0, u1, v0, v1) => {
          if (!quien) return;
          const pulso = 0.55 + 0.35 * Math.sin(ms / 500);
          ctx.fillStyle = rgba(color, pulso);
          ctx.beginPath(); ctx.arc((u0 + u1) / 2, (v0 + v1) / 2, 0.1, 0, Math.PI * 2); ctx.fill();
        } },
      });
    }

    _lamparas(ctx, ms) {
      const v = VISTA;
      const puntos = [[ASIENTOS.capataz.x + 1.5, ASIENTOS.capataz.y]].concat(ASIENTOS.peon.map((a) => [a.x - 1.2, a.y]));
      for (const [cx, cy] of puntos) {
        const [tx, ty] = v.p(cx, cy, 9.5);
        const [lx, ly] = v.p(cx, cy, 6.6);
        const r = 1.35;
        const [ax, ay] = v.p(cx - r, cy + r, 1.7);
        const [bx, by] = v.p(cx + r, cy - r, 1.7);
        ctx.strokeStyle = '#2A3245'; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(tx, ty); ctx.lineTo(lx, ly); ctx.stroke();
        const g = ctx.createLinearGradient(lx, ly, lx, (ay + by) / 2);
        g.addColorStop(0, rgba(P.ambar, 0.22)); g.addColorStop(1, rgba(P.ambar, 0));
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.moveTo(lx - 7, ly + 6); ctx.lineTo(lx + 7, ly + 6); ctx.lineTo(bx, by); ctx.lineTo(ax, ay); ctx.closePath(); ctx.fill();
        ctx.fillStyle = '#2E3648';
        ctx.beginPath(); ctx.moveTo(lx - 13, ly + 6); ctx.lineTo(lx - 5, ly - 6); ctx.lineTo(lx + 5, ly - 6); ctx.lineTo(lx + 13, ly + 6); ctx.closePath(); ctx.fill();
        ctx.fillStyle = P.ambar; ctx.beginPath(); ctx.ellipse(lx, ly + 6, 11, 3, 0, 0, Math.PI * 2); ctx.fill();
      }
      if (this.reducido) return;
      for (const d of this.polvo) {
        const k = ((ms / 1000 + d.fase) % d.dur) / d.dur;
        const [cx, cy] = puntos[Math.floor(d.lx * puntos.length) % puntos.length];
        const [x, y] = v.p(cx - 0.8 + d.ly * 1.6, cy - 0.8 + d.lz * 1.6, 2.2 + k * 3.5);
        ctx.fillStyle = rgba(P.ambar, 0.45 * Math.sin(k * Math.PI));
        ctx.fillRect(x, y, 2, 2);
      }
    }

    _letreroVacio(ctx) {
      const [x, y] = VISTA.p(12.5, 7.5, 0.1);
      ctx.save();
      ctx.translate(x, y - 40);
      ctx.fillStyle = '#0C0F16'; ctx.fillRect(-170, -30, 340, 60);
      ctx.fillStyle = P.ambar; ctx.fillRect(-164, -24, 328, 48);
      ctx.save(); ctx.beginPath(); ctx.rect(-164, 14, 328, 10); ctx.clip();
      ctx.fillStyle = '#1A1410';
      for (let u = -170; u < 170; u += 16) { ctx.beginPath(); ctx.moveTo(u, 24); ctx.lineTo(u + 8, 24); ctx.lineTo(u + 18, 14); ctx.lineTo(u + 10, 14); ctx.closePath(); ctx.fill(); }
      ctx.restore();
      ctx.font = '800 24px ' + FUENTE.display; ctx.fillStyle = '#1A1410'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('CASETA CERRADA', 0, -4);
      ctx.restore();
    }

    // ------------------------------------------------ globos (HTML, texto nítido)

    _globos(ms) {
      const e = this.escala;
      const compacto = e < 0.62;
      for (const p of this.personajes.values()) {
        const ag = p.agente;
        let tipo = 'accion', icono = ag.icono, txt = ag.texto, detalle = ag.detalle || '';
        if (p.reaccion && p.reaccion.globo) { tipo = p.reaccion.grita ? 'grito' : 'reaccion'; icono = ''; txt = p.reaccion.globo; }
        else if (ag.globo) { tipo = ag.globo.tipo === 'dijo' ? 'dijo' : 'piensa'; icono = ag.globo.tipo === 'dijo' ? '💬' : '💭'; txt = ag.globo.texto; }
        else if (!p.sentado && !p.saliendo) { icono = '🚶'; txt = ag.tarea ? 'Va a: ' + ag.tarea : 'Llegando…'; }
        else if (p.saliendo) { icono = '👋'; txt = 'Ya se va'; }
        if (tipo === 'accion') txt = acortarRutas(txt);
        const enfoque = this.hover === p;
        const atencion = ag.cat === 'permiso' || ag.cat === 'pregunta' || ag.cat === 'plan';
        const falla = ag.cat === 'error' && tipo === 'accion';
        const hueco = p.rol === 'capataz' ? 300 : p.rol === 'peon' ? 170 : 150;
        const ancho = enfoque || tipo === 'grito' || tipo === 'reaccion' ? Math.max(170, hueco * e) : Math.max(70, hueco * e - 4);
        const clave = [tipo, icono, txt, compacto, enfoque, atencion, falla, ancho].join('|');
        if (clave !== p._globoClave) {
          p._globoClave = clave;
          const g = p.globo;
          g.className = 'globo globo-' + tipo + (atencion ? ' atencion' : '') + (falla ? ' falla' : '') + (enfoque ? ' enfoque' : '') + (p.rol === 'capataz' ? ' de-capataz' : '');
          g.textContent = '';
          g.style.maxWidth = ancho + 'px';
          if (icono) { const i = document.createElement('span'); i.className = 'icono'; i.textContent = icono; g.appendChild(i); }
          if (!compacto || enfoque || tipo === 'grito' || tipo === 'reaccion') {
            const s2 = document.createElement('span'); s2.className = 'texto'; s2.textContent = txt; g.appendChild(s2);
          }
          g.title = detalle && detalle !== txt ? txt + '\n' + detalle : txt;
        }
        const [hx, hy] = this._cabeza(p);
        const gx = Math.round(hx * e), gy = Math.round((hy - 12) * e);
        const frac = hx < 90 ? 18 : hx > W - 90 ? 82 : 50;
        if (p._gx !== gx || p._gy !== gy || p._frac !== frac) {
          p._gx = gx; p._gy = gy; p._frac = frac;
          p.globo.style.transform = 'translate(' + gx + 'px,' + gy + 'px) translate(-' + frac + '%,-100%)';
          p.globo.style.setProperty('--cola', frac + '%');
        }
      }
    }
  }

  function acortarRutas(txt) {
    return String(txt || '').replace(/(?:[\w.@~-]+\/)+([\w.@-]+)/g, '$1');
  }

  global.OficinaIso = Oficina;
  global.OficinaIso.ASIENTOS = ASIENTOS;
  global.RetratoIso = F.retrato;
})(window);
