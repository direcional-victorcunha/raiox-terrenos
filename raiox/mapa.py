from __future__ import annotations

from collections.abc import Sequence
from typing import Any
import numpy as np
import shapely

from raiox import camadas, dados
from raiox.tipos import LoteCadastro

_LIMITE_FEICOES_MAPA = 2500
_PASSO_GRADE_INUNDACAO = 0.00025  # ~25 m em EPSG:4326: dissolve pixels 5x5 m contíguos


def tolerancia_zoom(zoom: int) -> float:
    """Retorna tolerância de simplificação em graus (EPSG:4326) segundo o nível de zoom."""
    if zoom >= 17:
        return 0.0
    if zoom == 16:
        return 0.00002
    if zoom == 15:
        return 0.00005
    if zoom == 14:
        return 0.00010
    if zoom == 13:
        return 0.00020
    return 0.00050


def _mancha_inundacao_dissolvida(
    bbox: tuple[float, float, float, float], zoom: int, rotulo: str
) -> tuple[list[dict[str, Any]], bool] | None:
    """Dissolve em grade rápida a mancha_inundacao_100 quando tem muitos pixels 5x5 m no bbox."""
    try:
        cache = dados._obter_cache_camada("mancha_inundacao_100", bbox)
    except dados.CamadaAusente:
        return None
    if not cache.tem_bbox or cache.minx is None or cache.miny is None or cache.maxx is None or cache.maxy is None:
        return None
    minx, miny, maxx, maxy = bbox
    mask = (cache.minx <= maxx) & (cache.maxx >= minx) & (cache.miny <= maxy) & (cache.maxy >= miny)
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        return [], False
    if len(idx) <= 600 and zoom >= 17:
        return None  # poucos pixels em zoom alto: usa a leitura normal com atributos

    passo = _PASSO_GRADE_INUNDACAO if zoom <= 15 else _PASSO_GRADE_INUNDACAO * 0.5
    gx = np.floor(cache.minx[idx] / passo).astype(np.int64)
    gy = np.floor(cache.miny[idx] / passo).astype(np.int64)
    chaves = (gx << 32) | (gy & 0xFFFFFFFF)
    unicas = np.unique(chaves)
    truncado = len(unicas) > 6000
    if truncado:
        unicas = unicas[:6000]
    ux = (unicas >> 32).astype(np.float64)
    uy = unicas.astype(np.int32).astype(np.float64)
    caixas = shapely.box(ux * passo, uy * passo, (ux + 1.02) * passo, (uy + 1.02) * passo)
    uniao = shapely.simplify(shapely.union_all(caixas), passo * 0.35, preserve_topology=True)
    if uniao is None or uniao.is_empty:
        return [], False
    return [
        {
            "type": "Feature",
            "geometry": uniao.__geo_interface__,
            "properties": {
                "camada": "inundacao",
                "rotulo": rotulo,
                "qt_tempo_retorno": 100,
                "celulas_agrupadas": int(len(idx)),
            },
        }
    ], truncado


def lote_geojson(lote: LoteCadastro) -> dict[str, Any]:
    """Devolve GeoJSON FeatureCollection do lote para destaque no mapa."""
    geom = shapely.from_wkt(lote.geometria_wkt)
    geo_interface = geom.__geo_interface__ if geom is not None and not geom.is_empty else None

    feature = {
        "type": "Feature",
        "geometry": geo_interface,
        "properties": {
            "cd_identificador": lote.cd_identificador,
            "sql": lote.sql,
            "logradouro": lote.logradouro,
            "numero_porta": lote.numero_porta,
            "area": lote.area_terreno_m2,
        },
    }
    return {
        "type": "FeatureCollection",
        "features": [feature],
    }


def camadas_geojson(
    bbox: tuple[float, float, float, float] | Sequence[float],
    ids: Sequence[str],
    zoom: int,
) -> dict[str, dict[str, Any]]:
    """Recorta camadas geográficas por bbox e devolve dicionário {id_camada: FeatureCollection}."""
    bbox_tuple = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    tol = tolerancia_zoom(zoom)
    resultado: dict[str, dict[str, Any]] = {}

    for camada_id in ids:
        if camada_id == "lotes":
            lotes = dados.lotes_no_bbox(bbox_tuple, limite=20001)
            truncado = len(lotes) > 20000
            if truncado:
                lotes = lotes[:20000]

            features: list[dict[str, Any]] = []
            for lote in lotes:
                geom = shapely.from_wkt(lote.geometria_wkt)
                if geom is None or geom.is_empty:
                    continue
                if tol > 0.0:
                    s_geom = shapely.simplify(geom, tol, preserve_topology=True)
                    if not s_geom.is_empty:
                        geom = s_geom

                features.append({
                    "type": "Feature",
                    "geometry": geom.__geo_interface__,
                    "properties": {
                        "camada": "lotes",
                        "rotulo": "Lotes",
                        "cd_identificador": lote.cd_identificador,
                        "sql": lote.sql,
                        "logradouro": lote.logradouro,
                        "numero_porta": lote.numero_porta,
                        "area": lote.area_terreno_m2,
                    },
                })

            resultado["lotes"] = {
                "type": "FeatureCollection",
                "features": features,
                "truncado": truncado,
            }
        else:
            try:
                reg = camadas.regra(camada_id)
            except KeyError:
                continue

            if "ver" not in reg.usos:
                continue

            feicoes_todas = []
            features = []
            truncado = False
            for subcamada in reg.camadas_banco:
                if subcamada == "mancha_inundacao_100":
                    dissolvida = _mancha_inundacao_dissolvida(bbox_tuple, zoom, reg.rotulo)
                    if dissolvida is not None:
                        feats_diss, trunc_diss = dissolvida
                        features.extend(feats_diss)
                        truncado = truncado or trunc_diss
                        continue
                feicoes_sub = dados.feicoes(subcamada, bbox_tuple, margem_m=0.0)
                feicoes_todas.extend(feicoes_sub)
                if len(feicoes_todas) > _LIMITE_FEICOES_MAPA:
                    break

            if len(feicoes_todas) > _LIMITE_FEICOES_MAPA:
                truncado = True
                feicoes_todas = feicoes_todas[:_LIMITE_FEICOES_MAPA]

            for feicao in feicoes_todas:
                geom = shapely.from_wkt(feicao.geometria_wkt)
                if geom is None or geom.is_empty:
                    continue
                if tol > 0.0:
                    s_geom = shapely.simplify(geom, tol, preserve_topology=True)
                    if not s_geom.is_empty:
                        geom = s_geom

                props: dict[str, Any] = {
                    "camada": camada_id,
                    "rotulo": reg.rotulo,
                }

                added = 0
                for med in reg.atributo_medida:
                    if med in feicao.atributos and feicao.atributos[med] is not None:
                        props[med] = feicao.atributos[med]
                        added += 1

                for k, v in feicao.atributos.items():
                    if added >= 4:
                        break
                    if k not in props and v is not None:
                        props[k] = v
                        added += 1

                features.append({
                    "type": "Feature",
                    "geometry": geom.__geo_interface__,
                    "properties": props,
                })

            resultado[camada_id] = {
                "type": "FeatureCollection",
                "features": features,
                "truncado": truncado,
            }

    return resultado
