/* ----------------------------------------------------------------------------
 * gen_traces.c — Gerador de traces de endereços para os benchmarks
 *
 * Reproduz fielmente a lógica do benchmarks.c original (mesmas constantes
 * de endereço, mesmo xorshift32 com seed 123). Cada acesso é escrito como
 * uma linha hexadecimal de 8 dígitos no arquivo de saída.
 *
 * Uso:  ./gen_traces <pasta_saida>
 * ---------------------------------------------------------------------------- */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <sys/stat.h>

#define HOT_ADDR     0x30000000ULL
#define ARRAY_BASE   0x10000000ULL
#define MATRIX_BASE  0x20000000ULL
#define LIST_BASE    0x40000000ULL
#define BLOB_BASE    0x50000000ULL
#define WS_BASE      0x10000000ULL
#define SCAN_BASE    0x40000000ULL
#define ELEM_SIZE    4

static FILE *out_fp = NULL;

static inline void emit(uint64_t addr) {
    fprintf(out_fp, "%08x\n", (uint32_t)addr);
}

static uint32_t xs(uint32_t *s) {
    uint32_t x = *s;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    *s = x;
    return x;
}

/* ------------------------------------------------------------------------ */
static void gen_streaming_hotset(size_t array_size_bytes, int iterations) {
    size_t n_elems = array_size_bytes / ELEM_SIZE;
    for (int it = 0; it < iterations; it++) {
        for (size_t i = 0; i < n_elems; i++) {
            uint64_t addr = ARRAY_BASE + i * ELEM_SIZE;
            emit(addr);                   /* read  */
            emit(addr);                   /* write */
            if (i % 64 == 0) {
                emit(HOT_ADDR);
                emit(HOT_ADDR);
            }
        }
    }
}

static void gen_matrix_conv(int width, int height) {
    size_t row_bytes = (size_t)width * ELEM_SIZE;
    for (int y = 1; y < height - 1; y++) {
        for (int x = 0; x < width; x++) {
            uint64_t base = MATRIX_BASE + (size_t)y * row_bytes + (size_t)x * ELEM_SIZE;
            emit(base - row_bytes);
            emit(base);
            emit(base + row_bytes);
            emit(base + row_bytes * (size_t)height);
        }
    }
}

static void gen_linked_list(int n_nodes, int iterations, int randomize) {
    int *order   = malloc(sizeof(int) * (size_t)n_nodes);
    int *next_of = malloc(sizeof(int) * (size_t)n_nodes);
    for (int i = 0; i < n_nodes; i++) order[i] = i;
    if (randomize) {
        uint32_t s = 123;
        for (int i = n_nodes - 1; i > 0; i--) {
            int j = (int)(xs(&s) % (uint32_t)(i + 1));
            int t = order[i]; order[i] = order[j]; order[j] = t;
        }
    }
    for (int i = 0; i < n_nodes; i++)
        next_of[order[i]] = order[(i + 1) % n_nodes];

    int node_size = 16;
    int curr = order[0];
    int total_visits = n_nodes * iterations;
    for (int v = 0; v < total_visits; v++) {
        uint64_t base = LIST_BASE + (uint64_t)curr * node_size;
        emit(base);
        emit(base);
        emit(base + 8);
        curr = next_of[curr];
    }
    free(order);
    free(next_of);
}

static void gen_pattern_search(size_t blob_size, int window) {
    size_t n_elems = blob_size / ELEM_SIZE;
    for (size_t i = (size_t)window; i < n_elems; i++) {
        for (int k = window; k > 0; k--)
            emit(BLOB_BASE + (i - (size_t)k) * ELEM_SIZE);
        emit(BLOB_BASE + i * ELEM_SIZE);
    }
}

static void gen_mixed_access(int ws_blocks, int scan_blocks,
                              int ws_repeats, int outer_iters) {
    int block_size = 32;
    for (int o = 0; o < outer_iters; o++) {
        for (int r = 0; r < ws_repeats; r++)
            for (int i = 0; i < ws_blocks; i++)
                emit(WS_BASE + (uint64_t)i * block_size);
        for (int i = 0; i < scan_blocks; i++)
            emit(SCAN_BASE + (uint64_t)i * block_size);
    }
}

/* ------------------------------------------------------------------------ */
static void run(const char *name, const char *outdir,
                void (*fn)(void), const char *desc) {
    char path[512];
    snprintf(path, sizeof(path), "%s/%s.hex", outdir, name);
    out_fp = fopen(path, "w");
    if (!out_fp) { perror(path); exit(1); }
    long pos_start = 0;
    fn();
    long pos_end = ftell(out_fp);
    fclose(out_fp);
    /* Conta linhas */
    out_fp = fopen(path, "r");
    int lines = 0; char b[64];
    while (fgets(b, sizeof(b), out_fp)) lines++;
    fclose(out_fp);
    printf("  %-20s %8d acessos  (%s)\n", name, lines, desc);
    (void)pos_start; (void)pos_end;
}

/* Funções "zero-arg" que vão para a tabela acima */
static void w_streaming_hotset(void) { gen_streaming_hotset(16*1024, 2); }
static void w_matrix_conv(void)      { gen_matrix_conv(64, 64); }
static void w_linked_list(void)      { gen_linked_list(2048, 2, 1); }
static void w_pattern_search(void)   { gen_pattern_search(16*1024, 32); }
static void w_mixed_access(void)     { gen_mixed_access(64, 128, 8, 8); }

int main(int argc, char **argv) {
    const char *outdir = (argc > 1) ? argv[1] : "traces";
    mkdir(outdir, 0755);

    printf("Gerando traces em '%s/'...\n", outdir);
    run("streaming_hotset", outdir, w_streaming_hotset, "array 16KB, 2 iters");
    run("matrix_conv",      outdir, w_matrix_conv,      "64x64");
    run("linked_list",      outdir, w_linked_list,      "2048 nos, 2 iters, random");
    run("pattern_search",   outdir, w_pattern_search,   "blob 16KB, janela 32");
    run("mixed_access",     outdir, w_mixed_access,     "ws=64 scan=128 r=8 o=8");
    printf("OK\n");
    return 0;
}
