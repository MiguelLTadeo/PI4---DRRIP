/* ============================================================================
 * benchmarks.c - versao bare-metal dos benchmarks do Apendice A.
 *
 * Diferencas do original:
 *   - Sem stdio: substituido por uart_print (a definir em hw_io.c)
 *   - Sem malloc: arrays declarados estaticamente em .bss (linker controla)
 *   - Profiling: lemos CSRs cycle/instret antes/depois para medir IPC e MPKI
 *   - Macros START_PERF/END_PERF leem CSRs do RV32I (Zicntr extension)
 *
 * O linker script deve mapear .bss em uma regiao adequada (~512KB) para
 * acomodar os arrays grandes. Ajustar L2_SIZE_BYTES conforme o teste.
 *
 * Compilacao:
 *   riscv32-unknown-elf-gcc -march=rv32i -mabi=ilp32 -O0 -nostdlib \
 *       -T link.ld benchmarks.c hw_io.c crt0.S -o benchmarks.elf
 *   riscv32-unknown-elf-objcopy -O binary benchmarks.elf benchmarks.bin
 * ============================================================================ */

#include <stdint.h>

/* Use tamanho menor para FPGA pequena (Cyclone III tem RAM limitada). */
#define L2_SIZE_BYTES   (32 * 1024)
#define ARRAY_SIZE_INT  (L2_SIZE_BYTES * 2 / 4)   /* dois L2 em ints */
#define LINKED_NODES    1000
#define BLOB_SIZE       (16 * 1024)

/* ---- prototipos do driver de UART (em hw_io.c) ---- */
void uart_puts(const char *s);
void uart_putint(uint32_t v);
void uart_putdec(uint32_t v);

/* ---- profiling: ler CSRs cycle e instret ---- */
static inline uint32_t read_cycle(void)   {
    uint32_t v;
    asm volatile ("rdcycle %0"   : "=r"(v));
    return v;
}
static inline uint32_t read_instret(void) {
    uint32_t v;
    asm volatile ("rdinstret %0" : "=r"(v));
    return v;
}

/* O processador disponibilizado pelo professor pode ter CSRs custom para
 * cache_hits e cache_misses. Substituir os offsets quando saber. */
#define CSR_CACHE_HITS    0xC03   /* placeholder */
#define CSR_CACHE_MISSES  0xC04   /* placeholder */

static inline uint32_t read_cache_hits(void) {
    uint32_t v;
    asm volatile ("csrr %0, 0xC03" : "=r"(v));
    return v;
}
static inline uint32_t read_cache_misses(void) {
    uint32_t v;
    asm volatile ("csrr %0, 0xC04" : "=r"(v));
    return v;
}

#define START_PERF(name)                                              \
    uart_puts("[INICIO " name "]\n");                                 \
    uint32_t _cyc0 = read_cycle();                                    \
    uint32_t _ins0 = read_instret();                                  \
    uint32_t _h0   = read_cache_hits();                               \
    uint32_t _m0   = read_cache_misses();

#define END_PERF()                                                    \
    {                                                                 \
        uint32_t dc = read_cycle()   - _cyc0;                         \
        uint32_t di = read_instret() - _ins0;                         \
        uint32_t dh = read_cache_hits()   - _h0;                      \
        uint32_t dm = read_cache_misses() - _m0;                      \
        uart_puts("  Ciclos="); uart_putdec(dc);                      \
        uart_puts("  Instr="); uart_putdec(di);                       \
        uart_puts("  Hits="); uart_putdec(dh);                        \
        uart_puts("  Miss="); uart_putdec(dm);                        \
        uart_puts("\n");                                              \
    }

/* Arrays estaticos grandes - alocados em .bss pelo linker */
static int          big_array  [ARRAY_SIZE_INT];
static int          out_array  [ARRAY_SIZE_INT];
static uint8_t      blob       [BLOB_SIZE];
static volatile int hot_data;

/* Lista encadeada estatica */
typedef struct Node {
    int data;
    struct Node *next;
} Node;
static Node nodes[LINKED_NODES];

void init_data(void) {
    /* Linker zera .bss; precisamos so inicializar a lista */
    int i;
    for (i = 0; i < LINKED_NODES - 1; i++)
        nodes[i].next = &nodes[i + 1];
    nodes[LINKED_NODES - 1].next = &nodes[0];
}

/* ============= Benchmark 1: streaming + hotset ============= */
void run_streaming(int outer_iters) {
    START_PERF("streaming");
    for (int it = 0; it < outer_iters; it++) {
        for (int i = 0; i < ARRAY_SIZE_INT; i++) {
            big_array[i] += i;
            if ((i & 63) == 0) hot_data += big_array[i];
        }
    }
    END_PERF();
}

/* ============= Benchmark 2: matriz convolucao ============= */
void run_matrix_conv(int width, int height) {
    START_PERF("matrix_conv");
    for (int y = 1; y < height - 1; y++) {
        for (int x = 1; x < width - 1; x++) {
            out_array[y*width + x] =
                big_array[(y-1)*width + x] +
                big_array[ y   *width + x] +
                big_array[(y+1)*width + x];
        }
    }
    END_PERF();
}

/* ============= Benchmark 3: linked list ============= */
void run_linked_list(int iters) {
    START_PERF("linked_list");
    Node *curr = &nodes[0];
    for (int i = 0; i < iters; i++) {
        curr->data += i;
        curr = curr->next;
    }
    END_PERF();
}

/* ============= Benchmark 4: pattern search ============= */
void run_pattern_search(int size) {
    START_PERF("pattern_search");
    for (int i = 1024; i < size; i++) {
        for (int j = 1; j < 64; j++) {
            if (blob[i] == blob[i-j]) { blob[i]++; break; }
        }
    }
    END_PERF();
}

/* ============= main ============= */
int main(void) {
    init_data();
    uart_puts("=== Cache Benchmark Suite (DRRIP vs LRU) ===\n");

    run_streaming(2);
    run_matrix_conv(128, 128);
    run_linked_list(LINKED_NODES * 5);
    run_pattern_search(BLOB_SIZE);

    uart_puts("=== fim ===\n");

    /* loop infinito para nao retornar do main em bare-metal */
    while (1) { asm volatile ("wfi"); }
    return 0;
}
