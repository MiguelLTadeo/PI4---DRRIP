#include "lru.h"

static int find_lru_victim(cache_t *c, int set_idx) {
    cache_line_t *base = &c->lines[set_idx * c->assoc];
    int victim = 0;
    uint16_t max_age = 0;
    for (int w = 0; w < c->assoc; w++) {
        if (base[w].lru_age > max_age) {
            max_age = base[w].lru_age;
            victim = w;
        }
    }
    return victim;
}

/* Em hit: só envelhecem linhas mais novas que a do hit (preserva invariante) */
static void on_hit(cache_t *c, int set_idx, int hit_way) {
    cache_line_t *base = &c->lines[set_idx * c->assoc];
    uint16_t prev_age = base[hit_way].lru_age;
    for (int w = 0; w < c->assoc; w++) {
        if (w == hit_way) continue;
        if (base[w].valid && base[w].lru_age < prev_age) {
            base[w].lru_age++;
        }
    }
    base[hit_way].lru_age = 0;
}

/* Em miss: nova entra como 0; todas as válidas envelhecem em 1 */
static void insert_as_mru(cache_t *c, int set_idx, int new_way, uint64_t tag) {
    cache_line_t *base = &c->lines[set_idx * c->assoc];
    for (int w = 0; w < c->assoc; w++) {
        if (w == new_way) continue;
        if (base[w].valid && base[w].lru_age < c->assoc - 1) {
            base[w].lru_age++;
        }
    }
    base[new_way].valid = 1;
    base[new_way].tag = tag;
    base[new_way].lru_age = 0;
}

int lru_access(cache_t *c, uint64_t addr) {
    int set_idx = cache_set_of(c, addr);
    uint64_t tag = cache_tag_of(c, addr);
    int way = cache_find_way(c, set_idx, tag);

    if (way >= 0) {
        c->hits++;
        on_hit(c, set_idx, way);
        return 1;
    }

    c->misses++;
    if (cache_mark_touched(c, cache_block_of(c, addr))) {
        c->cold_misses++;
    }

    int victim = cache_find_invalid_way(c, set_idx);
    if (victim < 0) victim = find_lru_victim(c, set_idx);

    insert_as_mru(c, set_idx, victim, tag);
    return 0;
}
