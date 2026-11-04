"""Atualização do programa pelo GitHub: avisa quando há versão nova e, se o usuário aceitar, troca os arquivos.

O repositório publica ``versao.json`` (na raiz, branch main) com ``{"versao", "url", "notas"}``; ``url`` é o zip
do Release. Só funciona no programa empacotado (``Raio-X.exe``), nunca no PC de desenvolvimento, e só troca os
arquivos se a pasta do programa for gravável pelo usuário (sem administrador, em Arquivos de Programas não é:
nesse caso o aviso manda abrir a página de download). Nada é baixado sem o usuário pedir.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

from raiox import caminhos
from raiox.versao import VERSAO

REPOSITORIO = "direcional-victorcunha/raiox-terrenos"
URL_MANIFESTO = f"https://raw.githubusercontent.com/{REPOSITORIO}/main/versao.json"
URL_PAGINA = f"https://github.com/{REPOSITORIO}/releases/latest"


def empacotado() -> bool:
    return bool(getattr(sys, "frozen", False))


def _numeros(versao: str) -> tuple[int, ...]:
    return tuple(int(p) for p in versao.strip().lstrip("v").split("."))


def e_mais_nova(candidata: str, atual: str = VERSAO) -> bool:
    try:
        return _numeros(candidata) > _numeros(atual)
    except ValueError:
        return False


def _baixar_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def verificar(buscar: Callable[[str], dict[str, Any]] = _baixar_json, forcar: bool = False) -> dict[str, Any] | None:
    """Versão nova disponível ({versao, url, notas, pode_trocar}) ou None. Qualquer falha de rede vira None."""
    if not empacotado() and not forcar:
        return None
    try:
        info = buscar(URL_MANIFESTO)
        if not e_mais_nova(str(info["versao"])):
            return None
        return {
            "versao": str(info["versao"]),
            "url": str(info["url"]),
            "notas": str(info.get("notas", "")),
            "pode_trocar": pode_trocar(),
            "pagina": URL_PAGINA,
        }
    except Exception:  # sem internet, arquivo ausente, JSON ruim: o aviso é opcional
        return None


def pasta_instalacao() -> Path:
    return Path(sys.executable).resolve().parent if empacotado() else caminhos.pasta_programa()


def pode_trocar() -> bool:
    return empacotado() and os.access(pasta_instalacao(), os.W_OK)


def baixar(info: dict[str, Any], pasta_base: Path | None = None) -> Path:
    """Baixa e extrai a versão nova numa pasta de trabalho do usuário. Devolve a pasta ``Raio-X`` extraída."""
    base = (pasta_base or caminhos.pasta_dados_usuario().parent) / "atualizacao"
    base.mkdir(parents=True, exist_ok=True)
    zip_local = base / "novo.zip"
    urllib.request.urlretrieve(info["url"], zip_local)  # noqa: S310 (https do próprio repositório)
    destino = base / "novo"
    if destino.exists():
        import shutil

        shutil.rmtree(destino)
    with zipfile.ZipFile(zip_local) as z:
        z.extractall(destino)
    zip_local.unlink(missing_ok=True)
    nova = destino / "Raio-X"
    if not (nova / "Raio-X.exe").exists():
        raise ValueError("O arquivo baixado não é um Raio-X válido.")
    return nova


def aplicar(nova: Path, instalacao: Path | None = None, executavel: str = "Raio-X.exe") -> Path:
    """Cria o script que espera o programa fechar, copia a versão nova por cima e abre de novo."""
    instalacao = instalacao or pasta_instalacao()
    bat = nova.parent / "trocar.bat"
    bat.write_text(
        "\r\n".join(
            [
                "@echo off",
                "timeout /t 2 /nobreak >nul",
                ":esperar",
                f'tasklist /FI "IMAGENAME eq {executavel}" 2>nul | find /I "{executavel}" >nul',
                "if not errorlevel 1 (timeout /t 1 /nobreak >nul & goto esperar)",
                f'robocopy "{nova}" "{instalacao}" /E /NFL /NDL /NJH /NJS /NP >nul',
                f'start "" "{instalacao}\\{executavel}"',
                "cd /d %TEMP%",
                f'(goto) 2>nul & rmdir /s /q "{nova.parent}"',  # o .bat se apaga junto com a pasta de trabalho
                "",
            ]
        ),
        encoding="ascii",
    )
    return bat


def iniciar_troca(bat: Path) -> None:
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=flags, close_fds=True)  # noqa: S603,S607
