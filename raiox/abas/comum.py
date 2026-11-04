"""Parte comum às abas: premissas atuais, terreno em foco, camadas do mapa, área de transferência,
pasta e autoteste.

O comum guarda as premissas e os identificadores do terreno em foco (a SELEÇÃO compartilhada
entre as abas: um lote, uma dupla ou uma trinca). O estado de cada aba (lote aberto, área
prospectada, simulação) continua na aba. Ver ARQUITETURA, "Tela e foco compartilhado".
"""

from __future__ import annotations

import base64
import datetime
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import traceback
from typing import Any, Mapping
import xml.etree.ElementTree as ET
import zipfile

import shapely
import webview

from raiox import atualizacao_dados, camadas, dados, kmz_entrada, oportunidades, zona
from raiox.area_util import area_computavel
from raiox.entorno import TRIAGEM
from raiox.tipos import Premissas

MAX_LOTES_FOCO = 3  # lote, dupla ou trinca (o Prospectar não monta composições de 4)


class ErroUsuario(Exception):
    """Exceção com mensagem em pt-BR para mostrar ao usuário como está."""


CAMPOS_PREMISSAS: tuple[str, ...] = (
    "regime",
    "cota_solidariedade",
    "zeup_ativada",
    "zem_ca4",
    "fator_privativo",
    "area_media_unidade_m2",
    "preco_m2",
    "retiradas",
    "base_vgv",
    "raio_entorno_m",
    "meta_vgv",
    "area_max_lote_m2",
    "limite_esconder_pct",
    "acesso_via_estreita",
    "vila",
    "ticket_unidade",
    "faixa_alta_tensao_m",
    "criterio_meta",
    "area_minima_m2",
    "triagem_esconde",
    "divisa_min_m",
    "mostrar_duplas",
    "mostrar_trincas",
    "multiplicador_ehis_ehmp",
    "limite_divergencia_area_pct",
)

_OPCIONAIS_POSITIVOS = ("fator_privativo", "preco_m2", "ticket_unidade")
_BOOLEANOS = (
    "cota_solidariedade",
    "zeup_ativada",
    "zem_ca4",
    "acesso_via_estreita",
    "vila",
    "mostrar_duplas",
    "mostrar_trincas",
    "multiplicador_ehis_ehmp",
)
_OBRIGATORIOS_POSITIVOS = (
    "area_media_unidade_m2",
    "raio_entorno_m",
    "meta_vgv",
    "area_max_lote_m2",
    "faixa_alta_tensao_m",
    "area_minima_m2",
)
_ROTULOS: dict[str, str] = {
    "fator_privativo": "O fator privativo",
    "preco_m2": "O preço por m²",
    "ticket_unidade": "O ticket da unidade",
    "area_media_unidade_m2": "A área média da unidade",
    "raio_entorno_m": "O raio do entorno",
    "meta_vgv": "A meta de VGV",
    "area_max_lote_m2": "A área máxima do lote",
    "faixa_alta_tensao_m": "A faixa da linha aérea",
    "area_minima_m2": "A área mínima",
}


def _vazio(valor: Any) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


def converter_numero(campo: str, valor: Any) -> float:
    """Converte número vindo da tela (int, float ou texto com vírgula decimal) ou levanta ErroUsuario."""
    mensagem = (
        f"Valor inválido na premissa '{campo}': {valor!r}. Use só números, com vírgula para decimais."
    )
    if isinstance(valor, bool):
        raise ErroUsuario(mensagem)
    if isinstance(valor, (int, float)):
        if not math.isfinite(valor):
            raise ErroUsuario(mensagem)
        return float(valor)
    if isinstance(valor, str):
        texto = valor.strip()
        if re.fullmatch(r"\d+(?:,\d+)?", texto):
            return float(texto.replace(",", "."))
    raise ErroUsuario(mensagem)


def _positivo(campo: str, valor: Any) -> float:
    numero = converter_numero(campo, valor)
    if numero <= 0:
        raise ErroUsuario(f"{_ROTULOS[campo]} deve ser maior que zero.")
    return numero


