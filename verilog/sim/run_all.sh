#!/bin/bash
# run_all.sh — Roda todas as combinações Config × Benchmark × Política
# e gera um CSV consolidado em sim/results.csv

set -e
cd "$(dirname "$0")/.."

CONFIGS=(A B C)
BENCHES=(streaming_hotset matrix_conv linked_list pattern_search mixed_access)
POLICIES=(lru drrip)

# 1) Recompila tudo
echo "[1/3] Compilando RTL..."
mkdir -p sim
for cfg in "${CONFIGS[@]}"; do
    for pol in "${POLICIES[@]}"; do
        iverilog -g2001 -s tb_cfg${cfg}_${pol} \
                 -o sim/cfg${cfg}_${pol}.vvp \
                 rtl/cache.v tb/tb_cache.v tb/tb_top.v
    done
done

# 2) Gera traces se ainda não existem
echo "[2/3] Verificando traces..."
if [ ! -f traces/streaming_hotset.hex ]; then
    ( cd traces && gcc -O2 -o gen_traces gen_traces.c && ./gen_traces . )
fi

# 3) Roda todas as 30 simulações
echo "[3/3] Rodando 30 simulações..."
CSV=sim/results.csv
echo "config,benchmark,policy,accesses,hits,misses,hit_rate" > $CSV

for cfg in "${CONFIGS[@]}"; do
    for bench in "${BENCHES[@]}"; do
        for pol in "${POLICIES[@]}"; do
            line=$(vvp sim/cfg${cfg}_${pol}.vvp \
                       +TRACE=traces/${bench}.hex 2>/dev/null \
                       | grep RESULT)
            # parse "accesses=X hits=Y misses=Z hit_rate=W"
            acc=$(echo "$line"   | sed -E 's/.*accesses=([0-9]+).*/\1/')
            hits=$(echo "$line"  | sed -E 's/.*hits=([0-9]+).*/\1/')
            miss=$(echo "$line"  | sed -E 's/.*misses=([0-9]+).*/\1/')
            rate=$(echo "$line"  | sed -E 's/.*hit_rate=([0-9.]+).*/\1/')
            POL_UPPER=$(echo $pol | tr a-z A-Z)
            printf "%s,%s,%s,%s,%s,%s,%s\n" \
                   "$cfg" "$bench" "$POL_UPPER" \
                   "$acc" "$hits" "$miss" "$rate" >> $CSV
            printf "  %s | %-18s | %-5s | %.4f\n" \
                   "$cfg" "$bench" "$POL_UPPER" "$rate"
        done
    done
done

echo ""
echo "CSV gravado em: $CSV"
