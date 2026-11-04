"""Lotes baixados do GeoSampa (WFS ``geoportal:lote_cidadao``) por quadrado de 3 km, com cache em disco.

Substitui o ``lotes.parquet`` da cidade inteira no programa instalado: o quadrado é baixado na hora
do uso e guardado em ``<pasta de dados>/lotes/q_<ix>_<iy>.parquet``. O esquema de saída é o mesmo do
``lotes.parquet`` (ver ``scripts/montar_pacote_dados.py``), então o resto do app não muda.

Cortesia com o servidor da prefeitura: uma página por vez, pausa de 1 s entre páginas.
"""
from __future__ import annotations

import json
import math
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

import pyarrow as pa
import pyarrow.parquet as pq
import shapely
import shapely.geometry
from pyproj import Transformer

from raiox.busca import normalizar_logradouro

WFS = "http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/wfs"
CAMADA = "geoportal:lote_cidadao"
LADO_M = 3000  # lado do quadrado, em metros (EPSG:31983)
POR_PAGINA = 2000
PAUSA_S = 1.0
TENTATIVAS = 3

_PARA_UTM = Transformer.from_crs(4326, 31983, always_xy=True)

ESQUEMA = pa.schema(
    [
        ("cd_identificador", pa.int64()),
        ("sql", pa.string()),
        ("setor", pa.string()),
        ("quadra", pa.string()),
        ("lote", pa.string()),
        ("digito", pa.string()),
        ("cd_condominio", pa.string()),
        ("nm_logradouro_completo", pa.string()),
        ("logradouro_norm", pa.string()),
        ("cd_numero_porta", pa.string()),
        ("numero", pa.int64()),
        ("qt_area_terreno", pa.float64()),
        ("qt_area_construida", pa.float64()),
        ("dc_tipo_uso_imovel", pa.string()),
        ("tx_situ_lote", pa.string()),
        ("geometry_wkt", pa.string()),
        ("minx", pa.float64()),
        ("miny", pa.float64()),
        ("maxx", pa.float64()),
        ("maxy", pa.float64()),
    ]
)


def pasta_lotes(pasta_dados: Path) -> Path:
    return pasta_dados / "lotes"


def quadrados_do_bbox(minx: float, miny: float, maxx: float, maxy: float) -> list[tuple[int, int]]:
    """Quadrados (ix, iy) de 3 km que cobrem um bbox em graus (WGS84)."""
    x0, y0 = _PARA_UTM.transform(minx, miny)
    x1, y1 = _PARA_UTM.transform(maxx, maxy)
    ix0, ix1 = math.floor(min(x0, x1) / LADO_M), math.floor(max(x0, x1) / LADO_M)
    iy0, iy1 = math.floor(min(y0, y1) / LADO_M), math.floor(max(y0, y1) / LADO_M)
    return [(ix, iy) for ix in range(ix0, ix1 + 1) for iy in range(iy0, iy1 + 1)]


def caminho_quadrado(pasta_dados: Path, ix: int, iy: int) -> Path:
    return pasta_lotes(pasta_dados) / f"q_{ix}_{iy}.parquet"


def _texto(valor: Any) -> str | None:
    return None if valor is None else str(valor)


def _numero(valor: Any) -> int | None:
    """Primeiro número do texto da porta ("49 53" vira 49), como no ``lotes.parquet``."""
    achado = re.search(r"\d+", "" if valor is None else str(valor))
    return int(achado.group()) if achado else None


def _flutuante(valor: Any) -> float | None:
    return None if valor is None else float(valor)


def feicao_para_linha(feicao: dict[str, Any]) -> dict[str, Any] | None:
    """Uma feição do WFS (saída em EPSG:4326) vira uma linha no esquema do ``lotes.parquet``."""
    props = feicao.get("properties") or {}
    geom_json = feicao.get("geometry")
    if not geom_json or props.get("cd_identificador") is None:
        return None
    geom = shapely.geometry.shape(geom_json)
    if geom.is_empty:
        return None
    setor = _texto(props.get("cd_setor_fiscal")) or ""
    quadra = _texto(props.get("cd_quadra_fiscal")) or ""
    lote = _texto(props.get("cd_lote")) or ""
    digito = _texto(props.get("cd_digito_sql")) or ""
    logradouro = _texto(props.get("nm_logradouro_completo"))
    porta = _texto(props.get("cd_numero_porta"))
    minx, miny, maxx, maxy = geom.bounds
    return {
        "cd_identificador": int(props["cd_identificador"]),
        "sql": setor + quadra + lote + digito,
        "setor": setor,
        "quadra": quadra,
        "lote": lote,
        "digito": digito,
        "cd_condominio": _texto(props.get("cd_condominio")),
        "nm_logradouro_completo": logradouro,
        "logradouro_norm": normalizar_logradouro(logradouro or ""),
        "cd_numero_porta": porta,
        "numero": _numero(porta),
        "qt_area_terreno": _flutuante(props.get("qt_area_terreno")),
        "qt_area_construida": _flutuante(props.get("qt_area_construida")),
        "dc_tipo_uso_imovel": _texto(props.get("dc_tipo_uso_imovel")),
        "tx_situ_lote": _texto(props.get("tx_situ_lote")),
        "geometry_wkt": shapely.to_wkt(geom, rounding_precision=7),
        "minx": minx,
        "miny": miny,
        "maxx": maxx,
        "maxy": maxy,
    }