def premissas_de_dict(dados_entrada: Mapping[str, Any] | None) -> Premissas:
    """Converte o dicionário da tela em Premissas, com validação estrita e mensagens em pt-BR."""
    entrada: Mapping[str, Any] = {} if dados_entrada is None else dados_entrada

    chaves_desconhecidas = sorted(k for k in entrada.keys() if k not in CAMPOS_PREMISSAS)
    if chaves_desconhecidas:
        raise ErroUsuario(f"Premissa desconhecida: {chaves_desconhecidas[0]!r}.")

    kwargs: dict[str, Any] = {}
    for campo in CAMPOS_PREMISSAS:
        if campo not in entrada:
            continue
        v = entrada[campo]

        if campo in _OPCIONAIS_POSITIVOS:
            kwargs[campo] = None if _vazio(v) else _positivo(campo, v)

        elif campo in _BOOLEANOS:
            if _vazio(v):
                raise ErroUsuario(f"Preencha a premissa '{campo}'.")
            if not isinstance(v, bool):
                raise ErroUsuario(f"A premissa '{campo}' deve ser verdadeiro ou falso.")
            kwargs[campo] = v

        elif campo in _OBRIGATORIOS_POSITIVOS:
            if _vazio(v):
                raise ErroUsuario(f"Preencha a premissa '{campo}'.")
            kwargs[campo] = _positivo(campo, v)

        elif campo == "limite_esconder_pct":
            if _vazio(v):
                raise ErroUsuario(f"Preencha a premissa '{campo}'.")
            numero = converter_numero(campo, v)
            # Mesma faixa do controle antigo (app.py:315-319): abaixo de 10% o sinal nem acende.
            if not 10 <= numero <= 100:
                raise ErroUsuario("O limite para esconder deve ficar entre 10% e 100%.")
            kwargs[campo] = numero

        elif campo == "limite_divergencia_area_pct":
            if _vazio(v):
                raise ErroUsuario(f"Preencha a premissa '{campo}'.")
            numero = converter_numero(campo, v)
            if not 0 < numero <= 100:
                raise ErroUsuario(
                    "O limite de diferença entre a área do cadastro e a do desenho deve ficar entre 0% e 100%."
                )
            kwargs[campo] = numero

        elif campo == "divisa_min_m":
            if _vazio(v):
                raise ErroUsuario(f"Preencha a premissa '{campo}'.")
            numero = converter_numero(campo, v)
            # Mesma faixa do controle antigo (app.py:361-365); 0 = basta encostar.
            if not 0 <= numero <= 60:
                raise ErroUsuario("A divisa mínima entre lotes deve ficar entre 0 e 60 m.")
            kwargs[campo] = numero

        elif campo == "criterio_meta":
            if not isinstance(v, str) or v not in ("vgv", "area"):
                raise ErroUsuario(
                    f"Valor inválido na premissa 'criterio_meta': {v!r}. Opções: vgv, area."
                )
            kwargs[campo] = v

        elif campo == "triagem_esconde":
            if not isinstance(v, (list, tuple)):
                raise ErroUsuario("A premissa 'triagem_esconde' deve ser uma lista de camadas.")
            for item in v:
                if not isinstance(item, str) or item not in TRIAGEM:
                    raise ErroUsuario(f"Camada de triagem desconhecida: {item!r}.")
            kwargs[campo] = tuple(k for k in TRIAGEM if k in v)

        elif campo == "regime":
            if _vazio(v):
                raise ErroUsuario(f"Preencha a premissa '{campo}'.")
            if not isinstance(v, str) or v not in ("R2V_LIVRE", "EHMP", "EHIS"):
                raise ErroUsuario(
                    f"Valor inválido na premissa 'regime': {v!r}. Opções: R2V_LIVRE, EHMP, EHIS."
                )
            kwargs[campo] = v

        elif campo == "base_vgv":
            if _vazio(v):
                raise ErroUsuario(f"Preencha a premissa '{campo}'.")
            if not isinstance(v, str) or v not in ("referencia_ca", "liquida"):
                raise ErroUsuario(
                    f"Valor inválido na premissa 'base_vgv': {v!r}. Opções: referencia_ca, liquida."
                )
            kwargs[campo] = v

        elif campo == "retiradas":
            if not isinstance(v, (list, tuple)):
                raise ErroUsuario("A premissa 'retiradas' deve ser uma lista de camadas.")
            regras_validas = {r.id for r in camadas.regras_com_uso("retirar")}
            # premissas salvas antes da aposentadoria da camada "app" continuam abrindo
            v = [item for item in v if item != "app"]
            for item in v:
                if not isinstance(item, str) or item not in regras_validas:
                    raise ErroUsuario(f"Camada de retirada desconhecida: {item!r}.")
            kwargs[campo] = tuple(v)

    return Premissas(**kwargs)


