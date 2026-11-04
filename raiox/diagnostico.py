"""Diagnóstico sem janela: baixa uma área pequena do GeoSampa e confere se o programa lê tudo.

Roda por ``Raio-X.exe --diagnostico``. Grava ``%TEMP%\raiox_diagnostico.json`` (o exe não tem console).
Serve para conferir o programa empacotado e, num PC de colega, se o download e a leitura funcionam.
"""
from __future__ import annotations

import json
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

from raiox import caminhos, dados, mapa

# ~300 m na Av. Marechal Tito: lotes, zoneamento (perimetro_zona) e água
_BBOX = (-46.4300, -23.5300, -46.4270, -23.5270)
_PASSOS = (
    ("lotes", lambda: len(dados.lotes_no_bbox(_BBOX))),
    ("zoneamento", lambda: len(dados.feicoes("perimetro_zona_lei_18177_24", _BBOX))),
    ("agua", lambda: len(dados.feicoes("massa_d_agua", _BBOX))),
    ("mancha_inundacao", lambda: len(mapa._mancha_inundacao_dissolvida(_BBOX, 14, "x")[0])),
)


def rodar() -> dict[str, Any]:
    resultado: dict[str, Any] = {
        "modo_instalado": dados.modo_instalado(),
        "pasta_dados": str(dados.pasta_dados()),
        "passos": {},
        "ok": True,
    }
    for nome, funcao in _PASSOS:
        t = time.time()
        try:
            resultado["passos"][nome] = {"itens": funcao(), "segundos": round(time.time() - t, 1)}
        except Exception as exc:  # o diagnóstico registra e segue
            resultado["ok"] = False
            resultado["passos"][nome] = {"erro": f"{type(exc).__name__}: {exc}", "detalhe": traceback.format_exc()[-600:]}
    return resultado


def main() -> None:
    resultado = rodar()
    arquivo = Path(tempfile.gettempdir()) / "raiox_diagnostico.json"
    arquivo.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
