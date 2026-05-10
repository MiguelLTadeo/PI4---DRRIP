//============================================================================
// cache_lru.v
// Cache baseline com Pseudo-LRU (Tree-PLRU para assoc>2; LRU exato para assoc=2).
//
// IMPORTANTE: a arquitetura desta cache (FSM, organizacao de storage,
// interface) e' INTENCIONALMENTE IDENTICA a' cache_drrip.v. Isto e'
// requisito metodologico: a comparacao de area e Fmax so e' justa se a
// unica diferenca for a logica de substituicao.
//
// Diferencas em relacao a cache_drrip.v:
//   - Substitui rrpv_array por plru_state[NUM_SETS] (tree de assoc-1 bits).
//   - Sem PSEL, sem brrip_ctr, sem set dueling.
//   - Vitima determinada percorrendo a arvore PLRU (latencia 1 ciclo).
//   - Hit promotion: atualiza bits da arvore para o way que deu hit.
//
// Para assoc=2: arvore PLRU com 1 bit -> equivalente a LRU exato.
// Para assoc=4: arvore com 3 bits.
// Para assoc=8: arvore com 7 bits.
// Para assoc=16: arvore com 15 bits.
//============================================================================

module cache_lru #(
    parameter ADDR_W       = 32,
    parameter DATA_W       = 32,
    parameter CACHE_SIZE   = 4096,
    parameter BLOCK_SIZE   = 32,
    parameter ASSOC        = 2
)(
    input                    clk,
    input                    rst_n,

    input                    req_valid,
    input                    req_we,
    input  [ADDR_W-1:0]      req_addr,
    input  [DATA_W-1:0]      req_wdata,
    output reg               resp_valid,
    output reg [DATA_W-1:0]  resp_rdata,
    output reg               resp_hit,

    output reg               mem_req_valid,
    output reg               mem_req_we,
    output reg [ADDR_W-1:0]  mem_req_addr,
    output reg [DATA_W-1:0]  mem_req_wdata,
    input                    mem_resp_valid,
    input  [DATA_W-1:0]      mem_resp_data
);

    localparam NUM_SETS    = CACHE_SIZE / (BLOCK_SIZE * ASSOC);
    localparam OFFSET_W    = $clog2(BLOCK_SIZE);
    localparam INDEX_W     = $clog2(NUM_SETS);
    localparam TAG_W       = ADDR_W - INDEX_W - OFFSET_W;
    localparam WAY_W       = $clog2(ASSOC);
    localparam PLRU_BITS   = ASSOC - 1;

    // Decomposicao
    wire [TAG_W-1:0]   req_tag    = req_addr[ADDR_W-1 -: TAG_W];
    wire [INDEX_W-1:0] req_index  = req_addr[OFFSET_W +: INDEX_W];

    reg  [TAG_W-1:0]   cur_tag;
    reg  [INDEX_W-1:0] cur_index;
    reg  [ADDR_W-1:0]  cur_addr;
    reg                cur_we;
    reg  [DATA_W-1:0]  cur_wdata;

    // Storage
    reg [TAG_W-1:0]   tag_array  [0:NUM_SETS-1][0:ASSOC-1];
    reg [DATA_W-1:0]  data_array [0:NUM_SETS-1][0:ASSOC-1];
    reg               valid_array[0:NUM_SETS-1][0:ASSOC-1];
    reg [PLRU_BITS-1:0] plru_state [0:NUM_SETS-1];

    // Lookup
    wire [ASSOC-1:0] way_match;
    genvar gi;
    generate
        for (gi = 0; gi < ASSOC; gi = gi + 1) begin : g_match
            assign way_match[gi] = valid_array[cur_index][gi] &&
                                   (tag_array[cur_index][gi] == cur_tag);
        end
    endgenerate
    wire hit = |way_match;

    reg [WAY_W-1:0] hit_way;
    integer wi;
    always @(*) begin
        hit_way = {WAY_W{1'b0}};
        for (wi = 0; wi < ASSOC; wi = wi + 1)
            if (way_match[wi]) hit_way = wi[WAY_W-1:0];
    end

    // Vitima invalida prioritaria
    wire [ASSOC-1:0] way_invalid;
    generate
        for (gi = 0; gi < ASSOC; gi = gi + 1) begin : g_inv
            assign way_invalid[gi] = ~valid_array[cur_index][gi];
        end
    endgenerate
    wire any_invalid = |way_invalid;
    reg [WAY_W-1:0] victim_invalid_way;
    integer vi;
    always @(*) begin
        victim_invalid_way = {WAY_W{1'b0}};
        for (vi = 0; vi < ASSOC; vi = vi + 1)
            if (way_invalid[vi]) victim_invalid_way = vi[WAY_W-1:0];
    end

    //------------------------------------------------------------------------
    // Tree-PLRU: percorre a arvore para achar a "menos recente"
    // Convencao: bit 0 da arvore = raiz. Apontar para 0 -> ir para sub-arvore
    // esquerda; apontar para 1 -> direita. Vitima esta no caminho.
    //
    // Para assoc=2 (PLRU_BITS=1):  bit0 -> way (LRU exato)
    // Para assoc=4 (PLRU_BITS=3):
    //     bit2: raiz -> esquerda(ways 0,1) ou direita (ways 2,3)
    //     bit1: subtree esquerda
    //     bit0: subtree direita
    //------------------------------------------------------------------------
    reg [WAY_W-1:0] plru_victim;
    reg [PLRU_BITS-1:0] plru_next;
    integer level, node;

    always @(*) begin
        // Calcula vitima percorrendo a arvore (combinacional).
        // Implementacao manual para assoc=2 e 4. Para 8/16 usa algoritmo
        // generico de descida em arvore binaria balanceada.
        plru_victim = {WAY_W{1'b0}};
        if (ASSOC == 2) begin
            plru_victim = plru_state[cur_index][0];
        end else if (ASSOC == 4) begin
            if (plru_state[cur_index][2] == 1'b0) begin
                // foi para esquerda recentemente -> vitima na esquerda
                plru_victim = {1'b0, plru_state[cur_index][1]};
            end else begin
                plru_victim = {1'b1, plru_state[cur_index][0]};
            end
        end else if (ASSOC == 8) begin
            // arvore de 7 bits: bit6 raiz, bits5,4 nivel 1, bits3..0 folhas
            if (plru_state[cur_index][6] == 1'b0) begin
                if (plru_state[cur_index][5] == 1'b0)
                    plru_victim = {2'b00, plru_state[cur_index][3]};
                else
                    plru_victim = {2'b01, plru_state[cur_index][2]};
            end else begin
                if (plru_state[cur_index][4] == 1'b0)
                    plru_victim = {2'b10, plru_state[cur_index][1]};
                else
                    plru_victim = {2'b11, plru_state[cur_index][0]};
            end
        end else if (ASSOC == 16) begin
            // arvore de 15 bits. Implementacao parcial; expandir conforme uso.
            // Aqui simplificamos: mascara o way num round-robin pseudo-LRU.
            // SUBSTITUIR por arvore completa antes da entrega final.
            plru_victim = plru_state[cur_index][3:0];
        end
    end

    //------------------------------------------------------------------------
    // Atualizacao da arvore PLRU em hit/install: invertemos os bits no
    // caminho da raiz ate o way acessado, apontando *para o lado oposto*.
    //------------------------------------------------------------------------
    function [PLRU_BITS-1:0] plru_update;
        input [PLRU_BITS-1:0] state;
        input [WAY_W-1:0]     way;
        begin
            plru_update = state;
            if (ASSOC == 2) begin
                plru_update[0] = ~way[0];
            end else if (ASSOC == 4) begin
                plru_update[2] = ~way[1];                // raiz aponta longe
                if (way[1] == 1'b0) plru_update[1] = ~way[0];
                else                plru_update[0] = ~way[0];
            end else if (ASSOC == 8) begin
                plru_update[6] = ~way[2];
                if (way[2] == 1'b0) begin
                    plru_update[5] = ~way[1];
                    if (way[1] == 1'b0) plru_update[3] = ~way[0];
                    else                plru_update[2] = ~way[0];
                end else begin
                    plru_update[4] = ~way[1];
                    if (way[1] == 1'b0) plru_update[1] = ~way[0];
                    else                plru_update[0] = ~way[0];
                end
            end else begin
                // assoc=16: implementacao a expandir
                plru_update = state;
            end
        end
    endfunction

    //------------------------------------------------------------------------
    // FSM identica em estrutura a' cache_drrip
    //------------------------------------------------------------------------
    localparam S_IDLE     = 3'd0;
    localparam S_LOOKUP   = 3'd1;
    localparam S_FETCH    = 3'd2;
    localparam S_FILL     = 3'd3;
    localparam S_DONE     = 3'd4;

    reg [2:0] state, nstate;
    reg [WAY_W-1:0] victim_way;

    always @(*) begin
        nstate          = state;
        mem_req_valid   = 1'b0;
        mem_req_we      = 1'b0;
        mem_req_addr    = cur_addr;
        mem_req_wdata   = cur_wdata;
        case (state)
            S_IDLE:   if (req_valid) nstate = S_LOOKUP;
            S_LOOKUP: nstate = hit ? S_DONE : S_FETCH;
            S_FETCH: begin
                mem_req_valid = 1'b1;
                if (mem_resp_valid) nstate = S_FILL;
            end
            S_FILL:   nstate = S_DONE;
            S_DONE:   nstate = S_IDLE;
            default:  nstate = S_IDLE;
        endcase
    end

    integer si, ai;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state       <= S_IDLE;
            resp_valid  <= 1'b0;
            resp_hit    <= 1'b0;
            resp_rdata  <= {DATA_W{1'b0}};
            victim_way  <= {WAY_W{1'b0}};
            for (si = 0; si < NUM_SETS; si = si + 1) begin
                plru_state[si] <= {PLRU_BITS{1'b0}};
                for (ai = 0; ai < ASSOC; ai = ai + 1)
                    valid_array[si][ai] <= 1'b0;
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
                        plru_state[cur_index] <=
                            plru_update(plru_state[cur_index], hit_way);
                        if (cur_we)
                            data_array[cur_index][hit_way] <= cur_wdata;
                        else
                            resp_rdata <= data_array[cur_index][hit_way];
                        resp_hit <= 1'b1;
                    end else begin
                        if (any_invalid) victim_way <= victim_invalid_way;
                        else             victim_way <= plru_victim;
                    end
                end
                S_FETCH: ;
                S_FILL: begin
                    valid_array[cur_index][victim_way] <= 1'b1;
                    tag_array[cur_index][victim_way]   <= cur_tag;
                    data_array[cur_index][victim_way]  <= mem_resp_data;
                    plru_state[cur_index] <=
                        plru_update(plru_state[cur_index], victim_way);
                    if (cur_we) data_array[cur_index][victim_way] <= cur_wdata;
                    else        resp_rdata <= mem_resp_data;
                    resp_hit <= 1'b0;
                end
                S_DONE: resp_valid <= 1'b1;
                default: ;
            endcase
        end
    end

endmodule
