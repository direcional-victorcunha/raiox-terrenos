"""Aba Prospectar: lotes, duplas e trincas que batem a meta numa área, e todos os lotes dela.

Área de busca (sempre explícita na tela, com o tamanho):
- "circulo": círculo de X m em volta de um lote central (SQL, endereço ou identificador);
- "faixa": faixa de X m ao longo de uma rua (raiox.faixa, aproximada pelos lotes do logradouro)
  ou a faixa pronta da Av. Marechal Tito (o polígono do app antigo, data/regioes/marechal-tito);
- "kmz": polígono de um KMZ de região (vários polígonos = união), salvo em disco para reabrir.

Modos de exibição (raiox.oportunidades): "Só oportunidades" e "Todos os lotes". O estado da aba
(lote central, área, entorno, premissas usadas) é só dela: abrir outro lote no Raio-X não mexe aqui.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import datetime
import math
from pathlib import Path
import re
import threading
import time
from typing import Any, Mapping

import numpy as np
import shapely

from raiox import dados, entorno, mapa, oportunidades, raio_x, regioes
from raiox import faixa as faixa_rua
from raiox.abas.comum import Comum, ErroUsuario, converter_numero, poligonos_do_kmz
from raiox.area_util import preco_m2_efetivo
from raiox.busca import Achado
from raiox.oportunidades import Consulta, Linha
from raiox.saidas import kmz
from raiox.tipos import Entorno, LoteCadastro, NaoEncontrado, Premissas

# Área pronta da Av. Marechal Tito: o polígono de 1.500 m do app antigo, feito sobre o traçado
# da via (43,8 km²). A faixa montada pelos lotes da "AV MAL TITO" dá 32,9 km² e cobre ~75% dele,
# por isso o atalho usa o polígono antigo (decisão da Aria, 29/10).
REGIAO_MARECHAL_TITO = "marechal-tito"
LARGURA_MAX_FAIXA_M = 5000.0  # contrato de raiox.faixa (largura > 5.000 m é recusada)
RAIO_PONTO_MIN_M, RAIO_PONTO_MAX_M = 100.0, 5000.0  # controle "Marcar no mapa" (pedido do autor)
MIN_VERTICES_DESENHO = 3
_FOLGA_CLIQUE_GRAUS = 0.0002  # ~20 m: retângulo para achar os lotes candidatos sob o clique
LIMITE_LOTES_MAPA = 8000  # modo "Todos os lotes": acima disto no retângulo, pede para aproximar (zoom 16 na faixa densa: ~7.600)
_AVISO_FAIXA_POR_LOTES = (
    "Faixa aproximada pelos lotes do logradouro: pode ficar menor que o traçado da via "
    "(na Av. Marechal Tito, 32,9 km² contra 43,8 km² do polígono antigo)."
)


@dataclass(frozen=True)
class AreaProspeccao:
    """Onde procurar: círculo em volta de um lote, faixa ao longo de uma rua ou polígono de KMZ."""

    tipo: str  # "circulo" | "ponto" | "faixa" | "kmz" | "desenho"
    rotulo: str
    area_wkt: str
    centro_wkt: str | None
    raio_m: float | None
    largura_m: float | None
    area_km2: float
    etiqueta_arquivo: str
    avisos: tuple[str, ...]


def _etiqueta(texto: str) -> str:
    return re.sub(r"[^\w.-]", "_", texto.strip())


def _exigir_preco(p: Premissas) -> None:
    """Sem preço não há VGV para comparar com a meta: diz exatamente o que falta preencher."""
    if preco_m2_efetivo(p) is None:
        raise ErroUsuario(
            "Para avaliar o entorno pela meta de VGV, falta preencher em ⚙ Premissas: "
            "o preço por m² ou o ticket da unidade (o preço sai de ticket ÷ área média)."
        )


def _metros(campo: str, valor: Any, maximo: float | None = None) -> float:
    numero = converter_numero(campo, valor)
    if numero <= 0 or (maximo is not None and numero > maximo):
        limite = f" e até {maximo:,.0f} m".replace(",", ".") if maximo is not None else ""
        raise ErroUsuario(f"O valor de '{campo}' deve ser um número de metros maior que zero{limite}.")
    return numero


def _txt_m(valor: float) -> str:
    return f"{valor:,.0f}".replace(",", ".")


def _aviso_area_grande(km2: float) -> tuple[str, ...]:
    if km2 <= regioes.LIMITE_KM2_AVISO:
        return ()
    km2_txt = f"{km2:.1f}".replace(".", ",")
    return (
        f"Área grande ({km2_txt} km², acima de {regioes.LIMITE_KM2_AVISO:.0f} km²): "
        "o cálculo pode levar mais de um minuto.",
    )


def consulta_de_dict(entrada: Mapping[str, Any] | None) -> Consulta:
    """Converte o pedido da tela (modo, filtro, ordem, página) em Consulta, com erros em pt-BR."""
    if entrada is None:
        return Consulta()
    if not isinstance(entrada, Mapping):
        raise ErroUsuario("O pedido da tabela precisa vir como um conjunto de campos.")
    tipos: dict[str, type | tuple[type, ...]] = {
        "modo": str, "filtro": str, "ordem": str, "decrescente": bool, "ver_todas": bool,
        "pagina": int, "por_pagina": int, "zona": (str, type(None)), "uso": (str, type(None)),
    }
    kwargs: dict[str, Any] = {}
    for chave, valor in entrada.items():
        if chave not in tipos:
            raise ErroUsuario(f"Campo desconhecido no pedido da tabela: {chave!r}.")
        if isinstance(valor, bool) and tipos[chave] is int or not isinstance(valor, tipos[chave]):
            raise ErroUsuario(f"Valor inválido no pedido da tabela: {chave} = {valor!r}.")
        kwargs[chave] = valor or None if chave in ("zona", "uso") else valor
    consulta = Consulta(**kwargs)
    try:
        oportunidades.validar(consulta)
    except ValueError as exc:
        raise ErroUsuario(str(exc)) from exc
    return consulta


class AbaProspectar:
    """Estado e ações da aba Prospectar."""

    nome = "prospectar"

    def __init__(self, comum: Comum) -> None:
        self.trava = threading.Lock()
        self._comum = comum
        self._centro: LoteCadastro | None = None
        self._area: AreaProspeccao | None = None
        self._entorno: Entorno | None = None
        self._premissas: Premissas | None = None
        self._tempo_s: float | None = None
        self._linhas: dict[str, list[Linha]] = {}
        self._limites: np.ndarray | None = None

    def opcoes(self) -> dict[str, Any]:
        """Caixas da triagem (as seis do antigo, na mesma ordem) para a tela montar os campos."""
        return {"triagem": [{"id": k, "rotulo": v} for k, v in entorno.TRIAGEM.items()]}

    # --- Lote central (área "círculo") ---

    def _definir_centro(self, lote: LoteCadastro, avisos: list[str]) -> dict[str, Any]:
        self._centro = lote
        return {
            "tipo": "Centro",
            "lote": asdict(lote),
            "lote_geojson": mapa.lote_geojson(lote),
            "avisos": avisos,
        }

    def buscar_centro(self, texto: str) -> dict[str, Any]:
        """Acha o lote central por SQL, endereço ou identificador (sem calcular o entorno)."""
        if not isinstance(texto, str) or not texto.strip():
            raise ErroUsuario("Digite o SQL, o endereço ou o identificador do lote central.")
        achado = raio_x.localizar(texto.strip())
        if isinstance(achado, Achado):
            return self._definir_centro(achado.lote, list(achado.avisos))
        self._centro = None
        return {"tipo": type(achado).__name__, "resultado": asdict(achado)}

    def escolher_centro(self, cd_identificador: str) -> dict[str, Any]:
        """Usa como centro o lote do identificador (lista de opções ou botão do Raio-X do lote)."""
        if not isinstance(cd_identificador, str) or not cd_identificador.strip():
            raise ErroUsuario("Informe o identificador do lote central.")
        identificador = cd_identificador.strip()
        lote = dados.lote_por_id(identificador)
        if lote is None:
            self._centro = None
            nao = NaoEncontrado(
                texto=identificador,
                motivo=f"Identificador {identificador} não encontrado na base de lotes.",
            )
            return {"tipo": "NaoEncontrado", "resultado": asdict(nao)}
        return self._definir_centro(lote, [])

    def lote_no_ponto(self, lon: float | int | str, lat: float | int | str) -> dict[str, Any]:
        """Lote do cadastro sob o ponto clicado (ferramenta "Escolher lote"); condomínio = opções."""
        x = converter_numero("lon", lon)
        y = converter_numero("lat", lat)
        if not (-180.0 <= x <= 180.0 and -90.0 <= y <= 90.0):
            raise ErroUsuario("O ponto clicado está fora do mapa (longitude/latitude inválidas).")
        ponto = shapely.Point(x, y)
        d = _FOLGA_CLIQUE_GRAUS
        sob = [
            l for l in dados.lotes_no_bbox((x - d, y - d, x + d, y + d))
            if shapely.covers(shapely.from_wkt(l.geometria_wkt), ponto)
        ]
        if not sob:
            return {"tipo": "Nenhum"}
        # Chave da linha do detalhe quando o lote está na área calculada (None se está fora).
        na_area = {a.cadastro.cd_identificador for a in self._entorno.lotes} if self._entorno else set()
        chaves = {l.cd_identificador: (f"l{l.cd_identificador}" if l.cd_identificador in na_area else None) for l in sob}
        if len(sob) == 1:
            return {"tipo": "Lote", "lote": asdict(sob[0]), "chave": chaves[sob[0].cd_identificador]}
        return {"tipo": "Candidatos", "opcoes": [asdict(l) for l in sob], "chaves": chaves}

    # --- Cálculo e resposta ---

    def _calcular(self, area: AreaProspeccao, p: Premissas) -> dict[str, Any]:
        _exigir_preco(p)
        inicio = time.perf_counter()
        resultado = entorno.calcular(area.area_wkt, p, centro_wkt=area.centro_wkt, raio_m=area.raio_m)
        self._tempo_s = time.perf_counter() - inicio
        self._area = area
        self._entorno = resultado
        self._premissas = p
        self._linhas = {}
        self._limites = None
        return self._resposta()

    def _estado(self) -> tuple[AreaProspeccao, Entorno, Premissas]:
        if self._area is None or self._entorno is None or self._premissas is None:
            raise ErroUsuario("Escolha a área de busca e calcule as oportunidades primeiro.")
        return self._area, self._entorno, self._premissas

    def _resposta(self) -> dict[str, Any]:
        area, ent, p = self._estado()
        area_geom = shapely.from_wkt(area.area_wkt)
        preco = preco_m2_efetivo(p)
        assert preco is not None  # _calcular já exigiu o preço
        return {
            "tipo": "Entorno",
            # Só as oportunidades: os lotes da área (dezenas de milhares) vêm pela tabela paginada.
            "entorno": {
                "centro_wkt": ent.centro_wkt,
                "raio_m": ent.raio_m,
                "candidatos": [asdict(c) for c in ent.candidatos],
                "avisos": list(ent.avisos),
            },
            "geojson": entorno.geojson(ent),
            "area": {
                "tipo": area.tipo,
                "rotulo": area.rotulo,
                "raio_m": area.raio_m,
                "largura_m": area.largura_m,
                "area_km2": area.area_km2,
                "n_lotes": len(ent.lotes),
            },
            "area_geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": area_geom.__geo_interface__,
                        "properties": {"rotulo": area.rotulo},
                    }
                ],
            },
            "resumo": oportunidades.resumo(ent),
            "avisos": list(area.avisos) + list(ent.avisos),
            "meta_vgv": p.meta_vgv,
            "criterio_meta": p.criterio_meta,
            "area_minima_m2": p.area_minima_m2,
            "tempo_s": round(self._tempo_s or 0.0, 1),
            "cortes_meta": oportunidades.cortes_meta(p, preco),
        }

    # --- Áreas de busca ---

    def entorno(self, raio_m: float | int | str, p: Premissas) -> dict[str, Any]:
        """Círculo de `raio_m` metros em volta do lote central."""
        if self._centro is None:
            raise ErroUsuario("Escolha o lote central antes de ver o entorno.")
        raio = _metros("raio_m", raio_m)
        centro = self._centro
        area_wkt = entorno.circulo_wkt(centro, raio)
        area = AreaProspeccao(
            tipo="circulo",
            rotulo=(
                f"círculo de {_txt_m(raio)} m em volta de {centro.logradouro} {centro.numero_porta or ''}"
            ).strip(),
            area_wkt=area_wkt,
            centro_wkt=centro.geometria_wkt,
            raio_m=raio,
            largura_m=None,
            area_km2=round(math.pi * raio * raio / 1_000_000.0, 2),
            etiqueta_arquivo=_etiqueta(centro.sql) if centro.sql else "",
            avisos=(),
        )
        return self._calcular(area, p)

    def ponto(
        self, lon: float | int | str, lat: float | int | str, raio_m: float | int | str, p: Premissas
    ) -> dict[str, Any]:
        """Círculo de `raio_m` metros em volta de um ponto marcado no mapa (não precisa ser lote)."""
        x = converter_numero("lon", lon)
        y = converter_numero("lat", lat)
        if not (-180.0 <= x <= 180.0 and -90.0 <= y <= 90.0):
            raise ErroUsuario("O ponto marcado está fora do mapa (longitude/latitude inválidas).")
        raio = converter_numero("raio_m", raio_m)
        if not RAIO_PONTO_MIN_M <= raio <= RAIO_PONTO_MAX_M:
            raise ErroUsuario(
                f"O raio deve ficar entre {_txt_m(RAIO_PONTO_MIN_M)} e {_txt_m(RAIO_PONTO_MAX_M)} m."
            )
        lat_txt = f"{y:.4f}".replace(".", ",")
        lon_txt = f"{x:.4f}".replace(".", ",")
        area = AreaProspeccao(
            tipo="ponto",
            rotulo=f"círculo de {_txt_m(raio)} m em volta do ponto marcado ({lat_txt}, {lon_txt})",
            area_wkt=entorno.circulo_ponto_wkt(x, y, raio),
            centro_wkt=str(shapely.Point(x, y).wkt),
            raio_m=raio,
            largura_m=None,
            area_km2=round(math.pi * raio * raio / 1_000_000.0, 2),
            etiqueta_arquivo=_etiqueta(f"ponto_{y:.5f}_{x:.5f}"),
            avisos=(),
        )
        return self._calcular(area, p)

    def desenho(self, vertices: Any, nome: str | None, p: Premissas) -> dict[str, Any]:
        """Polígono desenhado no mapa ([[lon, lat], ...]) como área; com `nome`, salva como região."""
        if not isinstance(vertices, (list, tuple)) or len(vertices) < MIN_VERTICES_DESENHO:
            raise ErroUsuario("Desenhe a área com pelo menos 3 pontos no mapa.")
        pontos: list[tuple[float, float]] = []
        for v in vertices:
            if not isinstance(v, (list, tuple)) or len(v) != 2:
                raise ErroUsuario("Ponto inválido no desenho: cada ponto precisa de longitude e latitude.")
            pontos.append((converter_numero("lon", v[0]), converter_numero("lat", v[1])))
        poligono = shapely.make_valid(shapely.Polygon(pontos))
        if shapely.area(poligono) <= 0:
            raise ErroUsuario("A área desenhada não tem tamanho: os pontos estão alinhados ou repetidos.")
        wkt = str(poligono.wkt)
        km2 = regioes.area_km2(wkt)
        avisos: list[str] = []
        if poligono.geom_type != "Polygon":
            avisos.append("O desenho cruzava as próprias linhas: usei as partes fechadas que ele forma.")
        _exigir_preco(p)
        rotulo = "área desenhada no mapa"
        etiqueta = "area_desenhada"
        salva: str | None = None
        if isinstance(nome, str) and nome.strip():
            try:
                regiao, substituiu = regioes.salvar(self._comum.pasta_config(), nome.strip(), wkt, "desenhada no mapa")
            except ValueError as exc:
                raise ErroUsuario(str(exc)) from exc
            avisos.append(
                f"Região “{regiao.nome}” {'substituída' if substituiu else 'salva'}: "
                "dá para reabrir pela lista de regiões salvas."
            )
            rotulo = f"área desenhada “{regiao.nome}”"
            etiqueta = _etiqueta(regiao.id)
            salva = regiao.id
        area = AreaProspeccao(
            tipo="desenho",
            rotulo=rotulo,
            area_wkt=wkt,
            centro_wkt=None,
            raio_m=None,
            largura_m=None,
            area_km2=km2,
            etiqueta_arquivo=etiqueta,
            avisos=tuple(avisos) + _aviso_area_grande(km2),
        )
        resposta = self._calcular(area, p)
        resposta["regiao_salva"] = salva
        return resposta

    def faixa(self, texto: str, largura_m: float | int | str, p: Premissas) -> dict[str, Any]:
        """Faixa de `largura_m` metros ao longo de uma rua (aproximada pelos lotes do logradouro)."""
        if not isinstance(texto, str) or not texto.strip():
            raise ErroUsuario("Digite o nome da rua ou avenida (ex.: AV MAL TITO).")
        largura = _metros("largura_m", largura_m, LARGURA_MAX_FAIXA_M)
        _exigir_preco(p)
        try:
            fx = faixa_rua.faixa_ao_longo_da_rua(texto.strip(), largura)
        except ValueError as exc:
            return {
                "tipo": "FaixaNaoEncontrada",
                "mensagem": str(exc),
                "sugestoes": faixa_rua.logradouros_parecidos(texto.strip()),
            }
        area = AreaProspeccao(
            tipo="faixa",
            rotulo=f"faixa de {_txt_m(largura)} m ao longo de {fx.logradouro} ({fx.n_lotes_eixo} lotes no eixo)",
            area_wkt=fx.wkt_wgs84,
            centro_wkt=None,
            raio_m=None,
            largura_m=largura,
            area_km2=fx.area_km2,
            etiqueta_arquivo=_etiqueta(f"faixa_{fx.logradouro}"),
            avisos=(_AVISO_FAIXA_POR_LOTES, *fx.avisos, *_aviso_area_grande(fx.area_km2)),
        )
        return self._calcular(area, p)

    def faixa_marechal_tito(self, p: Premissas) -> dict[str, Any]:
        """Atalho: a faixa de 1.500 m da Av. Marechal Tito do app antigo (mesmo polígono)."""
        try:
            wkt = dados.regiao_pronta(REGIAO_MARECHAL_TITO)
        except dados.RegiaoProntaAusente as exc:
            raise ErroUsuario(str(exc)) from exc
        km2 = round(regioes.area_km2(wkt), 2)
        area = AreaProspeccao(
            tipo="faixa",
            rotulo="faixa de 1.500 m da Av. Marechal Tito (polígono do app antigo)",
            area_wkt=wkt,
            centro_wkt=None,
            raio_m=None,
            largura_m=1500.0,
            area_km2=km2,
            etiqueta_arquivo="faixa_marechal_tito",
            avisos=_aviso_area_grande(km2),
        )
        return self._calcular(area, p)

    def _area_regiao(self, regiao: regioes.RegiaoSalva, avisos: tuple[str, ...]) -> AreaProspeccao:
        return AreaProspeccao(
            tipo="kmz",
            rotulo=f"região “{regiao.nome}”",
            area_wkt=regiao.wkt,
            centro_wkt=None,
            raio_m=None,
            largura_m=None,
            area_km2=regiao.area_km2,
            etiqueta_arquivo=_etiqueta(regiao.id),
            avisos=avisos + _aviso_area_grande(regiao.area_km2),
        )

    def carregar_kmz(self, nome: str, conteudo_base64: str, p: Premissas) -> dict[str, Any]:
        """Usa o KMZ/KML como área (vários polígonos = união) e salva a região para reabrir."""
        nome_arquivo = nome if isinstance(nome, str) and nome.strip() else "KMZ"
        poligonos = poligonos_do_kmz(nome_arquivo, conteudo_base64)
        uniao = str(shapely.union_all([shapely.make_valid(shapely.from_wkt(w)) for w in poligonos]).wkt)
        avisos: list[str] = []
        if len(poligonos) > 1:
            avisos.append(
                f"O arquivo tem {len(poligonos)} polígonos; usei a união de todos como área de busca."
            )
        _exigir_preco(p)
        try:
            regiao, substituiu = regioes.salvar(
                self._comum.pasta_config(), nome_arquivo.rsplit(".", 1)[0], uniao, nome_arquivo
            )
        except ValueError as exc:
            raise ErroUsuario(str(exc)) from exc
        avisos.append(
            f"Região “{regiao.nome}” {'substituída' if substituiu else 'salva'}: "
            "dá para reabrir pela lista de regiões salvas."
        )
        resposta = self._calcular(self._area_regiao(regiao, tuple(avisos)), p)
        resposta["regiao_salva"] = regiao.id
        return resposta

    def listar_regioes(self) -> dict[str, Any]:
        """Regiões salvas (id, nome, km²), para o seletor da tela."""
        try:
            lista = regioes.listar(self._comum.pasta_config())
        except ValueError as exc:
            raise ErroUsuario(str(exc)) from exc
        return {
            "regioes": [
                {"id": r.id, "nome": r.nome, "area_km2": r.area_km2, "origem": r.origem, "salva_em": r.salva_em}
                for r in lista
            ]
        }

    def abrir_regiao(self, ident: str, p: Premissas) -> dict[str, Any]:
        if not isinstance(ident, str) or not ident.strip():
            raise ErroUsuario("Escolha uma região salva.")
        try:
            regiao = regioes.abrir(self._comum.pasta_config(), ident)
        except ValueError as exc:
            raise ErroUsuario(str(exc)) from exc
        return self._calcular(self._area_regiao(regiao, ()), p)

    def excluir_regiao(self, ident: str) -> dict[str, Any]:
        if not isinstance(ident, str) or not ident.strip():
            raise ErroUsuario("Escolha uma região salva.")
        try:
            regioes.excluir(self._comum.pasta_config(), ident)
        except ValueError as exc:
            raise ErroUsuario(str(exc)) from exc
        return self.listar_regioes()

    def recalcular(self, p: Premissas) -> dict[str, Any]:
        """Refaz o entorno aberto com as premissas novas (nada aberto: só confirma)."""
        if self._area is None:
            return {"tipo": "Vazio"}
        return self._calcular(self._area, p)

    def _atual(self) -> tuple[AreaProspeccao, Entorno, Premissas]:
        """Entorno com as premissas atuais (refaz a conta se elas mudaram)."""
        area, _, p = self._estado()
        if p != self._comum.premissas:
            self._calcular(area, self._comum.premissas)
        return self._estado()

    # --- Tabela, detalhe e mapa do modo "Todos os lotes" ---

    def _linhas_do_modo(self, modo: str) -> list[Linha]:
        _, ent, p = self._estado()
        if modo not in self._linhas:
            self._linhas[modo] = oportunidades.linhas(ent, p, modo)
        return self._linhas[modo]

    def tabela(self, pedido: Mapping[str, Any] | None) -> dict[str, Any]:
        """Uma página da tabela (modo, filtro, ordem, "ver todas"), com os totais e as opções."""
        consulta = consulta_de_dict(pedido)
        todas = self._linhas_do_modo(consulta.modo)
        pag = oportunidades.pagina(oportunidades.filtrar_e_ordenar(todas, consulta), consulta)
        return {
            **pag,
            "linhas": [asdict(l) for l in pag["linhas"]],
            "modo": consulta.modo,
            "opcoes": oportunidades.opcoes_filtro(todas),
            "top_padrao": oportunidades.TOP_PADRAO,
        }

    def detalhe(self, chave: str) -> dict[str, Any]:
        """Detalhe de um lote, dupla ou trinca: lotes que compõem, conta do VGV e divisas."""
        if not isinstance(chave, str) or not chave:
            raise ErroUsuario("Escolha uma linha da tabela ou um lote no mapa.")
        _, ent, p = self._estado()
        preco = preco_m2_efetivo(p)
        assert preco is not None  # _calcular já exigiu o preço
        try:
            return {"detalhe": oportunidades.detalhe(ent, p, preco, chave)}
        except ValueError as exc:
            raise ErroUsuario(str(exc)) from exc

    def mapa_lotes(self, bbox: list[float], zoom: int) -> dict[str, Any]:
        """Lotes da área dentro do retângulo do mapa (modo "Todos os lotes"), com VGV e marca."""
        if (
            not isinstance(bbox, (list, tuple))
            or len(bbox) != 4
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in bbox)
        ):
            raise ErroUsuario("O retângulo do mapa precisa de 4 números.")
        if isinstance(zoom, bool) or not isinstance(zoom, int):
            raise ErroUsuario("O zoom precisa ser um número inteiro.")
        _, ent, _ = self._estado()
        if self._limites is None:
            geoms = shapely.from_wkt(np.array([a.cadastro.geometria_wkt for a in ent.lotes], dtype=object))
            self._limites = shapely.bounds(geoms).reshape(-1, 4)
        b = self._limites
        oeste, sul, leste, norte = (float(v) for v in bbox)
        idx = np.nonzero((b[:, 0] <= leste) & (b[:, 2] >= oeste) & (b[:, 1] <= norte) & (b[:, 3] >= sul))[0]
        if len(idx) > LIMITE_LOTES_MAPA:
            return {"truncado": True, "n": int(len(idx)), "limite": LIMITE_LOTES_MAPA, "geojson": None}
        tol = mapa.tolerancia_zoom(zoom)
        features = []
        for i in idx:
            a = ent.lotes[int(i)]
            g = shapely.from_wkt(a.cadastro.geometria_wkt)
            if tol > 0:
                g = shapely.simplify(g, tol, preserve_topology=True)
            features.append(
                {
                    "type": "Feature",
                    "geometry": g.__geo_interface__,
                    "properties": {
                        "chave": f"l{a.cadastro.cd_identificador}",
                        "sql": oportunidades.sql_formatado(a.cadastro),
                        "endereco": oportunidades.endereco(a.cadastro),
                        "area_m2": a.cadastro.area_terreno_m2,
                        "vgv": a.vgv,
                        "bate_meta": a.bate_meta,
                        "escondido_por": a.escondido_por,
                    },
                }
            )
        return {
            "truncado": False,
            "n": len(features),
            "limite": LIMITE_LOTES_MAPA,
            "geojson": {"type": "FeatureCollection", "features": features},
        }

    # --- Exportações ---

    def _caminho_livre(self, prefixo: str, extensao: str) -> tuple[str, Path]:
        area, _, _ = self._estado()
        hoje = datetime.date.today().isoformat()
        etiqueta = f"{area.etiqueta_arquivo}_" if area.etiqueta_arquivo else ""
        pasta = self._comum.pasta_saida()
        nome_base = f"{prefixo}_{etiqueta}{hoje}"
        caminho = pasta / f"{nome_base}.{extensao}"
        contador = 1
        while caminho.exists():
            caminho = pasta / f"{nome_base}_{contador}.{extensao}"
            contador += 1
        return nome_base, caminho

    def exportar_csv(self, pedido: Mapping[str, Any] | None) -> dict[str, Any]:
        """CSV das linhas que a tabela mostra (modo, filtro, ordem, 15 primeiras ou todas)."""
        consulta = consulta_de_dict(pedido)
        self._atual()
        ordenadas = oportunidades.filtrar_e_ordenar(self._linhas_do_modo(consulta.modo), consulta)
        _, caminho = self._caminho_livre("oportunidades", "csv")
        exibidas = oportunidades.exibidas(ordenadas, consulta)
        oportunidades.gravar_csv(caminho, exibidas)
        return {"caminho": str(caminho), "linhas": len(exibidas)}

    def exportar_kmz(self) -> dict[str, Any]:
        """KMZ do entorno (área de busca + lotes, duplas, trincas e escondidos) via saidas.kmz."""
        _, ent, p = self._atual()
        nome_base, _ = self._caminho_livre("entorno", "kmz")
        caminho = kmz.gerar_entorno(ent, p, self._comum.pasta_saida(), nome_base)
        return {"caminho": str(caminho)}
