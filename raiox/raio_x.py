"""Orquestrador do Raio-X de Terrenos SP.

Integra busca, zoneamento, cálculo de potencial construtivo, restrições e estações.
"""
from __future__ import annotations

from typing import Sequence
import numpy as np
import pyproj
import shapely

from raiox import dados, retiradas, uso
from raiox.area_util import calcular
from raiox.busca import Achado, buscar
from raiox.restricoes import avaliar, estacao_mais_proxima
from raiox.tipos import (
    AreaLote,
    Candidatos,
    LoteCadastro,
    NaoEncontrado,
    Premissas,
    RaioX,
    Retirada,
)
from raiox.zona import avisos_de_zonas, ca_do_lote, zonas_do_lote

_TRANSFORMER_4326_TO_31983 = pyproj.Transformer.from_crs(
    "EPSG:4326", "EPSG:31983", always_xy=True
)

_AVISO_FIXO_GABARITO = "Gabarito não limita o CA nesta versão."
VIA_ESTREITA_M = 10.0  # caixa "Acesso por via de até 10 m" (Lei 18.081, art. 3º, III; app antigo)


def _calcular_area_geometrica(geometria_wkt: str | None) -> float:
    """Calcula a área do polígono reprojetado para EPSG:31983 (SIRGAS 2000 / UTM 23S)."""
    if not geometria_wkt:
        return 0.0

    geom = shapely.from_wkt(geometria_wkt)
    if geom.is_empty:
        return 0.0

    if not geom.is_valid:
        geom = shapely.make_valid(geom)

    geom_proj = shapely.transform(
        geom,
        lambda coords: np.column_stack(
            _TRANSFORMER_4326_TO_31983.transform(coords[:, 0], coords[:, 1])
        ),
    )
    return float(geom_proj.area)


def divergencia_area_pct(area: AreaLote) -> float | None:
    """Diferença entre a área do desenho e a do cadastro, em % do cadastro (None sem cadastro)."""
    if area.bruta_m2 <= 0:
        return None
    return abs(area.geometrica_m2 - area.bruta_m2) / area.bruta_m2 * 100.0


def consultar_lote(
    lote: LoteCadastro,
    premissas: Premissas,
    avisos_busca: Sequence[str] = (),
) -> RaioX:
    """Realiza a análise completa de viabilidade para um lote já identificado."""
    zonas = zonas_do_lote(lote)
    sigla_principal = zonas[0][0]
    ca_teto, cp_max, av_ca = ca_do_lote(sigla_principal, lote.area_terreno_m2, premissas)

    if premissas.retiradas:
        area = retiradas.calcular(
            lote,
            premissas.retiradas,
            {"alta_tensao": premissas.faixa_alta_tensao_m},
        )
        bruta = area.bruta_m2
        geometrica = area.geometrica_m2
        liquida = area.liquida_m2
    else:
        bruta = float(lote.area_terreno_m2)
        geometrica = _calcular_area_geometrica(lote.geometria_wkt)
        liquida = bruta
        retiradas_lista: list[Retirada] = []
        geometria_liquida_wkt = lote.geometria_wkt or ""
        area = AreaLote(
            bruta_m2=bruta,
            geometrica_m2=geometrica,
            liquida_m2=liquida,
            retiradas=retiradas_lista,
            geometria_liquida_wkt=geometria_liquida_wkt,
        )

    aviso_poligono: str | None = None
    divergencia = divergencia_area_pct(area)
    if divergencia is not None and divergencia > premissas.limite_divergencia_area_pct:
        bruta_fmt = f"{round(bruta):,}".replace(",", ".")
        geom_fmt = f"{round(geometrica):,}".replace(",", ".")
        pct_fmt = f"{divergencia:.1f}".replace(".", ",")
        aviso_poligono = (
            f"Cadastro × desenho divergem {pct_fmt}%; confira "
            f"({bruta_fmt} m² no cadastro × {geom_fmt} m² no desenho; a conta usa o cadastro)."
        )

    a_ref = bruta if premissas.base_vgv == "referencia_ca" else liquida
    area_util = calcular(a_ref, ca_teto, premissas, cp_max)

    sinais = avaliar(lote)
    estacao = estacao_mais_proxima(lote)

    lista_avisos: list[str] = list(avisos_busca)
    if aviso_poligono:
        lista_avisos.append(aviso_poligono)
    lista_avisos.extend(avisos_de_zonas(zonas))
    lista_avisos.extend(av_ca)
    lista_avisos.append(_AVISO_FIXO_GABARITO)

    avisos_finais: list[str] = []
    for av in lista_avisos:
        if av and av not in avisos_finais:
            avisos_finais.append(av)

    pct_construido: float | None = None
    if lote.area_construida_m2 is not None and lote.area_terreno_m2 > 0:
        pct_construido = round((lote.area_construida_m2 / lote.area_terreno_m2) * 100.0, 1)

    # Uso e porte pelo motor antigo (regime, ZEIS > 1.000 m², via mínima). A caixa "via de até
    # 10 m" entra como via de 10 m, o maior valor que ela admite: o alerta que sai vale para
    # qualquer via mais estreita. Sem a caixa, a via fica "não conferida".
    uso_porte = uso.avaliar_uso_porte_completo(
        sigla_principal,
        lote.area_terreno_m2,
        area_util.a_comp,
        regime=premissas.regime,
        via_acesso_m=VIA_ESTREITA_M if premissas.acesso_via_estreita else None,
    )

    return RaioX(
        lote=lote,
        zonas=zonas,
        area=area,
        area_util=area_util,
        sinais=sinais,
        estacao=estacao,
        avisos=avisos_finais,
        pct_construido=pct_construido,
        uso_porte=uso_porte,
    )


def localizar(texto: str) -> Achado | Candidatos | NaoEncontrado:
    """Acha o lote do texto (SQL, endereço ou identificador cadastral), sem calcular o Raio-X."""
    resultado_busca = buscar(texto)
    if isinstance(resultado_busca, NaoEncontrado):
        lote_id = dados.lote_por_id(texto.strip())
        if lote_id is not None:
            return Achado(lote=lote_id)
    return resultado_busca


def consultar(texto: str, premissas: Premissas) -> RaioX | Candidatos | NaoEncontrado:
    """Busca o lote pelo texto informado e executa a consulta urbanística completa."""
    resultado = localizar(texto)
    if isinstance(resultado, Achado):
        return consultar_lote(resultado.lote, premissas, avisos_busca=resultado.avisos)
    return resultado
