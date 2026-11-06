// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 E. T. Carter <support@shader.gallery>
// Drape (Veil) - Shader Lab adaptation. Single-pass approximation of gallery post.
// Original drape geometry, shading, motion and supplied palette are preserved.
// The gallery uses separate framebuffer post-FX; this file approximates them inline.

// Original preview palette (unchanged, floats retained for exact precision):
const vec3 DRAPE_0 = vec3(0.757, 0.125, 0.196);
const vec3 DRAPE_1 = vec3(0.031, 0.043, 0.071);
const vec3 DRAPE_2 = vec3(0.757, 0.125, 0.196);
const vec3 DRAPE_3 = vec3(0.757, 0.125, 0.196);

// Original gallery shader parameters:
const float FOLD_WIDTH = 200.0;
const float SWAY_SPEED = 0.5;
const float SHEEN = 0.7;

// Original gallery post-processing settings:
const float POST_GRAIN = 0.05;
const float POST_GRAIN_SIZE = 1.5;
const float POST_GRAIN_SPEED = 10.0;
const float POST_ABERRATION = 0.0015;
const float POST_VIGNETTE = 0.5;
const float POST_EXPOSURE = 1.0;
const float POST_CONTRAST = 1.0;
const float POST_SATURATION = 1.1;
const float POST_BLOOM = 0.7;
const float POST_BLOOM_RADIUS = 4.0;
const float POST_SCANLINE = 0.5;
const float POST_CRT_MASK = 0.5;

// Controls: set these to 0.0/1.0 to isolate primary shader and post effects.
const float ENABLE_POST = 1.0;
const float ENABLE_BLOOM = 1.0;

// Match the gallery's rendering coordinates. Shader Lab supplies iResolution / iTime.

// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 E. T. Carter <support@shader.gallery>
// drape (Veil) — heavy silk hung in vertical folds. A smooth periodic
// heightfield of large folds plus low-octave FBM wrinkles, lit with
// analytically derived normals so every crest carries a soft specular ridge of
// light while valleys fall to near-black. Crest highlights blend the four
// palette colours by horizontal position and fold phase, so neighbouring folds
// glow in different restrained hues over a dark cloth body. The cloth sways as
// if hung at an open window — fold centres lean and wrinkle detail drift on slow
// incommensurate sine phases, breathing continuously with no repeat point.
//
// Uniforms provided by the runtime:
//   u_time        seconds, monotonically increasing
//   u_resolution  drawing-buffer size in device pixels
//   u_mouse       pointer in device pixels (0,0 when absent)
//   u_pixelRatio  devicePixelRatio used for the buffer
//   u_palette[4]  four glow colours, themeable (linear-ish 0..1 rgb)

const vec3  BG = vec3(0.035, 0.035, 0.043); // near-black cloth shadow base

// hash + value noise for low-octave wrinkle FBM
float hash(vec2 p) {
  p = fract(p * vec2(123.34, 345.45));
  p += dot(p, p + 34.345);
  return fract(p.x * p.y);
}
float vnoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float a = hash(i);
  float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0));
  float d = hash(i + vec2(1.0, 1.0));
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

// cyclic triangular weight for a palette entry centred at c on a 0..4 wheel
float wheelW(float s, float c) {
  float d = abs(s - c);
  return max(0.0, 1.0 - min(d, 4.0 - d));
}

// silk height as a function of horizontal css-px coordinate x and vertical y.
// returns surface height (0..~1); larger = crest toward the viewer.
float silkHeight(float x, float y, float foldW, float t) {
  // slow horizontal lean of fold centres: incommensurate sine phases so the
  // sway never repeats (full sway reads over ~15-25 s)
  float lean = sin(x / foldW * 1.7 + t * 0.21) * 0.18
             + sin(x / foldW * 0.9 - t * 0.13 + 1.7) * 0.10;
  float fx = x / foldW + lean + y * 0.0004 * foldW * 0.0; // phase per fold
  // primary smooth periodic fold profile (rounded, never faceted)
  float fold = 0.5 + 0.5 * sin(fx * 6.2831853);
  fold = fold * fold * (3.0 - 2.0 * fold); // smootherstep -> rounded crests
  // low-octave FBM wrinkles drifting slowly on their own phases
  float w = 0.0;
  w += vnoise(vec2(x / (foldW * 0.55) + t * 0.05, y / (foldW * 1.1) - t * 0.037)) * 0.55;
  w += vnoise(vec2(x / (foldW * 0.27) - t * 0.031, y / (foldW * 0.6) + t * 0.022)) * 0.28;
  return fold * 0.8 + w * 0.32;
}

