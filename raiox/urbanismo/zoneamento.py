# Cópia congelada de prospeccao-marechal-tito/core/zoneamento.py em 2026-10-28.
"""
Cruzamento lote × zoneamento e CA máximo por lote (fonte única, usada pelo
data_loader e pelo scripts/preparar_parquet.py).

Regra de segurança (ver SPEC): zona fora do Quadro 3 (ZEPAM, ZOE, praças...) ou lote sem
zona NÃO recebe CA padrão. ca_maximo = 0 -> o lote sai de VGV e composições.
"""

import numpy as np
import shapely

from raiox.urbanismo.ca_engine import ZEIS_LOTE_PEQUENO, ZONAS

SEM_ZONA = "SEM_ZONA"


def ca_max_para_lote(zona: str, area_m2: float) -> float:
    """CA máximo do Quadro 3 da LPUOS; 0.0 se a zona não está na tabela."""
    if zona not in ZONAS:
        return 0.0
    ca = ZONAS[zona]["ca_max"]
    if zona in ZEIS_LOTE_PEQUENO:
        limite, ca_pequeno = ZEIS_LOTE_PEQUENO[zona]
        if area_m2 < limite:
            ca = ca_pequeno
    return float(ca)


def atribuir_zonas(lotes_geoms, zonas_geoms, zonas_siglas) -> list[str]:
    """Zona de cada lote = zona que CONTÉM o ponto representativo do lote
    (representative_point garante ponto dentro do polígono, ao contrário do centroide).
    Se houver sobreposição de zonas, vale a primeira da lista."""
    tree = shapely.STRtree(list(zonas_geoms))
    pontos = np.array([g.representative_point() for g in lotes_geoms], dtype=object)
    idx_lote, idx_zona = tree.query(pontos, predicate="within")
    resultado = [SEM_ZONA] * len(pontos)
    # query devolve pares ordenados por lote; mantém a 1ª zona de cada um
    for i, z in zip(idx_lote[::-1], idx_zona[::-1]):
        resultado[i] = zonas_siglas[z] or SEM_ZONA
    return resultado


def ca_cenario(
    zonas,
    areas,
    regime: str = "R2V_LIVRE",
    cota_solidariedade: bool = False,
    zeup_ativada: bool = False,
    zem_ca4: bool = False,
    mult: dict | None = None,
):
    """CA teto de cada lote no cenário escolhido, vindo de ca_engine.limites_ca (mesma regra do
    simulador). zonas/areas: pandas Series alinhadas. Zona fora do Quadro 3 -> 0.

    `mult` só repassa o multiplicador por regime a limites_ca (None = MULT_PRODUTO, como antes);
    é o único acréscimo à cópia congelada (Raio-X, 29/10: premissa do multiplicador de EHIS/EHMP).

    Premissa embutida: acesso de veículos por via > 10 m (Lei 18.081 art. 3º, III); o
    rebaixamento por via estreita depende do projeto e não é aplicado por lote.
    MULT_PRODUTO de EHIS/EHMP é inferência na SPEC (confirmar no Dec. 63.728).
    """
    import pandas as pd

    from raiox.urbanismo.ca_engine import Lote, limites_ca

    zeup = {"ZEUP": "ZEU", "ZEUPa": "ZEUa"}
    z = zonas.map(lambda s: zeup.get(s, s)) if zeup_ativada else zonas
    pequeno = pd.Series(False, index=zonas.index)
    for zona, (limite, _) in ZEIS_LOTE_PEQUENO.items():
        pequeno |= (z == zona) & (areas < limite)

    lote = Lote(sql="", area_m2=0.0, zona_base="", mapa_base="L18081", zem_ca4=zem_ca4)
    out = pd.Series(0.0, index=zonas.index)
    for zona, peq in set(zip(z, pequeno)):
        if zona not in ZONAS:
            continue  # CA 0: fora do Quadro 3
        area_rep = 1.0 if peq else 1e9  # só decide a regra de "lote pequeno" da ZEIS
        ca = limites_ca(zona, area_rep, regime, lote, cota_solidariedade, mult=mult).ca_teto
        out[(z == zona) & (pequeno == peq)] = ca
    return out
