"""Dados baixados com mais de 30 dias: o app avisa e, se o usuário pedir, baixa de novo.

Nada é atualizado sozinho. Cada quadrado é baixado de volta por cima do antigo de forma atômica:
se a rede cair no meio, o arquivo antigo continua valendo.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

from raiox import camadas_wfs, lotes_wfs

DIAS_PARA_ATUALIZAR = 30
_QUADRADO = re.compile(r"^q_(-?\d+)_(-?\d+)\.(parquet|vazio)$")


def _quadrados_baixados(pasta: Path) -> list[tuple[str | None, int, int, Path]]:
    """(camada ou None para lotes, ix, iy, arquivo) de tudo que há em disco."""
    achados: list[tuple[str | None, int, int, Path]] = []
    pastas: list[tuple[str | None, Path]] = [(None, lotes_wfs.pasta_lotes(pasta))]
    camadas = pasta / "camadas"
    if camadas.is_dir():
        pastas += [(d.name, d) for d in sorted(camadas.iterdir()) if d.is_dir()]
    for camada, d in pastas:
        if not d.is_dir():
            continue
        for arq in d.iterdir():
            m = _QUADRADO.match(arq.name)
            if m:
                achados.append((camada, int(m.group(1)), int(m.group(2)), arq))
    return achados


def situacao(pasta: Path, dias: int = DIAS_PARA_ATUALIZAR, agora: float | None = None) -> dict[str, Any]:
    agora = time.time() if agora is None else agora
    limite = dias * 86400
    total = antigos = 0
    mais_antigo = 0.0
    for _, _, _, arq in _quadrados_baixados(pasta):
        idade = agora - arq.stat().st_mtime
        total += 1
        mais_antigo = max(mais_antigo, idade)
        if idade > limite:
            antigos += 1
    return {"total": total, "antigos": antigos, "mais_antigo_dias": int(mais_antigo // 86400), "dias_limite": dias}


def atualizar(
    pasta: Path,
    progresso: Callable[[str, int, int, int], None] | None = None,
    dias: int = DIAS_PARA_ATUALIZAR,
    agora: float | None = None,
) -> int:
    """Baixa de novo os quadrados com mais de ``dias`` dias. Devolve quantos atualizou."""
    agora = time.time() if agora is None else agora
    velhos = [q for q in _quadrados_baixados(pasta) if agora - q[3].stat().st_mtime > dias * 86400]
    for n, (camada, ix, iy, _) in enumerate(velhos):
        if progresso:
            progresso(camada or "lotes", n, len(velhos), 0)
        if camada is None:
            lotes_wfs.baixar_quadrado(pasta, ix, iy)
        else:
            camadas_wfs.baixar_quadrado(pasta, camada, ix, iy)
        time.sleep(lotes_wfs.PAUSA_S)
    return len(velhos)