def premissas_para_dict(premissas: Premissas) -> dict[str, Any]:
    """Serializa Premissas num dicionário JSON com todos os campos de premissas."""
    saida: dict[str, Any] = {}
    for campo in CAMPOS_PREMISSAS:
        valor = getattr(premissas, campo)
        saida[campo] = list(valor) if campo in ("retiradas", "triagem_esconde") else valor
    return saida


def poligonos_do_kmz(nome: str, conteudo_base64: str) -> list[str]:
    """Lê o KMZ/KML enviado pela tela (base64) e devolve os polígonos em WKT, com erros em pt-BR."""
    if not isinstance(conteudo_base64, str) or not conteudo_base64.strip():
        raise ErroUsuario("Arquivo KMZ/KML vazio ou não fornecido.")
    try:
        conteudo = base64.b64decode(conteudo_base64, validate=True)
    except ValueError as exc:  # binascii.Error (base64 ruim) e texto com caractere fora do ASCII
        raise ErroUsuario("Conteúdo do arquivo KMZ/KML inválido.") from exc

    sufixo = ".kmz" if nome.lower().endswith(".kmz") else ".kml"
    with tempfile.TemporaryDirectory(prefix="raiox_kmz_") as pasta:
        caminho = Path(pasta) / f"entrada{sufixo}"
        caminho.write_bytes(conteudo)
        try:
            poligonos = kmz_entrada.ler(caminho)
        except zipfile.BadZipFile as exc:
            raise ErroUsuario(
                f"“{nome}” não abre como KMZ (o arquivo não é um zip válido). "
                "Exporte de novo pelo Google Earth."
            ) from exc
        except ET.ParseError as exc:
            raise ErroUsuario(
                f"“{nome}” tem o conteúdo KML quebrado (XML inválido). Exporte de novo pelo Google Earth."
            ) from exc

    if not poligonos:
        raise ErroUsuario("Nenhum polígono encontrado no arquivo KMZ/KML.")
    return poligonos


def aviso_varios_poligonos(poligonos: list[str]) -> list[str]:
    """Aviso explícito quando o arquivo traz mais de um polígono e só o primeiro é usado."""
    if len(poligonos) <= 1:
        return []
    return [f"O arquivo tem {len(poligonos)} polígonos; usei só o primeiro."]