vec3 drapeBase(vec2 fc, float t) {
  vec2 u_resolution = iResolution.xy;
  float u_pixelRatio = 1.0;
  float u_foldWidth = FOLD_WIDTH;
  float u_swaySpeed = SWAY_SPEED;
  float u_sheen = SHEEN;
  float pr  = u_pixelRatio;

  vec2  res = u_resolution;
  vec2  ctr = res * 0.5;


  // guard params so the full slider range stays safe
  float refScale = min(u_resolution.x, u_resolution.y) / (max(u_pixelRatio, 1.0) * 400.0);
  float foldW = max(u_foldWidth, 24.0) * refScale * pr; // css-px fold width -> device px
  float sway  = max(u_swaySpeed, 0.0);
  float sheen = max(u_sheen, 0.0);

  // sway-scaled time for the heightfield animation
  float ts = t * sway;

  // sample the heightfield + neighbours for analytic normal (central diff)
  float e = 1.5 * pr;
  float h  = silkHeight(fc.x,     fc.y,     foldW, ts);
  float hxp = silkHeight(fc.x + e, fc.y,     foldW, ts);
  float hxm = silkHeight(fc.x - e, fc.y,     foldW, ts);
  float hyp = silkHeight(fc.x,     fc.y + e, foldW, ts);
  float hym = silkHeight(fc.x,     fc.y - e, foldW, ts);
  // slope of the heightfield in cloth units. relief converts the dimensionless
  // height (~0..1) into the px depth of the folds so normals tilt meaningfully.
  float relief = foldW * 0.16;
  float dhx = (hxp - hxm) / (2.0 * e) * relief;
  float dhy = (hyp - hym) / (2.0 * e) * relief;
  vec3 n = normalize(vec3(-dhx, -dhy, 1.0));

  // lighting: a soft key from upper-left, grazing so crests catch a sheen ridge
  vec3 L = normalize(vec3(-0.55, 0.45, 0.70));
  vec3 V = vec3(0.0, 0.0, 1.0);
  vec3 H = normalize(L + V);

  float diff = max(dot(n, L), 0.0);
  float ndh  = max(dot(n, H), 0.0);
  // sheen tightens the specular lobe and scales its strength
  float specPow = mix(8.0, 60.0, clamp(sheen / 1.5, 0.0, 1.0));
  float spec = pow(ndh, specPow) * mix(0.9, 3.4, clamp(sheen / 1.5, 0.0, 1.0));

  // crest emphasis: the surface height itself, so highlights ride fold crests
  float crest = smoothstep(0.40, 1.0, h);
  // valley darkening: push the troughs between folds toward black
  float valley = smoothstep(0.0, 0.45, h);

  vec3 c0 = DRAPE_0, c1 = DRAPE_1, c2 = DRAPE_2, c3 = DRAPE_3;

  // crest hue blends the four palette colours by horizontal position + fold
  // phase, so neighbouring folds glow in different restrained hues. No dynamic
  // array indexing — cyclic triangular weights only.
  float foldPhase = fc.x / foldW;
  float k = foldPhase * 0.6 + sin(foldPhase * 2.1 + ts * 0.07) * 0.5 + ts * 0.01;
  float s = fract(k) * 4.0;
  float w0 = wheelW(s, 0.0), w1 = wheelW(s, 1.0), w2 = wheelW(s, 2.0), w3 = wheelW(s, 3.0);
  vec3  hue = (c0 * w0 + c1 * w1 + c2 * w2 + c3 * w3) / max(w0 + w1 + w2 + w3, 0.001);

  // vertical warp-thread grain running DOWN the folds — fine ribs in css px so
  // the silk reads as woven hanging cloth (the vertical identity vs billow's
  // horizontal weave). modulated weakly by lean so threads follow the sway.
  float warp = 0.5 + 0.5 * sin((fc.x / pr) * 2.3 + h * 3.0);
  float rib  = mix(0.86, 1.10, warp);
  // deepen the valleys into fold-shadow: square the valley term so the gaps
  // between hanging folds read as real occluded depth, not a flat dark wash
  float occ = valley * valley;

  // --- compose the lit silk ---
  vec3 col = BG;
  // dark cloth body: a low diffuse wash in the fold hue, valleys near-black
  col += hue * diff * mix(0.05, 0.21, crest) * occ * rib;
  // soft ambient so the body isn't pure black between crests
  col += hue * (0.009 + 0.040 * crest) * occ;
  // the luminous specular sheen ridge along the crests — the silk's signature,
  // broken into fine vertical thread glints by the warp ribs
  col += hue * spec * (0.35 + 0.65 * crest) * 1.40 * rib;
  // a tighter white-ish glint core at the very top of the sheen for liquid silk
  col += vec3(1.0) * pow(spec, 1.4) * crest * 0.35 * clamp(sheen / 1.5, 0.0, 1.0);

  // gentle vertical falloff + radial vignette to compose the framing
  float vign = 1.0 - smoothstep(0.55, 1.25, length((fc - ctr) / res));
  col *= mix(0.82, 1.0, vign);

  // subtle dithering to kill banding in the dark gradients
  float dither = (hash(fc + t) - 0.5) * (1.5 / 255.0);
  col += dither;

  return max(col, 0.0);
}


