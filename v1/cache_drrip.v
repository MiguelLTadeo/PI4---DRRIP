//============================================================================
// cache_drrip.v
// Cache set-associative com politica de substituicao DRRIP.
//
// Parametros:
//   ADDR_W       : largura do endereco (32 para RV32I)
//   DATA_W       : largura do barramento de dados (32 ou 64)
//   CACHE_SIZE   : capacidade em bytes (potencia de 2)
//   BLOCK_SIZE   : tamanho do bloco em bytes (potencia de 2)
//   ASSOC        : associatividade (potencia de 2)
//   RRPV_BITS    : largura do contador RRPV (M); tipico = 2
//   PSEL_BITS    : largura do contador PSEL; tipico = 10
//   SD_LOG2      : log2 do tamanho da constituency de set dueling (5 -> 32)
//
// Interface (cpu side, simplificada):
//   req_valid    : CPU faz uma requisicao
//   req_we       : 1 = write, 0 = read
//   req_addr     : endereco
//   req_wdata    : dado a escrever (se write)
//   resp_valid   : resposta pronta (1 ciclo apos hit, mais em miss)
//   resp_rdata   : dado lido
//   resp_hit     : informativo (para profiling)
//
// Interface (mem side):
//   mem_req_valid, mem_req_addr, mem_resp_valid, mem_resp_data
//
// FSM:
//   IDLE -> LOOKUP -> (HIT_DONE | MISS_VICTIM -> MISS_AGE -> MISS_FILL -> ...)
// Em hit, latencia = 1 ciclo. Em miss, latencia = (vitima + aging) +
// memoria + escrita = ~3-5 ciclos + latencia da memoria.
//
// IMPORTANTE: este modulo e' parametrizado. Para a configuracao L1D
// (4KB, bloco 32B, assoc 2), instanciar com:
//   cache_drrip #(.CACHE_SIZE(4096), .BLOCK_SIZE(32), .ASSOC(2), ...)
// Para L2 unificada (32KB, bloco 64B, assoc 8):
//   cache_drrip #(.CACHE_SIZE(32768), .BLOCK_SIZE(64), .ASSOC(8), ...)
//============================================================================

