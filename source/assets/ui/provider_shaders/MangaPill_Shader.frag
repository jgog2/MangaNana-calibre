
// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 E. T. Carter <support@shader.gallery>
//
// Beat — Shader Lab adaptation
// Original shader.gallery geometry and parameters.
// Post-processing adapted into a single fragment shader.

// ==========================================
// COLOR PALETTE — ORIGINAL VALUES
// ==========================================

const vec3 COLOR_1 = vec3(0.0, 0.439, 0.953);
const vec3 COLOR_2 = vec3(0.255, 0.518, 0.835);
const vec3 COLOR_3 = vec3(0.451, 0.682, 0.918);
const vec3 COLOR_4 = vec3(0.110, 0.176, 0.392);

// ==========================================
// SHADER SETTINGS
// ==========================================

const float RING_FREQUENCY = 26.0;
const float DETUNE         = 0.12;
const float DRIFT          = 0.40;
const float CRISPNESS      = 0.60;

// ==========================================
// POST PROCESSING — ORIGINAL SETTINGS
// ==========================================

const float GRAIN          = 0.05;
const float GRAIN_SIZE     = 1.50;
const float GRAIN_SPEED    = 10.0;
const float ABERRATION     = 0.0015;
const float VIGNETTE       = 0.50;
const float EXPOSURE       = 1.00;
const float CONTRAST       = 1.00;
const float SATURATION     = 1.10;
const float BLOOM          = 0.70;
const float BLOOM_RADIUS   = 4.00;
const float SCANLINE       = 0.50;
const float CRT_MASK       = 0.05;

// ==========================================
// UTILITY FUNCTIONS
// ==========================================

float hashBeat(vec2 p) {
    p = fract(p * vec2(123.34, 345.45));
    p += dot(p, p + 34.345);
    return fract(p.x * p.y);
}

// ==========================================
// ORIGINAL BEAT SHADER
// ==========================================

vec3 renderBeat(vec2 uv, float time, vec2 resolution) {

    float aspect = resolution.x / resolution.y;

    vec2 p = vec2(
        (uv.x - 0.5) * aspect,
        uv.y - 0.5
    );

    // Two independently drifting ring centers.

    vec2 cA = vec2(-0.28, 0.0)
        + vec2(
            sin(time * 0.31 * DRIFT),
            cos(time * 0.27 * DRIFT)
        ) * 0.18;

    vec2 cB = vec2(0.28, 0.0)
        + vec2(
            cos(time * 0.29 * DRIFT),
            sin(time * 0.33 * DRIFT)
        ) * 0.18;

    float f = max(RING_FREQUENCY, 4.0);

    // Two concentric ring gratings.

    float ra = sin(
        length(p - cA) * f - time * 1.3
    );

    float rb = sin(
        length(p - cB) * f * (1.0 + DETUNE)
        + time * 1.1
    );

    // Multiplication generates the moire pattern.

    float moire = ra * rb;

    float k = mix(
        0.32,
        0.04,
        clamp(CRISPNESS, 0.0, 1.0)
    );

    float band = smoothstep(
        0.5 - k,
        0.5 + k,
        moire * 0.5 + 0.5
    );

    // Palette modulation.

    float hue = 0.5 + 0.5 * sin(
        length(p) * 3.0 + (ra + rb)
    );

    vec3 lit = mix(COLOR_3, COLOR_2, hue);

    lit = mix(
        lit,
        COLOR_1,
        smoothstep(0.3, 0.9, band) * 0.5
    );

    vec3 bg = COLOR_4 * 0.10;

    return mix(bg, lit, band);
}

// ==========================================
// CHROMATIC ABERRATION
// ==========================================

vec3 sampleBeat(
    vec2 uv,
    float time,
    vec2 resolution
) {
    vec2 toCenter = uv - 0.5;

    vec2 offset = toCenter * ABERRATION;

    vec3 col;

    col.r = renderBeat(
        uv + offset, time, resolution
    ).r;

    col.g = renderBeat(
        uv, time, resolution
    ).g;

    col.b = renderBeat(
        uv - offset, time, resolution
    ).b;

    return col;
}

// ==========================================
// APPROXIMATE BLOOM
// ==========================================

vec3 bloomBeat(
    vec2 uv,
    float time,
    vec2 resolution
) {
    vec3 sum = vec3(0.0);

    // Same golden-angle sampling pattern used
    // by shader.gallery's post-processing pass.

    for (int i = 0; i < 12; i++) {

        float fi = float(i) + 0.5;

        float angle = fi * 2.39996323;

        float radius = sqrt(fi / 12.0)
                     * BLOOM_RADIUS;

        vec2 offset = vec2(
            cos(angle),
            sin(angle)
        ) * radius / resolution;

        vec3 s = renderBeat(
            uv + offset,
            time,
            resolution
        );

        float brightness = max(
            max(max(s.r, s.g), s.b) - 0.55,
            0.0
        );

        sum += s * brightness;
    }

    return sum * (BLOOM / 12.0);
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

    // Original Beat image.

    vec3 col = sampleBeat(
        uv, time, resolution
    );

    // Bloom.

    if (BLOOM > 0.0) {
        col += bloomBeat(
            uv, time, resolution
        );
    }

    // Exposure and contrast.

    col *= EXPOSURE;

    col = (col - 0.5) * CONTRAST + 0.5;

    // Saturation.

    float luminance = dot(
        col,
        vec3(0.299, 0.587, 0.114)
    );

    col = mix(
        vec3(luminance),
        col,
        SATURATION
    );

    // Vignette.

    vec2 centered = uv - 0.5;

    float vig = 1.0
        - VIGNETTE * dot(centered, centered) * 2.0;

    col *= clamp(vig, 0.0, 1.0);

    // CRT scanline effect.

    if (SCANLINE > 0.0) {

        float s = sin(
            fragCoord.y * 3.14159265
        ) * 0.5 + 0.5;

        col *= 1.0 - SCANLINE * s * 0.6;
    }

    // CRT RGB phosphor mask.

    if (CRT_MASK > 0.0) {

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
            CRT_MASK
        );
    }

    // Animated film grain.

    if (GRAIN > 0.0) {

        vec2 cell = floor(
            fragCoord / max(GRAIN_SIZE, 1.0)
        );

        float frame = floor(
            time * GRAIN_SPEED
        );

        float noise = hashBeat(
            cell + frame * vec2(63.7, 31.3)
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

        col += noise * GRAIN * visibility;
    }

    fragColor = vec4(
        clamp(col, 0.0, 1.0),
        1.0
    );
}
