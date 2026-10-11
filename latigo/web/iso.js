/* Motor isométrico mínimo para la caseta: proyección, cajas con caras sombreadas,
   planos para dibujar sobre una cara y orden de pintado por dependencias. */
'use strict';
(function (global) {
  const C = Math.cos(Math.PI / 6), S = 0.5;

  // ---------------------------------------------------------------- color

  function rgb(h) {
    h = h.replace('#', '');
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  }
  function hex(c) {
    return '#' + c.map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('');
  }
  const cacheTono = new Map();
  function tono(color, k) {
    const clave = color + k;
    let r = cacheTono.get(clave);
    if (!r) { r = hex(rgb(color).map((v) => v * k)); cacheTono.set(clave, r); }
    return r;
  }
  function mezcla(a, b, t) {
    const ra = rgb(a), rb = rgb(b);
    return hex(ra.map((v, i) => v + (rb[i] - v) * t));
  }
  function rgba(color, a) {
    const c = rgb(color);
    return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')';
  }

  // ---------------------------------------------------------------- vista

  class Vista {
    constructor(s, ox, oy) { this.s = s; this.ox = ox; this.oy = oy; }
    p(x, y, z) { return [this.ox + (x - y) * C * this.s, this.oy + (x + y) * S * this.s - z * this.s]; }
    // Transformaciones para dibujar en 2D sobre un plano (u a la derecha en pantalla, v hacia abajo).
    planoX(ctx, x0) { const s = this.s; ctx.transform(C * s, -S * s, 0, s, this.ox + x0 * C * s, this.oy + x0 * S * s); }
    planoY(ctx, y0) { const s = this.s; ctx.transform(C * s, S * s, 0, s, this.ox - y0 * C * s, this.oy + y0 * S * s); }
    planoZ(ctx, z0) { const s = this.s; ctx.transform(C * s, S * s, -C * s, S * s, this.ox, this.oy - z0 * s); }
  }

  const LUZ = { top: 1.0, y: 0.8, x: 0.62 };

  function poligono(ctx, v, pts, relleno) {
    ctx.beginPath();
    for (let i = 0; i < pts.length; i++) {
      const q = v.p(pts[i][0], pts[i][1], pts[i][2]);
      if (i === 0) ctx.moveTo(q[0], q[1]); else ctx.lineTo(q[0], q[1]);
    }
    ctx.closePath();
    ctx.fillStyle = relleno;
    ctx.fill();
  }

  /** Caja alineada a los ejes. Caras visibles: arriba, x (en x+w) e y (en y+d).
      op.caras: colores por cara ('none' la omite); op.sobre: {x, y, top}: funciones que dibujan sobre la cara
      con coordenadas del plano; op.alfa: transparencia. */
  class Caja {
    constructor(x, y, z, w, d, h, color, op) {
      this.x = x; this.y = y; this.z = z; this.w = w; this.d = d; this.h = h;
      this.color = color;
      this.op = op || {};
    }
    limites() { return [this.x, this.y, this.z, this.x + this.w, this.y + this.d, this.z + this.h]; }
    dibujar(ctx, v) {
      const { x, y, z, w, d, h } = this;
      const caras = this.op.caras || {};
      const alfa = this.op.alfa;
      if (alfa !== undefined) { ctx.save(); ctx.globalAlpha *= alfa; }
      const yc = caras.y || tono(this.color, LUZ.y);
      if (yc !== 'none') poligono(ctx, v, [[x, y + d, z], [x + w, y + d, z], [x + w, y + d, z + h], [x, y + d, z + h]], yc);
      const xc = caras.x || tono(this.color, LUZ.x);
      if (xc !== 'none') poligono(ctx, v, [[x + w, y, z], [x + w, y + d, z], [x + w, y + d, z + h], [x + w, y, z + h]], xc);
      const tc = caras.top || this.color;
      if (tc !== 'none') poligono(ctx, v, [[x, y, z + h], [x + w, y, z + h], [x + w, y + d, z + h], [x, y + d, z + h]], tc);
      const sobre = this.op.sobre;
      if (sobre) {
        if (sobre.x) { ctx.save(); v.planoX(ctx, x + w); sobre.x(ctx, -(y + d), -(y), -(z + h), -z); ctx.restore(); }
        if (sobre.y) { ctx.save(); v.planoY(ctx, y + d); sobre.y(ctx, x, x + w, -(z + h), -z); ctx.restore(); }
        if (sobre.top) { ctx.save(); v.planoZ(ctx, z + h); sobre.top(ctx, x, x + w, y, y + d); ctx.restore(); }
      }
      if (alfa !== undefined) ctx.restore();
    }
  }

  /** Algo que se ordena como si ocupara una caja pero se dibuja con su propia función. */
  class Pieza {
    constructor(lim, dibujar) { this.lim = lim; this.fn = dibujar; }
    limites() { return this.lim; }
    dibujar(ctx, v) { this.fn(ctx, v); }
  }

  function cajaPantalla(v, b) {
    const xs = [b[0], b[3]], ys = [b[1], b[4]], zs = [b[2], b[5]];
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const x of xs) for (const y of ys) for (const z of zs) {
      const q = v.p(x, y, z);
      if (q[0] < x0) x0 = q[0]; if (q[0] > x1) x1 = q[0];
      if (q[1] < y0) y0 = q[1]; if (q[1] > y1) y1 = q[1];
    }
    return [x0, y0, x1, y1];
  }

  function atras(a, b) {
    const e = 1e-6;
    if (a[3] <= b[0] + e) return true;
    if (b[3] <= a[0] + e) return false;
    if (a[4] <= b[1] + e) return true;
    if (b[4] <= a[1] + e) return false;
    if (a[5] <= b[2] + e) return true;
    if (b[5] <= a[2] + e) return false;
    return (a[0] + a[3] + a[1] + a[4] + a[2] + a[5]) < (b[0] + b[3] + b[1] + b[4] + b[2] + b[5]);
  }

  /** Orden de pintado: A antes que B si A queda detrás y sus siluetas se tocan en pantalla. */
  function ordenar(v, piezas) {
    const n = piezas.length;
    const lim = new Array(n), scr = new Array(n), suma = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      const b = piezas[i].limites();
      lim[i] = b; scr[i] = cajaPantalla(v, b);
      suma[i] = b[0] + b[1] + b[2] + b[3] + b[4] + b[5];
    }
    const despues = new Array(n), grado = new Int32Array(n);
    for (let i = 0; i < n; i++) despues[i] = [];
    for (let i = 0; i < n; i++) {
      const a = scr[i];
      for (let j = i + 1; j < n; j++) {
        const b = scr[j];
        if (a[2] <= b[0] || b[2] <= a[0] || a[3] <= b[1] || b[3] <= a[1]) continue;
        if (atras(lim[i], lim[j])) { despues[i].push(j); grado[j]++; } else { despues[j].push(i); grado[i]++; }
      }
    }
    const listos = [];
    for (let i = 0; i < n; i++) if (!grado[i]) listos.push(i);
    const orden = [];
    const porSuma = (a, b) => suma[b] - suma[a];
    listos.sort(porSuma);
    while (listos.length) {
      const i = listos.pop();
      orden.push(i);
      let agrego = false;
      for (const j of despues[i]) if (--grado[j] === 0) { listos.push(j); agrego = true; }
      if (agrego) listos.sort(porSuma);
    }
    if (orden.length < n) {
      const vistos = new Set(orden);
      const resto = [];
      for (let i = 0; i < n; i++) if (!vistos.has(i)) resto.push(i);
      resto.sort((a, b) => suma[a] - suma[b]);
      orden.push(...resto);
    }
    return orden.map((i) => piezas[i]);
  }

  function pintar(ctx, v, piezas) {
    for (const p of ordenar(v, piezas)) p.dibujar(ctx, v);
  }

  global.Iso = { C, S, Vista, Caja, Pieza, ordenar, pintar, poligono, tono, mezcla, rgba, LUZ };
})(window);
