"""Onde ficam as coisas do Raio-X, no PC de desenvolvimento e no PC instalado.

Instalado em Arquivos de Programas, a pasta do programa é só leitura para o usuário comum:
nada que o app grava pode ficar lá. Regra:

- programa (código, tela, vendor): ao lado deste arquivo, somente leitura;
- dados baixados e cache: ``%LOCALAPPDATA%\\Raio-X\\dados`` (fora do Git e fora do programa);
- configuração, regiões salvas e log: ``%APPDATA%\\RaioX`` (ver ``abas/comum.py``);
- arquivos gerados (Excel, KMZ, CSV): ``Downloads\\RaioX`` (ver ``abas/comum.py``).

No PC de desenvolvimento a pasta ``data/`` ao lado do projeto continua valendo, para nada mudar.
"""
from __future__ import annotations

import os
from pathlib import Path

NOME_PASTA_USUARIO = "Raio-X"


def pasta_programa() -> Path:
    """Raiz do projeto/programa (a pasta que contém ``raiox/``). Tratar como somente leitura."""
    return Path(__file__).resolve().parent.parent


def pasta_dados_usuario() -> Path:
    """Pasta de dados baixados do usuário: ``%LOCALAPPDATA%\\Raio-X\\dados``."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / NOME_PASTA_USUARIO / "dados"


def pasta_dados_padrao() -> Path:
    """Ordem: ``RAIOX_DADOS`` > ``data/`` do projeto, se já existir (PC de desenvolvimento) > pasta do usuário."""
    env = os.environ.get("RAIOX_DADOS")
    if env:
        return Path(env)
    local = pasta_programa() / "data"
    if local.is_dir():
        return local
    return pasta_dados_usuario()
