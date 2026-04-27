#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

// --- CONFIGURAÇÕES DE TAMANHO ---
// Ajuste para ser ~2x o tamanho da sua Cache L2 para forçar o Miss
#define L2_SIZE_BYTES (128 * 1024)
#define ARRAY_SIZE (L2_SIZE_BYTES * 2 / sizeof(int))

// --- MACROS PARA MÉTRICAS (PROFILING) ---
// No PC, você pode usar 'perf' externo. No RISC-V, insira leitura de CSRs aqui.
#define START_PERF() printf("\n[Iniciando medição...]\n")
#define END_PERF() printf("[Fim da medição.]\n\n")

typedef struct Node {
    int data;
    struct Node *next;
} Node;

// --- DEFINIÇÃO DOS BENCHMARKS ---
void run_streaming(int *array, volatile int *hot_data) {
    printf("Executando: Streaming + HotSet (Antagonista ao LRU)\n");
    START_PERF();
    for (int it = 0; it < 10; it++) {
        for (int i = 0; i < ARRAY_SIZE; i++) {
            array[i] += i;
            if (i % 64 == 0) *hot_data += array[i];
        }
    }
    END_PERF();
}

void run_matrix_conv(int *img, int *out) {
    printf("Executando: Matriz 2D - Convolução (Reuso em Janela)\n");
    int width = 128;
    int height = ARRAY_SIZE / width;
    
    START_PERF();
    for (int y = 1; y < height - 1; y++) {
        for (int x = 1; x < width - 1; x++) {
            out[y * width + x] = img[(y - 1) * width + x] + 
                                 img[y * width + x] + 
                                 img[(y + 1) * width + x];
        }
    }
    END_PERF();
}

void run_linked_list(Node *nodes, int count) {
    printf("Executando: Linked List (Ponteiros/Saltos de Memória)\n");
    Node *curr = nodes;
    
    START_PERF();
    for (int i = 0; i < count * 50; i++) {
        curr->data += i;
        curr = curr->next;
    }
    END_PERF();
}

void run_pattern_search(uint8_t *blob, int size) {
    printf("Executando: Pattern Search (Estresse de L2 Unificada)\n");
    
    START_PERF();
    for (int i = 1024; i < size; i++) {
        for (int j = 1; j < 64; j++) {
            if (blob[i] == blob[i - j]) {
                blob[i]++;
                break;
            }
        }
    }
    END_PERF();
}

// --- MENU PRINCIPAL ---
void print_menu() {
    printf("========================================\n");
    printf(" SELETOR DE BENCHMARKS - CACHE IA \n");
    printf("========================================\n");
    printf("1. Streaming + HotSet (L1/L2 Data)\n");
    printf("2. Matrix Convolution (Temporal Reuse)\n");
    printf("3. Linked List Traversal (Pointer Chasing)\n");
    printf("4. Pattern Search (L2 Unified Stress)\n");
    printf("5. Executar Todos em Sequência\n");
    printf("0. Sair\n");
    printf("Escolha uma opção: ");
}

int main() {
    int choice = -1;
    volatile int hot_val = 0;
    
    // Alocação e Inicialização
    int *big_array = (int *) calloc(ARRAY_SIZE, sizeof(int));
    int *out_array = (int *) calloc(ARRAY_SIZE, sizeof(int));
    uint8_t *blob = (uint8_t *) malloc(L2_SIZE_BYTES);
    Node *nodes = (Node *) malloc(2000 * sizeof(Node));
    
    // Inicializando a lista encadeada circular
    for (int i = 0; i < 1999; i++) {
        nodes[i].next = &nodes[i + 1];
    }
    nodes[1999].next = &nodes[0];
    
    while (choice != 0) {
        print_menu();
        if (scanf("%d", &choice) != 1) break;

        switch (choice) {
            case 1:
                run_streaming(big_array, &hot_val);
                break;
            case 2:
                run_matrix_conv(big_array, out_array);
                break;
            case 3:
                run_linked_list(nodes, 2000);
                break;
            case 4:
                run_pattern_search(blob, L2_SIZE_BYTES);
                break;
            case 5:
                run_streaming(big_array, &hot_val);
                run_matrix_conv(big_array, out_array);
                run_linked_list(nodes, 2000);
                run_pattern_search(blob, L2_SIZE_BYTES);
                break;
            case 0:
                printf("Encerrando...\n");
                break;
            default:
                printf("Opção inválida!\n");
        }
    }
    
    // Limpeza de memória
    free(big_array);
    free(out_array);
    free(nodes);
    free(blob);
    
    return 0;
}