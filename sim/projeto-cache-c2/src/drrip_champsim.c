#include "drrip_champsim.h"
#include <stdlib.h>
#include <string.h>
#include <assert.h>

/*
 * std::knuth_b é Knuth's subtract-with-carry com discard (lag 256, n=24,
 * shuffle de 256). Não vou portar o algoritmo exato — seria absurdo.
 *
 * O que importa é o EFEITO: o std::knuth_b{1} default-construído com seed 1
 * produz valores no range [0, 2^31), ordens de magnitude maiores que qualquer
 * num_sets razoável (~32-128). Esses valores são ARMAZENADOS em rand_sets
 * sem módulo, então `find` nunca encontra um conjunto válido em caches pequenas.
 *
 * Para reproduzir esse efeito fielmente, basta usar QUALQUER gerador
 * pseudo-aleatório que produza valores grandes. Aqui uso a função rand()
 * da libc com seed 1 (que satisfaz a propriedade: valores no range
 * [0, RAND_MAX], tipicamente até 2^31-1).
 */
static size_t knuth_b_proxy(uint32_t *state) {
    /* xorshift simples — produz valores em [0, 2^32) */
    uint32_t x = *state;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    *state = x;
    return (size_t)x;  /* preserva valor "grande" — o ponto do bug */
}

static int size_t_cmp(const void *a, const void *b) {
    size_t x = *(const size_t*)a, y = *(const size_t*)b;
    return (x > y) - (x < y);
}

void drrip_champsim_init(drrip_champsim_t *d, cache_t *c) {
    memset(d, 0, sizeof(*d));
    d->c = c;
    d->psel = 0;          /* ChampSim default */
    d->bip_counter = 0;

    size_t TOTAL_SDM_SETS = CSIM_NUM_CPUS * CSIM_NUM_POLICY * CSIM_SDM_SIZE;
    uint32_t state = 1;   /* knuth_b{1} -> seed = 1 */
    for (size_t i = 0; i < TOTAL_SDM_SETS; i++) {
        d->rand_sets[i] = knuth_b_proxy(&state);
    }
    qsort(d->rand_sets, TOTAL_SDM_SETS, sizeof(size_t), size_t_cmp);
}

void drrip_champsim_free(drrip_champsim_t *d) {
    memset(d, 0, sizeof(*d));
}

/* update_bip: insere com RRPV=MAX; contador GLOBAL; a cada BIP_MAX vira LONG */
static void update_bip(drrip_champsim_t *d, int set_idx, int way) {
    cache_line_t *L = &d->c->lines[set_idx * d->c->assoc + way];
    L->rrpv = CSIM_MAX_RRPV;
    d->bip_counter++;
    if (d->bip_counter == CSIM_BIP_MAX) {
        d->bip_counter = 0;
        L->rrpv = CSIM_MAX_RRPV - 1;
    }
}

/* update_srrip: insere com RRPV=MAX-1 (long) */
static void update_srrip(drrip_champsim_t *d, int set_idx, int way) {
    d->c->lines[set_idx * d->c->assoc + way].rrpv = CSIM_MAX_RRPV - 1;
}

/* Substitui std::find(rand_sets, set) — busca linear */
static int find_in_rand_sets(const drrip_champsim_t *d, size_t value, int begin, int end) {
    for (int i = begin; i < end; i++) {
        if (d->rand_sets[i] == value) return i;
    }
    return end;  /* não encontrou */
}

/* find_victim: max_element + aging delta (fiel ao ChampSim) */
static int find_drrip_victim(cache_t *c, int set_idx) {
    cache_line_t *base = &c->lines[set_idx * c->assoc];
    int victim = 0;
    uint8_t max_rrpv = base[0].rrpv;
    for (int w = 1; w < c->assoc; w++) {
        if (base[w].rrpv > max_rrpv) {
            max_rrpv = base[w].rrpv;
            victim = w;
        }
    }
    int delta = CSIM_MAX_RRPV - max_rrpv;
    if (delta != 0) {
        for (int w = 0; w < c->assoc; w++) {
            base[w].rrpv += (uint8_t)delta;
        }
    }
    return victim;
}

int drrip_champsim_access(drrip_champsim_t *d, uint64_t addr) {
    cache_t *c = d->c;
    int set_idx = cache_set_of(c, addr);
    uint64_t tag = cache_tag_of(c, addr);
    int way = cache_find_way(c, set_idx, tag);

    if (way >= 0) {
        c->hits++;
        c->lines[set_idx * c->assoc + way].rrpv = 0;
        return 1;
    }

    c->misses++;
    if (cache_mark_touched(c, cache_block_of(c, addr))) {
        c->cold_misses++;
    }

    /* Escolhe vítima ANTES de update_replacement_state (ordem do ChampSim) */
    int victim = cache_find_invalid_way(c, set_idx);
    if (victim < 0) victim = find_drrip_victim(c, set_idx);
    cache_line_t *L = &c->lines[set_idx * c->assoc + victim];
    L->valid = 1;
    L->tag = tag;

    /* update_replacement_state em miss: lógica de set dueling */
    int triggering_cpu = 0;
    int begin = triggering_cpu * CSIM_NUM_POLICY * CSIM_SDM_SIZE;
    int end = begin + CSIM_NUM_POLICY * CSIM_SDM_SIZE;
    int leader = find_in_rand_sets(d, (size_t)set_idx, begin, end);

    if (leader == end) {
        /* follower */
        if (d->psel > CSIM_PSEL_MAX / 2) {
            update_bip(d, set_idx, victim);
        } else {
            update_srrip(d, set_idx, victim);
        }
    } else if (leader == begin) {
        /* leader 0: BIP. PSEL-- */
        if (d->psel > 0) d->psel--;
        update_bip(d, set_idx, victim);
    } else if (leader == begin + 1) {
        /* leader 1: SRRIP. PSEL++ */
        if (d->psel < CSIM_PSEL_MAX) d->psel++;
        update_srrip(d, set_idx, victim);
    } else {
        /* Outros leaders são tratados como followers no ChampSim original */
        if (d->psel > CSIM_PSEL_MAX / 2) update_bip(d, set_idx, victim);
        else update_srrip(d, set_idx, victim);
    }
    return 0;
}
