"""Compara hit rate da implementação C (tida como referência) e do Verilog
gerado nesta sprint, política por política. Demonstra que o RTL bate com o C."""

import csv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

CONFIGS    = ['A', 'B', 'C']
BENCHES    = ['streaming_hotset', 'matrix_conv', 'linked_list',
              'pattern_search',   'mixed_access']
LABELS     = ['stream\nhotset', 'matrix\nconv', 'linked\nlist',
              'pattern\nsearch', 'mixed\naccess']

# Resultado do binário C (rodando ./sim do projeto da sprint 2) — referência
C_RES = {
    'A': {
        'streaming_hotset': {'LRU': 0.938452, 'DRRIP': 0.938452},
        'matrix_conv':      {'LRU': 0.937004, 'DRRIP': 0.937004},
        'linked_list':      {'LRU': 0.672000, 'DRRIP': 0.672000},
        'pattern_search':   {'LRU': 0.996197, 'DRRIP': 0.996197},
        'mixed_access':     {'LRU': 0.681818, 'DRRIP': 0.712500},
    },
    'B': {
        'streaming_hotset': {'LRU': 0.938457, 'DRRIP': 0.938457},
        'matrix_conv':      {'LRU': 0.937004, 'DRRIP': 0.937004},
        'linked_list':      {'LRU': 0.672000, 'DRRIP': 0.672033},
        'pattern_search':   {'LRU': 0.996205, 'DRRIP': 0.996205},
        'mixed_access':     {'LRU': 0.681818, 'DRRIP': 0.721023},
    },
    'C': {
        'streaming_hotset': {'LRU': 0.938459, 'DRRIP': 0.938459},
        'matrix_conv':      {'LRU': 0.937004, 'DRRIP': 0.937004},
        'linked_list':      {'LRU': 0.677800, 'DRRIP': 0.677908},
        'pattern_search':   {'LRU': 0.996208, 'DRRIP': 0.996208},
        'mixed_access':     {'LRU': 0.681818, 'DRRIP': 0.784091},
    },
}

V_RES = {c: {b: {} for b in BENCHES} for c in CONFIGS}
with open('sim/results.csv') as f:
    for row in csv.DictReader(f):
        V_RES[row['config']][row['benchmark']][row['policy']] = float(row['hit_rate'])


def panel(ax, policy, title):
    x = np.arange(len(BENCHES))
    n_cfgs = len(CONFIGS)
    total_width = 0.8
    pair_width = total_width / n_cfgs
    bar_width  = pair_width * 0.45

    for k, cfg in enumerate(CONFIGS):
        c_vals = [C_RES[cfg][b][policy] * 100 for b in BENCHES]
        v_vals = [V_RES[cfg][b][policy] * 100 for b in BENCHES]
        center = (k - (n_cfgs - 1) / 2) * pair_width
        ax.bar(x + center - bar_width/2, c_vals, bar_width,
               color='#1f4e79', edgecolor='black', linewidth=0.4,
               label='C' if k == 0 else None)
        ax.bar(x + center + bar_width/2, v_vals, bar_width,
               color='#c14e1f', edgecolor='black', linewidth=0.4,
               label='Verilog' if k == 0 else None)
        # rótulo de Config abaixo da dupla
        ax.text(x[-1] + center, -7, cfg, fontsize=8,
                ha='center', va='top', color='gray')

    ax.set_xticks(x)
    ax.set_xticklabels(LABELS, fontsize=9)
    ax.set_ylim(0, 105)
    ax.set_title(title, fontsize=11)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_axisbelow(True)


fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
panel(axes[0], 'LRU',   'LRU — Verilog vs C')
panel(axes[1], 'DRRIP', 'DRRIP — Verilog vs C')
axes[0].set_ylabel('Hit rate (%)')
axes[0].legend(loc='lower right', fontsize=9)
fig.suptitle('Validação cruzada: implementação Verilog vs referência C',
             fontsize=13, fontweight='bold')
fig.tight_layout(rect=[0, 0, 1, 0.95])
fig.savefig('docs/c_vs_verilog.png', dpi=130, bbox_inches='tight')
print("gerado: docs/c_vs_verilog.png")
