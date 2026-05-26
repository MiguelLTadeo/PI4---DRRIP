/*
 * main.c — driver experimental.
 *
 * Para cada (config_cache, benchmark, política), executa a hierarquia L1+L2
 * e produz:
 *   - results/hit_rates.csv  : hit/miss/AMAT por configuração
 *   - results/overhead.csv   : bits de SRAM por política
 *
 * Configurações:
 *   A: L1D 4 KB / 32 B / 2 vias,  L2 32 KB  / 64 B / 8 vias
 *   B: L1D 4 KB / 32 B / 4 vias,  L2 64 KB  / 64 B / 8 vias
 *   C: L1D 8 KB / 32 B / 4 vias,  L2 128 KB / 64 B / 16 vias
 *
 * Latências: L1=1, L2=10, MEM=100 ciclos
 *   AMAT = 1 + (1-h_L1)*(10 + (1-h_L2)*100)
 */

#include "cache.h"
#include "lru.h"
#include "drrip_jaleel.h"
#include "drrip_champsim.h"
#include "benchmarks.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

typedef struct {
    const char *name;
    int l1_size, l1_block, l1_assoc;
    int l2_size, l2_block, l2_assoc;
} cache_config_t;

static const cache_config_t CONFIGS[] = {
    {"A",  4*1024, 32, 2,  32*1024, 64, 8},
    {"B",  4*1024, 32, 4,  64*1024, 64, 8},
    {"C",  8*1024, 32, 4, 128*1024, 64, 16},
};
#define N_CONFIGS (sizeof(CONFIGS)/sizeof(CONFIGS[0]))

typedef enum { POL_LRU = 0, POL_DRRIP_JALEEL = 1, POL_DRRIP_CHAMPSIM = 2 } policy_kind_t;
static const char *POLICY_NAMES[] = {"LRU", "DRRIP_jaleel", "DRRIP_champsim"};

/* Tamanho-teto p/ buffer de trace — pegamos um valor grande o suficiente */
#define TRACE_CAP (8 * 1024 * 1024)
static uint64_t trace_buf[TRACE_CAP];

/* Gera trace de um benchmark; retorna número de acessos */
static ssize_t generate_trace(const char *bench, const cache_config_t *cfg) {
    size_t l2_bytes = (size_t)cfg->l2_size;
    if (!strcmp(bench, "streaming_hotset"))
        return gen_streaming_hotset(trace_buf, TRACE_CAP,
                                     2 * l2_bytes, 3);
    if (!strcmp(bench, "matrix_conv"))
        return gen_matrix_conv(trace_buf, TRACE_CAP, 128, 128);
    if (!strcmp(bench, "linked_list"))
        /* Fiel ao Python: 8000 nós, 5 iterações, ordem aleatória */
        return gen_linked_list(trace_buf, TRACE_CAP, 8000, 5, 1);
    if (!strcmp(bench, "pattern_search"))
        return gen_pattern_search(trace_buf, TRACE_CAP, l2_bytes, 32);
    if (!strcmp(bench, "mixed_access"))
        return gen_mixed_access(trace_buf, TRACE_CAP, 64, 384, 16, 10);
    return -1;
}

/* Roda uma política numa hierarquia L1+L2 e retorna métricas */
typedef struct {
    uint64_t l1_hits, l1_misses;
    uint64_t l2_hits, l2_misses;
    double   amat;
} run_result_t;

static run_result_t run_simulation(const cache_config_t *cfg,
                                     policy_kind_t pol,
                                     const uint64_t *trace,
                                     ssize_t n_accesses) {
    cache_t l1, l2;
    cache_init(&l1, cfg->l1_size, cfg->l1_block, cfg->l1_assoc);
    cache_init(&l2, cfg->l2_size, cfg->l2_block, cfg->l2_assoc);

    /* Alocação dinâmica das estruturas de política (uma para cada nível) */
    drrip_jaleel_t  l1_jal,  l2_jal;
    drrip_champsim_t l1_csim, l2_csim;

    if (pol == POL_DRRIP_JALEEL) {
        drrip_jaleel_init(&l1_jal, &l1, 0xC0FFEEu);
        drrip_jaleel_init(&l2_jal, &l2, 0xC0FFEEu);
    } else if (pol == POL_DRRIP_CHAMPSIM) {
        drrip_champsim_init(&l1_csim, &l1);
        drrip_champsim_init(&l2_csim, &l2);
    }

    for (ssize_t i = 0; i < n_accesses; i++) {
        uint64_t addr = trace[i];
        int hit;
        if (pol == POL_LRU)                hit = lru_access(&l1, addr);
        else if (pol == POL_DRRIP_JALEEL)  hit = drrip_jaleel_access(&l1_jal, addr);
        else                                hit = drrip_champsim_access(&l1_csim, addr);

        if (!hit) {
            if (pol == POL_LRU)               lru_access(&l2, addr);
            else if (pol == POL_DRRIP_JALEEL) drrip_jaleel_access(&l2_jal, addr);
            else                              drrip_champsim_access(&l2_csim, addr);
        }
    }

    run_result_t r;
    r.l1_hits = l1.hits; r.l1_misses = l1.misses;
    r.l2_hits = l2.hits; r.l2_misses = l2.misses;
    double h1 = (double)l1.hits / (double)(l1.hits + l1.misses);
    double h2 = (l2.hits + l2.misses > 0)
                  ? (double)l2.hits / (double)(l2.hits + l2.misses)
                  : 0.0;
    r.amat = 1.0 + (1.0 - h1) * (10.0 + (1.0 - h2) * 100.0);

    if (pol == POL_DRRIP_JALEEL)  { drrip_jaleel_free(&l1_jal); drrip_jaleel_free(&l2_jal); }
    if (pol == POL_DRRIP_CHAMPSIM){ drrip_champsim_free(&l1_csim); drrip_champsim_free(&l2_csim); }
    cache_free(&l1); cache_free(&l2);
    return r;
}

