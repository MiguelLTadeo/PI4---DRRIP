# Makefile do projeto cache-replacement em C
#
# Uso:
#   make            # compila build/sim
#   make run        # compila e roda a simulação (gera CSVs em results/)
#   make plots      # gera gráficos em plots/ (precisa Python+matplotlib)
#   make all        # tudo
#   make clean

CC      ?= gcc
CFLAGS  ?= -std=c99 -O2 -Wall -Wextra -Wno-unused-parameter -D_DEFAULT_SOURCE
LDFLAGS ?= -lm

SRCDIR   = src
BUILDDIR = build
TARGET   = $(BUILDDIR)/sim

SRCS = $(wildcard $(SRCDIR)/*.c)
OBJS = $(patsubst $(SRCDIR)/%.c,$(BUILDDIR)/%.o,$(SRCS))

all: $(TARGET)

$(BUILDDIR):
	mkdir -p $(BUILDDIR)

$(BUILDDIR)/%.o: $(SRCDIR)/%.c | $(BUILDDIR)
	$(CC) $(CFLAGS) -I$(SRCDIR) -c $< -o $@

$(TARGET): $(OBJS)
	$(CC) $(OBJS) -o $@ $(LDFLAGS)

run: $(TARGET)
	mkdir -p results
	./$(TARGET)

plots: run
	mkdir -p plots
	python3 plot_results.py

clean:
	rm -rf $(BUILDDIR) results/*.csv plots/*.png

.PHONY: all run plots clean
