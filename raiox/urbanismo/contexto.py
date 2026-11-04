# Cópia congelada de prospeccao-marechal-tito/core/contexto.py em 2026-10-28.
"""
Contexto de cada lote a partir de camadas oficiais do GeoSampa (fatos, não julgamento):
sobreposição com áreas públicas/parques, favelas, áreas contaminadas e risco geológico, e
distância em linha reta até a estação de metrô/trem mais próxima.

Funções puras (sem rede).
Geometrias em metros (EPSG:31983).
"""

import numpy as np
import shapely


def para_utm(geoms_wgs84, transformer):
    """Reprojeta um array de geometrias WGS84 -> metros com um pyproj Transformer(always_xy)."""

    def _f(coords):
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    return shapely.transform(np.asarray(geoms_wgs84, dtype=object), _f)


def pct_sobreposicao(lotes, camada) -> np.ndarray:
    """% da área de cada lote coberta pela união das geometrias da camada (0–100).
    A união evita contar duas vezes onde feições da mesma camada se sobrepõem."""
    lotes = shapely.make_valid(np.asarray(lotes, dtype=object))
    saida = np.zeros(len(lotes))
    camada = [g for g in camada if g is not None and not g.is_empty]
    if not camada:
        return saida
    uniao = shapely.union_all(shapely.make_valid(np.asarray(camada, dtype=object)))
    idx = shapely.STRtree(lotes).query(uniao, predicate="intersects")
    if len(idx):
        inter = shapely.intersection(lotes[idx], uniao)
        saida[idx] = 100.0 * shapely.area(inter) / shapely.area(lotes[idx])
    return np.clip(saida, 0.0, 100.0)


def estacao_mais_proxima(lotes, estacoes, nomes):
    """Distância (m, em linha reta) e nome da estação mais próxima de cada lote.
    Mede do ponto representativo do lote, que está sempre dentro dele."""
    lotes = np.asarray(lotes, dtype=object)
    pontos = shapely.point_on_surface(lotes)
    if len(estacoes) == 0:
        return np.full(len(lotes), np.nan), np.array([""] * len(lotes), dtype=object)
    arvore = shapely.STRtree(np.asarray(estacoes, dtype=object))
    pares, dist = arvore.query_nearest(pontos, return_distance=True, all_matches=False)
    d = np.full(len(lotes), np.nan)
    n = np.array([""] * len(lotes), dtype=object)
    d[pares[0]] = dist
    n[pares[0]] = [nomes[i] for i in pares[1]]
    return d, n


def distancia_ate(lotes, linhas, max_m=1000.0) -> np.ndarray:
    """Distância (m) de cada lote até a feição mais próxima (0 se tocar); NaN se estiver a
    mais de max_m. Serve para linhas (dutos, alta tensão) ou qualquer camada."""
    lotes = np.asarray(lotes, dtype=object)
    saida = np.full(len(lotes), np.nan)
    linhas = [g for g in linhas if g is not None and not g.is_empty]
    if not linhas:
        return saida
    arvore = shapely.STRtree(np.asarray(linhas, dtype=object))
    pares, dist = arvore.query_nearest(
        lotes, max_distance=max_m, return_distance=True, all_matches=False
    )
    saida[pares[0]] = dist
    return saida


LIMIAR_PCT = 10.0  # sobreposição mínima (% do lote) para acender um sinal
LIMIAR_DUTO_M = 30.0  # distância máxima (m) até duto da Transpetro para acender o sinal
LIMIAR_ALTA_M = 1.0  # linha de alta tensão que cruza o lote (tolerância de 1 m)
