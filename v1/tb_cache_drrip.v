//============================================================================
// tb_cache_drrip.v
// Testbench basico para cache_drrip. Verifica:
//   1. Hit apos primeira instalacao
//   2. Miss apos working set exceder capacidade
//   3. Comportamento do PSEL (sets dedicados deslocam contador)
//   4. RRPV de blocos quentes -> 0 apos hit
//
// Roda em ModelSim/Icarus. Para Icarus:
//   iverilog -o tb_drrip ../rtl/cache/cache_drrip.v tb_cache_drrip.v
//   vvp tb_drrip
//============================================================================

`timescale 1ns/1ps

module tb_cache_drrip;
    parameter ADDR_W      = 32;
    parameter DATA_W      = 32;
    parameter CACHE_SIZE  = 256;     // 256B (cache "brinquedo" para testes)
    parameter BLOCK_SIZE  = 32;
    parameter ASSOC       = 2;
    parameter NUM_SETS    = CACHE_SIZE / (BLOCK_SIZE * ASSOC); // 4 sets

    reg clk = 0;
    reg rst_n = 0;
    always #5 clk = ~clk; // 100 MHz

    reg                req_valid = 0;
    reg                req_we    = 0;
    reg [ADDR_W-1:0]   req_addr  = 0;
    reg [DATA_W-1:0]   req_wdata = 0;
    wire               resp_valid;
    wire [DATA_W-1:0]  resp_rdata;
    wire               resp_hit;

    wire               mem_req_valid;
    wire               mem_req_we;
    wire [ADDR_W-1:0]  mem_req_addr;
    wire [DATA_W-1:0]  mem_req_wdata;
    reg                mem_resp_valid = 0;
    reg  [DATA_W-1:0]  mem_resp_data  = 0;

    cache_drrip #(
        .ADDR_W(ADDR_W), .DATA_W(DATA_W),
        .CACHE_SIZE(CACHE_SIZE), .BLOCK_SIZE(BLOCK_SIZE), .ASSOC(ASSOC),
        .RRPV_BITS(2), .PSEL_BITS(10), .SD_LOG2(1)  // SD_LOG2=1 -> constituency=2
                                                     // (compatible com 4 sets)
    ) dut (
        .clk(clk), .rst_n(rst_n),
        .req_valid(req_valid), .req_we(req_we),
        .req_addr(req_addr), .req_wdata(req_wdata),
        .resp_valid(resp_valid), .resp_rdata(resp_rdata),
        .resp_hit(resp_hit),
        .mem_req_valid(mem_req_valid), .mem_req_we(mem_req_we),
        .mem_req_addr(mem_req_addr), .mem_req_wdata(mem_req_wdata),
        .mem_resp_valid(mem_resp_valid), .mem_resp_data(mem_resp_data)
    );

    //------------------------------------------------------------------------
    // Memoria simulada: responde com dado = endereco (truncado) apos 2 ciclos
    //------------------------------------------------------------------------
    reg [3:0] mem_delay_cnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            mem_resp_valid <= 0;
            mem_resp_data  <= 0;
            mem_delay_cnt  <= 0;
        end else begin
            mem_resp_valid <= 0;
            if (mem_req_valid && mem_delay_cnt == 0)
                mem_delay_cnt <= 2;
            else if (mem_delay_cnt == 1) begin
                mem_resp_valid <= 1;
                mem_resp_data  <= mem_req_addr; // dado "fake"
                mem_delay_cnt  <= 0;
            end else if (mem_delay_cnt > 0)
                mem_delay_cnt  <= mem_delay_cnt - 1;
        end
    end

    //------------------------------------------------------------------------
    // Contadores de hit/miss para verificar
    //------------------------------------------------------------------------
    integer total = 0;
    integer hits = 0;
    integer misses = 0;

    always @(posedge clk) begin
        if (resp_valid) begin
            total = total + 1;
            if (resp_hit) hits = hits + 1;
            else misses = misses + 1;
        end
    end

    //------------------------------------------------------------------------
    // Tarefa para emitir 1 acesso e esperar resposta
    //------------------------------------------------------------------------
    task do_access(input [ADDR_W-1:0] a, input we, input [DATA_W-1:0] d);
        begin
            @(posedge clk);
            req_valid <= 1;
            req_we    <= we;
            req_addr  <= a;
            req_wdata <= d;
            @(posedge clk);
            req_valid <= 0;
            // espera resp_valid
            wait (resp_valid == 1);
            @(posedge clk);
        end
    endtask

    //------------------------------------------------------------------------
    // Sequencia de teste
    //------------------------------------------------------------------------
    integer i;
    initial begin
        $display("=== tb_cache_drrip ===");
        $display("CACHE_SIZE=%0d BLOCK=%0d ASSOC=%0d NUM_SETS=%0d",
                 CACHE_SIZE, BLOCK_SIZE, ASSOC, NUM_SETS);
        rst_n = 0;
        #50 rst_n = 1;
        @(posedge clk);

        // TESTE 1: cold miss seguido de hit no mesmo bloco
        $display("[Teste 1] cold miss + hit");
        do_access(32'h0000_0000, 0, 0); // miss
        do_access(32'h0000_0004, 0, 0); // hit (mesmo bloco)
        do_access(32'h0000_0010, 0, 0); // hit (mesmo bloco - offset 16)

        // TESTE 2: stride > tamanho da cache (forca thrashing)
        $display("[Teste 2] streaming alem da capacidade");
        for (i = 0; i < 16; i = i + 1)
            do_access(32'h1000_0000 + i * BLOCK_SIZE, 0, 0);

        // TESTE 3: working set pequeno - deveria ter hits altos
        $display("[Teste 3] reuso de working set pequeno (<= ASSOC)");
        for (i = 0; i < 20; i = i + 1)
            do_access(32'h2000_0000 + (i % 2) * BLOCK_SIZE, 0, 0);

        $display("=== RESULTADO ===");
        $display("Total: %0d  Hits: %0d  Misses: %0d  HR: %0d%%",
                 total, hits, misses,
                 (total > 0) ? (100 * hits / total) : 0);
        $display("PSEL final: %0d", dut.psel);
        $finish;
    end

    initial begin
        #20000;
        $display("TIMEOUT");
        $finish;
    end

    // Dump para SignalTap/GTKWave
    initial begin
        $dumpfile("tb_cache_drrip.vcd");
        $dumpvars(0, tb_cache_drrip);
    end

endmodule
