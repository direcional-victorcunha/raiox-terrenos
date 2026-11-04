"""Fachada JS-Python exposta ao pywebview no aplicativo Raio-X de Terrenos SP.

A classe `Api` não tem regra de negócio: cada método chama a aba dona da ação dentro do
envelope `_executar`, que devolve `{"ok": True, ...}` ou, em qualquer exceção,
`{"ok": False, "erro": <mensagem pt-BR>, "aba": <nome>}` e grava o traceback no log.
Assim um erro numa aba nunca derruba a janela nem as outras abas. Ver ARQUITETURA, "Abas isoladas".
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import threading
from typing import Any, Callable, Mapping, Protocol

import webview

from raiox.abas.comum import Comum, ErroUsuario
from raiox.abas.lote import AbaLote
from raiox.abas.prospectar import AbaProspectar
from raiox.abas.simulador import AbaSimulador


class _Aba(Protocol):
    nome: str
    trava: threading.Lock


class Api:
    """Fachada fina: um método por ação da tela, cada um delegando para a sua aba."""

    def __init__(
        self,
        autoteste: bool = False,
        pasta_saida: Path | None = None,
        pasta_config: Path | None = None,
    ) -> None:
        self._comum = Comum(autoteste, pasta_saida, pasta_config)
        self._lote = AbaLote(self._comum)
        self._prospectar = AbaProspectar(self._comum)
        self._simulador = AbaSimulador(self._comum)

    def set_window(self, window: webview.Window) -> None:
        self._comum.set_window(window)

    # --- Envelope único ---

    def _executar(
        self,
        aba: _Aba,
        acao: str,
        funcao: Callable[[], dict[str, Any]],
        trava: threading.Lock | None = None,
    ) -> dict[str, Any]:
        """`trava` troca a trava da aba (o mapa não pode segurar as ações de foco e premissas)."""
        try:
            with trava or aba.trava:
                retorno = funcao()
        except ErroUsuario as exc:
            return {"ok": False, "erro": f"{exc}{self._registrar(aba, acao, exc)}", "aba": aba.nome}
        except Exception as exc:  # envelope: nenhum erro de uma aba pode derrubar a janela
            sufixo = self._registrar(aba, acao, exc)
            mensagem = (
                f"Não consegui {acao}: erro interno ({type(exc).__name__}: {exc}). "
                f"Detalhes no log: {self._comum.caminho_log()}{sufixo}"
            )
            return {"ok": False, "erro": mensagem, "aba": aba.nome}
        return {"ok": True, **retorno}

    def _registrar(self, aba: _Aba, acao: str, exc: BaseException) -> str:
        """Grava o erro no log; devolve o sufixo da mensagem se o log não puder ser gravado."""
        try:
            self._comum.registrar_erro(aba.nome, acao, exc)
        except OSError:
            return " (não consegui gravar o log)"
        return ""

    # --- Comum ---

    def ler_premissas(self) -> dict[str, Any]:
        return self._executar(self._comum, "ler as premissas", self._comum.ler_premissas)

    def salvar_premissas(self, premissas: Mapping[str, Any]) -> dict[str, Any]:
        return self._executar(
            self._comum, "salvar as premissas", lambda: self._comum.salvar_premissas(premissas)
        )

    def foco_definir(self, ids: list[str], premissas: Mapping[str, Any]) -> dict[str, Any]:
        return self._executar(
            self._comum,
            "pôr o terreno em foco",
            lambda: self._comum.definir_foco(ids, self._comum.definir_premissas(premissas)),
        )

    def foco_atual(self) -> dict[str, Any]:
        return self._executar(self._comum, "ler o terreno em foco", self._comum.foco_atual)

    def foco_limpar(self) -> dict[str, Any]:
        return self._executar(self._comum, "tirar o terreno do foco", self._comum.limpar_foco)

    def lista_camadas(self) -> dict[str, Any]:
        return self._executar(self._comum, "listar as camadas", self._comum.lista_camadas)

    def camadas_mapa(self, bbox: list[float], ids: list[str], zoom: int) -> dict[str, Any]:
        return self._executar(
            self._comum,
            "carregar as camadas do mapa",
            lambda: self._comum.camadas_mapa(bbox, ids, zoom),
            trava=self._comum._trava_mapa,
        )

    def copiar_texto(self, texto: str) -> dict[str, Any]:
        return self._executar(self._comum, "copiar o texto", lambda: self._comum.copiar_texto(texto))

    def abrir_pasta_saida(self) -> dict[str, Any]:
        return self._executar(self._comum, "abrir a pasta de saída", self._comum.abrir_pasta_saida)

    def estado_download(self) -> dict[str, Any]:
        try:
            return {"ok": True, **self._comum.estado_download()}
        except Exception:  # só alimenta a faixa de progresso; nunca atrapalha a tela
            return {"ok": True, "ativo": False}

    def dados_estado(self) -> dict[str, Any]:
        return self._executar(self._comum, "ver a idade dos dados", self._comum.dados_estado)

    def dados_atualizar(self) -> dict[str, Any]:
        return self._executar(
            self._comum, "atualizar os dados", self._comum.dados_atualizar, trava=self._comum._trava_mapa
        )

    def modo(self) -> dict[str, Any]:
        return self._executar(self._comum, "ler o modo da janela", self._comum.modo)

    def registrar_autoteste(self, resultado: Mapping[str, Any]) -> dict[str, Any]:
        return self._executar(
            self._comum, "gravar o autoteste", lambda: self._comum.registrar_autoteste(resultado)
        )

    # --- Aba Raio-X do lote ---

    def lote_consultar(self, texto: str, premissas: Mapping[str, Any]) -> dict[str, Any]:
        return self._executar(
            self._lote,
            "consultar o lote",
            lambda: self._lote.consultar(texto, self._comum.definir_premissas(premissas)),
        )

    def lote_escolher(self, cd_identificador: str, premissas: Mapping[str, Any]) -> dict[str, Any]:
        return self._executar(
            self._lote,
            "abrir o lote escolhido",
            lambda: self._lote.escolher(cd_identificador, self._comum.definir_premissas(premissas)),
        )

    def lote_carregar_kmz(
        self, nome: str, conteudo_base64: str, premissas: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._executar(
            self._lote,
            "carregar o KMZ do terreno",
            lambda: self._lote.carregar_kmz(
                nome, conteudo_base64, self._comum.definir_premissas(premissas)
            ),
        )

    def lote_recalcular(self, premissas: Mapping[str, Any]) -> dict[str, Any]:
        return self._executar(
            self._lote,
            "recalcular o lote com as premissas novas",
            lambda: self._lote.recalcular(self._comum.definir_premissas(premissas)),
        )

    def lote_croqui(self) -> dict[str, Any]:
        return self._executar(self._lote, "gerar o croqui", self._lote.croqui)

    def lote_copiar_resumo(self) -> dict[str, Any]:
        return self._executar(self._lote, "gerar o resumo", self._lote.copiar_resumo)

    def lote_exportar_excel(self) -> dict[str, Any]:
        return self._executar(self._lote, "exportar o Excel", self._lote.exportar_excel)

    def lote_exportar_kmz(self) -> dict[str, Any]:
        return self._executar(self._lote, "exportar o KMZ", self._lote.exportar_kmz)

    # --- Aba Prospectar ---

    def prospectar_opcoes(self) -> dict[str, Any]:
        return self._executar(self._prospectar, "ler as opções do Prospectar", self._prospectar.opcoes)

    def prospectar_buscar_centro(self, texto: str) -> dict[str, Any]:
        return self._executar(
            self._prospectar, "achar o lote central", lambda: self._prospectar.buscar_centro(texto)
        )

    def prospectar_escolher_centro(self, cd_identificador: str) -> dict[str, Any]:
        return self._executar(
            self._prospectar,
            "usar o lote como centro",
            lambda: self._prospectar.escolher_centro(cd_identificador),
        )

    def prospectar_lote_no_ponto(self, lon: float | int | str, lat: float | int | str) -> dict[str, Any]:
        return self._executar(
            self._prospectar, "achar o lote clicado", lambda: self._prospectar.lote_no_ponto(lon, lat)
        )

    def prospectar_entorno(self, raio_m: float | int | str, premissas: Mapping[str, Any]) -> dict[str, Any]:
        return self._executar(
            self._prospectar,
            "calcular o entorno",
            lambda: self._prospectar.entorno(raio_m, self._comum.definir_premissas(premissas)),
        )

    def prospectar_carregar_kmz(
        self, nome: str, conteudo_base64: str, premissas: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._executar(
            self._prospectar,
            "carregar o KMZ da região",
            lambda: self._prospectar.carregar_kmz(
                nome, conteudo_base64, self._comum.definir_premissas(premissas)
            ),
        )

    def prospectar_recalcular(self, premissas: Mapping[str, Any]) -> dict[str, Any]:
        return self._executar(
            self._prospectar,
            "recalcular o entorno com as premissas novas",
            lambda: self._prospectar.recalcular(self._comum.definir_premissas(premissas)),
        )

    def prospectar_ponto(
        self,
        lon: float | int | str,
        lat: float | int | str,
        raio_m: float | int | str,
        premissas: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._executar(
            self._prospectar,
            "calcular o círculo do ponto marcado",
            lambda: self._prospectar.ponto(lon, lat, raio_m, self._comum.definir_premissas(premissas)),
        )

    def prospectar_desenho(
        self, vertices: list[list[float]], nome: str | None, premissas: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._executar(
            self._prospectar,
            "calcular a área desenhada",
            lambda: self._prospectar.desenho(vertices, nome, self._comum.definir_premissas(premissas)),
        )

    def prospectar_faixa(
        self, texto: str, largura_m: float | int | str, premissas: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._executar(
            self._prospectar,
            "calcular a faixa ao longo da rua",
            lambda: self._prospectar.faixa(texto, largura_m, self._comum.definir_premissas(premissas)),
        )

    def prospectar_faixa_marechal_tito(self, premissas: Mapping[str, Any]) -> dict[str, Any]:
        return self._executar(
            self._prospectar,
            "calcular a faixa da Av. Marechal Tito",
            lambda: self._prospectar.faixa_marechal_tito(self._comum.definir_premissas(premissas)),
        )

    def prospectar_listar_regioes(self) -> dict[str, Any]:
        return self._executar(
            self._prospectar, "listar as regiões salvas", self._prospectar.listar_regioes
        )

    def prospectar_abrir_regiao(self, ident: str, premissas: Mapping[str, Any]) -> dict[str, Any]:
        return self._executar(
            self._prospectar,
            "abrir a região salva",
            lambda: self._prospectar.abrir_regiao(ident, self._comum.definir_premissas(premissas)),
        )

    def prospectar_excluir_regiao(self, ident: str) -> dict[str, Any]:
        return self._executar(
            self._prospectar, "excluir a região salva", lambda: self._prospectar.excluir_regiao(ident)
        )

    def prospectar_tabela(self, pedido: Mapping[str, Any]) -> dict[str, Any]:
        return self._executar(
            self._prospectar, "montar a tabela de oportunidades", lambda: self._prospectar.tabela(pedido)
        )

    def prospectar_detalhe(self, chave: str) -> dict[str, Any]:
        return self._executar(
            self._prospectar, "abrir o detalhe", lambda: self._prospectar.detalhe(chave)
        )

    def prospectar_mapa_lotes(self, bbox: list[float], zoom: int) -> dict[str, Any]:
        return self._executar(
            self._prospectar,
            "desenhar os lotes da área",
            lambda: self._prospectar.mapa_lotes(bbox, zoom),
        )

    def prospectar_exportar_csv(self, pedido: Mapping[str, Any]) -> dict[str, Any]:
        return self._executar(
            self._prospectar,
            "exportar o CSV de oportunidades",
            lambda: self._prospectar.exportar_csv(pedido),
        )

    def prospectar_exportar_kmz(self) -> dict[str, Any]:
        return self._executar(
            self._prospectar, "exportar o KMZ do entorno", self._prospectar.exportar_kmz
        )

    # --- Aba Simulador ---

    def simulador_buscar(self, texto: str, premissas: Mapping[str, Any]) -> dict[str, Any]:
        return self._executar(
            self._simulador,
            "achar o terreno para simular",
            lambda: self._simulador.buscar(texto, self._comum.definir_premissas(premissas)),
        )

    def simulador_abrir(self, ids: list[str], premissas: Mapping[str, Any]) -> dict[str, Any]:
        return self._executar(
            self._simulador,
            "abrir o terreno no simulador",
            lambda: self._simulador.abrir(ids, self._comum.definir_premissas(premissas)),
        )

    def simulador_simular(self, parametros: Mapping[str, Any]) -> dict[str, Any]:
        return self._executar(
            self._simulador, "simular", lambda: self._simulador.simular(parametros)
        )

    def simulador_simular_terreno(
        self, ids: list[str], parametros: Mapping[str, Any], premissas: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._executar(
            self._simulador,
            "simular o terreno",
            lambda: self._simulador.simular_terreno(
                ids, parametros, self._comum.definir_premissas(premissas)
            ),
        )

    def simulador_copiar_resumo(self) -> dict[str, Any]:
        return self._executar(
            self._simulador, "gerar o resumo da simulação", self._simulador.copiar_resumo
        )

    def simulador_exportar_excel(self) -> dict[str, Any]:
        return self._executar(
            self._simulador, "exportar o Excel da simulação", self._simulador.exportar_excel
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Raio-X de Terrenos SP")
    parser.add_argument(
        "--autoteste",
        action="store_true",
        help="Abre a janela, confere as abas e a ponte, grava %%TEMP%%\\raiox_autoteste.json e fecha",
    )
    args = parser.parse_args()

    api = Api(autoteste=args.autoteste)
    index_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "index.html")
    # Abre maximizada: com o Windows em 125% ou 150% uma janela fixa de 1400×900 passava do
    # monitor e cortava a tela (29/10). O layout se ajusta à área que sobrar.
    window = webview.create_window(
        "Raio-X de Terrenos SP",
        index_path,
        js_api=api,
        maximized=True,
        min_size=(1000, 600),
    )
    api.set_window(window)
    webview.start()


if __name__ == "__main__":
    main()