module cache_drrip #(
    parameter ADDR_W       = 32,
    parameter DATA_W       = 32,
    parameter CACHE_SIZE   = 4096,
    parameter BLOCK_SIZE   = 32,
    parameter ASSOC        = 2,
    parameter RRPV_BITS    = 2,
    parameter PSEL_BITS    = 10,
    parameter SD_LOG2      = 5    // constituency = 32 sets
)(
    input                    clk,
    input                    rst_n,

    // --- CPU side ---
    input                    req_valid,
    input                    req_we,
    input  [ADDR_W-1:0]      req_addr,
    input  [DATA_W-1:0]      req_wdata,
    output reg               resp_valid,
    output reg [DATA_W-1:0]  resp_rdata,
    output reg               resp_hit,

    // --- MEM side (downstream cache or main memory) ---
    output reg               mem_req_valid,
    output reg               mem_req_we,
    output reg [ADDR_W-1:0]  mem_req_addr,
    output reg [DATA_W-1:0]  mem_req_wdata,
    input                    mem_resp_valid,
    input  [DATA_W-1:0]      mem_resp_data
);

    //------------------------------------------------------------------------
    // Parametros derivados
    //------------------------------------------------------------------------
    localparam NUM_SETS    = CACHE_SIZE / (BLOCK_SIZE * ASSOC);
    localparam OFFSET_W    = $clog2(BLOCK_SIZE);
    localparam INDEX_W     = $clog2(NUM_SETS);
    localparam TAG_W       = ADDR_W - INDEX_W - OFFSET_W;
    localparam WAY_W       = $clog2(ASSOC);
    localparam RRPV_MAX    = (1 << RRPV_BITS) - 1;        // ex: 3 para M=2
    localparam RRPV_LONG   = RRPV_MAX - 1;                // ex: 2 (insercao SRRIP)
    localparam RRPV_DIST   = RRPV_MAX;                    // ex: 3 (insercao BRRIP)
    localparam PSEL_MAX    = (1 << PSEL_BITS) - 1;
    localparam PSEL_INIT   = PSEL_MAX / 2;

    //------------------------------------------------------------------------
    // Decomposicao de endereco
    //------------------------------------------------------------------------
    wire [TAG_W-1:0]   req_tag    = req_addr[ADDR_W-1 -: TAG_W];
    wire [INDEX_W-1:0] req_index  = req_addr[OFFSET_W +: INDEX_W];

    // Latched para uso na FSM (se a CPU mudar req_addr durante miss)
    reg  [TAG_W-1:0]   cur_tag;
    reg  [INDEX_W-1:0] cur_index;
    reg  [ADDR_W-1:0]  cur_addr;
    reg                cur_we;
    reg  [DATA_W-1:0]  cur_wdata;

    //------------------------------------------------------------------------
    // Storage: tags + dados em arrays. Em sintese para Cyclone III:
    //   tag_array  -> M9K se NUM_SETS*ASSOC for grande; senao MLAB/LE.
    //   data_array -> M9K (CACHE_SIZE bytes).
    //   rrpv_array -> registradores (precisa leitura de assoc valores em 1 ciclo).
    //   valid_array-> registradores.
    //------------------------------------------------------------------------
    reg [TAG_W-1:0]   tag_array  [0:NUM_SETS-1][0:ASSOC-1];
    reg [DATA_W-1:0]  data_array [0:NUM_SETS-1][0:ASSOC-1];
    reg [RRPV_BITS-1:0] rrpv_array [0:NUM_SETS-1][0:ASSOC-1];
    reg               valid_array[0:NUM_SETS-1][0:ASSOC-1];

    // Estado LRU para hit promotion adicional (DRRIP nao precisa, mas
    // mantemos um pseudo-LRU 1-bit caso queira coexistir com baseline.
    // Aqui DEIXAMOS DESLIGADO; somente comentado para referencia.)

    //------------------------------------------------------------------------
    // PSEL e brrip counter (set dueling)
    //------------------------------------------------------------------------
    reg [PSEL_BITS-1:0] psel;
    reg [4:0]           brrip_ctr;     // contador para 1-em-32

    wire psel_msb = psel[PSEL_BITS-1];
    wire follower_use_srrip = (psel_msb == 1'b0); // PSEL baixo -> SRRIP venceu

    // Identifica sets dedicados via mascara dos LSBs do indice.
    wire [SD_LOG2-1:0] sd_id = cur_index[SD_LOG2-1:0];
    wire is_dedicated_srrip = (sd_id == {SD_LOG2{1'b0}});      // padrao 0
    wire is_dedicated_brrip = (sd_id == {SD_LOG2{1'b1}});      // padrao 1

    //------------------------------------------------------------------------
    // Lookup combinacional: gera hit_way one-hot e flag de hit.
    //------------------------------------------------------------------------
    wire [ASSOC-1:0] way_match;
    genvar gi;
    generate
        for (gi = 0; gi < ASSOC; gi = gi + 1) begin : g_match
            assign way_match[gi] = valid_array[cur_index][gi] &&
                                   (tag_array[cur_index][gi] == cur_tag);
        end
    endgenerate
    wire hit = |way_match;

    // Codifica way_match (one-hot) em binario (priority encoder).
    reg [WAY_W-1:0] hit_way;
    integer wi;
    always @(*) begin
        hit_way = {WAY_W{1'b0}};
        for (wi = 0; wi < ASSOC; wi = wi + 1)
            if (way_match[wi]) hit_way = wi[WAY_W-1:0];
    end

    //------------------------------------------------------------------------
    // FSM
    //------------------------------------------------------------------------
    localparam S_IDLE     = 3'd0;
    localparam S_LOOKUP   = 3'd1;
    localparam S_AGE      = 3'd2;   // incrementa todos rrpv ate aparecer max
    localparam S_FETCH    = 3'd3;   // espera memoria
    localparam S_FILL     = 3'd4;   // grava bloco vindo da memoria
    localparam S_DONE     = 3'd5;

    reg [2:0] state, nstate;
    reg [WAY_W-1:0] victim_way;

    // ---- victim search combinacional ----
    // Procura primeiro uma via invalida; senao, alguma com rrpv == max.
    // Se nenhuma == max, sinaliza need_age = 1 (FSM faz aging step).
    wire [ASSOC-1:0] way_invalid;
    wire [ASSOC-1:0] way_at_max;
    generate
        for (gi = 0; gi < ASSOC; gi = gi + 1) begin : g_vict
            assign way_invalid[gi] = ~valid_array[cur_index][gi];
            assign way_at_max[gi]  = valid_array[cur_index][gi] &&
                                     (rrpv_array[cur_index][gi] == RRPV_MAX);
        end
    endgenerate
    wire any_invalid = |way_invalid;
    wire any_at_max  = |way_at_max;
    wire need_age    = ~any_invalid & ~any_at_max;

    reg [WAY_W-1:0] victim_invalid_way, victim_max_way;
    integer vi;
    always @(*) begin
        victim_invalid_way = {WAY_W{1'b0}};
        victim_max_way     = {WAY_W{1'b0}};
        for (vi = 0; vi < ASSOC; vi = vi + 1) begin
            if (way_invalid[vi]) victim_invalid_way = vi[WAY_W-1:0];
            if (way_at_max[vi])  victim_max_way     = vi[WAY_W-1:0];
        end
    end

    //------------------------------------------------------------------------
    // Decisao do RRPV de insercao (combinacional, baseado em set dueling)
    //------------------------------------------------------------------------
    // SRRIP path -> RRPV_LONG
    // BRRIP path -> RRPV_DIST a maioria, RRPV_LONG quando brrip_ctr == 0
    wire use_srrip_for_this_set =
        is_dedicated_srrip ? 1'b1 :
        is_dedicated_brrip ? 1'b0 :
        follower_use_srrip;

    wire brrip_inject_long = (brrip_ctr == 5'd0);

    wire [RRPV_BITS-1:0] insert_rrpv =
        use_srrip_for_this_set       ? RRPV_LONG[RRPV_BITS-1:0] :
        brrip_inject_long            ? RRPV_LONG[RRPV_BITS-1:0] :
                                       RRPV_DIST[RRPV_BITS-1:0];

    //------------------------------------------------------------------------
    // FSM: proxima logica de estado e saidas
    //------------------------------------------------------------------------
    always @(*) begin
        nstate          = state;
        mem_req_valid   = 1'b0;
        mem_req_we      = 1'b0;
        mem_req_addr    = cur_addr;
        mem_req_wdata   = cur_wdata;
        case (state)
            S_IDLE: begin
                if (req_valid) nstate = S_LOOKUP;
            end
            S_LOOKUP: begin
                if (hit)        nstate = S_DONE;
                else if (need_age) nstate = S_AGE;
                else            nstate = S_FETCH;
            end
            S_AGE: begin
                // Apos incrementar todos os rrpvs, refaz analise: se ainda
                // need_age, fica em S_AGE. Senao, segue para S_FETCH.
                if (need_age) nstate = S_AGE;
                else          nstate = S_FETCH;
            end
            S_FETCH: begin
                mem_req_valid = 1'b1;
                mem_req_we    = 1'b0;
                if (mem_resp_valid) nstate = S_FILL;
            end
            S_FILL: begin
                nstate = S_DONE;
            end
            S_DONE: begin
                nstate = S_IDLE;
            end
            default: nstate = S_IDLE;
        endcase
    end

    //------------------------------------------------------------------------
    // FSM: registradores e atualizacoes do storage
    //------------------------------------------------------------------------
    integer si, ai;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state       <= S_IDLE;
            psel        <= PSEL_INIT[PSEL_BITS-1:0];
            brrip_ctr   <= 5'd0;
            resp_valid  <= 1'b0;
            resp_hit    <= 1'b0;
            resp_rdata  <= {DATA_W{1'b0}};
            victim_way  <= {WAY_W{1'b0}};
            // limpa valid_array (custoso em sintese; recomenda-se reset
            // sequencial na inicializacao real)
            for (si = 0; si < NUM_SETS; si = si + 1)
                for (ai = 0; ai < ASSOC; ai = ai + 1) begin
                    valid_array[si][ai] <= 1'b0;
                    rrpv_array[si][ai]  <= RRPV_MAX[RRPV_BITS-1:0];
                end
        end else begin
            state       <= nstate;
            resp_valid  <= 1'b0;

            case (state)
                S_IDLE: begin
                    if (req_valid) begin
                        cur_addr  <= req_addr;
                        cur_tag   <= req_tag;
                        cur_index <= req_index;
                        cur_we    <= req_we;
                        cur_wdata <= req_wdata;
                    end
                end

                S_LOOKUP: begin
                    if (hit) begin
                        // Hit Promotion: RRPV -> 0
                        rrpv_array[cur_index][hit_way] <= {RRPV_BITS{1'b0}};
                        if (cur_we) begin
                            data_array[cur_index][hit_way] <= cur_wdata;
                        end else begin
                            resp_rdata <= data_array[cur_index][hit_way];
                        end
                        resp_hit <= 1'b1;
                    end else begin
                        // Selecionar vitima agora (latch).
                        if (any_invalid) victim_way <= victim_invalid_way;
                        else if (any_at_max) victim_way <= victim_max_way;
                        // Atualizar PSEL se este set e' dedicado
                        if (is_dedicated_srrip && psel < PSEL_MAX)
                            psel <= psel + 1'b1;
                        else if (is_dedicated_brrip && psel != {PSEL_BITS{1'b0}})
                            psel <= psel - 1'b1;
                    end
                end

                S_AGE: begin
                    // Incrementa todos os rrpvs do set ate a saturacao.
                    for (ai = 0; ai < ASSOC; ai = ai + 1)
                        if (valid_array[cur_index][ai] &&
                            rrpv_array[cur_index][ai] != RRPV_MAX[RRPV_BITS-1:0])
                            rrpv_array[cur_index][ai] <=
                                rrpv_array[cur_index][ai] + 1'b1;
                    // Apos incrementar, pode ainda estar em S_AGE se
                    // continuar sem nenhum max (raro - so se todos eram 0).
                    // Recheca na proxima borda.
                    if (any_at_max) victim_way <= victim_max_way;
                end

                S_FETCH: begin
                    // espera memoria responder
                end

                S_FILL: begin
                    // Grava bloco vindo da memoria na vitima.
                    valid_array[cur_index][victim_way] <= 1'b1;
                    tag_array[cur_index][victim_way]   <= cur_tag;
                    data_array[cur_index][victim_way]  <= mem_resp_data;
                    rrpv_array[cur_index][victim_way]  <= insert_rrpv;
                    // Atualiza brrip_ctr quando inseriu em politica BRRIP
                    if (!use_srrip_for_this_set)
                        brrip_ctr <= brrip_ctr + 1'b1;
                    if (cur_we) data_array[cur_index][victim_way] <= cur_wdata;
                    else        resp_rdata <= mem_resp_data;
                    resp_hit <= 1'b0;
                end

                S_DONE: begin
                    resp_valid <= 1'b1;
                end

                default: ;
            endcase
        end
    end

endmodule
