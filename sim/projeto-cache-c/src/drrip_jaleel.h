/*
 * drrip_jaleel.h / drrip_jaleel.c
 *
 * DRRIP fiel ao paper Jaleel et al. (ISCA 2010), com adaptações necessárias
 * para caches pequenas de FPGA:
 *   - PSEL inicia em 0 (convenção DIP: SRRIP vence no início, conforme Jaleel 2010)
 *   - SDMs selecionados via shuffle DETERMINÍSTICO dentro do range [0, num_sets)
 *   - Contador BIP per-set (evita correlação entre SDM_BRRIP e followers)
 */
#ifndef DRRIP_JALEEL_H
#define DRRIP_JALEEL_H

#include "cache.h"
#include <stdint.h>

#define DRRIP_M           2
#define DRRIP_MAX_RRPV    3
#define DRRIP_LONG_RRPV   2
#define DRRIP_PSEL_WIDTH  10
#define DRRIP_PSEL_MAX    1023
#define DRRIP_PSEL_INIT   0      /* convenção DIP: SRRIP vence inicialmente */
#define DRRIP_SDM_SIZE    32
#define DRRIP_BIP_DENOM   32

typedef struct {
    cache_t *c;

    /* Set Dueling — sets dedicados a SRRIP e BRRIP (índices no range válido) */
    int   srrip_sdm[DRRIP_SDM_SIZE];
    int   brrip_sdm[DRRIP_SDM_SIZE];
    int   n_sdm;             /* sdm count efetivo (≤ DRRIP_SDM_SIZE) */
    int   sdm_kind[1 << 14]; /* lookup table: 0=follower, 1=srrip, 2=brrip; tamanho = num_sets max */

    int   psel;
    uint8_t *bip_counter_per_set;  /* contador BIP por conjunto */
} drrip_jaleel_t;

void drrip_jaleel_init(drrip_jaleel_t *d, cache_t *c, uint32_t seed);
void drrip_jaleel_free(drrip_jaleel_t *d);
int  drrip_jaleel_access(drrip_jaleel_t *d, uint64_t addr);

#endif
