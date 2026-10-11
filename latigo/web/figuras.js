/* Figuras de la caseta isométrica: gente de bloques con poses, pantallas por estado y el retrato del panel. */
'use strict';
(function (global) {
  const { Caja, Vista, tono, pintar } = global.Iso;

  const COLOR = {
    tinta: '#1A1410',
    boca: '#7A2E22',
    papel: '#E9E4DA',
    ambar: '#FFB547',
    menta: '#6FE3D0',
    rojo: '#FF6B5E',
    verde: '#3FB950',
    azul: '#6CB6FF',
    lila: '#C9A3FF',
    pantalla: '#0B1A1F',
    oscuro: '#1C2230',
    metal: '#3B4458',
  };

  // ---------------------------------------------------------------- azar con semilla

  function hash(s) {
    let h = 2166136261;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }
  function aleatorio(semilla) {
    let a = semilla >>> 0 || 1;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // ---------------------------------------------------------------- looks

  const PIELES = ['#C98E66', '#B97A56', '#A86B45', '#8D5A3B', '#D9A47C', '#7A4A2E'];
  const PELOS = ['#1A1410', '#2B1E16', '#3B2A1E', '#151515', '#4A3526'];
  const CASCOS = ['#F2A93B', '#F2A93B', '#F2A93B', '#E8833A', '#F4C542'];
  const CAMISAS = ['#3E5078', '#4A5F86', '#3A6670', '#57507A', '#6A5E50', '#3C5A78'];
  const PANTALONES = ['#2A3248', '#30384F', '#3A332C', '#2A3838'];
  const CHALECO = '#E8833A';

  function lookPara(agente) {
    const rnd = aleatorio(hash(String(agente.id) + ':' + (agente.tipo || '')));
    const de = (lista) => lista[Math.floor(rnd() * lista.length)];
    if (agente.rol === 'capataz') {
      return { piel: '#A9714C', pelo: '#1A1410', casco: '#E9E4DA', camisa: '#D9D2C4', chaleco: null,
        pantalon: '#2A3248', botas: '#2A1F18' };
    }
    if (agente.rol === 'peon') {
      const sombrero = rnd() < 0.8 ? 'casco' : 'gorra';
      return { piel: de(PIELES), pelo: de(PELOS), casco: sombrero === 'casco' ? de(CASCOS) : null,
        gorra: sombrero === 'gorra' ? de(['#B5473A', '#2F5F8A', '#2C3E50']) : null,
        camisa: de(CAMISAS), chaleco: rnd() < 0.55 ? CHALECO : null, pantalon: de(PANTALONES), botas: '#2A1F18',
        bigote: rnd() < 0.2 };
    }
    const tipo = agente.tipo || '';
    if (tipo === 'Explore') return { piel: de(PIELES), pelo: de(PELOS), casco: COLOR.menta, camisa: '#4A5560', chaleco: '#B5D334', pantalon: '#232A3B', botas: '#2A1F18' };
    if (tipo === 'Plan') return { piel: de(PIELES), pelo: '#9AA0A6', casco: null, camisa: '#6E8FB0', chaleco: null, pantalon: '#1E2333', botas: '#2A1F18', lentes: true };
    if (tipo === 'fork') return { piel: '#A9714C', pelo: '#1A1410', casco: '#F4E7C4', camisa: '#C9C2B4', chaleco: null, pantalon: '#1E2333', botas: '#2A1F18' };
    return { piel: de(PIELES), pelo: de(PELOS), casco: rnd() < 0.5 ? COLOR.azul : null, camisa: de(CAMISAS), chaleco: null,
      pantalon: de(PANTALONES), botas: '#2A1F18', lentes: rnd() < 0.3 };
  }

  // ---------------------------------------------------------------- caras

  function ojos(ctx, u0, u1, v0, look, gesto, mirar) {
    const cu = (u0 + u1) / 2 + mirar * 0.035;
    const vy = v0 + 0.25;
    ctx.fillStyle = COLOR.tinta;
    if (gesto === 'dolor') {
      ctx.strokeStyle = COLOR.tinta; ctx.lineWidth = 0.035; ctx.lineCap = 'round';
      for (const dx of [-0.12, 0.12]) {
        ctx.beginPath();
        ctx.moveTo(cu + dx - 0.045, vy - 0.045); ctx.lineTo(cu + dx + 0.045, vy + 0.045);
        ctx.moveTo(cu + dx + 0.045, vy - 0.045); ctx.lineTo(cu + dx - 0.045, vy + 0.045);
        ctx.stroke();
      }
    } else if (gesto === 'cerrados') {
      ctx.fillRect(cu - 0.17, vy + 0.01, 0.1, 0.028); ctx.fillRect(cu + 0.07, vy + 0.01, 0.1, 0.028);
    } else {
      ctx.fillRect(cu - 0.15, vy - 0.035, 0.065, 0.08); ctx.fillRect(cu + 0.085, vy - 0.035, 0.065, 0.08);
    }
    if (look.lentes && gesto !== 'cerrados') {
      ctx.strokeStyle = '#0E0F12'; ctx.lineWidth = 0.022;
      ctx.strokeRect(cu - 0.2, vy - 0.07, 0.15, 0.14); ctx.strokeRect(cu + 0.05, vy - 0.07, 0.15, 0.14);
      ctx.beginPath(); ctx.moveTo(cu - 0.05, vy - 0.02); ctx.lineTo(cu + 0.05, vy - 0.02); ctx.stroke();
    }
  }

  function boca(ctx, cu, vy, look, gesto, f) {
    if (look.bigote) { ctx.fillStyle = look.pelo; ctx.fillRect(cu - 0.12, vy - 0.06, 0.24, 0.045); }
    if (gesto === 'abierta' || (gesto === 'habla' && f % 2)) {
      ctx.fillStyle = COLOR.boca; ctx.fillRect(cu - 0.05, vy - 0.01, 0.1, 0.08);
    } else if (gesto === 'sonrisa') {
      ctx.strokeStyle = COLOR.boca; ctx.lineWidth = 0.03; ctx.lineCap = 'round';
      ctx.beginPath(); ctx.moveTo(cu - 0.09, vy); ctx.quadraticCurveTo(cu, vy + 0.07, cu + 0.09, vy); ctx.stroke();
    } else {
      ctx.fillStyle = tono(look.piel, 0.72); ctx.fillRect(cu - 0.07, vy + 0.01, 0.14, 0.03);
    }
  }

  /** Dibuja la cara según qué lado de la cabeza ve la cámara. */
  function caraFrente(look, gesto, ojosGesto, mirar, f) {
    return (ctx, u0, u1, v0) => {
      ojos(ctx, u0, u1, v0, look, ojosGesto, mirar);
      boca(ctx, (u0 + u1) / 2, v0 + 0.42, look, gesto, f);
    };
  }
  function caraLado(look, gesto, ojosGesto, adelanteDerecha, f) {
    return (ctx, u0, u1, v0, v1) => {
      const ancho = u1 - u0;
      // pelo de la nuca
      ctx.fillStyle = look.pelo;
      if (adelanteDerecha) ctx.fillRect(u0, v0, ancho * 0.3, (v1 - v0) * 0.55); else ctx.fillRect(u1 - ancho * 0.3, v0, ancho * 0.3, (v1 - v0) * 0.55);
      // oreja
      ctx.fillStyle = tono(look.piel, 0.82);
      ctx.fillRect((u0 + u1) / 2 - 0.05, v0 + 0.22, 0.1, 0.14);
      // ojo y boca cerca del frente
      const ojoU = adelanteDerecha ? u1 - 0.13 : u0 + 0.07;
      ctx.fillStyle = COLOR.tinta;
      if (ojosGesto === 'cerrados') ctx.fillRect(ojoU, v0 + 0.25, 0.07, 0.025);
      else if (ojosGesto === 'dolor') { ctx.fillRect(ojoU, v0 + 0.21, 0.025, 0.09); ctx.fillRect(ojoU - 0.03, v0 + 0.245, 0.09, 0.025); }
      else ctx.fillRect(ojoU, v0 + 0.21, 0.06, 0.08);
      if (look.lentes && ojosGesto !== 'cerrados') { ctx.fillStyle = '#0E0F12'; ctx.fillRect(adelanteDerecha ? ojoU - 0.12 : ojoU + 0.05, v0 + 0.22, 0.13, 0.022); }
      const bocaU = adelanteDerecha ? u1 - 0.1 : u0 + 0.02;
      if (gesto === 'abierta' || (gesto === 'habla' && f % 2)) { ctx.fillStyle = COLOR.boca; ctx.fillRect(bocaU, v0 + 0.41, 0.08, 0.07); }
      else { ctx.fillStyle = tono(look.piel, 0.72); ctx.fillRect(bocaU, v0 + 0.43, 0.08, 0.025); }
      if (look.bigote) { ctx.fillStyle = look.pelo; ctx.fillRect(bocaU - 0.01, v0 + 0.37, 0.1, 0.04); }
    };
  }
  function nuca(look) {
    return (ctx, u0, u1, v0, v1) => {
      ctx.fillStyle = look.pelo;
      ctx.fillRect(u0, v0, u1 - u0, (v1 - v0) * 0.7);
    };
  }

  // ---------------------------------------------------------------- figura

  /* dir: 0 mira a +x, 1 a +y, 2 a -x, 3 a -y. Se construye en coordenadas locales:
     u hacia adelante, w a los lados; luego se rota a mundo. */
  function marco(x, y, dir) {
    return function (u0, u1, w0, w1) {
      switch (dir) {
        case 0: return [x + u0, y + w0, u1 - u0, w1 - w0];
        case 2: return [x - u1, y - w1, u1 - u0, w1 - w0];
        case 1: return [x - w1, y + u0, w1 - w0, u1 - u0];
        default: return [x + w0, y - u1, w1 - w0, u1 - u0];
      }
    };
  }

  /** Lista de cajas de una persona.
      op: { x, y, z, dir, sentado, f, parpadeo, mirar, alfa, salto, latigoEnMano } */
  function figura(look, pose, op) {
    const dir = op.dir || 0;
    const f = op.f || 0;
    const sentado = !!op.sentado;
    const m = marco(op.x, op.y, dir);
    const z = (op.z || 0) + (op.salto || 0);
    const alfa = op.alfa;
    const cajas = [];
    const caja = (u0, u1, w0, w1, z0, z1, color, extra) => {
      const [x, y, w, d] = m(u0, u1, w0, w1);
      const o = extra || {};
      if (alfa !== undefined && alfa < 1) o.alfa = alfa;
      cajas.push(new Caja(x, y, z + z0, w, d, z1 - z0, color, o));
      return cajas[cajas.length - 1];
    };
    const piel = look.piel, manga = tono(look.camisa, 0.9);

    // altura de cada parte
    const zT0 = sentado ? 1.12 : 1.42;
    const zT1 = sentado ? 2.32 : 2.62;
    let zH0 = zT1 + 0.07;
    let uH = 0;
    if (pose === 'dormir') { zH0 -= 0.38; uH = 0.22; }

    // piernas
    if (sentado) {
      caja(-0.12, 0.62, -0.31, -0.04, 1.0, 1.22, look.pantalon);
      caja(-0.12, 0.62, 0.04, 0.31, 1.0, 1.22, look.pantalon);
      caja(0.48, 0.66, -0.29, -0.07, 0.18, 1.0, look.pantalon);
      caja(0.48, 0.66, 0.07, 0.29, 0.18, 1.0, look.pantalon);
      caja(0.46, 0.86, -0.3, -0.06, 0, 0.18, look.botas);
      caja(0.46, 0.86, 0.06, 0.3, 0, 0.18, look.botas);
    } else {
      let a = 0;
      if (pose === 'caminar') a = (f % 2 ? 1 : -1) * 0.16;
      caja(-0.13 + a, 0.13 + a, -0.3, -0.05, 0.2, zT0, look.pantalon);
      caja(-0.13 - a, 0.13 - a, 0.05, 0.3, 0.2, zT0, look.pantalon);
      caja(-0.14 + a, 0.24 + a, -0.31, -0.04, 0, 0.2, look.botas);
      caja(-0.14 - a, 0.24 - a, 0.04, 0.31, 0, 0.2, look.botas);
    }

    // torso (con chaleco pintado encima)
    const chaleco = look.chaleco;
    const pintaChaleco = chaleco ? (ctx, u0, u1, v0, v1) => {
      const an = u1 - u0;
      ctx.fillStyle = chaleco;
      ctx.fillRect(u0, v0, an * 0.3, v1 - v0); ctx.fillRect(u1 - an * 0.3, v0, an * 0.3, v1 - v0);
      ctx.fillStyle = '#E8E4DA';
      ctx.fillRect(u0, v0 + (v1 - v0) * 0.55, an * 0.3, 0.06); ctx.fillRect(u1 - an * 0.3, v0 + (v1 - v0) * 0.55, an * 0.3, 0.06);
    } : null;
    const pintaLado = chaleco ? (ctx, u0, u1, v0, v1) => {
      ctx.fillStyle = chaleco; ctx.fillRect(u0, v0, u1 - u0, v1 - v0);
      ctx.fillStyle = '#E8E4DA'; ctx.fillRect(u0, v0 + (v1 - v0) * 0.55, u1 - u0, 0.06);
    } : null;
    const sobreTorso = {};
    if (chaleco) {
      // la cara de frente o de espalda lleva los paneles; la de lado va completa
      const frontal = dir === 0 || dir === 2 ? 'x' : 'y';
      const lateral = frontal === 'x' ? 'y' : 'x';
      sobreTorso[frontal] = pintaChaleco; sobreTorso[lateral] = pintaLado;
    }
    caja(-0.21, 0.21, -0.42, 0.42, zT0, zT1, look.camisa, { sobre: sobreTorso });
    caja(-0.08, 0.1, -0.1, 0.1, zT1, zH0, tono(piel, 0.85));

    // brazos
    const zS = zT1 - 0.04;
    const mano = (u0, u1, w0, w1, z0, z1) => caja(u0, u1, w0, w1, z0, z1, piel);
    const colgado = (lado) => {
      const w0 = lado < 0 ? -0.6 : 0.42, w1 = lado < 0 ? -0.42 : 0.6;
      caja(-0.08, 0.12, w0, w1, zS - 0.72, zS, manga);
      mano(-0.06, 0.1, w0 + 0.02, w1 - 0.02, zS - 0.86, zS - 0.72);
    };
    const adelante = (lado, alto, largo, bob) => {
      const w0 = lado < 0 ? -0.58 : 0.4, w1 = lado < 0 ? -0.4 : 0.58;
      caja(-0.06, 0.14, w0, w1, zS - 0.42, zS, manga);
      caja(0.1, largo, w0, w1, zS - 0.48 + alto + bob, zS - 0.3 + alto + bob, manga);
      mano(largo, largo + 0.14, w0 + 0.02, w1 - 0.02, zS - 0.47 + alto + bob, zS - 0.31 + alto + bob);
    };
    const arriba = (lado, ola, alto) => {
      const w0 = lado < 0 ? -0.6 : 0.42, w1 = lado < 0 ? -0.42 : 0.6;
      const abre = lado * (alto ? 0.12 : 0);
      caja(-0.08 + ola, 0.1 + ola, w0 + abre, w1 + abre, zS - 0.05, zS + 0.68, manga);
      mano(-0.07 + ola, 0.09 + ola, w0 + 0.02 + abre, w1 - 0.02 + abre, zS + 0.68, zS + 0.84);
    };
    const bob = (k) => (pose === 'teclear' ? ((f + k) % 2) * 0.06 : 0);
    switch (pose) {
      case 'teclear':
        adelante(-1, 0, 0.6, bob(0)); adelante(1, 0, 0.6, bob(1)); break;
      case 'pensar':
        colgado(-1);
        caja(0.08, 0.3, 0.12, 0.3, zS - 0.5, zS - 0.32, manga);
        caja(0.24, 0.4, 0.02, 0.2, zS - 0.5, zH0 + 0.06, manga);
        mano(0.26, 0.42, 0.0, 0.18, zH0 + 0.02, zH0 + 0.18);
        break;
      case 'leer': {
        adelante(-1, 0.12, 0.42, 0); adelante(1, 0.12, 0.42, 0);
        const lineas = (ctx, u0, u1, v0, v1) => {
          ctx.fillStyle = '#9AA3B2';
          for (let i = 0; i < 5; i++) ctx.fillRect(u0 + 0.06, v0 + 0.08 + i * 0.09, (u1 - u0 - 0.12) * (0.55 + ((i + f) % 3) * 0.15), 0.03);
        };
        caja(0.5, 0.56, -0.34, 0.34, zS - 0.5, zS + 0.02, COLOR.papel, { sobre: { x: lineas, y: lineas } });
        break;
      }
      case 'mano':
        colgado(-1); arriba(1, f % 2 ? 0.07 : -0.07, false); break;
      case 'pulgar':
        colgado(-1);
        caja(-0.06, 0.4, 0.4, 0.58, zS - 0.3, zS - 0.12, manga);
        caja(0.3, 0.46, 0.4, 0.58, zS - 0.3, zS + 0.16, manga);
        mano(0.3, 0.48, 0.41, 0.57, zS + 0.16, zS + 0.32);
        mano(0.36, 0.44, 0.45, 0.53, zS + 0.32, zS + 0.44);
        break;
      case 'dormir':
        caja(0.1, 0.62, -0.5, 0.5, zS - 0.6, zS - 0.42, manga); break;
      case 'dolor': case 'asustado':
        arriba(-1, 0, true); arriba(1, 0, true); break;
      case 'senalar':
        colgado(-1);
        caja(-0.06, 0.95, 0.42, 0.6, zS - 0.2, zS - 0.02, manga);
        mano(0.95, 1.1, 0.43, 0.59, zS - 0.2, zS - 0.03);
        break;
      case 'latigo':
        colgado(-1);
        if (f % 2 === 0) {
          caja(-0.36, -0.1, 0.42, 0.6, zS - 0.05, zS + 0.72, manga);
          mano(-0.36, -0.18, 0.43, 0.59, zS + 0.72, zS + 0.88);
          caja(-0.32, -0.24, 0.47, 0.55, zS + 0.86, zS + 1.32, '#5A3A24');
        } else {
          caja(-0.06, 0.92, 0.42, 0.6, zS - 0.12, zS + 0.06, manga);
          mano(0.92, 1.08, 0.43, 0.59, zS - 0.12, zS + 0.05);
          caja(1.06, 1.5, 0.47, 0.55, zS - 0.08, zS, '#5A3A24');
        }
        break;
      case 'caminar': {
        const s = (f % 2 ? 1 : -1) * 0.14;
        for (const lado of [-1, 1]) {
          const w0 = lado < 0 ? -0.6 : 0.42, w1 = lado < 0 ? -0.42 : 0.6;
          const k = lado * s;
          caja(-0.08 + k, 0.12 + k, w0, w1, zS - 0.72, zS, manga);
          mano(-0.06 + k, 0.1 + k, w0 + 0.02, w1 - 0.02, zS - 0.86, zS - 0.72);
        }
        break;
      }
      default:
        colgado(-1); colgado(1);
    }
    if (op.latigoEnMano && pose !== 'latigo') {
      // látigo enrollado en el cinturón
      caja(-0.1, 0.12, 0.42, 0.52, zT0 + 0.05, zT0 + 0.35, '#5A3A24');
    }

    // cabeza
    const gesto = pose === 'dolor' || pose === 'asustado' ? 'abierta' : pose === 'pulgar' ? 'sonrisa' : pose === 'hablar' ? 'habla' : '';
    const ojosGesto = pose === 'dolor' ? 'dolor' : (pose === 'dormir' || op.parpadeo) ? 'cerrados' : '';
    const mirar = op.mirar || 0;
    let caraX, caraY;
    if (dir === 0) { caraX = caraFrente(look, gesto, ojosGesto, mirar, f); caraY = caraLado(look, gesto, ojosGesto, true, f); }
    else if (dir === 1) { caraY = caraFrente(look, gesto, ojosGesto, mirar, f); caraX = caraLado(look, gesto, ojosGesto, false, f); }
    else if (dir === 2) { caraX = nuca(look); caraY = caraLado(look, gesto, ojosGesto, false, f); }
    else { caraY = nuca(look); caraX = caraLado(look, gesto, ojosGesto, true, f); }
    const tieneSombrero = look.casco || look.gorra;
    caja(uH - 0.28, uH + 0.28, -0.29, 0.29, zH0, zH0 + 0.58, piel,
      { sobre: { x: caraX, y: caraY }, caras: { top: tieneSombrero ? undefined : look.pelo } });
    if (look.casco) {
      const c = look.casco;
      caja(uH - 0.36, uH + 0.48, -0.37, 0.37, zH0 + 0.44, zH0 + 0.5, tono(c, 0.86));
      caja(uH - 0.3, uH + 0.3, -0.31, 0.31, zH0 + 0.5, zH0 + 0.78, c);
      caja(uH - 0.24, uH + 0.24, -0.06, 0.06, zH0 + 0.78, zH0 + 0.83, c);
    } else if (look.gorra) {
      const c = look.gorra;
      caja(uH - 0.3, uH + 0.3, -0.31, 0.31, zH0 + 0.48, zH0 + 0.7, c);
      caja(uH + 0.28, uH + 0.62, -0.26, 0.26, zH0 + 0.48, zH0 + 0.53, tono(c, 0.75));
    } else {
      caja(uH - 0.29, uH + 0.22, -0.3, 0.3, zH0 + 0.5, zH0 + 0.64, look.pelo);
    }
    return cajas;
  }

  /** Altura de la coronilla (para globos y para apuntar el látigo). */
  function alturaCabeza(sentado) { return (sentado ? 2.39 : 2.69) + 0.8; }

  // ---------------------------------------------------------------- pantallas

  /* Dibuja el contenido de un monitor en un rectángulo del plano (unidades del mundo). */
  function pantalla(ctx, u0, u1, v0, v1, cat, t, semilla) {
    const w = u1 - u0, h = v1 - v0;
    const rnd = aleatorio(semilla || 1);
    const fase = Math.floor(t / 180);
    const lento = Math.floor(t / 420);
    const filas = 9;
    const alto = h / (filas + 1);
    const fondo = (c) => { ctx.fillStyle = c; ctx.fillRect(u0, v0, w, h); };
    const linea = (i, desde, largo, c) => { ctx.fillStyle = c; ctx.fillRect(u0 + w * desde, v0 + alto * (i + 0.6), w * largo, alto * 0.42); };
    switch (cat) {
      case 'escribiendo': {
        fondo('#101626');
        const cols = [COLOR.ambar, COLOR.menta, COLOR.azul, '#E9E4DA', COLOR.lila];
        const tope = Math.min(filas, (fase % (filas + 4)) + 1);
        for (let i = 0; i < tope; i++) {
          const r2 = aleatorio(semilla * 31 + i + Math.floor(fase / (filas + 4)) * 97);
          const sangria = Math.floor(r2() * 3) * 0.08;
          const largo = 0.2 + r2() * 0.55;
          const parcial = i === tope - 1 ? Math.min(1, (t % 180) / 180 + 0.2) : 1;
          linea(i, 0.06 + sangria, largo * 0.45 * parcial, cols[i % cols.length]);
          linea(i, 0.06 + sangria + largo * 0.48, largo * 0.4 * parcial, cols[(i + 2) % cols.length]);
        }
        break;
      }
      case 'terminal': {
        fondo('#07100C');
        for (let i = 0; i < filas; i++) {
          const r2 = aleatorio(semilla * 17 + i + fase);
          linea(i, 0.06, 0.15 + r2() * 0.7, i === filas - 1 ? '#7CFF8A' : '#2FAF4A');
        }
        if (fase % 2) { ctx.fillStyle = '#7CFF8A'; ctx.fillRect(u0 + w * 0.85, v0 + alto * (filas - 0.4), w * 0.05, alto * 0.6); }
        break;
      }
      case 'leyendo': case 'buscando': {
        fondo('#E3E8EF');
        for (let i = 0; i < filas; i++) {
          const r2 = aleatorio(semilla * 13 + i + lento);
          linea(i, 0.08, 0.2 + r2() * 0.65, '#8D96A6');
        }
        if (cat === 'buscando') { ctx.fillStyle = 'rgba(255,181,71,0.85)'; ctx.fillRect(u0, v0 + alto * ((fase % filas) + 0.45), w, alto * 0.7); }
        break;
      }
      case 'web': {
        fondo('#F4F6F9');
        ctx.fillStyle = '#2F6FD0'; ctx.fillRect(u0, v0, w, h * 0.16);
        ctx.fillStyle = '#C9D6E8'; ctx.fillRect(u0 + w * 0.08, v0 + h * 0.26, w * 0.5, h * 0.14);
        for (let i = 5; i < filas; i++) linea(i, 0.08, 0.5 + ((i + lento) % 4) * 0.1, '#AAB4C3');
        break;
      }
      case 'delegando': {
        fondo('#14223A');
        const cu = u0 + w / 2;
        ctx.fillStyle = '#E9E4DA'; ctx.fillRect(cu - w * 0.08, v0 + h * 0.15, w * 0.16, h * 0.18);
        ctx.fillStyle = '#8D96A6'; ctx.fillRect(u0 + w * 0.18, v0 + h * 0.45, w * 0.64, h * 0.03); ctx.fillRect(cu - w * 0.01, v0 + h * 0.33, w * 0.02, h * 0.12);
        for (let k = 0; k < 3; k++) {
          ctx.fillStyle = (fase + k) % 3 === 0 ? COLOR.ambar : '#3B4458';
          ctx.fillRect(u0 + w * (0.12 + k * 0.3), v0 + h * 0.55, w * 0.16, h * 0.18);
        }
        break;
      }
      case 'permiso': case 'pregunta': case 'plan': {
        fondo('#1E2533');
        if (fase % 4 !== 3) {
          ctx.fillStyle = '#E9E4DA'; ctx.fillRect(u0 + w * 0.12, v0 + h * 0.18, w * 0.76, h * 0.64);
          ctx.fillStyle = '#59636E'; ctx.fillRect(u0 + w * 0.2, v0 + h * 0.3, w * 0.5, h * 0.06); ctx.fillRect(u0 + w * 0.2, v0 + h * 0.42, w * 0.38, h * 0.06);
          ctx.fillStyle = COLOR.verde; ctx.fillRect(u0 + w * 0.2, v0 + h * 0.6, w * 0.22, h * 0.12);
          ctx.fillStyle = '#C0392B'; ctx.fillRect(u0 + w * 0.5, v0 + h * 0.6, w * 0.22, h * 0.12);
        }
        ctx.strokeStyle = COLOR.ambar; ctx.lineWidth = Math.min(w, h) * 0.05;
        ctx.strokeRect(u0 + ctx.lineWidth / 2, v0 + ctx.lineWidth / 2, w - ctx.lineWidth, h - ctx.lineWidth);
        break;
      }
      case 'error': {
        fondo(fase % 2 ? '#7A1F1A' : '#5A1714');
        ctx.fillStyle = '#FFE1DD';
        ctx.fillRect(u0 + w * 0.47, v0 + h * 0.2, w * 0.06, h * 0.4); ctx.fillRect(u0 + w * 0.47, v0 + h * 0.68, w * 0.06, h * 0.1);
        break;
      }
      case 'compactando': {
        fondo('#151B28');
        ctx.fillStyle = '#2A3245'; ctx.fillRect(u0 + w * 0.1, v0 + h * 0.45, w * 0.8, h * 0.1);
        ctx.fillStyle = COLOR.lila; ctx.fillRect(u0 + w * 0.1, v0 + h * 0.45, w * 0.8 * ((t / 2400) % 1), h * 0.1);
        break;
      }
      case 'terminado': {
        fondo('#0F2A1C');
        ctx.strokeStyle = '#7CFF8A'; ctx.lineWidth = Math.min(w, h) * 0.08; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
        ctx.beginPath();
        ctx.moveTo(u0 + w * 0.3, v0 + h * 0.52); ctx.lineTo(u0 + w * 0.45, v0 + h * 0.68); ctx.lineTo(u0 + w * 0.72, v0 + h * 0.32);
        ctx.stroke();
        break;
      }
      case 'pendientes': {
        fondo('#EDE8DC');
        for (let i = 0; i < 6; i++) {
          ctx.fillStyle = i < (lento % 7) ? COLOR.verde : '#8D96A6';
          ctx.fillRect(u0 + w * 0.08, v0 + h * (0.1 + i * 0.14), w * 0.07, h * 0.08);
          ctx.fillStyle = '#AAB4C3'; ctx.fillRect(u0 + w * 0.2, v0 + h * (0.12 + i * 0.14), w * (0.4 + (i % 3) * 0.12), h * 0.05);
        }
        break;
      }
      case 'hablando': {
        fondo('#151B28');
        ctx.fillStyle = COLOR.menta; ctx.fillRect(u0 + w * 0.08, v0 + h * 0.15, w * 0.6, h * 0.22);
        ctx.fillStyle = '#E9E4DA'; ctx.fillRect(u0 + w * 0.32, v0 + h * 0.5, w * 0.6, h * 0.22);
        break;
      }
      case 'skill': case 'mcp': case 'herramienta': {
        fondo('#151B28');
        ctx.fillStyle = cat === 'mcp' ? COLOR.lila : COLOR.ambar;
        ctx.fillRect(u0 + w * 0.36, v0 + h * 0.38, w * 0.28, h * 0.32);
        ctx.fillStyle = '#C9D6E8'; ctx.fillRect(u0 + w * 0.42, v0 + h * 0.28, w * 0.16, h * 0.1);
        break;
      }
      case 'arrancando': {
        fondo('#16305A');
        ctx.fillStyle = '#E9E4DA'; ctx.fillRect(u0 + w * 0.1, v0 + h * 0.5, w * 0.8 * ((t / 1600) % 1), h * 0.06);
        break;
      }
      case 'esperando_peones': {
        fondo('#0F1522');
        for (let k = 0; k < 3; k++) {
          const y = v0 + h * (0.18 + k * 0.26);
          ctx.fillStyle = '#E8833A'; ctx.fillRect(u0 + w * 0.08, y, w * 0.08, h * 0.14);
          ctx.fillStyle = '#232B3B'; ctx.fillRect(u0 + w * 0.22, y + h * 0.03, w * 0.68, h * 0.08);
          const avance = ((t / (5200 + k * 1900)) + k * 0.31) % 1;
          ctx.fillStyle = COLOR.ambar; ctx.fillRect(u0 + w * 0.22, y + h * 0.03, w * 0.68 * avance, h * 0.08);
        }
        break;
      }
      case 'durmiendo': case 'esperando': case 'saliendo': {
        fondo('#111826');
        ctx.fillStyle = 'rgba(111,227,208,0.05)'; ctx.fillRect(u0, v0, w, h * 0.5);
        const bu = u0 + w * (0.1 + 0.8 * ((t / 9000) % 1));
        const bv = v0 + h * (0.2 + 0.6 * (0.5 + 0.5 * Math.sin(t / 2100)));
        ctx.fillStyle = '#2E4A6A';
        ctx.fillRect(bu, bv, w * 0.06, h * 0.08);
        break;
      }
      default: { // pensando
        fondo('#151B28');
        const n = fase % 4;
        for (let k = 0; k < 3; k++) {
          ctx.fillStyle = k < n ? '#9DB7D5' : '#2A3245';
          ctx.fillRect(u0 + w * (0.36 + k * 0.1), v0 + h * 0.46, w * 0.06, h * 0.1);
        }
      }
    }
    void rnd;
  }

  /** Color que identifica un estado (para luces, contornos y el panel). */
  function colorEstado(cat) {
    switch (cat) {
      case 'escribiendo': return COLOR.ambar;
      case 'terminal': return '#7CFF8A';
      case 'leyendo': case 'buscando': return COLOR.menta;
      case 'web': return COLOR.azul;
      case 'permiso': case 'pregunta': case 'plan': return COLOR.ambar;
      case 'error': return COLOR.rojo;
      case 'terminado': return COLOR.verde;
      case 'delegando': return '#E8833A';
      case 'compactando': case 'skill': case 'mcp': case 'herramienta': case 'pendientes': return COLOR.lila;
      case 'pensando': return '#9DB7D5';
      default: return '#3B4A63';
    }
  }

  // ---------------------------------------------------------------- retrato para el panel

  function retrato(canvas, agente, cat) {
    const ctx = canvas.getContext('2d');
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const look = lookPara(agente);
    const pose = cat === 'permiso' || cat === 'pregunta' ? 'mano' : cat === 'terminado' ? 'pulgar' : 'idle';
    const s = canvas.width / 2.15;
    const v = new Vista(s, canvas.width * 0.5, canvas.height * 1.38);
    const cajas = figura(look, pose, { x: 0, y: 0, z: -1.05, dir: 0, sentado: true, f: 0 });
    pintar(ctx, v, cajas);
  }

  global.Figuras = { COLOR, hash, aleatorio, lookPara, figura, alturaCabeza, pantalla, colorEstado, retrato };
})(window);
