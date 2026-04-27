class CacheLine:
    def __init__(self):
        self.valid = False
        self.dirty = False
        self.tag   = None
        # campos dos dois algoritmos coexistem, mas só um é usado por vez
        self.rrpv  = 3              # usado pelo DRRIP
        self.lru_rank = 0           # usado pelo LRU

class CacheSet:
    def __init__(self, num_ways):
        self.ways = [CacheLine() for _ in range(num_ways)]
        # sem lru_order aqui — o rank fica dentro de cada CacheLine

class Cache:
    def __init__(self, capacity, block_size, associativity, policy):
        self.num_ways   = associativity
        self.num_sets   = capacity // (block_size * associativity)
        self.block_size = block_size
        self.sets       = [CacheSet(associativity) for _ in range(self.num_sets)]
        self.policy     = policy    # 'LRU' ou 'DRRIP'
        self.hits       = 0
        self.misses     = 0
        # DRRIP
        self.psel       = 0         # contador do Set Dueling
        self.num_leader_sets = 32   # sets líderes por política
