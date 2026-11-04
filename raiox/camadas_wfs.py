"""Camadas do GeoSampa (WFS ``geoportal:<camada>``) baixadas por quadrado de 3 km, com cache em disco.

Mesma ideia de ``lotes_wfs``: no programa instalado a camada não vem inteira, só os quadrados que o
usuário usa, em ``<pasta de dados>/camadas/<camada>/q_<ix>_<iy>.parquet``. Quadrado sem nenhuma
feição vira um marcador ``q_<ix>_<iy>.vazio`` (assim não baixa de novo). A data do arquivo é a data do
download e serve ao aviso de atualização.

Uma feição que cruza dois quadrados aparece nos dois arquivos; quem lê tira a duplicata
(``dados._tabela_camada_instalada``).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

import pyarrow as pa
import pyarrow.parquet as pq
import shapely
import shapely.geometry

from raiox.lotes_wfs import LADO_M, PAUSA_S, TENTATIVAS, WFS, quadrados_do_bbox  # noqa: F401

PAUSA_CAMADA_S = 0.3  # entre quadrados de camadas (pedidos curtos, de camadas diferentes)
LIMITE_FEICOES = 200_000  # por quadrado; bem acima do que se vê (a mancha de inundação tem ~40 mil)


class CamadaNaoExiste(ValueError):
    """O GeoSampa não tem essa camada."""


def pasta_camada(pasta_dados: Path, camada: str) -> Path:
    return pasta_dados / "camadas" / camada


def caminho_quadrado(pasta_dados: Path, camada: str, ix: int, iy: int) -> Path:
    return pasta_camada(pasta_dados, camada) / f"q_{ix}_{iy}.parquet"


def marcador_vazio(pasta_dados: Path, camada: str, ix: int, iy: int) -> Path:
    return pasta_camada(pasta_dados, camada) / f"q_{ix}_{iy}.vazio"


def quadrado_baixado(pasta_dados: Path, camada: str, ix: int, iy: int) -> bool:
    return (
        caminho_quadrado(pasta_dados, camada, ix, iy).exists()
        or marcador_vazio(pasta_dados, camada, ix, iy).exists()
    )


def _buscar(camada: str, bbox_m: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": f"geoportal:{camada}",
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "count": LIMITE_FEICOES,
        "bbox": "{},{},{},{},EPSG:31983".format(*bbox_m),
    }
    url = WFS + "?" + urllib.parse.urlencode(params)
    ultimo: Exception | None = None
    for tentativa in range(TENTATIVAS):
        try:
            with urllib.request.urlopen(url, timeout=180) as resp:
                corpo = resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404):  # o GeoServer responde 400 a um nome de camada que não existe
                raise CamadaNaoExiste(f"O GeoSampa não tem a camada '{camada}'.") from exc
            ultimo = exc
            time.sleep(PAUSA_S * (tentativa + 1))
            continue
        except Exception as exc:  # rede, timeout
            ultimo = exc
            time.sleep(PAUSA_S * (tentativa + 1))
            continue
        if b"Bloqueada" in corpo or b"rejeitada" in corpo:  # firewall da prefeitura barrando esta camada
            raise CamadaNaoExiste(f"O GeoSampa está bloqueando o acesso à camada '{camada}' neste momento.")
        try:
            return json.loads(corpo)["features"]
        except (ValueError, KeyError) as exc:
            if b"ExceptionReport" in corpo or b"not a valid" in corpo or b"Unknown" in corpo:
                raise CamadaNaoExiste(f"O GeoSampa não tem a camada '{camada}'.") from exc
            ultimo = exc
            time.sleep(PAUSA_S * (tentativa + 1))
    raise ConnectionError(
        f"Não consegui baixar a camada '{camada}' do GeoSampa ({ultimo}). Verifique a conexão com a internet."
    )


def feicao_para_linha(feicao: dict[str, Any]) -> dict[str, Any] | None:
    geom_json = feicao.get("geometry")
    if not geom_json:
        return None
    geom = shapely.geometry.shape(geom_json)
    if geom.is_empty:
        return None
    minx, miny, maxx, maxy = geom.bounds
    linha = dict(feicao.get("properties") or {})
    linha.update(
        geometry_wkt=shapely.to_wkt(geom, rounding_precision=7),
        minx=minx,
        miny=miny,
        maxx=maxx,
        maxy=maxy,
    )
    return linha


def baixar_quadrado(
    pasta_dados: Path,
    camada: str,
    ix: int,
    iy: int,
    buscar: Callable[[str, tuple[float, float, float, float]], list[dict[str, Any]]] | None = None,
) -> Path | None:
    """Baixa a camada num quadrado e grava de forma atômica. Devolve o arquivo (None se não houver feição)."""
    buscar = buscar or _buscar
    bbox_m = (ix * LADO_M, iy * LADO_M, (ix + 1) * LADO_M, (iy + 1) * LADO_M)
    linhas = [l for l in (feicao_para_linha(f) for f in buscar(camada, bbox_m)) if l is not None]
    pasta = pasta_camada(pasta_dados, camada)
    pasta.mkdir(parents=True, exist_ok=True)
    if not linhas:
        marcador = marcador_vazio(pasta_dados, camada, ix, iy)
        marcador.write_text("", encoding="utf-8")
        caminho_quadrado(pasta_dados, camada, ix, iy).unlink(missing_ok=True)  # atualização que esvaziou
        return None
    destino = caminho_quadrado(pasta_dados, camada, ix, iy)
    tmp = destino.with_suffix(".parquet.tmp")
    pq.write_table(pa.Table.from_pylist(linhas), tmp)
    tmp.replace(destino)
    marcador_vazio(pasta_dados, camada, ix, iy).unlink(missing_ok=True)  # agora tem feição
    return destino


def garantir_quadrados(
    pasta_dados: Path,
    camada: str,
    minx: float,
    miny: float,
    maxx: float,
    maxy: float,
    progresso: Callable[[int, int, int], None] | None = None,
) -> int:
    """Baixa os quadrados da camada que faltam para cobrir o bbox (graus). Devolve quantos baixou."""
    faltam = [
        q
        for q in quadrados_do_bbox(minx, miny, maxx, maxy)
        if not quadrado_baixado(pasta_dados, camada, *q)
    ]
    for n, (ix, iy) in enumerate(faltam):
        if progresso:
            progresso(n, len(faltam), 0)  # avisa antes: o download de um quadrado leva alguns segundos
        baixar_quadrado(pasta_dados, camada, ix, iy)
        time.sleep(PAUSA_CAMADA_S)
    return len(faltam)
