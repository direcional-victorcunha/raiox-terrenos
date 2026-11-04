"""Módulo de leitura e classificação de arquivos KMZ/KML e cálculo de lotes cobertos."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import pyproj
import shapely

from raiox import dados
from raiox.tipos import LoteCadastro

LIMITE_AREA_TERRENO_M2: float = 50_000.0  # Limite máximo de lote individual (mesmo valor de Premissas.area_max_lote_m2, ARQUITETURA §6)
LIMIAR_COBERTURA_PCT: float = 50.0  # Porcentagem mínima de cobertura da área do lote para ser selecionado

_PARA_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:31983", always_xy=True)
_PARA_WGS = pyproj.Transformer.from_crs("EPSG:31983", "EPSG:4326", always_xy=True)


def _reprojetar(geom: shapely.Geometry, tf: pyproj.Transformer) -> shapely.Geometry:
    """Reprojeta uma geometria shapely usando o transformer fornecido."""
    return shapely.transform(
        geom, lambda c: np.column_stack(tf.transform(c[:, 0], c[:, 1]))
    )


def _tag(elem: ET.Element) -> str:
    """Retorna o nome da tag XML sem prefixo de namespace."""
    return elem.tag.split("}")[-1]


def _coords(texto: str | None) -> list[tuple[float, float]]:
    """Extrai lista de coordenadas (lon, lat) a partir do texto KML."""
    if not texto:
        return []
    pontos: list[tuple[float, float]] = []
    for token in texto.strip().split():
        partes = token.split(",")
        if len(partes) >= 2:
            try:
                lon = float(partes[0])
                lat = float(partes[1])
                pontos.append((lon, lat))
            except ValueError:
                continue
    if len(pontos) >= 3 and pontos[0] != pontos[-1]:
        pontos.append(pontos[0])
    return pontos


def _extrair_poligono(elem: ET.Element) -> shapely.Geometry | None:
    """Extrai uma geometria de polígono a partir de um elemento <Polygon> KML."""
    casca: list[tuple[float, float]] = []
    for f in elem:
        if _tag(f) == "outerBoundaryIs":
            for lr in f:
                if _tag(lr) == "LinearRing":
                    for coord_elem in lr:
                        if _tag(coord_elem) == "coordinates":
                            casca = _coords(coord_elem.text)
                            break
                    break
            break

    if len(casca) < 4:
        return None

    buracos: list[list[tuple[float, float]]] = []
    for f in elem:
        if _tag(f) == "innerBoundaryIs":
            for lr in f:
                if _tag(lr) == "LinearRing":
                    for coord_elem in lr:
                        if _tag(coord_elem) == "coordinates":
                            coords_buraco = _coords(coord_elem.text)
                            if len(coords_buraco) >= 4:
                                buracos.append(coords_buraco)
                            break
                    break

    p = shapely.Polygon(casca, holes=buracos)
    valido = shapely.make_valid(p)
    if valido.is_empty:
        return None
    return valido


def ler(caminho: str | Path) -> list[str]:
    """Lê um arquivo KMZ ou KML e retorna a lista de geometrias de polígonos em WKT WGS84."""
    caminho_path = Path(caminho)
    if not caminho_path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")

    if str(caminho_path).lower().endswith(".kmz") or zipfile.is_zipfile(caminho_path):
        with zipfile.ZipFile(caminho_path, "r") as zf:
            nomes = zf.namelist()
            nome_kml: str | None = None
            for n in nomes:
                if n.lower() == "doc.kml" or n.lower().endswith("/doc.kml"):
                    nome_kml = n
                    break
            if nome_kml is None:
                for n in nomes:
                    if n.lower().endswith(".kml"):
                        nome_kml = n
                        break
            if nome_kml is None:
                return []
            conteudo_bytes = zf.read(nome_kml)
    else:
        conteudo_bytes = caminho_path.read_bytes()

    raiz = ET.fromstring(conteudo_bytes)

    poligonos_em_mg: set[ET.Element] = set()
    geometrias_resultado: list[shapely.Geometry] = []

    for elem in raiz.iter():
        if _tag(elem) == "MultiGeometry":
            polys: list[shapely.Polygon] = []
            for sub in elem.iter():
                if sub is not elem and _tag(sub) == "Polygon":
                    poligonos_em_mg.add(sub)
                    geom = _extrair_poligono(sub)
                    if geom is not None and not geom.is_empty:
                        if isinstance(geom, shapely.Polygon):
                            polys.append(geom)
                        elif isinstance(geom, shapely.MultiPolygon):
                            polys.extend(geom.geoms)
            if polys:
                if len(polys) == 1:
                    mg = polys[0]
                else:
                    mg = shapely.multipolygons(polys)
                mg = shapely.make_valid(mg)
                if not mg.is_empty:
                    geometrias_resultado.append(mg)

    for elem in raiz.iter():
        if _tag(elem) == "Polygon" and elem not in poligonos_em_mg:
            geom = _extrair_poligono(elem)
            if geom is not None and not geom.is_empty:
                geometrias_resultado.append(geom)

    return [g.wkt for g in geometrias_resultado]


def classificar(wkt: str) -> str:
    """Classifica a geometria WKT em 'terreno' (<= 50.000 m²) ou 'regiao' (> 50.000 m²)."""
    try:
        geom = shapely.from_wkt(wkt)
    except shapely.errors.GEOSException as exc:
        raise ValueError(f"Geometria WKT vazia ou inválida: {exc}") from exc

    if geom is None:
        raise ValueError("Geometria WKT vazia ou inválida.")

    geom = shapely.make_valid(geom)
    if geom.is_empty:
        raise ValueError("Geometria WKT vazia ou inválida.")

    geom_utm = _reprojetar(geom, _PARA_UTM)
    area_m2 = float(geom_utm.area)

    if area_m2 <= LIMITE_AREA_TERRENO_M2:
        return "terreno"
    return "regiao"


def lotes_cobertos(wkt: str) -> list[LoteCadastro]:
    """Retorna lotes cadastrais cobertos (>= 50% da área do lote dentro do polígono WKT),

    ordenados pela área coberta em EPSG:31983 decrescente.
    """
    if not wkt or not wkt.strip():
        return []

    geom = shapely.from_wkt(wkt)
    if geom is None:
        return []

    geom = shapely.make_valid(geom)
    if geom.is_empty:
        return []

    minx, miny, maxx, maxy = tuple(float(v) for v in shapely.bounds(geom))
    geom_utm = _reprojetar(geom, _PARA_UTM)

    candidatos = dados.lotes_no_bbox((minx, miny, maxx, maxy))
    resultados: list[tuple[LoteCadastro, float]] = []

    for lote in candidatos:
        if not lote.geometria_wkt:
            continue
        lote_geom = shapely.make_valid(shapely.from_wkt(lote.geometria_wkt))
        if lote_geom.is_empty or not geom.intersects(lote_geom):
            continue

        lote_utm = _reprojetar(lote_geom, _PARA_UTM)
        area_lote_m2 = float(lote_utm.area)
        if area_lote_m2 <= 0.0:
            continue

        inter_utm = geom_utm.intersection(lote_utm)
        area_coberta_m2 = float(inter_utm.area)
        pct_coberta = (area_coberta_m2 / area_lote_m2) * 100.0
        # Também vale o polígono desenhado DENTRO de um lote grande (o polígono fica coberto pelo lote)
        pct_do_poligono = (area_coberta_m2 / float(geom_utm.area)) * 100.0 if geom_utm.area > 0 else 0.0

        if pct_coberta >= LIMIAR_COBERTURA_PCT or pct_do_poligono >= LIMIAR_COBERTURA_PCT:
            resultados.append((lote, area_coberta_m2))

    resultados.sort(key=lambda item: item[1], reverse=True)
    return [item[0] for item in resultados]
