
// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 E. T. Carter <support@shader.gallery>
//
// Oil — Iridescent Thin Film
// MangaAnka / Shader Lab single-pass adaptation
//
// Input:  iTime, iResolution
// Entry:  mainImage(out vec4, in vec2)
//
// Preserve original shader.gallery palette and parameters.

// ==========================================
// ORIGINAL HTML PALETTE
// ==========================================

const vec3 COLOR_1 = vec3(0.039, 0.518, 0.553);
const vec3 COLOR_2 = vec3(0.122, 0.737, 0.667);
const vec3 COLOR_3 = vec3(0.616, 0.918, 0.776);
const vec3 COLOR_4 = vec3(0.063, 0.286, 0.451);

// ==========================================
// ORIGINAL HTML PARAMETER OVERRIDES
// ==========================================

const float FLOW         = 0.08;
const float SCALE        = 707.0;
const float IRIDESCENCE  = 1.25;
const float SHEEN        = 0.75;

// Original theme water color
const vec3 BG = vec3(0.035, 0.035, 0.043);

const float TAU = 6.28318530718;

// ==========================================
// ORIGINAL POST-PROCESSING SETTINGS
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
const float POST_SCANLINE    = 0.25;
const float POST_CRT_MASK    = 0.50;

// ==========================================
// NOISE
// ==========================================

float hash21(vec2 p) {
    p = fract(p * vec2(234.34, 435.345));
    p += dot(p, p + 34.23);
    return fract(p.x * p.y);
}

float vnoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);

    vec2 u = f * f * (3.0 - 2.0 * f);

    float a = hash21(i);
    float b = hash21(i + vec2(1.0, 0.0));
    float c = hash21(i + vec2(0.0, 1.0));
    float d = hash21(i + vec2(1.0, 1.0));

    return mix(
        mix(a, b, u.x),
        mix(c, d, u.x),
        u.y
    );
}

const mat2 M2 = mat2(
     0.80, 0.60,
    -0.60, 0.80
);

float fbm(vec2 p) {
    float a = 0.5;
    float s = 0.0;

    for (int i = 0; i < 5; i++) {
        s += a * vnoise(p);
        p = M2 * p * 2.03 + vec2(11.7, 5.3);
        a *= 0.5;
    }

    return s * 1.032;
}

// ==========================================
// CYCLIC FOUR-COLOR PALETTE
// ==========================================

vec3 palLoop(
    float u,
    vec3 a,
    vec3 b,
    vec3 c,
    vec3 d
) {
    float x = fract(u) * 4.0;
    float seg = floor(x);
    float f = smoothstep(
        0.0, 1.0, fract(x)
    );

    vec3 lo =
        seg < 0.5 ? a :
        seg < 1.5 ? b :
        seg < 2.5 ? c : d;

    vec3 hi =
        seg < 0.5 ? b :
        seg < 1.5 ? c :
        seg < 2.5 ? d : a;

    return mix(lo, hi, f);
}

// ==========================================
// ORIGINAL OIL FILM RENDERER
// ==========================================

vec3 renderOil(
    vec2 uv,
    float time,
    vec2 resolution
) {
    // Original shader uses a CSS-pixel-based
    // scale. Assume pixelRatio = 1.0.
    //
    // This reproduces the original scale
    // relationship for a 400px reference.

    float refScale =
        min(resolution.x, resolution.y) / 400.0;

    float scalePx =
        max(SCALE, 40.0) * refScale;

    vec2 p =
        (uv * resolution) / scalePx;

    float t =
        time * clamp(FLOW, 0.0, 4.0);

    float sheen =
        max(SHEEN, 0.0);

    float orders =
        max(IRIDESCENCE, 0.0) * 6.0;

    // --------------------------------------
    // Thin-film thickness
    // --------------------------------------
    // First turbulent warp.

    vec2 q = vec2(
        fbm(
            p + vec2(
                0.07 * t,
               -0.05 * t
            )
        ),
        fbm(
            p + vec2(3.7, 8.1)
              + vec2(
                 -0.06 * t,
                  0.07 * t
              )
        )
    ) - 0.5;

    vec2 pw =
        p + sheen * 1.3 * q;

    // Main film thickness.

    float thick = fbm(
        pw + vec2(
             0.04 * t,
            -0.03 * t
        )
    );

    // Fine surface ripple.

    thick += 0.40 * fbm(
        pw * 2.4 + vec2(
            -0.05 * t,
             0.06 * t
        )
    );

    thick *= 0.72;

    // --------------------------------------
    // Thin-film interference
    // --------------------------------------

    float order =
        thick * orders + 0.06 * t;

    vec3 sheenCol = palLoop(
        order * 0.34,
        COLOR_1,
        COLOR_2,
        COLOR_3,
        COLOR_4
    );

    // Constructive / destructive fringes.

    float fringe =
        0.5 + 0.5 * cos(TAU * order);

    fringe = pow(fringe, 2.0);

    // Brightness envelope.

    float bright = mix(
        0.16,
        0.92,
        fringe
    );

    // Reflective crest.

    float crest = smoothstep(
        0.55,
        0.95,
        fringe
    );

    // --------------------------------------
    // Compose original surface
    // --------------------------------------

    vec3 col = BG;

    col += sheenCol * bright * 0.62;
    col += sheenCol * crest * 0.28;
    col += vec3(0.10) * crest * crest;

    // Original internal vignette.

    vec2 vq = uv - 0.5;

    col *= 1.0 - 0.30 * smoothstep(
        0.40,
        1.08,
        length(vq) * 1.42
    );

    return col;
}

