from __future__ import annotations

from dataclasses import dataclass
import difflib
import math

import numpy as np
import pyproj
import shapely

from raiox import dados
from raiox.busca import _extrair_numero_e_logradouro, normalizar_logradouro

_PARA_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:31983", always_xy=True)
_PARA_WGS = pyproj.Transformer.from_crs("EPSG:31983", "EPSG:4326", always_xy=True)


def _reprojetar_para_utm(geom: shapely.Geometry) -> shapely.Geometry:
    return shapely.transform(geom, lambda c: np.column_stack(_PARA_UTM.transform(c[:, 0], c[:, 1])))


def _reprojetar_para_wgs(geom: shapely.Geometry) -> shapely.Geometry:
    return shapely.transform(geom, lambda c: np.column_stack(_PARA_WGS.transform(c[:, 0], c[:, 1])))


@dataclass(frozen=True)
class Faixa:
    logradouro: str
    largura_m: float
    wkt_wgs84: str
    area_km2: float
    n_lotes_eixo: int
    avisos: list[str]


def logradouros_parecidos(texto: str, limite: int = 10) -> list[str]:
    """Sugere nomes válidos de logradouro da base quando o usuário digitar um nome inexistente ou incompleto."""
    if not texto or not texto.strip() or limite <= 0:
        return []
    termo = _extrair_numero_e_logradouro(texto)[0].strip()
    if not termo:
        termo = normalizar_logradouro(texto).strip()
    unicos = dados.logradouros_unicos()
    por_substring = [x for x in unicos if termo in x]
    por_diff = difflib.get_close_matches(termo, unicos, n=limite, cutoff=0.5)
    resultado: list[str] = []
    for item in por_substring + por_diff:
        if item not in resultado:
            resultado.append(item)
            if len(resultado) == limite:
                break
    return resultado


def faixa_ao_longo_da_rua(texto_logradouro: str, largura_m: float = 1500.0) -> Faixa:
    """Gera a faixa de prospecção (buffer métrico) ao longo dos lotes de um logradouro."""
    if not texto_logradouro or not texto_logradouro.strip():
        raise ValueError("Logradouro não informado.")
    if not math.isfinite(largura_m) or largura_m <= 0 or largura_m > 5000.0:
        raise ValueError(
            f"Largura da faixa deve ser maior que zero e até 5.000 metros (informado: {largura_m} m)."
        )

    nome_abreviado = _extrair_numero_e_logradouro(texto_logradouro)[0]
    lotes = dados.lotes_por_logradouro(nome_abreviado)
    logradouro_resolvido = nome_abreviado

    if not lotes:
        nome_norm = normalizar_logradouro(texto_logradouro)
        lotes = dados.lotes_por_logradouro(nome_norm)
        logradouro_resolvido = nome_norm

    if not lotes:
        sugestoes = logradouros_parecidos(texto_logradouro, limite=5)
        if sugestoes:
            raise ValueError(
                f"Logradouro '{texto_logradouro}' não encontrado na base. Sugestões: {', '.join(sugestoes)}."
            )
        raise ValueError(
            f"Logradouro '{texto_logradouro}' não encontrado na base (não encontrado na base não quer dizer que não existe)."
        )

    geoms: list[shapely.Geometry] = []
    for lote in lotes:
        if lote.geometria_wkt and lote.geometria_wkt.strip():
            g = shapely.from_wkt(lote.geometria_wkt)
            if not g.is_empty:
                if not g.is_valid:
                    g = shapely.make_valid(g)
                geoms.append(g)

    if not geoms:
        raise ValueError(f"Nenhum lote com geometria válida encontrado para '{texto_logradouro}'.")

    n_lotes_eixo = len(geoms)
    uniao_lotes = shapely.unary_union(geoms)
    uniao_utm = _reprojetar_para_utm(uniao_lotes)
    buffer_utm = uniao_utm.buffer(float(largura_m))
    if not buffer_utm.is_valid:
        buffer_utm = shapely.make_valid(buffer_utm)

    area_km2 = round(float(buffer_utm.area) / 1_000_000.0, 2)
    buffer_wgs = _reprojetar_para_wgs(buffer_utm)
    wkt_wgs84 = buffer_wgs.wkt

    avisos: list[str] = []
    if hasattr(buffer_utm, "geoms") and len(buffer_utm.geoms) > 1:
        avisos.append(
            f"Logradouro com {len(buffer_utm.geoms)} trechos desconectados; todos foram unidos na faixa."
        )
    if area_km2 > 100.0:
        avisos.append("Área grande (acima de 100 km²): o cálculo do entorno pode demorar.")

    return Faixa(
        logradouro=logradouro_resolvido,
        largura_m=float(largura_m),
        wkt_wgs84=wkt_wgs84,
        area_km2=area_km2,
        n_lotes_eixo=n_lotes_eixo,
        avisos=avisos,
    )