// Shader Lab provides mainImage; do not declare another main() or gl_FragColor.
void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 res = iResolution.xy;
    vec2 uv = fragCoord / res;
    vec2 fromCenter = uv - vec2(0.5);
    vec3 col = drapeBase(fragCoord, iTime);
    if (ENABLE_POST > 0.5) {
        // Gallery's radial chromatic aberration (second-pass approximation).
        if (POST_ABERRATION > 0.0) {
            vec2 off = fromCenter * POST_ABERRATION * res;
            vec3 red = drapeBase(fragCoord + off, iTime);
            vec3 blue = drapeBase(fragCoord - off, iTime);
            col.r = red.r;
            col.b = blue.b;
        }
        // True gallery bloom is a 12-tap texture pass. Restrict expensive
        // re-evaluations to two quarter-strength taps for this single-pass lab.
        if (ENABLE_BLOOM > 0.5 && POST_BLOOM > 0.0) {
            vec3 a = drapeBase(fragCoord + vec2(POST_BLOOM_RADIUS, 0.0), iTime);
            vec3 b = drapeBase(fragCoord - vec2(POST_BLOOM_RADIUS, 0.0), iTime);
            vec3 s = 0.5 * (a + b);
            float bright = max(max(s.r, s.g), s.b);
            col += s * max(bright - 0.55, 0.0) * POST_BLOOM * 0.35;
        }
        col *= POST_EXPOSURE;
        col = (col - vec3(0.5)) * POST_CONTRAST + vec3(0.5);
        float lum = dot(col, vec3(0.299, 0.587, 0.114));
        col = mix(vec3(lum), col, POST_SATURATION);
        col *= clamp(1.0 - POST_VIGNETTE * dot(fromCenter, fromCenter) * 2.0, 0.0, 1.0);
        // The original gallery scanline formula (phase per device pixel).
        float sl = sin(fragCoord.y * 3.14159265) * 0.5 + 0.5;
        col *= 1.0 - POST_SCANLINE * sl * 0.6;
        float m = mod(floor(fragCoord.x), 3.0);
        vec3 mask = m < 1.0 ? vec3(1.0, 0.7, 0.7)
                  : (m < 2.0 ? vec3(0.7, 1.0, 0.7) : vec3(0.7, 0.7, 1.0));
        col *= mix(vec3(1.0), mask, POST_CRT_MASK);
        vec2 cell = floor(fragCoord / max(POST_GRAIN_SIZE, 1.0));
        float tick = floor(iTime * POST_GRAIN_SPEED);
        float n = hash(cell + tick * vec2(63.7, 31.3)) - 0.5;
        float l = dot(col, vec3(0.299, 0.587, 0.114));
        float visibility = clamp(1.0 - abs(l - 0.5) * 1.1, 0.4, 1.0);
        col += n * POST_GRAIN * visibility;
    }
    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