// ==========================================
// FILM GRAIN
// ==========================================

float postHash(vec2 p) {
    p = fract(
        p * vec2(123.34, 345.45)
    );

    p += dot(p, p + 34.345);

    return fract(p.x * p.y);
}

// ==========================================
// MAIN IMAGE
// ==========================================

void mainImage(
    out vec4 fragColor,
    in vec2 fragCoord
) {
    vec2 resolution = max(
        iResolution.xy,
        vec2(1.0)
    );

    vec2 uv = fragCoord / resolution;
    float time = iTime;

    // --------------------------------------
    // Original image
    // --------------------------------------

    vec3 col = renderOil(
        uv,
        time,
        resolution
    );

    // --------------------------------------
    // Subtle chromatic aberration
    // --------------------------------------
    //
    // True RGB displacement using three
    // scene evaluations. This costs more
    // than a single film evaluation.

    if (POST_ABERRATION > 0.0) {
        vec2 centered = uv - 0.5;
        vec2 offset =
            centered * POST_ABERRATION;

        vec3 redSample = renderOil(
            clamp(uv + offset, 0.0, 1.0),
            time,
            resolution
        );

        vec3 blueSample = renderOil(
            clamp(uv - offset, 0.0, 1.0),
            time,
            resolution
        );

        col.r = redSample.r;
        col.b = blueSample.b;
    }

    // --------------------------------------
    // Approximate local bloom
    // --------------------------------------
    //
    // Original shader.gallery uses a
    // separate texture-sampling bloom pass.
    // This version highlights bright
    // fringes without extra blur samples.

    if (POST_BLOOM > 0.0) {
        float bright = max(
            max(col.r, col.g),
            col.b
        );

        float glow = max(
            bright - 0.55,
            0.0
        );

        col += col * glow
             * POST_BLOOM * 0.25;
    }

    // --------------------------------------
    // Exposure / contrast
    // --------------------------------------

    col *= POST_EXPOSURE;

    col =
        (col - 0.5) * POST_CONTRAST + 0.5;

    // --------------------------------------
    // Saturation
    // --------------------------------------

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
    // Additional post vignette
    // --------------------------------------

    vec2 center = uv - 0.5;

    float vignette =
        1.0 -
        POST_VIGNETTE *
        dot(center, center) * 2.0;

    col *= clamp(
        vignette,
        0.0,
        1.0
    );

    // --------------------------------------
    // CRT scanlines
    // --------------------------------------

    if (POST_SCANLINE > 0.0) {
        float scan = sin(
            fragCoord.y * 3.14159265
        ) * 0.5 + 0.5;

        col *= 1.0 -
            POST_SCANLINE * scan * 0.6;
    }

    // --------------------------------------
    // RGB phosphor mask
    // --------------------------------------

    if (POST_CRT_MASK > 0.0) {
        float m = mod(
            fragCoord.x,
            3.0
        );

        vec3 mask;

        if (m < 1.0) {
            mask = vec3(
                1.0, 0.7, 0.7
            );
        }
        else if (m < 2.0) {
            mask = vec3(
                0.7, 1.0, 0.7
            );
        }
        else {
            mask = vec3(
                0.7, 0.7, 1.0
            );
        }

        col *= mix(
            vec3(1.0),
            mask,
            POST_CRT_MASK
        );
    }

    // --------------------------------------
    // Animated film grain
    // --------------------------------------

    if (POST_GRAIN > 0.0) {
        vec2 cell = floor(
            fragCoord /
            max(POST_GRAIN_SIZE, 1.0)
        );

        float frame = floor(
            time * POST_GRAIN_SPEED
        );

        float noise = postHash(
            cell +
            frame * vec2(
                63.7, 31.3
            )
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

        col += noise *
            POST_GRAIN *
            visibility;
    }

    fragColor = vec4(
        clamp(col, 0.0, 1.0),
        1.0
    );
}
