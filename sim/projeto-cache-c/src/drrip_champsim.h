/*
 * drrip_champsim.h / drrip_champsim.c
 *
 * Porte literal do `drrip.cc` do ChampSim (C++) para C.
 *
 * Preserva exatamente:
 *   - Contador BIP GLOBAL (não per-set)
 *   - PSEL inicia em 0
 *   - Seleção de SDM via knuth_b SEM aplicar módulo NUM_SET
 *   - find_victim com std::max_element + aging delta
 *
 * Por preservar esses detalhes, em caches pequenas o algoritmo degenera
 * (knuth_b produz índices fora do range válido, nenhum SDM é "encontrado",
 * PSEL nunca atualiza, e o DRRIP se comporta como SRRIP puro).
 *
 * Mantemos assim PROPOSITALMENTE para reproduzir o comportamento exato
 * que o ChampSim teria em C++. Isso é evidência do nosso trabalho.
 */
#ifndef DRRIP_CHAMPSIM_H
#define DRRIP_CHAMPSIM_H

#include "cache.h"
#include <stdint.h>
#include <stddef.h>

#define CSIM_MAX_RRPV    3
#define CSIM_SDM_SIZE    32
#define CSIM_NUM_POLICY  2
#define CSIM_BIP_MAX     32
#define CSIM_PSEL_WIDTH  10
#define CSIM_PSEL_MAX    1023
#define CSIM_NUM_CPUS    1

typedef struct {
    cache_t *c;

    /* rand_sets: TOTAL_SDM_SETS = NUM_CPUS * NUM_POLICY * SDM_SIZE = 64.
     * Mantém valores BRUTOS do gerador knuth_b (size_t), ordenados. */
    size_t  rand_sets[CSIM_NUM_CPUS * CSIM_NUM_POLICY * CSIM_SDM_SIZE];

    int     psel;            /* inicia em 0, como o ChampSim */
    unsigned bip_counter;    /* contador GLOBAL */
} drrip_champsim_t;

void drrip_champsim_init(drrip_champsim_t *d, cache_t *c);
void drrip_champsim_free(drrip_champsim_t *d);
int  drrip_champsim_access(drrip_champsim_t *d, uint64_t addr);

#endif
