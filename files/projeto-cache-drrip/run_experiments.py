"""
run_experiments.py
-----------------

Executa todos os benchmarks da especificação (Apêndice A) sob as
configurações de cache previstas, comparando LRU (baseline) contra
DRRIP (algoritmo proposto), e grava os resultados em CSV.

Saída:
    results/hit_rates.csv         tabela longa com todos os pontos
    results/summary_by_bench.csv  resumo por benchmark (média entre configs)
    results/overhead.csv          comparação de overhead de metadados
"""

from __future__ import annotations

import csv
import itertools
import os
import time
from typing import Callable

from model.lru import LRUCache
from model.drrip import DRRIPCache
from model.memory_hierarchy import MemoryHierarchy
from model.benchmarks import (
    streaming_hotset,
    matrix_convolution,
    linked_list,
    pattern_search,
    mixed_access_pattern,
)


# ============================================================================
# CONFIGURAÇÕES DE CACHE (varridas - conforme especificação Seção 4)
# ============================================================================

# L1 (Dados): 4-8KB, bloco 32B, 2 ou 4 vias
# L2 (Unif.):  32-128KB, bloco 64B, 8 ou 16 vias
CACHE_CONFIGS = [
    # (nome_curto,  l1_size, l1_assoc, l2_size, l2_assoc)
    ("A",  4 * 1024, 2,  32 * 1024, 8),     # config compacta (pior caso área)
    ("B",  4 * 1024, 4,  64 * 1024, 8),
    ("C",  8 * 1024, 4, 128 * 1024, 16),    # config robusta
]

BLOCK_SIZE_L1 = 32
BLOCK_SIZE_L2 = 64

POLICIES = ("LRU", "DRRIP")


# ============================================================================
# CONFIGURAÇÕES DE BENCHMARKS
# ============================================================================

# Escala adaptada ao tamanho do L2. Para que o working set realmente
# pressione a L2 (~2x), normalizamos pelo maior L2 testado (128KB).
def benchmark_factories(l2_size_bytes: int):
    """Constrói os geradores parametrizados pelo tamanho da L2."""
    # Working set escolhido para caber confortavelmente em L1 4KB (= 128 blocos),
    # mas que será expulso por LRU quando o scan invadir a cache.
    return {
        "streaming_hotset": lambda: streaming_hotset(
            array_size_bytes=2 * l2_size_bytes,
            iterations=3,
        ),
        "matrix_conv": lambda: matrix_convolution(
            width=128,
            height=128,
        ),
        "linked_list": lambda: linked_list(
            n_nodes=l2_size_bytes // 8,   # ~working set = 2x L2
            iterations=3,
            randomize_order=True,
        ),
        "pattern_search": lambda: pattern_search(
            size=l2_size_bytes,           # blob com mesmo tamanho da L2
            window=32,
        ),
        # Complementar: padrão Fig.1d (working set + scan) onde DRRIP brilha.
        # Calibração que pressiona TODAS as 3 configs:
        #   - WS = 64 blocos (cabe na capacidade total das 3 L1)
        #   - Scan = 384 blocos (excede a capacidade da L1 nas 3 configs)
        # Para a Eq.(1) do artigo (Slen <= (2^M-1)*(A-w), M=2):
        #   * Config A (64 sets, 2-vias): Slen=6, limite=3   → SRRIP perde, BRRIP segura
        #   * Config B (32 sets, 4-vias): Slen=12, limite=9  → SRRIP perde, BRRIP segura
        #   * Config C (64 sets, 4-vias): Slen=6, limite=9   → SRRIP segura
        # Em qualquer cenário, o DRRIP (set-dueling SRRIP×BRRIP) escolhe o
        # vencedor automaticamente, enquanto o LRU é arruinado pelo scan.
        "mixed_access": lambda: mixed_access_pattern(
            ws_blocks=64,
            scan_blocks=384,
            ws_repeats=16,
            outer_iters=10,
        ),
    }


# ============================================================================
# CONSTRUTORES DE HIERARQUIA
# ============================================================================

