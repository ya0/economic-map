import { ramp } from "../scales/scales";
import type { View } from "./smooth";

/** A css colour (#rrggbb, #rrggbbaa or rgb(r, g, b)) as R, G, B, A bytes. */
const rgba = (c: string) => (c[0] === "#" ? [1, 3, 5, 7].map((j) => (j < c.length ? parseInt(c.slice(j, j + 2), 16) : 255)) : [...c.match(/\d+/g)!.map(Number), 255].slice(0, 4));
/** The palette as RGBA bytes: one colour per class, or 256 steps for the gradient (`n` = 0). */
export const lut = (pal: string, n: number) => Uint8Array.from(Array.from({ length: n || 256 }, (_, i) => rgba(ramp(i / ((n || 256) - 1), pal))).flat());

const VS = `#version 300 es
void main() { gl_Position = vec4(gl_VertexID == 1 ? 3.0 : -1.0, gl_VertexID == 2 ? 3.0 : -1.0, 0.0, 1.0); }`;
/** Shared by both passes: the surface bytes, which pixels are shown (alpha from `u_min`, inside the focus mask) and their log10 value
 * as `decode()` computes it. Output rows run top down. */
const COMMON = `#version 300 es
precision highp float; precision highp int; precision highp usampler2D;
uniform usampler2D u_s; uniform usampler2D u_c; uniform sampler2D u_mask;
uniform ivec2 u_sz, u_csz, u_out; uniform int u_min, u_masked, u_sea, u_mode;
uniform float u_lo, u_k, u_add;
out vec4 o;
ivec2 px() { return ivec2(int(gl_FragCoord.x), u_out.y - 1 - int(gl_FragCoord.y)); }
bool shown(ivec2 p) { return texelFetch(u_s, p, 0).a >= uint(u_min) && (u_masked == 0 || texelFetch(u_mask, p, 0).r > 0.0); }
float lg(float x) { return log(x) * 0.43429448190325176; }
float land(uvec4 t) { return lg(max(float(t.b), 0.5) / 255.0); }
float dec(uvec4 t) { return u_lo + float(t.r * 256u + t.g) * u_k + u_add + (u_sea == 1 ? land(t) : 0.0); }
`;
/** The rule of smooth.ts' `sample()`: bilinear over the defined neighbours, undefined where they hold less than half the weight. */
const bilinear = (name: string, at: string, size: string) => `
float ${name}(float x, float y, out bool ok) {
  float fx = clamp(x - 0.5, 0.0, float(${size}.x - 1)), fy = clamp(y - 0.5, 0.0, float(${size}.y - 1));
  int x0 = int(fx), y0 = int(fy), x1 = min(x0 + 1, ${size}.x - 1), y1 = min(y0 + 1, ${size}.y - 1);
  float ax = fx - float(x0), ay = fy - float(y0); bool oa, ob, oc, od;
  float a = ${at}(ivec2(x0, y0), oa), b = ${at}(ivec2(x1, y0), ob), c = ${at}(ivec2(x0, y1), oc), d = ${at}(ivec2(x1, y1), od);
  float wa = oa ? (1.0 - ax) * (1.0 - ay) : 0.0, wb = ob ? ax * (1.0 - ay) : 0.0, wc = oc ? (1.0 - ax) * ay : 0.0, wd = od ? ax * ay : 0.0, n = wa + wb + wc + wd;
  ok = n >= 0.5; return ok ? ((oa ? wa * a : 0.0) + (ob ? wb * b : 0.0) + (oc ? wc * c : 0.0) + (od ? wd * d : 0.0)) / n : 0.0;
}`;
/** Every pixel shown in the palette over the domain, in `u_n` flat classes if set (else the 256 steps); `u_f` canvas pixels per surface
 * pixel (bilinear), which keeps class edges crisp. With `u_soft` sea pixels (A < 255) under the floor fade out over half a decade
 * (gradient) or go transparent (classes); land under it takes the lowest colour. Mode 1 is the local excess over the wide surface
 * `u_c`. */
const COLOUR = COMMON + `
uniform sampler2D u_lut; uniform vec2 u_dom; uniform int u_n, u_soft, u_f;
float wide(ivec2 p, out bool ok) { uvec4 t = texelFetch(u_c, p, 0); ok = t.a > 0u; return ok ? dec(t) : 0.0; }
${bilinear("sampC", "wide", "u_csz")}
float val(ivec2 p, out bool ok) {
  uvec4 t = texelFetch(u_s, p, 0); ok = t.a > 0u;
  if (!ok) return 0.0;
  if (u_mode == 0) return dec(t);
  vec2 k = vec2(u_csz) / vec2(u_sz);
  return dec(t) - sampC((float(p.x) + 0.5) * k.x, (float(p.y) + 0.5) * k.y, ok);
}
${bilinear("samp", "val", "u_sz")}
void main() {
  ivec2 p = px(), j = p / u_f;
  if (!shown(j)) discard;
  bool ok; float q = u_f == 1 ? val(j, ok) : samp((float(p.x) + 0.5) / float(u_f), (float(p.y) + 0.5) / float(u_f), ok);
  if (!ok) discard;
  int nc = u_n > 0 ? u_n : 256;
  vec4 c = texelFetch(u_lut, ivec2(clamp(int(floor((q - u_dom.x) / (u_dom.y - u_dom.x) * float(nc))), 0, nc - 1), 0), 0);
  float a = (u_soft == 0 || q >= u_dom.x || texelFetch(u_s, j, 0).a == 255u) ? 1.0 : u_n > 0 ? 0.0 : clamp(1.0 + (q - u_dom.x) / 0.5, 0.0, 1.0);
  if (a == 0.0) discard;
  o = vec4(c.rgb, a);
}`;
/** The sea veil over the shaded relief: `u_col` on every block of k x k surface pixels without one shown, so the shading stays on land. */
const VEIL = COMMON + `
uniform vec4 u_col; uniform int u_kk;
void main() {
  ivec2 p = px() * u_kk;
  for (int y = 0; y < u_kk; y++) for (int x = 0; x < u_kk; x++) { ivec2 q = p + ivec2(x, y); if (q.x < u_sz.x && q.y < u_sz.y && shown(q)) discard; }
  o = u_col;
}`;

