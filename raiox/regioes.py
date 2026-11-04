"""Regiões de prospecção salvas em disco (KMZ de região), para reabrir sem soltar o arquivo.

Ficam na pasta de dados do usuário, ao lado das premissas: %APPDATA%\\RaioX\\regioes\\<id>.json,
um arquivo por região com o nome, o polígono (WKT, WGS84), a área em km², o arquivo de origem e
a data. Como no app antigo (ui/nova_area.py), o nome vem do arquivo e um nome repetido substitui
a região anterior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import datetime
import json
from pathlib import Path
import re
import unicodedata

import numpy as np
import pyproj
import shapely

_PARA_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:31983", always_xy=True)

# Acima disto o antigo pedia confirmação (core/regiao_builder.py:31, LIMITE_KM2_AVISO = 30.0)
LIMITE_KM2_AVISO = 30.0


@dataclass(frozen=True)
class RegiaoSalva:
    id: str
    nome: str
    wkt: str
    area_km2: float
    origem: str
    salva_em: str


def area_km2(wkt: str) -> float:
    """Área do polígono WGS84 em km², medida em EPSG:31983."""
    geom = shapely.from_wkt(wkt)
    utm = shapely.transform(geom, lambda c: np.column_stack(_PARA_UTM.transform(c[:, 0], c[:, 1])))
    return float(shapely.area(utm)) / 1_000_000.0


def identificador(nome: str) -> str:
    """Nome -> id de arquivo (sem acento, minúsculo, hífens)."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    ident = re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")
    if not ident:
        raise ValueError(f"O nome {nome!r} não serve para salvar a região: use letras ou números.")
    return ident


def _pasta(pasta_config: Path) -> Path:
    pasta = pasta_config / "regioes"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _ler(caminho: Path) -> RegiaoSalva:
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
        return RegiaoSalva(**dados)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"O arquivo da região salva não é válido: {caminho}.") from exc


def listar(pasta_config: Path) -> list[RegiaoSalva]:
    """Regiões salvas, em ordem de nome."""
    regioes = [_ler(c) for c in sorted(_pasta(pasta_config).glob("*.json"))]
    return sorted(regioes, key=lambda r: r.nome.lower())


def salvar(pasta_config: Path, nome: str, wkt: str, origem: str) -> tuple[RegiaoSalva, bool]:
    """Grava a região; devolve (região, True se substituiu uma de mesmo nome)."""
    ident = identificador(nome)
    caminho = _pasta(pasta_config) / f"{ident}.json"
    substituiu = caminho.exists()
    regiao = RegiaoSalva(
        id=ident,
        nome=nome,
        wkt=wkt,
        area_km2=area_km2(wkt),
        origem=origem,
        salva_em=datetime.datetime.now().isoformat(timespec="seconds"),
    )
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(asdict(regiao), f, ensure_ascii=False)
    return regiao, substituiu


def abrir(pasta_config: Path, ident: str) -> RegiaoSalva:
    caminho = _pasta(pasta_config) / f"{identificador(ident)}.json"
    if not caminho.exists():
        raise ValueError(f"A região salva '{ident}' não existe mais (foi excluída?).")
    return _ler(caminho)


def excluir(pasta_config: Path, ident: str) -> None:
    caminho = _pasta(pasta_config) / f"{identificador(ident)}.json"
    if not caminho.exists():
        raise ValueError(f"A região salva '{ident}' não existe.")
    caminho.unlink()
