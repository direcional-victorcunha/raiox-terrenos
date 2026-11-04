# Cópia congelada de prospeccao-marechal-tito/core/contexto.py em 2026-10-28.
"""
Sinais e alertas legados extraídos de core.contexto para manter compatibilidade com geo_engine.
"""

LIMIAR_PCT = 10.0  # sobreposição mínima (% do lote) para acender um sinal
LIMIAR_DUTO_M = 30.0  # distância máxima (m) até duto da Transpetro para acender o sinal
LIMIAR_ALTA_M = 1.0  # linha de alta tensão que cruza o lote (tolerância de 1 m)

SINAIS_ORDEM = (
    "Área pública/parque",
    "Favela",
    "Área contaminada",
    "Risco geológico",
    "Duto (≤ 30 m)",
    "Alta tensão (cruza)",
)


def texto_alertas(pub, favela, contaminada, risco, duto=float("nan"), alta=float("nan")) -> str:
    """Resumo curto dos sinais para tabela e etiqueta do mapa.
    Áreas: ≥10% de sobreposição. Duto: a até LIMIAR_DUTO_M. Alta tensão: cruza o lote."""
    itens = []
    if pub >= LIMIAR_PCT:
        itens.append("Área pública/parque")
    if favela >= LIMIAR_PCT:
        itens.append("Favela")
    if contaminada >= LIMIAR_PCT:
        itens.append("Área contaminada")
    if risco >= LIMIAR_PCT:
        itens.append("Risco geológico")
    if duto == duto and duto <= LIMIAR_DUTO_M:
        itens.append("Duto (≤ 30 m)")
    if alta == alta and alta <= LIMIAR_ALTA_M:
        itens.append("Alta tensão (cruza)")
    return " · ".join(itens)
