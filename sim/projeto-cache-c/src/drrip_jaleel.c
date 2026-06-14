#include "drrip_jaleel.h"
#include <stdlib.h>
#include <string.h>
#include <assert.h>

/* PRNG determinístico simples (xorshift32) para seleção reprodutível dos SDMs */
static uint32_t xs32(uint32_t *s) {
    uint32_t x = *s;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    *s = x;
    return x;
}

void drrip_jaleel_init(drrip_jaleel_t *d, cache_t *c, uint32_t seed) {
    memset(d, 0, sizeof(*d));
    d->c = c;
    d->psel = DRRIP_PSEL_INIT;

    /* SDMs: amostragem deterministica dentro de [0, num_sets) sem repetição.
     * Usa-se min(SDM_SIZE, num_sets/4) por política para caches pequenas. */
    int n_per_policy = DRRIP_SDM_SIZE;
    if (c->num_sets / 4 < n_per_policy) {
        n_per_policy = c->num_sets / 4;
        if (n_per_policy < 1) n_per_policy = 1;
    }
    d->n_sdm = n_per_policy;

    /* Fisher-Yates shuffle de [0..num_sets-1], pega primeiros 2*n_per_policy */
    int *pool = malloc(sizeof(int) * c->num_sets);
    for (int i = 0; i < c->num_sets; i++) pool[i] = i;
    uint32_t rng = seed;
    for (int i = c->num_sets - 1; i > 0; i--) {
        int j = xs32(&rng) % (uint32_t)(i + 1);
        int tmp = pool[i]; pool[i] = pool[j]; pool[j] = tmp;
    }
    /* primeiros n -> SRRIP_SDM; próximos n -> BRRIP_SDM */
    assert(c->num_sets < (int)(sizeof(d->sdm_kind)/sizeof(d->sdm_kind[0])));
    memset(d->sdm_kind, 0, sizeof(d->sdm_kind));
    for (int i = 0; i < n_per_policy; i++) {
        d->srrip_sdm[i] = pool[i];
        d->sdm_kind[pool[i]] = 1;
    }
    for (int i = 0; i < n_per_policy; i++) {
        d->brrip_sdm[i] = pool[n_per_policy + i];
        d->sdm_kind[pool[n_per_policy + i]] = 2;
    }
    free(pool);

    d->bip_counter_per_set = calloc(c->num_sets, sizeof(uint8_t));
    assert(d->bip_counter_per_set);
}

void drrip_jaleel_free(drrip_jaleel_t *d) {
    free(d->bip_counter_per_set);
    memset(d, 0, sizeof(*d));
}

/* Decide qual política aplicar para um conjunto específico */
static int decide_policy(drrip_jaleel_t *d, int set_idx) {
    int kind = d->sdm_kind[set_idx];
    if (kind == 1) return 1;  /* SRRIP_SDM */
    if (kind == 2) return 2;  /* BRRIP_SDM */
    /* follower: MSB do PSEL decide (bit 9 de contador de 10 bits = valor > 511) */
    return (d->psel > DRRIP_PSEL_MAX / 2) ? 2 : 1;  /* psel alto = BRRIP vence */
}

/* RRPV de inserção para BRRIP (contador per-set) */
static uint8_t brrip_insert_rrpv(drrip_jaleel_t *d, int set_idx) {
    d->bip_counter_per_set[set_idx]++;
    if (d->bip_counter_per_set[set_idx] % DRRIP_BIP_DENOM == 0) {
        return DRRIP_LONG_RRPV;
    }
    return DRRIP_MAX_RRPV;
}

/* Encontra vítima: linha inválida > linha com RRPV=3 > aging */
static int find_drrip_victim(cache_t *c, int set_idx) {
    int inv = cache_find_invalid_way(c, set_idx);
    if (inv >= 0) return inv;

    cache_line_t *base = &c->lines[set_idx * c->assoc];
    /* Loop de aging com cota de segurança */
    for (int iter = 0; iter <= DRRIP_MAX_RRPV + 1; iter++) {
        for (int w = 0; w < c->assoc; w++) {
            if (base[w].rrpv == DRRIP_MAX_RRPV) return w;
        }
        /* Nenhuma com MAX; envelhece todas as válidas */
        for (int w = 0; w < c->assoc; w++) {
            if (base[w].rrpv < DRRIP_MAX_RRPV) base[w].rrpv++;
        }
    }
    return 0;  /* nunca deveria chegar aqui */
}

int drrip_jaleel_access(drrip_jaleel_t *d, uint64_t addr) {
    cache_t *c = d->c;
    int set_idx = cache_set_of(c, addr);
    uint64_t tag = cache_tag_of(c, addr);
    int way = cache_find_way(c, set_idx, tag);

    if (way >= 0) {
        /* HIT — política Hit Priority: RRPV -> 0 */
        c->hits++;
        c->lines[set_idx * c->assoc + way].rrpv = 0;
        return 1;
    }

    /* MISS */
    c->misses++;
    if (cache_mark_touched(c, cache_block_of(c, addr))) {
        c->cold_misses++;
    }

    /* Atualiza PSEL se este conjunto é SDM */
    int kind = d->sdm_kind[set_idx];
    if (kind == 1 && d->psel < DRRIP_PSEL_MAX) d->psel++;
    else if (kind == 2 && d->psel > 0) d->psel--;

    int policy = decide_policy(d, set_idx);
    uint8_t insert_rrpv = (policy == 1) ? DRRIP_LONG_RRPV
                                        : brrip_insert_rrpv(d, set_idx);

    int victim = find_drrip_victim(c, set_idx);
    cache_line_t *L = &c->lines[set_idx * c->assoc + victim];
    L->valid = 1;
    L->tag = tag;
    L->rrpv = insert_rrpv;
    return 0;
}
