// ----------------------------------------------------------------------------
// tb_cache.v — Testbench para a cache parametrizável
//
// Lê um trace de endereços (um endereço hexadecimal por linha) e injeta
// os acessos na cache, contando hits/misses. Imprime o hit rate ao fim.
//
// Uso com plusargs (iverilog/ModelSim):
//   +TRACE=traces/<nome>.hex
//   +POLICY=0|1
//   +SIZE=4096 +BLOCK=32 +ASSOC=2
//
// Como o iverilog não permite override de parâmetros dinâmico para
// uma única binary, geramos um wrapper que instancia configurações
// específicas. Veja tb_cfg_A_lru.v, tb_cfg_A_drrip.v, etc.
// ----------------------------------------------------------------------------

`timescale 1ns / 1ps

module tb_cache #(
    parameter integer SIZE_BYTES  = 4096,
    parameter integer BLOCK_BYTES = 32,
    parameter integer ASSOC       = 2,
    parameter integer POLICY      = 0,         // 0=LRU, 1=DRRIP
    parameter         CFG_NAME    = "A",
    parameter         BENCH_NAME  = "unknown"
);

    // ------------------------------------------------------------
    reg clk = 0;
    reg rst_n = 0;
    always #5 clk = ~clk;       // período 10 ns -> clock de 100 MHz

    reg          req_valid = 0;
    reg  [31:0]  req_addr  = 32'd0;
    wire         resp_hit;
    wire         resp_valid;
    wire [31:0]  cnt_hits;
    wire [31:0]  cnt_misses;
    wire [31:0]  cnt_accesses;

    cache #(
        .SIZE_BYTES(SIZE_BYTES),
        .BLOCK_BYTES(BLOCK_BYTES),
        .ASSOC(ASSOC),
        .POLICY(POLICY),
        .ADDR_W(32)
    ) dut (
        .clk          (clk),
        .rst_n        (rst_n),
        .req_valid    (req_valid),
        .req_addr     (req_addr),
        .resp_hit     (resp_hit),
        .resp_valid   (resp_valid),
        .cnt_hits     (cnt_hits),
        .cnt_misses   (cnt_misses),
        .cnt_accesses (cnt_accesses)
    );

    // ------------------------------------------------------------
    // Loop de leitura do trace
    // ------------------------------------------------------------
    integer fd, code;
    reg [255*8-1:0] trace_path;
    reg [255*8-1:0] policy_str;
    integer n_lines;
    reg [31:0] addr_in;

    initial begin
        if (!$value$plusargs("TRACE=%s", trace_path)) begin
            $display("ERRO: passe +TRACE=<arquivo>");
            $finish;
        end

        if (POLICY == 0) policy_str = "LRU";
        else             policy_str = "DRRIP";

        // Reset
        rst_n = 0;
        repeat (3) @(posedge clk);
        rst_n = 1;
        @(posedge clk);

        // Abre trace
        fd = $fopen(trace_path, "r");
        if (fd == 0) begin
            $display("ERRO: nao consegui abrir %0s", trace_path);
            $finish;
        end

        n_lines = 0;
        while (!$feof(fd)) begin
            code = $fscanf(fd, "%h\n", addr_in);
            if (code == 1) begin
                @(negedge clk);
                req_valid = 1'b1;
                req_addr  = addr_in;
                n_lines   = n_lines + 1;
            end
        end
        $fclose(fd);

        // Drena o pipeline: ainda há 1 acesso pendente na borda atual
        @(negedge clk);
        req_valid = 1'b0;
        @(posedge clk);
        @(posedge clk);

        // Resultado
        $display("RESULT cfg=%0s bench=%0s policy=%0s accesses=%0d hits=%0d misses=%0d hit_rate=%0.4f",
                 CFG_NAME, BENCH_NAME, policy_str,
                 cnt_accesses, cnt_hits, cnt_misses,
                 (cnt_accesses == 0) ? 0.0 : (cnt_hits * 1.0 / cnt_accesses));

        $finish;
    end

    // Timeout de segurança
    initial begin
        #50000000;        // 50 ms simulados
        $display("TIMEOUT");
        $finish;
    end

endmodule
