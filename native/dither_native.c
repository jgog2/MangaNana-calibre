#include <stdint.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
#include <limits.h>
#include "manganana_dither.h"

#if defined(_WIN32)
#define API __declspec(dllexport)
#else
#define API __attribute__((visibility("default")))
#endif

typedef struct { int dx, dy; double w; } Tap;
API int manganana_dither_abi_version(void) { return 1; }
/* Exact binary fractions: MSVC /fp:strict disallows FP division in static initializers. */
static const Tap FS[] = {{1,0,.4375},{-1,1,.1875},{0,1,.3125},{1,1,.0625}};
static const Tap ATK[] = {{1,0,.125},{2,0,.125},{-1,1,.125},{0,1,.125},{1,1,.125},{0,2,.125}};
static const Tap SL[] = {{1,0,.5},{-1,1,.25},{0,1,.25}};

static uint8_t py_round_nonnegative(double x) {
    // Python round() ties-to-even. Inputs here are non-negative.
    double fl = floor(x);
    double frac = x - fl;
    if (frac < 0.5) return (uint8_t)fl;
    if (frac > 0.5) return (uint8_t)(fl + 1.0);
    long long base = (long long)fl;
    return (uint8_t)((base & 1LL) ? base + 1LL : base);
}

API int manganana_dither_u8(const uint8_t *src, uint8_t *out, int width, int height,
                            int channels, int levels, double strength, int algorithm) {
    if (!src || !out || width <= 0 || height <= 0 || (channels != 1 && channels != 3)) return -1;
    if (width > INT_MAX-2 || height > INT_MAX-2) return -1;
    if (!(levels==2 || levels==4 || levels==8 || levels==16)) return -2;
    if (!(strength >= 0.0 && strength <= 2.0)) return -3;
    const Tap *kernel = NULL; int ntaps = 0;
    if (algorithm == 1) { kernel = FS; ntaps = 4; }
    else if (algorithm == 2) { kernel = ATK; ntaps = 6; }
    else if (algorithm == 3) { kernel = SL; ntaps = 3; }
    else return -4;

    if ((size_t)width > SIZE_MAX / (size_t)channels) return -1;
    size_t stride = (size_t)width * (size_t)channels;
    if (stride > SIZE_MAX / (3 * sizeof(float)) || (size_t)height > SIZE_MAX / stride) return -1;
    size_t nbuf = 3 * stride;
    float *buf = (float*)malloc(nbuf * sizeof(float));
    if (!buf) return -5;
    memset(buf, 0, nbuf * sizeof(float));
    size_t srcn = (size_t)height * stride;
    size_t initn = 2 * stride < srcn ? 2 * stride : srcn;
    for (size_t i=0; i<initn; ++i) buf[i] = (float)src[i];

    const double step = 255.0 / (double)(levels - 1);
    for (int y=0; y<height; ++y) {
        if (y + 2 < height) {
            size_t boff = (size_t)((y+2)%3) * stride;
            size_t soff = (size_t)(y+2) * stride;
            for (size_t i=0; i<stride; ++i) buf[boff+i] = (float)src[soff+i];
        }
        int direction = (y % 2 == 0) ? 1 : -1;
        for (int scan=0; scan<width; ++scan) {
            int x = direction == 1 ? scan : width - 1 - scan;
            for (int ch=0; ch<channels; ++ch) {
                size_t index = (size_t)(y%3) * stride + (size_t)x*channels + ch;
                double old = (double)buf[index];
                if (old < 0.0) old = 0.0; else if (old > 255.0) old = 255.0;
                double newv = floor(old/step + 0.5) * step;
                out[(size_t)y*stride + (size_t)x*channels + ch] = py_round_nonnegative(newv);
                double err = (old - newv) * strength;
                for (int k=0; k<ntaps; ++k) {
                    int nx = x + kernel[k].dx * direction;
                    int ny = y + kernel[k].dy;
                    if ((unsigned)nx < (unsigned)width && ny < height) {
                        size_t target = (size_t)(ny%3) * stride + (size_t)nx*channels + ch;
                        buf[target] = (float)((double)buf[target] + err * kernel[k].w);
                    }
                }
            }
        }
    }
    free(buf);
    return 0;
}
