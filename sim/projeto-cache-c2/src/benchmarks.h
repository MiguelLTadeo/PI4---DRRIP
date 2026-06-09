/*
 * benchmarks.h / benchmarks.c — geradores de trace de endereços.
 *
 * Reproduzem os 4 padrões do Apêndice A da spec + 1 complementar (mixed_access)
 * baseado na Fig. 1d do paper Jaleel et al.
 */
#ifndef BENCHMARKS_H
#define BENCHMARKS_H

#include <stdint.h>
#include <stddef.h>
#include <sys/types.h>

/* Cada gerador escreve endereços no buffer; retorna quantos foram escritos.
 * O caller passa buf de tamanho cap. Se cap não couber, retorna -1. */

ssize_t gen_streaming_hotset(uint64_t *buf, size_t cap,
                              size_t array_size_bytes, int iterations);
ssize_t gen_matrix_conv(uint64_t *buf, size_t cap,
                         int width, int height);
ssize_t gen_linked_list(uint64_t *buf, size_t cap,
                         int n_nodes, int iterations, int randomize);
ssize_t gen_pattern_search(uint64_t *buf, size_t cap,
                            size_t blob_size, int window);
ssize_t gen_mixed_access(uint64_t *buf, size_t cap,
                          int ws_blocks, int scan_blocks,
                          int ws_repeats, int outer_iters);
ssize_t gen_validation(uint64_t *buf, size_t cap);

#endif
