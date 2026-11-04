"""Cálculo de retiradas e área líquida do lote."""

from __future__ import annotations

import numpy as np
import pyproj
import shapely

from raiox import camadas, dados
from raiox.tipos import AreaLote, LoteCadastro, Retirada

_PARA_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:31983", always_xy=True)
_PARA_WGS = pyproj.Transformer.from_crs("EPSG:31983", "EPSG:4326", always_xy=True)


def _reprojetar(geom: shapely.Geometry, tf: pyproj.Transformer) -> shapely.Geometry:
    """Reprojeta geometria entre sistemas de coordenadas."""
    return shapely.transform(
        geom, lambda c: np.column_stack(tf.transform(c[:, 0], c[:, 1]))
    )


def _num(v: float) -> str:
    """Formata número no padrão pt-BR: milhar '.' e decimal ','."""
    if v == int(v):
        return f"{int(v):,}".replace(",", ".")
    s = f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if s.endswith(",0"):
        return s[:-2]
    return s


def calcular(
    lote: LoteCadastro,
    ids: tuple[str, ...],
    faixas_m: dict[str, float] | None = None,
) -> AreaLote:
    """Calcula as retiradas e a área líquida de um lote a partir de regras."""
    ids_unicos = tuple(dict.fromkeys(ids))
    regras_retirar = camadas.regras_com_uso("retirar")
    lista_validas = ", ".join(r.id for r in regras_retirar)

    for id_camada in ids_unicos:
        try:
            regra = camadas.regra(id_camada)
        except KeyError as erro:
            raise ValueError(
                f"Camada desconhecida para retirada: '{id_camada}'. "
                f"Camadas que admitem retirada: {lista_validas}."
            ) from erro

        if "retirar" not in regra.usos:
            raise ValueError(
                f"A camada '{id_camada}' ({regra.rotulo}) não admite retirada. "
                f"Camadas que admitem retirada: {lista_validas}."
            )

    if faixas_m is not None:
        for chave in ids_unicos:
            if chave in faixas_m:
                valor = faixas_m[chave]
                if valor <= 0:
                    valor_ptbr = _num(valor)
                    raise ValueError(
                        f"A faixa de '{chave}' deve ser maior que zero "
                        f"(recebido: {valor_ptbr} m)."
                    )

    g = shapely.from_wkt(lote.geometria_wkt)
    if not shapely.is_valid(g):
        g = shapely.make_valid(g)
    lote_utm = _reprojetar(g, _PARA_UTM)
    geometrica = float(shapely.area(lote_utm))
    bbox = tuple(float(v) for v in shapely.bounds(g))

    retiradas: list[Retirada] = []
    unioes_gerais: list[shapely.Geometry] = []

    for id_camada in ids_unicos:
        regra = camadas.regra(id_camada)
        faixa = (
            faixas_m[id_camada]
            if faixas_m is not None and id_camada in faixas_m
            else regra.faixa_m
        )
        margem = faixa if faixa is not None else 0.0

        geometrias_da_regra: list[shapely.Geometry] = []
        houve_linha = False

        for camada_banco in regra.camadas_banco:
            for feicao in dados.feicoes(camada_banco, bbox, margem_m=margem):
                if not feicao.geometria_wkt:
                    continue
                gf = shapely.from_wkt(feicao.geometria_wkt)
                if gf is None or shapely.is_empty(gf):
                    continue
                if not shapely.is_valid(gf):
                    gf = shapely.make_valid(gf)
                gu = _reprojetar(gf, _PARA_UTM)
                dim = shapely.get_dimensions(gu)

                if dim == 2:
                    geometrias_da_regra.append(gu)
                elif dim == 1:
                    houve_linha = True
                    if faixa is not None:
                        geometrias_da_regra.append(
                            shapely.buffer(gu, faixa / 2.0)
                        )
                # dim == 0 -> ignore

        if geometrias_da_regra:
            uniao_regra = shapely.union_all(geometrias_da_regra)
            area = float(
                shapely.area(shapely.intersection(lote_utm, uniao_regra))
            )
            unioes_gerais.append(uniao_regra)
        else:
            area = 0.0

        if houve_linha and faixa is None:
            rotulo = f"{regra.rotulo} (faixa não definida)"
        elif faixa is not None and (houve_linha or regra.faixa_m is not None):
            rotulo = f"{regra.rotulo} (faixa de {_num(faixa)} m)"
        else:
            rotulo = regra.rotulo

        retiradas.append(
            Retirada(camada=id_camada, rotulo=rotulo, area_m2=area)
        )

    # A conta parte do cadastro (decisão do autor, 29/10): líquida = área do cadastro − o que as
    # retiradas tiram do desenho (a união, sem contar sobreposição duas vezes).
    bruta = float(lote.area_terreno_m2)
    if not unioes_gerais:
        liquida = bruta
        geometria_liquida_wkt = lote.geometria_wkt
    else:
        uniao_todas = shapely.union_all(unioes_gerais)
        resto = shapely.difference(lote_utm, uniao_todas)
        retirado = max(0.0, geometrica - float(shapely.area(resto)))
        liquida = max(0.0, bruta - retirado)
        if shapely.is_empty(resto):
            geometria_liquida_wkt = "POLYGON EMPTY"
        else:
            geometria_liquida_wkt = str(_reprojetar(resto, _PARA_WGS).wkt)

    return AreaLote(
        bruta_m2=bruta,
        geometrica_m2=geometrica,
        liquida_m2=liquida,
        retiradas=retiradas,
        geometria_liquida_wkt=geometria_liquida_wkt,
    )
