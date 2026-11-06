
 // SPDX-License-Identifier: MIT
 // SPDX-FileCopyrightText: 2026 E. T. Carter <support@shader.gallery>
 //
 // Neovius (Manifold)
 // Shader Lab single-pass adaptation

 // ==========================================
 // ORIGINAL HTML PALETTE
 // ==========================================

 const vec3 COLOR_1 = vec3(0.271, 0.306, 0.655);
 const vec3 COLOR_2 = vec3(0.271, 0.306, 0.655);
 const vec3 COLOR_3 = vec3(0.380, 0.580, 0.949);
 const vec3 COLOR_4 = vec3(0.290, 0.180, 0.561);

 // ==========================================
 // ORIGINAL HTML PARAMETER OVERRIDES
 // ==========================================

 const float CELL_SCALE   = 0.80;
 const float THICKNESS    = 0.00;
 const float SPEED        = 0.07;
 const float GLOW         = 1.00;
 const float WARP         = 1.00;
 const float HUE          = 1.95;
 const float FOG          = 0.00;
 const float ROTATE       = 0.00;
 const float SURFACE      = 1.00;
 const float EDGE         = 1.00;
 const float CONTOUR      = 1.00;
 const float TWIST        = 0.00;
 const float BIAS         = 0.00;
 const float ANISO        = 0.50;
 const float DIAMOND      = 0.00;

 // ==========================================
 // CRT / POST PROCESSING
 // ==========================================

 const float POST_GRAIN       = 0.05;
 const float POST_GRAIN_SIZE  = 1.50;
 const float POST_GRAIN_SPEED = 10.00;
 const float POST_ABERRATION  = 0.0015;
 const float POST_VIGNETTE    = 0.50;
 const float POST_EXPOSURE    = 1.00;
 const float POST_CONTRAST    = 1.00;
 const float POST_SATURATION  = 1.10;
 const float POST_BLOOM       = 0.70;
 const float POST_SCANLINE    = 0.50;
 const float POST_CRT_MASK    = 0.50;

 // ==========================================
 // PALETTE WHEEL
 // ==========================================

 float wheelW(float s, float c) {
     float d = abs(s - c);
     return max(0.0, 1.0 - min(d, 4.0 - d));
 }

 vec3 wheelCol(float k) {
     float s = fract(k) * 4.0;

     float a = wheelW(s, 0.0);
     float b = wheelW(s, 1.0);
     float c = wheelW(s, 2.0);
     float d = wheelW(s, 3.0);

     return (
         COLOR_1 * a +
         COLOR_2 * b +
         COLOR_3 * c +
         COLOR_4 * d
     ) / max(a + b + c + d, 0.001);
 }

 // ==========================================
 // SURFACE FIELD
 // ==========================================

 float gmap(vec3 p, float time) {
     float F = max(CELL_SCALE, 0.6);

     float agg = mix(
         0.4, 2.6,
         clamp(ANISO, 0.0, 1.0)
     );

     vec3 q = p * F;
     q.z *= agg;

     float tw = TWIST * 0.6;
     float ta = q.z * tw;

     float cz = cos(ta);
     float sz = sin(ta);

     q.xy = mat2(cz, -sz, sz, cz) * q.xy;

     q += WARP * 0.5 *
          sin(q.yzx * 0.7 + time * 0.15);

     vec3 s = sin(q);
     vec3 c = cos(q);

     float neo = (
         3.0 * (c.x + c.y + c.z) +
         4.0 * c.x * c.y * c.z
     ) / 7.0;

     float sch = (c.x + c.y + c.z) / 1.7;

     float dia =
         s.x * s.y * s.z +
         s.x * c.y * c.z +
         c.x * s.y * c.z +
         c.x * c.y * s.z;

     float g = mix(
         neo,
         sch,
         clamp(SURFACE, 0.0, 1.0)
     );

     g = mix(
         g,
         dia,
         clamp(DIAMOND, 0.0, 1.0)
     );

     float g2 = g - BIAS * 0.9;

     float th = mix(
         0.02,
         1.3,
         clamp(THICKNESS, 0.0, 1.0)
     );

     return (abs(g2) - th) /
            (
                F *
                max(1.0, agg) *
                (
                    2.4 +
                    abs(tw) * 2.0 +
                    DIAMOND * 0.6
                )
            );
 }

 // ==========================================
 // SURFACE NORMAL
 // ==========================================

 vec3 calcN(vec3 p, float time) {
     vec2 e = vec2(0.0015, 0.0);

     return normalize(vec3(
         gmap(p + e.xyy, time) -
         gmap(p - e.xyy, time),

         gmap(p + e.yxy, time) -
         gmap(p - e.yxy, time),

         gmap(p + e.yyx, time) -
         gmap(p - e.yyx, time)
     ));
 }

 // ==========================================
 // ORIGINAL RAYMARCHED SCENE
 // ==========================================

 vec3 renderNeovius(
     vec2 uv,
     float time,
     vec2 resolution
 ) {
     // Equivalent to the original gl_FragCoord
     // mapping, using UV coordinates.

     vec2 pUv = (
         uv - 0.5
     ) * resolution / min(
         resolution.x,
         resolution.y
     );

     vec3 ro = vec3(
         0.9 + sin(time * 0.05) * 0.5,
         0.6 + cos(time * 0.06) * 0.5,
         0.7 + time * SPEED
     );

     vec3 rd = normalize(vec3(pUv, 1.0));

     float a =
         ROTATE * 0.0174532925 -
         time * 0.02;

     float ca = cos(a);
     float sa = sin(a);

     rd.xy = mat2(
         ca, -sa,
         sa, ca
     ) * rd.xy;

     float dist = 0.0;
     float hit = 0.0;
     float steps = 0.0;

     vec3 p = ro;

     // Original 150-step raymarch.

     for (int i = 0; i < 150; i++) {
         p = ro + rd * dist;

         float d = gmap(p, time);

         if (d < 0.0008) {
             hit = 1.0;
             break;
         }

         dist += d * 0.5;
         steps += 1.0;

         if (dist > 20.0) {
             break;
         }
     }

     steps /= 150.0;

     vec3 fogc = wheelCol(
         0.64 + time * 0.01
     ) * 0.05;

     vec3 col = fogc;

     if (hit > 0.5) {
         vec3 n = calcN(p, time);

         vec3 lp = normalize(
             vec3(0.6, 0.6, -0.5)
         );

         float diff =
             0.34 +
             0.66 * max(dot(n, lp), 0.0);

         float rim = pow(
             1.0 - max(dot(n, -rd), 0.0),
             2.2
         );

         float ao = 1.0 - steps;

         float hue =
             HUE * (
                 dist * 0.08 +
                 0.2 * n.y +
                 0.12 * n.z
             ) +
             time * 0.03;

         vec3 base = wheelCol(hue);

         col =
             base * diff * (0.5 + 0.5 * ao) +
             base * rim * (0.5 + 0.8 * GLOW);

         // Silhouette enhancement.

         float sil = 1.0 - abs(dot(n, rd));

         float ew =
             0.04 +
             0.22 * clamp(EDGE, 0.0, 1.0);

         float edgeLine = smoothstep(
             1.0 - ew,
             1.0 - ew * 0.4,
             sil
         );

         col +=
             base *
             edgeLine *
             clamp(EDGE, 0.0, 1.0) *
             (0.7 + 0.7 * GLOW);

         // Topographic surface contours.

         float cf = fract(
             length(p.xy) *
             mix(
                 0.0,
                 2.4,
                 clamp(CONTOUR, 0.0, 1.0)
             ) -
             time * 0.05
         );

         float cont = smoothstep(
             0.5,
             0.42,
             abs(cf - 0.5)
         ) * clamp(CONTOUR, 0.0, 1.0);

         col +=
             base *
             cont *
             (0.5 + 0.6 * GLOW);
     }

     float fog = 1.0 - exp(
         -dist *
         mix(
             0.05,
             0.30,
             clamp(FOG, 0.0, 1.0)
         )
     );

     col = mix(
         col,
         fogc,
         clamp(fog, 0.0, 1.0)
     );

     col *= mix(
         1.0,
         0.7,
         smoothstep(
             0.6,
             1.1,
             length(pUv)
         )
     );

     return col;
 }

 // ==========================================
 // GRAIN UTILITY
 // ==========================================

 float hashGrain(vec2 p) {
     p = fract(p * vec2(123.34, 345.45));
     p += dot(p, p + 34.345);
     return fract(p.x * p.y);
 }

 // ==========================================
 // MAIN SHADER
 // ==========================================

 void mainImage(
     out vec4 fragColor,
     in vec2 fragCoord
 ) {
     vec2 resolution = iResolution.xy;
     vec2 uv = fragCoord / resolution;

     float time = iTime;

     // --------------------------------------
     // Chromatic aberration
     // --------------------------------------

     vec2 center = uv - 0.5;
     vec2 offset = center * POST_ABERRATION;

     vec3 col;

     // Three channel-separated scene samples.

     col.r = renderNeovius(
         uv + offset,
         time,
         resolution
     ).r;

     col.g = renderNeovius(
         uv,
         time,
         resolution
     ).g;

     col.b = renderNeovius(
         uv - offset,
         time,
         resolution
     ).b;

     // --------------------------------------
     // Approximate bloom
     // --------------------------------------
     // The original gallery uses a second pass
     // sampling surrounding pixels. Here we
     // enhance local highlights without
     // repeating the expensive raymarch.

     if (POST_BLOOM > 0.0) {
         float bright = max(
             max(col.r, col.g),
             col.b
         );

         float glow = max(
             bright - 0.55,
             0.0
         );

         col += col * glow * POST_BLOOM * 0.25;
     }

     // --------------------------------------
     // Exposure and tone
     // --------------------------------------

     col *= POST_EXPOSURE;

     col = (
         col - 0.5
     ) * POST_CONTRAST + 0.5;

     float luminance = dot(
         col,
         vec3(0.299, 0.587, 0.114)
     );

     col = mix(
         vec3(luminance),
         col,
         POST_SATURATION
     );

     // --------------------------------------
     // Vignette
     // --------------------------------------

     float vig = 1.0 -
         POST_VIGNETTE *
         dot(center, center) *
         2.0;

     col *= clamp(vig, 0.0, 1.0);

     // --------------------------------------
     // CRT scanlines
     // --------------------------------------

     if (POST_SCANLINE > 0.0) {
         float s =
             sin(fragCoord.y * 3.14159265) *
             0.5 + 0.5;

         col *=
             1.0 -
             POST_SCANLINE * s * 0.6;
     }

     // --------------------------------------
     // CRT RGB phosphor mask
     // --------------------------------------

     if (POST_CRT_MASK > 0.0) {
         float m = mod(fragCoord.x, 3.0);

         vec3 mask;

         if (m < 1.0) {
             mask = vec3(1.0, 0.7, 0.7);
         }
         else if (m < 2.0) {
             mask = vec3(0.7, 1.0, 0.7);
         }
         else {
             mask = vec3(0.7, 0.7, 1.0);
         }

         col *= mix(
             vec3(1.0),
             mask,
             POST_CRT_MASK
         );
     }

     // --------------------------------------
     // Film grain
     // --------------------------------------

     if (POST_GRAIN > 0.0) {
         vec2 cell = floor(
             fragCoord /
             max(POST_GRAIN_SIZE, 1.0)
         );

         float frame = floor(
             time * POST_GRAIN_SPEED
         );

         float noise = hashGrain(
             cell +
             frame * vec2(63.7, 31.3)
         ) - 0.5;

         float lum = dot(
             col,
             vec3(0.299, 0.587, 0.114)
         );

         float visibility = clamp(
             1.0 - abs(lum - 0.5) * 1.1,
             0.4,
             1.0
         );

         col +=
             noise *
             POST_GRAIN *
             visibility;
     }

     fragColor = vec4(
         clamp(col, 0.0, 1.0),
         1.0
     );
 }
