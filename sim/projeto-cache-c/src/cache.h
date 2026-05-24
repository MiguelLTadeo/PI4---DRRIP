/*
 * cache.h
 * ---------------------------------------------------------------------------
 * Geometria base de uma cache set-associativa. Define a estrutura de linhas,
 * decomposição de endereço (tag/index/offset), e contadores de hit/miss.
 *
 * As três políticas (LRU, DRRIP-Jaleel, DRRIP-ChampSim) reusam esta estrutura
 * e diferem apenas na lógica de atualização e busca de vítima.
 */
#ifndef CACHE_H
#define CACHE_H

#include <stdint.h>
#include <stddef.h>

#define MAX_ASSOC 32  /* limite estático razoável p/ FPGA */

/* Uma linha de cache. Mantemos campos pra LRU e DRRIP simultaneamente —
 * em hardware seria UM ou OUTRO, mas em modelagem custo zero. */
typedef struct {
    uint8_t  valid;
    uint64_t tag;
    uint16_t lru_age;   /* 0..assoc-1, usado por LRU */
    uint8_t  rrpv;      /* 0..3 (M=2 bits), usado por DRRIP */
} cache_line_t;

/* Cache set-associativa. Tamanho dos arrays é dinâmico (num_sets * assoc). */
typedef struct {
    /* Geometria */
    int      block_bytes;
    int      assoc;
    int      num_sets;
    int      offset_bits;
    int      index_bits;

    /* Armazenamento */
    cache_line_t *lines;   /* num_sets * assoc */

    /* Contadores */
    uint64_t hits;
    uint64_t misses;
    uint64_t cold_misses;

    /* Set p/ contar misses compulsórios (hash table simples) */
    uint8_t *seen_blocks;  /* bitmap esparso; alocação preguiçosa */
    size_t   seen_capacity;
} cache_t;

/* Inicializa cache. size_bytes deve ser múltiplo de block_bytes * assoc. */
void cache_init(cache_t *c, int size_bytes, int block_bytes, int assoc);

/* Libera memória alocada. */
void cache_free(cache_t *c);

/* Decomposição de endereço */
static inline int  cache_set_of(const cache_t *c, uint64_t addr) {
    return (addr >> c->offset_bits) & ((1 << c->index_bits) - 1);
}
static inline uint64_t cache_tag_of(const cache_t *c, uint64_t addr) {
    return addr >> (c->offset_bits + c->index_bits);
}
static inline uint64_t cache_block_of(const cache_t *c, uint64_t addr) {
    return addr >> c->offset_bits;
}

/* Busca a way que contém este tag no conjunto; retorna -1 se miss */
int cache_find_way(const cache_t *c, int set_idx, uint64_t tag);

/* Way inválida (livre), ou -1 */
int cache_find_invalid_way(const cache_t *c, int set_idx);

/* Marca bloco como já visto; retorna 1 se é primeiro contato (cold miss) */
int cache_mark_touched(cache_t *c, uint64_t block_addr);

#endif