/** Colours the smoothed surface on the GPU, in WebGL2 on its own canvas: the bytes of the surface are a texture, decoded, binned,
 * faded and masked in the fragment shader, so a palette, theme, domain, class or Include sea change is one draw call. */
export function gpuPainter(canvas: HTMLCanvasElement) {
  const gl = canvas.getContext("webgl2", { premultipliedAlpha: false, preserveDrawingBuffer: true, antialias: false, depth: false, stencil: false });
  if (!gl) throw new Error("WebGL2 is not available");
  const program = (fs: string) => {
    const p = gl.createProgram();
    for (const [type, src] of [[gl.VERTEX_SHADER, VS], [gl.FRAGMENT_SHADER, fs]] as const) {
      const s = gl.createShader(type)!;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      gl.attachShader(p, s);
    }
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) ?? "shader");
    return p;
  };
  const colour = program(COLOUR), veiler = program(VEIL);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  // texture units: 0 the surface, 1 the wide surface, 2 the focus mask, 3 the palette; each uploaded only when its bytes change
  const held: Uint8Array[] = [];
  for (let unit = 0; unit < 4; unit++) {
    gl.activeTexture(gl.TEXTURE0 + unit);
    gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
    for (const k of [gl.TEXTURE_MIN_FILTER, gl.TEXTURE_MAG_FILTER]) gl.texParameteri(gl.TEXTURE_2D, k, gl.NEAREST);
  }
  const upload = (unit: number, w: number, h: number, data: Uint8Array) => {
    if (held[unit] === data) return;
    held[unit] = data;
    gl.activeTexture(gl.TEXTURE0 + unit);
    if (unit === 2) gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, w, h, 0, gl.RED, gl.UNSIGNED_BYTE, data);
    else if (unit === 3) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, data);
    else gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8UI, w, h, 0, gl.RGBA_INTEGER, gl.UNSIGNED_BYTE, data);
  };
  /** Bind the textures of `v` and the uniforms common to both passes, size the drawing to w x h (at the bottom of the buffer) and draw. */
  const draw = (p: WebGLProgram, v: View, w: number, h: number, set: (u: (name: string) => WebGLUniformLocation | null) => void) => {
    const u = (name: string) => gl.getUniformLocation(p, name);
    gl.useProgram(p);
    upload(0, v.w, v.h, v.rgba);
    if (v.wide) upload(1, v.wide.w, v.wide.h, v.wide.rgba);
    if (v.mask) upload(2, v.w, v.h, v.mask);
    ["u_s", "u_c", "u_mask", "u_lut"].forEach((name, unit) => gl.uniform1i(u(name), unit));
    gl.uniform2i(u("u_sz"), v.w, v.h);
    gl.uniform2i(u("u_csz"), v.wide?.w ?? 1, v.wide?.h ?? 1);
    gl.uniform2i(u("u_out"), w, h);
    gl.uniform1i(u("u_min"), v.min);
    gl.uniform1i(u("u_masked"), v.mask ? 1 : 0);
    gl.uniform1i(u("u_sea"), v.dec.sea ? 1 : 0);
    gl.uniform1i(u("u_mode"), v.wide ? 1 : 0);
    gl.uniform1f(u("u_lo"), v.dec.lo);
    gl.uniform1f(u("u_k"), (v.dec.hi - v.dec.lo) / 65535);
    gl.uniform1f(u("u_add"), Math.log10(v.dec.price));
    set(u);
    gl.viewport(0, 0, w, h);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  };
  let last: Parameters<typeof paint> | undefined;
  /** Colour `v` over the domain [lo, hi] in `n` classes (0: the gradient); `f` canvas pixels per surface pixel; `soft`: the sea fades. */
  const paint = (v: View, pal: string, dom: [number, number], n: number, f: number, soft: boolean) => {
    last = [v, pal, dom, n, f, soft];
    const w = v.w * f, h = v.h * f;
    if (canvas.width !== w || canvas.height !== h) [canvas.width, canvas.height] = [w, h];
    upload(3, n || 256, 1, lut(pal, n));
    draw(colour, v, w, h, (u) => {
      gl.uniform2f(u("u_dom"), dom[0], dom[1]);
      gl.uniform1i(u("u_n"), n);
      gl.uniform1i(u("u_soft"), soft ? 1 : 0);
      gl.uniform1i(u("u_f"), f);
    });
  };
  /** The veil of `v` in colour `col` (css) at most 2048 columns wide (k surface pixels per veil pixel), drawn here, copied into `into`
   * and the surface painted again. */
  const veil = (v: View, col: string, into: HTMLCanvasElement) => {
    const k = Math.ceil(v.w / 2048), w = Math.ceil(v.w / k), h = Math.ceil(v.h / k);
    if (canvas.width < w || canvas.height < h) [canvas.width, canvas.height] = [w, h];
    draw(veiler, v, w, h, (u) => {
      gl.uniform4fv(u("u_col"), rgba(col).map((x) => x / 255));
      gl.uniform1i(u("u_kk"), k);
    });
    [into.width, into.height] = [w, h];
    into.getContext("2d")!.drawImage(canvas, 0, canvas.height - h, w, h, 0, 0, w, h);
    if (last) paint(...last);
    return { w, h, k };
  };
  return { paint, veil };
}
