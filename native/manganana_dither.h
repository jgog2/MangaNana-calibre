#ifndef MANGANANA_DITHER_H
#define MANGANANA_DITHER_H

#include <stdint.h>

#if defined(_WIN32)
  #define MANGANANA_API __declspec(dllexport)
#else
  #define MANGANANA_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

/*
ABI 1. Buffers must be distinct and hold width*height*channels bytes.
No callback or Python/host object crosses this boundary.
Algorithm IDs:
  1 = Floyd-Steinberg
  2 = Atkinson
  3 = Sierra-Lite

channels must be 1 (L) or 3 (RGB).
levels must be 2, 4, 8, or 16.
strength is 0.0 through 2.0.

Returns 0 on success, negative error code on invalid input/allocation failure.
The caller owns src/out buffers. The function allocates only its bounded
three-row float work buffer and is re-entrant/thread-safe.
*/
MANGANANA_API int manganana_dither_abi_version(void);
MANGANANA_API int manganana_dither_u8(
    const uint8_t *src,
    uint8_t *out,
    int width,
    int height,
    int channels,
    int levels,
    double strength,
    int algorithm
);

#ifdef __cplusplus
}
#endif

#endif
