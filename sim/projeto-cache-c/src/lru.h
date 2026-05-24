/*
 * lru.h / lru.c — LRU verdadeiro
 *
 * Cada linha guarda idade 0..assoc-1 distinta.
 * Em hit:  promovida -> 0; linhas mais novas envelhecem em 1
 * Em miss: nova -> 0; todas as válidas envelhecem em 1; vítima = idade assoc-1
 */
#ifndef LRU_H
#define LRU_H
#include "cache.h"
int lru_access(cache_t *c, uint64_t addr);  /* retorna 1 se hit, 0 se miss */
#endif
