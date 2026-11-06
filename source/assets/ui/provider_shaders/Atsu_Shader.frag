
// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 E. T. Carter <support@shader.gallery>
//
// Inkflow (Current)
// Single-pass Shader Lab adaptation

// ==========================================
// ORIGINAL HTML COLOR PALETTE
// RGB values are normalized from 0.0 to 1.0
// ==========================================

const vec3 COLOR_1 = vec3(0.612, 0.682, 0.769);
const vec3 COLOR_2 = vec3(0.776, 0.831, 0.890);
const vec3 COLOR_3 = vec3(0.918, 0.945, 0.973);
const vec3 COLOR_4 = vec3(0.408, 0.471, 0.561);

// ==========================================
// ORIGINAL HTML PARAMETER OVERRIDES
// ==========================================

const float SPEED           = 0.58;
const float TURBULENCE      = 1.68;
const float SPREAD          = 0.30;
const float TENDRILS        = 2.00;
const float SEPARATION      = 0.61;
const float MOUSE_INFLUENCE = 0.00;

const int NP = 5;
const float PERIOD = 26.0;

// ==========================================
// CRT / POST-PROCESSING SETTINGS
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
// NOISE FUNCTIONS
// ==========================================

float hash11(float n) {
    return fract(sin(n * 127.1) * 43758.5453123);
}

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

float fbm4(vec2 p) {
    float a = 0.5;
    float s = 0.0;

    for (int i = 0; i < 4; i++) {
        s += a * vnoise(p);
        p = M2 * p * 2.03 + vec2(11.7, 5.3);
        a *= 0.5;
    }

    return s * 1.07;
}

float fbm3(vec2 p) {
    float a = 0.5;
    float s = 0.0;

    for (int i = 0; i < 3; i++) {
        s += a * vnoise(p);
        p = M2 * p * 2.03 + vec2(11.7, 5.3);
        a *= 0.5;
    }

    return s * 1.14;
}

float ridged5(vec2 p) {
    float a = 0.5;
    float s = 0.0;

    for (int i = 0; i < 5; i++) {
        float n = 1.0 - abs(
            2.0 * vnoise(p) - 1.0
        );

        s += a * n * n;
        p = M2 * p * 2.11 + vec2(7.3, 3.1);
        a *= 0.52;
    }

    return s;
}

// ==========================================
// INK DENSITY FIELD
// ==========================================

