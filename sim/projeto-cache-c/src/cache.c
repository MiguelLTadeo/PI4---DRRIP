/*
 * cache.c — implementação das funções comuns de geometria.
 */
#include "cache.h"
#include <stdlib.h>
#include <string.h>
#include <assert.h>

static int log2_int(int n) {
    int k = 0;
    while ((1 << k) < n) k++;
    return k;
}

void cache_init(cache_t *c, int size_bytes, int block_bytes, int assoc) {
    memset(c, 0, sizeof(*c));
    c->block_bytes = block_bytes;
    c->assoc = assoc;
    c->num_sets = size_bytes / (block_bytes * assoc);
    c->offset_bits = log2_int(block_bytes);
    c->index_bits = log2_int(c->num_sets);

    assert(c->num_sets > 0);
    assert(assoc <= MAX_ASSOC);

    c->lines = calloc((size_t)c->num_sets * assoc, sizeof(cache_line_t));
    assert(c->lines);

    /* Inicializa RRPV = MAX (3) e idades distintas pra LRU */
    for (int s = 0; s < c->num_sets; s++) {
        for (int w = 0; w < assoc; w++) {
            cache_line_t *L = &c->lines[s * assoc + w];
            L->valid = 0;
            L->tag = 0;
            L->lru_age = (uint16_t)w;   /* idades 0..assoc-1 distintas */
            L->rrpv = 3;
        }
    }
}

void cache_free(cache_t *c) {
    free(c->lines);
    free(c->seen_blocks);
    memset(c, 0, sizeof(*c));
}

int cache_find_way(const cache_t *c, int set_idx, uint64_t tag) {
    cache_line_t *base = &c->lines[set_idx * c->assoc];
    for (int w = 0; w < c->assoc; w++) {
        if (base[w].valid && base[w].tag == tag) return w;
    }
    return -1;
}

int cache_find_invalid_way(const cache_t *c, int set_idx) {
    cache_line_t *base = &c->lines[set_idx * c->assoc];
    for (int w = 0; w < c->assoc; w++) {
        if (!base[w].valid) return w;
    }
    return -1;
}

/* Hash set rápido pra rastrear blocos já vistos. Usa endereço de bloco
 * direto como chave (espaço de endereços pequeno em traces sintéticos). */
int cache_mark_touched(cache_t *c, uint64_t block_addr) {
    size_t cap = c->seen_capacity;
    if (cap == 0) {
        cap = 1 << 16;  /* 64k entradas iniciais */
        c->seen_blocks = calloc(cap, sizeof(uint8_t));
        c->seen_capacity = cap;
    }
    size_t idx = (size_t)(block_addr * 2654435761u) & (cap - 1);
    /* Linear probing simples; suficiente pra essa carga de trabalho */
    for (size_t probe = 0; probe < cap; probe++) {
        size_t pos = (idx + probe) & (cap - 1);
        if (c->seen_blocks[pos] == 0) {
            c->seen_blocks[pos] = 1;
            return 1;  /* primeira vez */
        }
        /* Não distinguimos colisões — em traces pequenos basta */
        if (probe > 32) break;
    }
    return 0;
}
