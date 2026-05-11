"""
run_experiments.py
==================
Executa benchmarks com varias configuracoes de cache, comparando LRU
contra DRRIP. Gera tabelas no formato exigido pelo Apendice B.

Uso:
    python3 run_experiments.py           # roda tudo, formato compacto
    python3 run_experiments.py --csv     # exporta CSV em resultados.csv
"""

import argparse
import csv
import sys
from typing import List, Dict, Tuple

from cache_model import MemoryHierarchy
from traces import BENCHMARKS


# Configuracoes a testar.
# IMPORTANTE: DRRIP so' supera LRU quando o working set EXCEDE a cache.
# Por isso incluimos configs pequenas (stress) e tambem as do range da
# especificacao (que mostram caso onde ambos sao equivalentes).
# (l1d_size, l1d_assoc, l2_size, l2_assoc)
CONFIGS = [
    # nome,           L1_size,  L1_assoc, L2_size,    L2_assoc
    # --- Caches pequenas (stress test - DRRIP deveria ganhar) ---
    ('stress_tiny',    1024,     2,        4 * 1024,    4),
    ('stress_small',   2048,     2,        8 * 1024,    4),
    # --- Configs do range da especificacao ---
    ('A_min',          4 * 1024, 2,        32 * 1024,   8),
    ('B_l1_4way',      4 * 1024, 4,        32 * 1024,   8),
    ('C_l2_16way',     4 * 1024, 4,        32 * 1024,  16),
    ('D_l2_64k',       4 * 1024, 4,        64 * 1024,  16),
    ('E_max',          8 * 1024, 4,        128 * 1024, 16),
]

L1_BLOCK = 32   # especificacao
L2_BLOCK = 64   # especificacao


def run_one(policy: str, cfg: Tuple, bench_name: str) -> Dict[str, float]:
    """Roda 1 benchmark com 1 config e 1 politica. Retorna metricas."""
    _, l1s, l1a, l2s, l2a = cfg
    hier = MemoryHierarchy(
        l1d_size=l1s, l1d_assoc=l1a, l1_block=L1_BLOCK,
        l2_size=l2s, l2_assoc=l2a, l2_block=L2_BLOCK,
        policy=policy,
    )
    gen = BENCHMARKS[bench_name]()
    for addr, kind in gen:
        hier.access(addr, kind)
    return hier.report()


def format_pct(x: float) -> str:
    return f"{100 * x:6.2f}%"


def print_table(rows: List[Dict], cols: List[str]) -> None:
    """Imprime tabela ASCII simples."""
    widths = {c: max(len(c), max((len(str(r[c])) for r in rows), default=0))
              for c in cols}
    line = ' | '.join(c.ljust(widths[c]) for c in cols)
    print(line)
    print('-+-'.join('-' * widths[c] for c in cols))
    for r in rows:
        print(' | '.join(str(r[c]).ljust(widths[c]) for c in cols))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', action='store_true',
                    help='exporta CSV detalhado em resultados.csv')
    ap.add_argument('--quick', action='store_true',
                    help='roda so 1 benchmark e 1 config (smoke test rapido)')
    args = ap.parse_args()

    configs = CONFIGS[:1] if args.quick else CONFIGS
    benches = ['streaming'] if args.quick else list(BENCHMARKS.keys())

    rows = []
    print('Rodando experimentos...')
    print()

    for cfg in configs:
        cname = cfg[0]
        for bench in benches:
            print(f'  [{cname}] {bench:<16}', end='', flush=True)
            r_lru   = run_one('LRU',   cfg, bench)
            r_drrip = run_one('DRRIP', cfg, bench)
            ohr_lru   = r_lru['overall_hit_rate']
            ohr_drrip = r_drrip['overall_hit_rate']
            delta = (ohr_drrip - ohr_lru) * 100
            print(f'  LRU={format_pct(ohr_lru)}  '
                  f'DRRIP={format_pct(ohr_drrip)}  '
                  f'delta={delta:+.2f}pp')

            rows.append({
                'config':          cname,
                'benchmark':       bench,
                'L1_KB':           cfg[1] // 1024,
                'L1_assoc':        cfg[2],
                'L2_KB':           cfg[3] // 1024,
                'L2_assoc':        cfg[4],
                'LRU_L1I_HR':      f'{r_lru["L1I_hit_rate"]*100:.2f}',
                'LRU_L1D_HR':      f'{r_lru["L1D_hit_rate"]*100:.2f}',
                'LRU_L2_HR':       f'{r_lru["L2_hit_rate"]*100:.2f}',
                'LRU_overall':     f'{ohr_lru*100:.2f}',
                'DRRIP_L1I_HR':    f'{r_drrip["L1I_hit_rate"]*100:.2f}',
                'DRRIP_L1D_HR':    f'{r_drrip["L1D_hit_rate"]*100:.2f}',
                'DRRIP_L2_HR':     f'{r_drrip["L2_hit_rate"]*100:.2f}',
                'DRRIP_overall':   f'{ohr_drrip*100:.2f}',
                'delta_pp':        f'{delta:+.2f}',
            })

    print()
    print('='*72)
    print('RESUMO POR BENCHMARK (Hit Rate global, todas as caches juntas)')
    print('='*72)
    cols = ['config', 'benchmark', 'L1_KB', 'L2_KB', 'L2_assoc',
            'LRU_overall', 'DRRIP_overall', 'delta_pp']
    print_table(rows, cols)

    if args.csv:
        with open('resultados.csv', 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f'\nCSV gravado em resultados.csv ({len(rows)} linhas)')


if __name__ == '__main__':
    main()