vec3 ink(
    vec2 p,
    float aspect,
    float t,
    float turb,
    float spread,
    float tend
) {
    // Two-stage turbulent domain warp.

    vec2 q = vec2(
        fbm4(
            p * 1.3 +
            vec2(t * 0.05, -t * 0.03)
        ),
        fbm4(
            p * 1.3 +
            vec2(4.7, 2.9) +
            vec2(-t * 0.04, t * 0.02)
        )
    ) - 0.5;

    vec2 r = vec2(
        fbm4(
            p * 1.3 +
            1.6 * q +
            vec2(1.7, 9.2) +
            vec2(0.0, t * 0.06)
        ),
        fbm4(
            p * 1.3 +
            1.6 * q +
            vec2(8.3, 2.8) +
            vec2(0.0, t * 0.05)
        )
    ) - 0.5;

    vec2 wq = q + 0.8 * r;

    // Fibrous tendrils.

    vec2 pw = p + wq * 0.9 * turb;

    float fib = ridged5(
        pw * vec2(3.2, 2.2) +
        vec2(0.0, t * 0.12)
    );

    float tdr = smoothstep(
        0.62, 0.95, fib
    );

    float dens = 0.0;
    float ageAcc = 0.0;

    // Five independently cycling ink drops.

    for (int i = 0; i < NP; i++) {
        float k = float(i);

        float phase = hash11(k + 3.0);

        float cyc = floor(
            t / PERIOD + phase
        );

        float age = fract(
            t / PERIOD + phase
        );

        float hj = hash11(
            cyc * 7.0 + k * 13.0
        );

        float hk = hash11(
            cyc * 3.0 + k * 5.0 + 1.0
        );

        // Drop release location.

        float x0 = (
            (k + 0.5) / float(NP) * 2.0
            - 1.0
        ) * aspect * 1.08;

        x0 += (hj - 0.5)
            * 0.45
            * aspect
            / float(NP)
            * 2.0;

        float y0 = 1.02 + hk * 0.12;

        // Sinking distance.

        float L = (
            2.55 + 0.3 * hk
        ) * (
            1.0 - exp(-age * 2.6)
        );

        vec2 qq = p - vec2(x0, y0);

        float s = -qq.y;

        float sn = clamp(
            s / max(L, 1e-3),
            0.0,
            1.0
        );

        // Warp increases away from the neck.

        float wA = turb
            * (0.05 + 0.30 * sn)
            * (0.6 + 0.7 * age);

        float xl = qq.x
            + wq.x * wA
            + (hj - 0.5)
            * 0.5
            * s * s
            * 0.35;

        float sl = s + wq.y * wA * 0.7;

        // Diffusion width.

        float w = spread * (
            0.014 +
            0.065 * sqrt(max(sn, 0.0))
            * (0.55 + 1.0 * age)
        );

        // Mushroom-shaped drop head.

        float hd = exp(
            -(sl - L) * (sl - L)
            / max(
                0.05 + 0.03 * L * L,
                1e-3
            )
        );

        w += spread
            * (
                0.05 +
                0.27 * smoothstep(0.0, 1.3, L)
            )
            * hd
            * (1.0 - 0.3 * age);

        float ra = xl / max(w, 1e-3);
        float ra2 = ra * ra;

        float body = exp(-ra2 * 1.1);

        float tail = max(
            sl - L, 0.0
        ) / (
            0.6 * w + 0.15
        );

        float capF = exp(
            -(tail * tail)
            * (1.0 + 1.6 * ra2)
        );

        float along =
            smoothstep(-0.05, 0.08, sl)
            * capF;

        // Main body.

        float d = body
            * along
            * (0.45 + 1.9 * fib)
            * (0.8 + 1.0 * hd)
            * 1.6;

        // Trailing tendrils.

        float sheath = exp(
            -ra2 * 0.10
        ) * along;

        d += tend
            * tdr
            * sheath
            * (0.4 + 0.8 * sn)
            * 1.3;

        // Age-dependent diffusion.

        d *= 1.0 - 0.5 * age;

        float life =
            smoothstep(0.0, 0.04, age)
            * (
                1.0 -
                smoothstep(0.62, 1.0, age)
            );

        d *= life;

        dens += d;
        ageAcc += d * age;
    }

    return vec3(
        dens,
        ageAcc / max(dens, 1e-4),
        fib
    );
}

// ==========================================
// ORIGINAL INKFLOW SCENE
// ==========================================