def make_hierarchy(policy: str, l1_size, l1_assoc, l2_size, l2_assoc) -> MemoryHierarchy:
    if policy == "LRU":
        l1 = LRUCache("L1D", l1_size, BLOCK_SIZE_L1, l1_assoc)
        l2 = LRUCache("L2",  l2_size, BLOCK_SIZE_L2, l2_assoc)
    elif policy == "DRRIP":
        l1 = DRRIPCache("L1D", l1_size, BLOCK_SIZE_L1, l1_assoc, policy="DRRIP")
        l2 = DRRIPCache("L2",  l2_size, BLOCK_SIZE_L2, l2_assoc, policy="DRRIP")
    else:
        raise ValueError(policy)
    return MemoryHierarchy(l1, l2)


# ============================================================================
# RUNNER
# ============================================================================

def run_one(policy: str, cfg_name: str, l1_size, l1_assoc, l2_size, l2_assoc,
            bench_name: str, bench_factory: Callable) -> dict:
    hier = make_hierarchy(policy, l1_size, l1_assoc, l2_size, l2_assoc)
    t0 = time.perf_counter()
    n_accesses = 0
    for addr in bench_factory():
        hier.access(addr)
        n_accesses += 1
    elapsed = time.perf_counter() - t0
    summary = hier.summary()
    summary.update({
        "policy": policy,
        "config": cfg_name,
        "l1_size": l1_size,
        "l1_assoc": l1_assoc,
        "l2_size": l2_size,
        "l2_assoc": l2_assoc,
        "benchmark": bench_name,
        "n_accesses": n_accesses,
        "wall_time_s": elapsed,
    })
    return summary


