"""Aba Raio-X do lote: consultar, escolher, KMZ de terreno, retiradas, croqui e exportações.

O estado da aba é o lote aberto (com os avisos da busca) e o Raio-X calculado com certas
premissas. Se as premissas atuais mudarem, o Raio-X é refeito antes de qualquer saída,
então resumo, Excel, KMZ e croqui sempre usam as premissas atuais (laudo D8).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import threading
from typing import Any

import numpy as np
import pyproj
import shapely

from raiox import camadas, dados, kmz_entrada, mapa, oportunidades, raio_x, zona
from raiox.abas.comum import Comum, ErroUsuario, aviso_varios_poligonos, poligonos_do_kmz
from raiox.busca import Achado
from raiox.saidas import croqui, excel, kmz, resumo
from raiox.tipos import Candidatos, LoteCadastro, NaoEncontrado, Premissas, RaioX

_PARA_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:31983", always_xy=True)
_PARA_WGS = pyproj.Transformer.from_crs("EPSG:31983", "EPSG:4326", always_xy=True)


def _reprojetar(geom: shapely.Geometry, tf: pyproj.Transformer) -> shapely.Geometry:
    return shapely.transform(geom, lambda c: np.column_stack(tf.transform(c[:, 0], c[:, 1])))


def _liquida_geojson(resultado: RaioX) -> dict[str, Any] | None:
    """Polígono da área líquida, só quando houve retirada."""
    if not resultado.area.retiradas:
        return None
    wkt = resultado.area.geometria_liquida_wkt
    if not wkt:
        return None
    geom = shapely.from_wkt(wkt)
    if geom.is_empty:
        return None
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": geom.__geo_interface__,
                "properties": {"rotulo": "Área líquida", "area_m2": resultado.area.liquida_m2},
            }
        ],
    }


def _retiradas_geojson(resultado: RaioX, premissas: Premissas) -> dict[str, Any] | None:
    """Pedaços do lote retirados por camada, para desenhar em vermelho no mapa."""
    if not resultado.area.retiradas:
        return None
    geom_lote = shapely.from_wkt(resultado.lote.geometria_wkt)
    if not shapely.is_valid(geom_lote):
        geom_lote = shapely.make_valid(geom_lote)
    lote_utm = _reprojetar(geom_lote, _PARA_UTM)
    bbox = tuple(float(v) for v in shapely.bounds(geom_lote))

    features: list[dict[str, Any]] = []
    for r in resultado.area.retiradas:
        if r.area_m2 <= 0:
            continue
        regra = camadas.regra(r.camada)
        faixa = premissas.faixa_alta_tensao_m if r.camada == "alta_tensao" else regra.faixa_m
        margem = faixa if faixa is not None else 0.0

        geometrias: list[shapely.Geometry] = []
        for camada_banco in regra.camadas_banco:
            for feicao in dados.feicoes(camada_banco, bbox, margem_m=margem):
                if not feicao.geometria_wkt:
                    continue
                gf = shapely.from_wkt(feicao.geometria_wkt)
                if shapely.is_empty(gf):
                    continue
                if not shapely.is_valid(gf):
                    gf = shapely.make_valid(gf)
                gu = _reprojetar(gf, _PARA_UTM)
                dim = shapely.get_dimensions(gu)
                if dim == 2:
                    geometrias.append(gu)
                elif dim == 1 and faixa is not None:
                    geometrias.append(shapely.buffer(gu, faixa / 2.0))

        if geometrias:
            inter_utm = shapely.intersection(lote_utm, shapely.union_all(geometrias))
            if not shapely.is_empty(inter_utm):
                features.append({
                    "type": "Feature",
                    "geometry": _reprojetar(inter_utm, _PARA_WGS).__geo_interface__,
                    "properties": {"camada": r.camada, "rotulo": r.rotulo, "area_m2": r.area_m2},
                })
    return {"type": "FeatureCollection", "features": features} if features else None


def quarteirao_geojson(lote: LoteCadastro) -> dict[str, Any]:
    """Só os lotes da mesma quadra (setor + quadra do SQL), com o lote aberto marcado.

    É o mapa da aba Raio-X do lote: algo menor e mais restrito que o entorno (29/10).
    """
    vizinhos = dados.lotes_da_quadra(lote.setor, lote.quadra) if lote.setor and lote.quadra else []
    if not any(v.cd_identificador == lote.cd_identificador for v in vizinhos):
        vizinhos.append(lote)  # lote de condomínio/KMZ sem par na quadra: o mapa nunca fica sem ele
    features = []
    for v in vizinhos:
        geom = shapely.from_wkt(v.geometria_wkt)
        if geom.is_empty:
            continue
        features.append({
            "type": "Feature",
            "geometry": geom.__geo_interface__,
            "properties": {
                "cd_identificador": v.cd_identificador,
                "sql": oportunidades.sql_formatado(v),
                "endereco": oportunidades.endereco(v),
                "area_m2": v.area_terreno_m2,
                "aberto": v.cd_identificador == lote.cd_identificador,
            },
        })
    return {"type": "FeatureCollection", "features": features}


@dataclass(frozen=True)
class _LoteAberto:
    """O que a aba precisa para refazer o Raio-X com outras premissas."""

    lote: LoteCadastro
    avisos_busca: tuple[str, ...]
    rx: RaioX
    premissas: Premissas


class AbaLote:
    """Estado e ações da aba Raio-X do lote."""

    nome = "lote"

    def __init__(self, comum: Comum) -> None:
        self.trava = threading.Lock()
        self._comum = comum
        self._aberto: _LoteAberto | None = None

    # --- Estado ---

    def _abrir(self, lote: LoteCadastro, avisos_busca: tuple[str, ...], p: Premissas) -> dict[str, Any]:
        rx = raio_x.consultar_lote(lote, p, avisos_busca=avisos_busca)
        self._aberto = _LoteAberto(lote=lote, avisos_busca=avisos_busca, rx=rx, premissas=p)
        return self._resposta_raiox(rx, p)

    def _fechar(self, resultado: Candidatos | NaoEncontrado) -> dict[str, Any]:
        self._aberto = None
        return {"tipo": type(resultado).__name__, "resultado": asdict(resultado)}

    def _atual(self, acao: str) -> tuple[RaioX, Premissas]:
        """Raio-X do lote aberto com as premissas atuais (refaz a conta se elas mudaram)."""
        if self._aberto is None:
            raise ErroUsuario(f"Abra um lote no Raio-X antes de {acao}.")
        p = self._comum.premissas
        if self._aberto.premissas != p:
            self._abrir(self._aberto.lote, self._aberto.avisos_busca, p)
        assert self._aberto is not None
        return self._aberto.rx, self._aberto.premissas

    @staticmethod
    def _resposta_raiox(rx: RaioX, p: Premissas) -> dict[str, Any]:
        return {
            "tipo": "RaioX",
            "resultado": asdict(rx),
            "meta_vgv": p.meta_vgv,
            "lote_geojson": mapa.lote_geojson(rx.lote),
            "liquida_geojson": _liquida_geojson(rx),
            "retiradas_geojson": _retiradas_geojson(rx, p),
            "quarteirao_geojson": quarteirao_geojson(rx.lote),
            "divergencia_area_pct": raio_x.divergencia_area_pct(rx.area),
            "limite_divergencia_area_pct": p.limite_divergencia_area_pct,
            "multiplicador": zona.texto_multiplicador(p),
        }

    # --- Ações ---

    def consultar(self, texto: str, p: Premissas) -> dict[str, Any]:
        """Consulta um lote por SQL, endereço ou identificador cadastral."""
        if not isinstance(texto, str) or not texto.strip():
            raise ErroUsuario("Digite um SQL ou endereço.")
        achado = raio_x.localizar(texto.strip())
        if isinstance(achado, Achado):
            return self._abrir(achado.lote, tuple(achado.avisos), p)
        return self._fechar(achado)

    def escolher(self, cd_identificador: str, p: Premissas) -> dict[str, Any]:
        """Abre o lote pelo identificador cadastral (lista de opções, tabela do Prospectar)."""
        if not isinstance(cd_identificador, str) or not cd_identificador.strip():
            raise ErroUsuario("Informe o identificador do lote.")
        identificador = cd_identificador.strip()
        lote = dados.lote_por_id(identificador)
        if lote is None:
            return self._fechar(
                NaoEncontrado(
                    texto=identificador,
                    motivo=f"Identificador {identificador} não encontrado na base de lotes.",
                )
            )
        return self._abrir(lote, (), p)

    def carregar_kmz(self, nome: str, conteudo_base64: str, p: Premissas) -> dict[str, Any]:
        """Abre o terreno desenhado num KMZ/KML (até 50.000 m²); região vai para o Prospectar."""
        nome_arquivo = nome if isinstance(nome, str) and nome.strip() else "KMZ"
        poligonos = poligonos_do_kmz(nome_arquivo, conteudo_base64)
        avisos = tuple(aviso_varios_poligonos(poligonos))
        wkt = poligonos[0]
        if kmz_entrada.classificar(wkt) == "regiao":
            limite = f"{kmz_entrada.LIMITE_AREA_TERRENO_M2:,.0f}".replace(",", ".")
            raise ErroUsuario(
                f"“{nome_arquivo}” desenha uma região (mais de {limite} m²), não um terreno. "
                "Abra-o na aba Prospectar."
            )
        cobertos = kmz_entrada.lotes_cobertos(wkt)
        if len(cobertos) == 1:
            return self._abrir(cobertos[0], avisos, p)
        if cobertos:
            return self._fechar(Candidatos(texto=nome_arquivo, opcoes=cobertos, avisos=list(avisos)))
        return self._fechar(
            NaoEncontrado(
                texto=nome_arquivo,
                motivo="Nenhum lote com pelo menos 50% de cobertura encontrado no polígono.",
            )
        )

    def recalcular(self, p: Premissas) -> dict[str, Any]:
        """Refaz o Raio-X do lote aberto com as premissas novas (nada aberto: só confirma)."""
        if self._aberto is None:
            return {"tipo": "Vazio"}
        return self._abrir(self._aberto.lote, self._aberto.avisos_busca, p)

    def croqui(self) -> dict[str, Any]:
        rx, _ = self._atual("gerar o croqui")
        return {"svg": croqui.gerar(rx)}

    def copiar_resumo(self) -> dict[str, Any]:
        rx, p = self._atual("copiar o resumo")
        return {"texto": resumo.gerar(rx, p)}

    def exportar_excel(self) -> dict[str, Any]:
        rx, p = self._atual("exportar o Excel")
        return {"caminho": str(excel.gerar(rx, p, self._comum.pasta_saida()))}

    def exportar_kmz(self) -> dict[str, Any]:
        rx, p = self._atual("exportar o KMZ")
        return {"caminho": str(kmz.gerar_terreno(rx, p, self._comum.pasta_saida()))}