class Comum:
    """Estado e funções compartilhados: premissas atuais, pastas, camadas e autoteste."""

    nome = "comum"

    def __init__(self, autoteste: bool, pasta_saida: Path | None, pasta_config: Path | None) -> None:
        self.trava = threading.Lock()
        self._autoteste = autoteste
        self._pasta_saida_fixa = pasta_saida
        self._pasta_config_fixa = pasta_config
        self._window: webview.Window | None = None
        self._premissas = Premissas()
        self._trava_premissas = threading.Lock()
        self._trava_mapa = threading.Lock()
        self._foco: tuple[str, ...] | None = None
        self._download: dict[str, Any] = {}
        dados.definir_aviso_download(self._registrar_download)

    def set_window(self, window: webview.Window) -> None:
        self._window = window

    # --- Premissas atuais (as exportações e os recálculos usam sempre estas) ---

    @property
    def premissas(self) -> Premissas:
        with self._trava_premissas:
            return self._premissas

    def definir_premissas(self, dados_entrada: Mapping[str, Any]) -> Premissas:
        """Valida as premissas vindas da tela e passa a usá-las como as atuais."""
        if not isinstance(dados_entrada, Mapping):
            raise ErroUsuario("As premissas precisam vir como um conjunto de campos.")
        p = premissas_de_dict(dados_entrada)
        with self._trava_premissas:
            self._premissas = p
        return p

    # --- Pastas e log ---

    def pasta_saida(self) -> Path:
        if self._pasta_saida_fixa is not None:
            caminho = self._pasta_saida_fixa
        else:
            caminho = Path(os.environ.get("USERPROFILE") or Path.home()) / "Downloads" / "RaioX"
        caminho.mkdir(parents=True, exist_ok=True)
        return caminho

    def pasta_config(self) -> Path:
        if self._pasta_config_fixa is not None:
            caminho = self._pasta_config_fixa
        else:
            base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
            caminho = base / "RaioX"
        caminho.mkdir(parents=True, exist_ok=True)
        return caminho

    def caminho_log(self) -> Path:
        return self.pasta_config() / "raiox.log"

    def registrar_erro(self, aba: str, acao: str, exc: BaseException) -> None:
        """Acrescenta o erro e o traceback ao log; levanta OSError se não conseguir gravar."""
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        linhas_tb = "".join(traceback.format_exception(exc))
        with open(self.caminho_log(), "a", encoding="utf-8") as f:
            f.write(f"{ts} [{aba}] {acao}: {type(exc).__name__}: {exc}\n{linhas_tb}\n")

    # --- Métodos expostos pela fachada ---

    def ler_premissas(self) -> dict[str, Any]:
        """Lê as premissas salvas (ou as padrão, se nunca salvou) e passa a usá-las como as atuais."""
        caminho = self.pasta_config() / "premissas.json"
        if not caminho.exists():
            p = Premissas()
        else:
            try:
                with open(caminho, "r", encoding="utf-8") as f:
                    dados_lidos = json.load(f)
            except json.JSONDecodeError as exc:
                raise ErroUsuario(f"O arquivo de premissas salvas não é válido: {caminho}.") from exc
            if not isinstance(dados_lidos, dict):
                raise ErroUsuario(f"O arquivo de premissas salvas não é válido: {caminho}.")
            p = premissas_de_dict(dados_lidos)
        with self._trava_premissas:
            self._premissas = p
        return {"premissas": premissas_para_dict(p)}

    def salvar_premissas(self, dados_entrada: Mapping[str, Any]) -> dict[str, Any]:
        """Valida, grava em disco e passa a usar as premissas como as atuais."""
        p = self.definir_premissas(dados_entrada)
        caminho = self.pasta_config() / "premissas.json"
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(premissas_para_dict(p), f, ensure_ascii=False, indent=2)
        return {"premissas": premissas_para_dict(p)}

    # --- Terreno em foco (a seleção compartilhada pelas abas) ---

    def _descrever_foco(self, ids: tuple[str, ...], p: Premissas) -> dict[str, Any]:
        """Barra do foco: SQL, endereço, área do cadastro, zona e CA (o mesmo do Raio-X do lote)."""
        achados = dados.lotes_por_ids(list(ids))
        faltando = [i for i in ids if i not in achados]
        if faltando:
            raise ErroUsuario(f"Identificador {faltando[0]} não encontrado na base de lotes.")
        lotes = [achados[i] for i in ids]
        zonas: list[str] = []
        cas: list[float] = []
        for lote in lotes:
            sigla = zona.zonas_do_lote(lote)[0][0]
            ca, _, _ = zona.ca_do_lote(sigla, lote.area_terreno_m2, p)
            zonas.append(sigla)
            cas.append(ca)
        area = sum(l.area_terreno_m2 for l in lotes)
        computavel = sum(area_computavel(l.area_terreno_m2, ca) for l, ca in zip(lotes, cas))
        geometrias = [shapely.from_wkt(l.geometria_wkt) for l in lotes]
        ponto = geometrias[0].representative_point()  # dentro do 1º lote: centro do círculo e do clique
        return {
            "ids": list(ids),
            "tipo": {1: "lote", 2: "dupla", 3: "trinca"}[len(ids)],
            "sql": " + ".join(oportunidades.sql_formatado(l) for l in lotes),
            "endereco": " + ".join(oportunidades.endereco(l) for l in lotes),
            "area_m2": area,
            "zonas": zonas,
            "zona": " + ".join(dict.fromkeys(zonas)),
            # Composição: CA = Σ computável ÷ Σ área (como o simulador e a view "gleba" do antigo).
            "ca": round(computavel / area, 2) if area > 0 else 0.0,
            "lotes": [
                {"cd_identificador": l.cd_identificador, "setor": l.setor, "quadra": l.quadra} for l in lotes
            ],
            "ponto": [ponto.y, ponto.x],  # [lat, lon]
            "geojson": {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "geometry": g.__geo_interface__, "properties": {"cd_identificador": l.cd_identificador}}
                    for l, g in zip(lotes, geometrias)
                ],
            },
        }

    def definir_foco(self, ids: Any, p: Premissas) -> dict[str, Any]:
        """Põe em foco um lote, uma dupla ou uma trinca (identificadores cadastrais)."""
        if (
            not isinstance(ids, (list, tuple))
            or not 1 <= len(ids) <= MAX_LOTES_FOCO
            or any(not isinstance(i, str) or not i.strip() for i in ids)
        ):
            raise ErroUsuario("O terreno em foco precisa de 1 a 3 identificadores de lote.")
        limpos = tuple(i.strip() for i in ids)
        if len(set(limpos)) != len(limpos):
            raise ErroUsuario("O mesmo lote apareceu duas vezes no terreno em foco.")
        descricao = self._descrever_foco(limpos, p)
        self._foco = limpos
        return {"foco": descricao}

    def foco_atual(self) -> dict[str, Any]:
        """O terreno em foco descrito com as premissas atuais (None se não há foco)."""
        if self._foco is None:
            return {"foco": None}
        return {"foco": self._descrever_foco(self._foco, self.premissas)}

    def limpar_foco(self) -> dict[str, Any]:
        self._foco = None
        return {"foco": None}

    def lista_camadas(self) -> dict[str, Any]:
        """Metadados das camadas (para ver no mapa e para retirar do lote)."""
        return {
            "camadas": [
                {"id": r.id, "rotulo": r.rotulo, "usos": sorted(r.usos), "faixa_m": r.faixa_m}
                for r in camadas.REGRAS
            ]
        }

    def camadas_mapa(self, bbox: list[float], ids: list[str], zoom: int) -> dict[str, Any]:
        """Feições GeoJSON das camadas ligadas dentro do retângulo do mapa."""
        if (
            not isinstance(bbox, (list, tuple))
            or len(bbox) != 4
            or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in bbox
            )
        ):
            raise ErroUsuario("O retângulo do mapa precisa de 4 números.")
        if not isinstance(ids, (list, tuple)):
            raise ErroUsuario("A lista de camadas é inválida.")
        regras_ids = {r.id for r in camadas.REGRAS}
        for camada_id in ids:
            if not isinstance(camada_id, str) or camada_id not in regras_ids:
                raise ErroUsuario(f"Camada desconhecida: {camada_id!r}.")
        if isinstance(zoom, bool) or not isinstance(zoom, int):
            raise ErroUsuario("O zoom precisa ser um número inteiro.")

        from raiox import mapa

        return {"camadas": mapa.camadas_geojson(tuple(float(v) for v in bbox), list(ids), zoom)}

    def copiar_texto(self, texto: str) -> dict[str, Any]:
        """Copia o texto para a área de transferência do Windows (clip.exe, UTF-16-LE)."""
        if not isinstance(texto, str):
            raise ErroUsuario("Não há texto para copiar.")
        subprocess.run(
            ["clip.exe"],
            input=texto.encode("utf-16-le"),
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return {}

    def abrir_pasta_saida(self) -> dict[str, Any]:
        """Abre a pasta onde ficam as exportações no Explorer."""
        caminho = self.pasta_saida()
        os.startfile(caminho)
        return {"caminho": str(caminho)}

    def modo(self) -> dict[str, Any]:
        """Informa se a janela foi aberta em modo de autoteste e se é o programa instalado."""
        try:
            instalado = dados.modo_instalado()
        except FileNotFoundError:
            instalado = False
        return {"autoteste": self._autoteste, "instalado": instalado}

    # --- Dados baixados do GeoSampa (modo instalado) ---

    def _registrar_download(self, rotulo: str, n: int, total: int, qtd: int) -> None:
        self._download = {"rotulo": rotulo, "n": n + 1, "total": total, "qtd": qtd, "quando": time.time()}

    def estado_download(self) -> dict[str, Any]:
        """Download em andamento (sem trava: a tela consulta enquanto outra chamada espera o download)."""
        d = dict(self._download)
        ativo = bool(d) and time.time() - d["quando"] < 8.0
        return {"ativo": ativo, **({k: v for k, v in d.items() if k != "quando"} if ativo else {})}

    def dados_estado(self) -> dict[str, Any]:
        """Quantos quadrados baixados já passaram de 30 dias (para o aviso de atualização)."""
        if not dados.modo_instalado():
            return {"instalado": False, "antigos": 0, "total": 0}
        return {"instalado": True, **atualizacao_dados.situacao(dados.pasta_dados())}

    def dados_atualizar(self) -> dict[str, Any]:
        """Baixa de novo, a pedido do usuário, o que passou de 30 dias."""
        n = atualizacao_dados.atualizar(dados.pasta_dados(), self._registrar_download)
        dados.limpar_caches()
        return {"atualizados": n}

    def registrar_autoteste(self, resultado: Mapping[str, Any]) -> dict[str, Any]:
        """Grava o resultado do autoteste em %TEMP%\\raiox_autoteste.json e fecha a janela no autoteste."""
        arquivo = Path(tempfile.gettempdir()) / "raiox_autoteste.json"
        with open(arquivo, "w", encoding="utf-8") as f:
            json.dump(dict(resultado), f, ensure_ascii=False, indent=2)

        if self._autoteste and self._window is not None:
            janela = self._window
            timer = threading.Timer(0.3, janela.destroy)
            timer.daemon = True
            timer.start()
        return {"arquivo": str(arquivo)}