vec3 renderInkflow(
    vec2 uv,
    float time,
    vec2 resolution
) {
    float aspect =
        resolution.x / resolution.y;

    vec2 p = vec2(
        (uv.x - 0.5) * aspect,
        uv.y - 0.5
    ) * 2.0;

    float t = time
        * clamp(SPEED, 0.0, 2.0)
        + 40.0;

    float turb = clamp(
        TURBULENCE, 0.0, 2.5
    );

    float spread = clamp(
        SPREAD, 0.3, 2.5
    );

    float tend = clamp(
        TENDRILS, 0.0, 2.0
    );

    float sep = clamp(
        SEPARATION, 0.0, 1.5
    );

    // Mouse interaction is disabled by default
    // in the original HTML configuration.

    // Density and top-light sample.

    float e = 0.014;

    vec3 d0 = ink(
        p, aspect, t,
        turb, spread, tend
    );

    float dy = ink(
        p + vec2(0.0, e),
        aspect, t,
        turb, spread, tend
    ).x;

    float D = d0.x;
    float age = d0.y;
    float fib = d0.z;

    // Optical thickness.

    float T = 1.0 - exp(-D * 1.05);

    float dif = clamp(
        0.5 + 6.0 * (D - dy),
        0.0,
        1.0
    );

    // Dark water background.

    vec3 lum3 = vec3(
        0.299, 0.587, 0.114
    );

    vec3 deep = mix(
        vec3(0.050, 0.054, 0.066),
        mix(
            vec3(dot(COLOR_4, lum3)),
            COLOR_4,
            0.55
        ) * 0.30,
        0.50
    );

    float haze = fbm4(
        p * 0.7 +
        vec2(t * 0.02, t * 0.035)
    ) - 0.5;

    vec3 water = deep
        * (0.70 + 0.80 * uv.y)
        * (1.0 + haze * 0.6);

    water += mix(
        COLOR_1,
        COLOR_3,
        0.5
    ) * 0.07
      * smoothstep(-0.25, 0.45, haze)
      * (0.4 + 0.6 * uv.y);

    // Pigment separation.

    float spr = sep * (
        0.6 + 0.6 * age
    );

    float fBody = smoothstep(
        0.06 + 0.06 * spr,
        0.45 + 0.20 * spr,
        T
    );

    float fCore = smoothstep(
        0.55 + 0.10 * spr,
        0.97,
        T
    );

    vec3 fringe = mix(
        COLOR_3,
        vec3(1.0),
        0.25
    );

    vec3 bodyC = mix(
        fringe,
        COLOR_1,
        0.55 + 0.45 * sep
    );

    vec3 coreC = mix(
        COLOR_1,
        COLOR_2,
        0.80
    ) * (
        0.55 + 0.55 * fib
    );

    vec3 inkCol = mix(
        fringe,
        bodyC,
        fBody
    );

    inkCol = mix(
        inkCol,
        coreC,
        fCore
    );

    // Luminous volume shading.

    float glowAmt = T
        * (1.0 - 0.5 * fCore)
        * (0.9 + 0.8 * fib)
        * 1.2;

    float shade =
        0.75 + 0.35 * dif;

    vec3 col = water
        * (1.0 - T * 0.9);

    col += inkCol
        * glowAmt
        * shade;

    // Original internal vignette.

    vec2 vq = uv - 0.5;

    col *= 1.0 - 0.22
        * smoothstep(
            0.3,
            1.0,
            length(vq) * 1.42
        );

    return col;
}

// ==========================================
// CRT GRAIN FUNCTION
// ==========================================

float postHash(vec2 p) {
    p = fract(
        p * vec2(123.34, 345.45)
    );

    p += dot(p, p + 34.345);

    return fract(p.x * p.y);
}

// ==========================================
// MAIN — SHADER LAB
// ==========================================

void mainImage(
    out vec4 fragColor,
    in vec2 fragCoord
) {
    vec2 resolution = iResolution.xy;
    vec2 uv = fragCoord / resolution;

    float time = iTime;

    // Original Inkflow image.

    vec3 col = renderInkflow(
        uv,
        time,
        resolution
    );

    // --------------------------------------
    // Approximate chromatic aberration
    // --------------------------------------
    // A full recreation would render the
    // expensive ink field three times.
    // This version uses a highlight tint.

    if (POST_ABERRATION > 0.0) {
        vec2 centered = uv - 0.5;

        float offset = length(centered)
            * POST_ABERRATION
            * 100.0;

        col.r *= 1.0 + offset * 0.08;
        col.b *= 1.0 - offset * 0.04;
    }

    // --------------------------------------
    // Approximate bloom
    // --------------------------------------

    if (POST_BLOOM > 0.0) {
        float bright = max(
            max(col.r, col.g),
            col.b
        );

        float glow = max(
            bright - 0.55,
            0.0
        );

        col += col
            * glow
            * POST_BLOOM
            * 0.25;
    }

    // --------------------------------------
    // Exposure and contrast
    // --------------------------------------

    col *= POST_EXPOSURE;

    col = (
        col - 0.5
    ) * POST_CONTRAST + 0.5;

    // Saturation.

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

    vec2 center = uv - 0.5;

    float vig =
        1.0 -
        POST_VIGNETTE *
        dot(center, center) *
        2.0;

    col *= clamp(vig, 0.0, 1.0);

    // --------------------------------------
    // CRT scanlines
    // --------------------------------------

    if (POST_SCANLINE > 0.0) {
        float s = sin(
            fragCoord.y * 3.14159265
        ) * 0.5 + 0.5;

        col *= 1.0
            - POST_SCANLINE * s * 0.6;
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

        col += noise
            * POST_GRAIN
            * visibility;
    }

    fragColor = vec4(
        clamp(col, 0.0, 1.0),
        1.0
    );
}
