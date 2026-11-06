// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 E. T. Carter <support@shader.gallery>
// Shader Lab Lite adaptation: welter + approximated gallery post FX.
// Paste into a Shader Lab .frag file. The lab supplies iTime/iResolution/mainImage wrapper.

// ===== EDIT COLORS HERE (RGB floats 0..1) =====
// These are the ACTUAL palette values in the supplied HTML renderer,
// not the blue/purple fallback palette in the standalone shader source.
const vec3 COLOR_0 = vec3(1.0, 0.404, 0.251);
const vec3 COLOR_1 = vec3(1.0, 0.953, 0.831);
const vec3 COLOR_2 = vec3(1.0, 0.251, 0.0);
const vec3 COLOR_3 = vec3(1.0, 0.482, 0.310);

// ===== EDIT EFFECT SETTINGS HERE =====
const float DRIFT_SPEED = 0.30;
const float SOFTNESS = 0.64;    // The HTML preview uses 0.64, not the 0.85 metadata default.
const float WARP = 0.95;
const float HEAT = 0.70;

const float CRT_SCANLINES = 0.40;
const float CRT_MASK = 0.45;
const float FILM_GRAIN = 0.05;
const float GRAIN_SPEED = 10.0;
const float VIGNETTE = 0.50;
const float ABERRATION = 0.0025;
const float BLOOM = 0.70;
const float BLOOM_RADIUS_PX = 4.0;
const float SATURATION = 1.10;

float hashWelter(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}
float valueNoise(vec2 p) {
    vec2 ip = floor(p), f = fract(p);
    vec2 u = f*f*(3.0 - 2.0*f);
    float a = hashWelter(ip);
    float b = hashWelter(ip + vec2(1.0, 0.0));
    float c = hashWelter(ip + vec2(0.0, 1.0));
    float d = hashWelter(ip + vec2(1.0, 1.0));
    return mix(mix(a,b,u.x), mix(c,d,u.x), u.y);
}
float fbmWelter(vec2 p) {
    float s = 0.0, a = 0.55;
    mat2 rot = mat2(0.80, 0.60, -0.60, 0.80);
    for (int i = 0; i < 4; ++i) {
        s += a * valueNoise(p);
        p = rot*p*2.03 + vec2(11.3,7.1);
        a *= 0.5;
    }
    return s;
}
float poleWeight(vec2 pos, vec2 center, float r) {
    vec2 d = pos - center;
    return exp(-dot(d,d)/max(r*r, 1e-3));
}

// The ORIGINAL molten-gradient function, evaluated at arbitrary UV.
// Calling it at offset UVs approximates shader.gallery's texture post pass.
vec3 welter(vec2 uv, float seconds) {
    float aspect = iResolution.x / iResolution.y;
    vec2 pos = vec2((uv.x-0.5)*aspect, uv.y-0.5);
    float t = seconds * DRIFT_SPEED;
    vec2 wv = vec2(fbmWelter(pos*1.9 + t*0.6),
                   fbmWelter(pos*1.9 + vec2(4.0,9.0) - t*0.5)) - 0.5;
    pos += wv * (0.55*WARP);

    vec2 p0 = vec2(-0.5, 0.55) + vec2(sin(t*0.9), cos(t*1.1+1.0))*0.40;
    vec2 p1 = vec2(0.55, 0.20) + vec2(sin(t*0.7+2.1), cos(t*1.3+0.4))*0.42;
    vec2 p2 = vec2(-0.10,-0.50) + vec2(sin(t*1.2+4.0), cos(t*0.8+3.0))*0.44;
    vec2 p3 = vec2(0.45,-0.30) + vec2(sin(t*0.8+5.5), cos(t*1.0+2.4))*0.40;
    vec2 p4 = vec2(-0.45,-0.05) + vec2(sin(t*1.05+1.3), cos(t*0.9+4.2))*0.42;
    float r = 0.42*max(SOFTNESS,0.25);
    float w0 = poleWeight(pos,p0,r), w1 = poleWeight(pos,p1,r);
    float w2 = poleWeight(pos,p2,r), w3 = poleWeight(pos,p3,r);
    float w4 = poleWeight(pos,p4,r);
    float wsum = w0+w1+w2+w3+w4+1e-3;
    vec3 col = (w0*COLOR_0 + w1*COLOR_1 + w2*COLOR_2
              + w3*COLOR_3 + w4*COLOR_2) / wsum;
    float hot = clamp(max(max(w0,w1), max(w2,max(w3,w4)))/wsum*1.6,0.0,1.0);
    col *= mix(0.62,1.18,pow(hot,mix(1.0,2.2,HEAT)));
    col += COLOR_2*0.18*HEAT*smoothstep(0.55,1.0,hot);
    return col;
}

vec3 sampleWelter(vec2 uv, float t) {
    return welter(clamp(uv,vec2(0.0),vec2(1.0)),t);
}

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 uv = fragCoord / iResolution.xy;
    float t = iTime;

    // Chromatic aberration, applied to the original molten image.
    vec2 off = (uv-0.5)*ABERRATION;
    vec3 col;
    col.r = sampleWelter(uv+off,t).r;
    col.g = sampleWelter(uv,t).g;
    col.b = sampleWelter(uv-off,t).b;

    // Approximate original gallery bloom. Disable BLOOM for faster iteration.
    if (BLOOM > 0.0001) {
        vec3 sum = vec3(0.0);
        for (int j = 0; j < 8; ++j) {
            float fi = float(j) + 0.5;
            float angle = fi*2.39996323;
            float rad = sqrt(fi/8.0)*BLOOM_RADIUS_PX;
            vec2 d = vec2(cos(angle),sin(angle))*rad/iResolution.xy;
            vec3 s = sampleWelter(uv+d,t);
            float bright = max(max(max(s.r,s.g),s.b)-0.55,0.0);
            sum += s*bright;
        }
        col += sum*(BLOOM/8.0);
    }

    float lum = dot(col, vec3(0.299,0.587,0.114));
    col = mix(vec3(lum),col,SATURATION);
    col *= clamp(1.0-VIGNETTE*dot(uv-0.5,uv-0.5)*2.0,0.0,1.0);

    // Same formulas as gallery scanline and RGB-column mask.
    if (CRT_SCANLINES > 0.0001) {
        float s = sin(fragCoord.y*3.14159265)*0.5+0.5;
        col *= 1.0-CRT_SCANLINES*s*0.6;
    }
    if (CRT_MASK > 0.0001) {
        float stripe = mod(floor(fragCoord.x),3.0);
        vec3 mask = stripe < 1.0 ? vec3(1.0,0.7,0.7)
                  : (stripe < 2.0 ? vec3(0.7,1.0,0.7)
                                  : vec3(0.7,0.7,1.0));
        col *= mix(vec3(1.0),mask,CRT_MASK);
    }
    if (FILM_GRAIN > 0.0001) {
        vec2 cell = floor(fragCoord/1.5);
        float frame = floor(t*GRAIN_SPEED);
        float n = hashWelter(cell+frame*vec2(63.7,31.3))-0.5;
        float l = dot(col,vec3(0.299,0.587,0.114));
        float vis = clamp(1.0-abs(l-0.5)*1.1,0.4,1.0);
        col += n*FILM_GRAIN*vis;
    }
    fragColor = vec4(clamp(col,0.0,1.0),1.0);
}