def main(out_dir: str = "results") -> None:
    os.makedirs(out_dir, exist_ok=True)
    rows = []

    print("=" * 78)
    print("MODELAGEM SEMANAS 1-4 — VALIDAÇÃO DE HIT RATE (LRU vs DRRIP)")
    print("=" * 78)

    for cfg_name, l1s, l1a, l2s, l2a in CACHE_CONFIGS:
        print(f"\n>>> Config {cfg_name}: "
              f"L1D {l1s//1024}KB/{l1a}-vias, L2 {l2s//1024}KB/{l2a}-vias")
        bfs = benchmark_factories(l2s)
        for bench_name, bench_factory in bfs.items():
            for policy in POLICIES:
                r = run_one(policy, cfg_name, l1s, l1a, l2s, l2a,
                            bench_name, bench_factory)
                rows.append(r)
                print(f"  {policy:5s}  {bench_name:18s}  "
                      f"L1D hit={r['l1d_hit_rate']*100:6.2f}%   "
                      f"L2 hit={r['l2_hit_rate']*100:6.2f}%   "
                      f"AMAT={r['amat_cycles']:5.2f} cy   "
                      f"({r['n_accesses']:>9} acessos, "
                      f"{r['wall_time_s']:.1f}s)")

    # --------------------------- grava CSV detalhado -------------------------
    detailed_path = os.path.join(out_dir, "hit_rates.csv")
    fieldnames = list(rows[0].keys())
    with open(detailed_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"\nCSV detalhado: {detailed_path}")

    # --------------------------- resumo: ganho por bench/config --------------
    summary_path = os.path.join(out_dir, "summary.csv")
    with open(summary_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "config", "benchmark",
            "l1_hit_LRU_%", "l1_hit_DRRIP_%", "l1_delta_pp",
            "l2_hit_LRU_%", "l2_hit_DRRIP_%", "l2_delta_pp",
            "amat_LRU_cy", "amat_DRRIP_cy", "amat_speedup_%",
        ])
        # indexa por (config, benchmark, policy)
        idx = {(r["config"], r["benchmark"], r["policy"]): r for r in rows}
        for cfg_name, *_ in CACHE_CONFIGS:
            for bench in ("streaming_hotset", "matrix_conv",
                          "linked_list", "pattern_search", "mixed_access"):
                lru = idx[(cfg_name, bench, "LRU")]
                drrip = idx[(cfg_name, bench, "DRRIP")]
                l1_lru = lru["l1d_hit_rate"] * 100
                l1_dr = drrip["l1d_hit_rate"] * 100
                l2_lru = lru["l2_hit_rate"] * 100
                l2_dr = drrip["l2_hit_rate"] * 100
                amat_lru = lru["amat_cycles"]
                amat_dr = drrip["amat_cycles"]
                speedup = (amat_lru - amat_dr) / amat_lru * 100 if amat_lru else 0
                w.writerow([
                    cfg_name, bench,
                    f"{l1_lru:.2f}", f"{l1_dr:.2f}", f"{l1_dr - l1_lru:+.2f}",
                    f"{l2_lru:.2f}", f"{l2_dr:.2f}", f"{l2_dr - l2_lru:+.2f}",
                    f"{amat_lru:.3f}", f"{amat_dr:.3f}", f"{speedup:+.2f}",
                ])
    print(f"CSV de resumo: {summary_path}")

    # --------------------------- overhead em bits ----------------------------
    overhead_path = os.path.join(out_dir, "overhead.csv")
    with open(overhead_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cache", "size_KB", "block_B", "assoc",
                    "LRU_total_bits", "DRRIP_total_bits",
                    "LRU_policy_bits_per_set", "DRRIP_policy_bits_per_set",
                    "savings_%"])
        for cfg_name, l1s, l1a, l2s, l2a in CACHE_CONFIGS:
            for label, size, blk, assoc in (
                (f"L1D-{cfg_name}", l1s, BLOCK_SIZE_L1, l1a),
                (f"L2-{cfg_name}",  l2s, BLOCK_SIZE_L2, l2a),
            ):
                lru_c = LRUCache(label, size, blk, assoc)
                dr_c = DRRIPCache(label, size, blk, assoc, policy="DRRIP")
                tag_bits = 32 - lru_c.offset_bits - lru_c.index_bits
                common = lru_c.num_sets * assoc * (1 + tag_bits)
                lru_total = lru_c.storage_overhead_bits()
                dr_total = dr_c.storage_overhead_bits()
                lru_pol = (lru_total - common) // lru_c.num_sets
                dr_pol = (dr_total - common - dr_c.PSEL_BITS) // dr_c.num_sets
                savings = (lru_total - dr_total) / lru_total * 100
                w.writerow([label, size // 1024, blk, assoc,
                            lru_total, dr_total, lru_pol, dr_pol,
                            f"{savings:+.2f}"])
    print(f"CSV de overhead: {overhead_path}")

    # ---------------------- impressão final no terminal ----------------------
    print("\n" + "=" * 78)
    print("RESUMO — Ganhos do DRRIP sobre LRU (médias entre configurações)")
    print("=" * 78)
    benches = ["streaming_hotset", "matrix_conv", "linked_list",
               "pattern_search", "mixed_access"]
    print(f"\n{'Benchmark':<20s} {'ΔL1 hit (pp)':>14s} {'ΔL2 hit (pp)':>14s} "
          f"{'AMAT speedup (%)':>18s}")
    print("-" * 70)
    for bench in benches:
        l1_d = []
        l2_d = []
        sp = []
        for cfg_name, *_ in CACHE_CONFIGS:
            lru = next(r for r in rows
                       if r["config"] == cfg_name
                       and r["benchmark"] == bench
                       and r["policy"] == "LRU")
            drrip = next(r for r in rows
                         if r["config"] == cfg_name
                         and r["benchmark"] == bench
                         and r["policy"] == "DRRIP")
            l1_d.append((drrip["l1d_hit_rate"] - lru["l1d_hit_rate"]) * 100)
            l2_d.append((drrip["l2_hit_rate"] - lru["l2_hit_rate"]) * 100)
            if lru["amat_cycles"] > 0:
                sp.append((lru["amat_cycles"] - drrip["amat_cycles"])
                          / lru["amat_cycles"] * 100)
            else:
                sp.append(0.0)
        avg_l1 = sum(l1_d) / len(l1_d)
        avg_l2 = sum(l2_d) / len(l2_d)
        avg_sp = sum(sp) / len(sp)
        print(f"{bench:<20s} {avg_l1:>+13.2f}  {avg_l2:>+13.2f}  {avg_sp:>+17.2f}")
    print()


if __name__ == "__main__":
    main()