def _pagina(bbox_m: tuple[float, float, float, float], inicio: int) -> list[dict[str, Any]]:
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": CAMADA,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "count": POR_PAGINA,
        "startIndex": inicio,
        "sortBy": "cd_identificador",
        "bbox": "{},{},{},{},EPSG:31983".format(*bbox_m),
    }
    url = WFS + "?" + urllib.parse.urlencode(params)
    ultimo: Exception | None = None
    for tentativa in range(TENTATIVAS):
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                return json.loads(resp.read())["features"]
        except Exception as exc:  # rede, timeout, JSON truncado
            ultimo = exc
            time.sleep(PAUSA_S * (tentativa + 1))
    raise ConnectionError(
        f"Não consegui baixar os lotes do GeoSampa ({ultimo}). Verifique a conexão com a internet."
    )


def quadrado_do_centro(linha: dict[str, Any]) -> tuple[int, int]:
    """Quadrado (ix, iy) que contém o centro do lote; cada lote pertence a um só quadrado."""
    x, y = _PARA_UTM.transform((linha["minx"] + linha["maxx"]) / 2, (linha["miny"] + linha["maxy"]) / 2)
    return math.floor(x / LADO_M), math.floor(y / LADO_M)


def baixar_quadrado(
    pasta_dados: Path,
    ix: int,
    iy: int,
    progresso: Callable[[int], None] | None = None,
    pagina: Callable[[tuple[float, float, float, float], int], list[dict[str, Any]]] | None = None,
) -> Path:
    """Baixa um quadrado, grava o parquet de forma atômica e devolve o caminho.

    O WFS devolve os lotes que cruzam o quadrado; ficam só os de centro dentro dele, para que um lote
    de divisa não apareça em dois arquivos.
    """
    pagina = pagina or _pagina
    bbox_m = (ix * LADO_M, iy * LADO_M, (ix + 1) * LADO_M, (iy + 1) * LADO_M)
    linhas: dict[int, dict[str, Any]] = {}
    inicio = 0
    while True:
        feicoes = pagina(bbox_m, inicio)
        for f in feicoes:
            linha = feicao_para_linha(f)
            if linha is not None and quadrado_do_centro(linha) == (ix, iy):
                linhas[linha["cd_identificador"]] = linha
        if progresso:
            progresso(len(linhas))
        if len(feicoes) < POR_PAGINA:
            break
        inicio += POR_PAGINA
        time.sleep(PAUSA_S)
    destino = caminho_quadrado(pasta_dados, ix, iy)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tabela = pa.Table.from_pylist(list(linhas.values()), schema=ESQUEMA)
    tmp = destino.with_suffix(".parquet.tmp")
    pq.write_table(tabela, tmp)
    tmp.replace(destino)
    return destino


def garantir_quadrados(
    pasta_dados: Path,
    minx: float,
    miny: float,
    maxx: float,
    maxy: float,
    progresso: Callable[[int, int, int], None] | None = None,
) -> list[Path]:
    """Garante em disco os quadrados que cobrem o bbox (graus); baixa os que faltam.

    ``progresso(feito, total, lotes_no_quadrado)`` é chamado a cada página baixada.
    """
    alvo = quadrados_do_bbox(minx, miny, maxx, maxy)
    caminhos: list[Path] = []
    for n, (ix, iy) in enumerate(alvo):
        caminho = caminho_quadrado(pasta_dados, ix, iy)
        if not caminho.exists():
            cb = (lambda lotes, n=n: progresso(n, len(alvo), lotes)) if progresso else None
            baixar_quadrado(pasta_dados, ix, iy, cb)
        caminhos.append(caminho)
    return caminhos
