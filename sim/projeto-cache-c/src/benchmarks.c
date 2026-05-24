#include "benchmarks.h"
#include <stdlib.h>
#include <stdint.h>

#define HOT_ADDR      0x30000000ULL
#define ARRAY_BASE    0x10000000ULL
#define MATRIX_BASE   0x20000000ULL
#define LIST_BASE     0x40000000ULL
#define BLOB_BASE     0x50000000ULL
#define WS_BASE       0x10000000ULL
#define SCAN_BASE     0x40000000ULL

#define ELEM_SIZE 4   /* sizeof(int) */

/* xorshift32 determinístico p/ shuffle */
static uint32_t xs(uint32_t *s) {
    uint32_t x = *s; x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    *s = x; return x;
}

#define WRITE(addr) do { \
    if (n >= cap) return -1; \
    buf[n++] = (addr); \
} while(0)

ssize_t gen_streaming_hotset(uint64_t *buf, size_t cap,
                              size_t array_size_bytes, int iterations) {
    size_t n = 0;
    size_t n_elems = array_size_bytes / ELEM_SIZE;
    for (int it = 0; it < iterations; it++) {
        for (size_t i = 0; i < n_elems; i++) {
            uint64_t addr = ARRAY_BASE + i * ELEM_SIZE;
            WRITE(addr);  /* read */
            WRITE(addr);  /* write */
            if (i % 64 == 0) {
                WRITE(HOT_ADDR);
                WRITE(HOT_ADDR);
            }
        }
    }
    return (ssize_t)n;
}

ssize_t gen_matrix_conv(uint64_t *buf, size_t cap, int width, int height) {
    size_t n = 0;
    /* Convolução vertical 3x1: dst[y][x] = src[y-1][x] + src[y][x] + src[y+1][x] */
    size_t row_bytes = (size_t)width * ELEM_SIZE;
    for (int y = 1; y < height - 1; y++) {
        for (int x = 0; x < width; x++) {
            uint64_t base = MATRIX_BASE + (size_t)y * row_bytes + (size_t)x * ELEM_SIZE;
            WRITE(base - row_bytes);   /* src[y-1][x] */
            WRITE(base);                /* src[y][x] */
            WRITE(base + row_bytes);    /* src[y+1][x] */
            WRITE(base + row_bytes * (size_t)height);  /* dst[y][x] (escrita) */
        }
    }
    return (ssize_t)n;
}

ssize_t gen_linked_list(uint64_t *buf, size_t cap,
                         int n_nodes, int iterations, int randomize) {
    size_t n = 0;
    /* Ordem dos nós (embaralhada se randomize) */
    int *order = malloc(sizeof(int) * (size_t)n_nodes);
    for (int i = 0; i < n_nodes; i++) order[i] = i;
    if (randomize) {
        uint32_t s = 123;
        for (int i = n_nodes - 1; i > 0; i--) {
            int j = (int)(xs(&s) % (uint32_t)(i + 1));
            int t = order[i]; order[i] = order[j]; order[j] = t;
        }
    }
    /* Cada nó: 8 bytes (next ptr + payload) */
    int node_size = 8;
    for (int it = 0; it < iterations; it++) {
        for (int k = 0; k < n_nodes; k++) {
            uint64_t addr = LIST_BASE + (uint64_t)order[k] * node_size;
            WRITE(addr);
        }
    }
    free(order);
    return (ssize_t)n;
}

ssize_t gen_pattern_search(uint64_t *buf, size_t cap, size_t blob_size, int window) {
    size_t n = 0;
    size_t n_elems = blob_size / ELEM_SIZE;
    /* Para cada posição i, reler as últimas `window` posições */
    for (size_t i = (size_t)window; i < n_elems; i++) {
        for (int k = window; k > 0; k--) {
            uint64_t addr = BLOB_BASE + (i - (size_t)k) * ELEM_SIZE;
            WRITE(addr);
        }
        WRITE(BLOB_BASE + i * ELEM_SIZE);
    }
    return (ssize_t)n;
}

ssize_t gen_mixed_access(uint64_t *buf, size_t cap,
                          int ws_blocks, int scan_blocks,
                          int ws_repeats, int outer_iters) {
    size_t n = 0;
    int block_size = 32;  /* mesmo tamanho do L1 */
    for (int it = 0; it < outer_iters; it++) {
        /* Working set acessado várias vezes */
        for (int r = 0; r < ws_repeats; r++) {
            for (int i = 0; i < ws_blocks; i++) {
                WRITE(WS_BASE + (uint64_t)i * block_size);
            }
        }
        /* Scan invasivo */
        for (int i = 0; i < scan_blocks; i++) {
            WRITE(SCAN_BASE + (uint64_t)i * block_size);
        }
    }
    return (ssize_t)n;
}