/* Calcula bits de metadados por política */
static int policy_bits_per_set(policy_kind_t pol, int assoc) {
    if (pol == POL_LRU) {
        /* n * ceil(log2(n)) */
        int k = 0; while ((1<<k) < assoc) k++;
        return assoc * k;
    }
    /* DRRIP: M=2 por linha */
    return assoc * 2;
}

static int total_storage_bits(const cache_t *c, policy_kind_t pol) {
    int tag_bits = 32 - c->offset_bits - c->index_bits;
    int per_line_data = 1 + tag_bits;  /* valid + tag */
    int policy_bits = policy_bits_per_set(pol, c->assoc);
    return c->num_sets * (c->assoc * per_line_data + policy_bits);
}

int main(void) {
    const char *benches[] = {
        "streaming_hotset", "matrix_conv", "linked_list",
        "pattern_search",   "mixed_access"
    };
    int n_benches = sizeof(benches) / sizeof(benches[0]);

    FILE *fout = fopen("results/hit_rates.csv", "w");
    if (!fout) { perror("results/hit_rates.csv"); return 1; }
    fprintf(fout, "config,benchmark,policy,n_accesses,l1_hits,l1_misses,"
                   "l1_hit_rate,l2_hits,l2_misses,l2_hit_rate,amat_cycles\n");

    printf("=== Simulação cache: LRU vs DRRIP-Jaleel vs DRRIP-ChampSim ===\n\n");
    for (size_t ic = 0; ic < N_CONFIGS; ic++) {
        const cache_config_t *cfg = &CONFIGS[ic];
        printf("Config %s: L1D %dKB/%dv, L2 %dKB/%dv\n",
               cfg->name, cfg->l1_size/1024, cfg->l1_assoc,
               cfg->l2_size/1024, cfg->l2_assoc);
        for (int ib = 0; ib < n_benches; ib++) {
            ssize_t n = generate_trace(benches[ib], cfg);
            if (n < 0) {
                fprintf(stderr, "  ERRO: trace %s muito grande (cap=%d)\n",
                        benches[ib], TRACE_CAP);
                continue;
            }
            printf("  %-18s (%zd acc.) | ", benches[ib], n);
            for (int p = 0; p < 3; p++) {
                run_result_t r = run_simulation(cfg, (policy_kind_t)p, trace_buf, n);
                double h1 = (double)r.l1_hits / (double)(r.l1_hits + r.l1_misses);
                double h2 = (r.l2_hits + r.l2_misses > 0)
                              ? (double)r.l2_hits / (double)(r.l2_hits + r.l2_misses)
                              : 0.0;
                printf("%s=%.2f%%  ", POLICY_NAMES[p], h1*100);
                fprintf(fout, "%s,%s,%s,%zd,%llu,%llu,%.6f,%llu,%llu,%.6f,%.4f\n",
                         cfg->name, benches[ib], POLICY_NAMES[p], n,
                         (unsigned long long)r.l1_hits,
                         (unsigned long long)r.l1_misses, h1,
                         (unsigned long long)r.l2_hits,
                         (unsigned long long)r.l2_misses, h2, r.amat);
            }
            printf("\n");
        }
        printf("\n");
    }
    fclose(fout);

    /* Overhead — duas linhas por cache (L1D e L2) por config */
    FILE *fov = fopen("results/overhead.csv", "w");
    if (!fov) { perror("results/overhead.csv"); return 1; }
    fprintf(fov, "cache,size_KB,block_B,assoc,policy,total_bits,policy_bits_per_set\n");

    for (size_t ic = 0; ic < N_CONFIGS; ic++) {
        const cache_config_t *cfg = &CONFIGS[ic];
        cache_t l1, l2;
        cache_init(&l1, cfg->l1_size, cfg->l1_block, cfg->l1_assoc);
        cache_init(&l2, cfg->l2_size, cfg->l2_block, cfg->l2_assoc);
        const char *labels[2] = {"L1D", "L2"};
        cache_t *caches[2] = {&l1, &l2};
        for (int k = 0; k < 2; k++) {
            cache_t *cc = caches[k];
            for (int p = 0; p < 3; p++) {
                fprintf(fov, "%s-%s,%d,%d,%d,%s,%d,%d\n",
                         labels[k], cfg->name,
                         (k == 0 ? cfg->l1_size : cfg->l2_size)/1024,
                         (k == 0 ? cfg->l1_block : cfg->l2_block),
                         (k == 0 ? cfg->l1_assoc : cfg->l2_assoc),
                         POLICY_NAMES[p],
                         total_storage_bits(cc, (policy_kind_t)p),
                         policy_bits_per_set((policy_kind_t)p,
                                              k == 0 ? cfg->l1_assoc : cfg->l2_assoc));
            }
        }
        cache_free(&l1); cache_free(&l2);
    }
    fclose(fov);

    printf("CSVs gerados em results/\n");
    return 0;
}
