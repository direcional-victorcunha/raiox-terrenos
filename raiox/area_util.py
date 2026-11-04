"""Cálculo de área computável, unidades estimadas e VGV potencial.

Decisão do autor (29/10): o VGV de referência em todo o app é o VGV POTENCIAL,
área de referência × CA × preço/m², sem fator privativo (como no app antigo).
A meta de VGV compara com ele, no Raio-X do lote e na tabela do Prospectar.
O fator privativo, quando informado, gera só a área útil privativa, uma linha
informativa que não muda VGV, unidades nem meta.
"""
from __future__ import annotations

import math

from raiox.tipos import AreaUtil, Premissas


def _m2(valor: float) -> str:
    """Formata valor em m² sem casas decimais (arredondamento padrão) e separador de milhar pt-BR."""
    val_int = round(valor)
    return f"{val_int:,}".replace(",", ".") + " m²"


def _num(valor: float) -> str:
    """Formata número com 2 casas decimais e vírgula decimal (ex: CA ou fator)."""
    return f"{valor:.2f}".replace(".", ",")


def _brl(valor: float) -> str:
    """Formata valor monetário sem centavos (arredondamento padrão) e separador de milhar pt-BR."""
    val_int = round(valor)
    return "R$ " + f"{val_int:,}".replace(",", ".")


def area_computavel(area_ref_m2: float, ca: float) -> float:
    """Área computável arredondada ao m²: área de referência × CA."""
    return float(round(area_ref_m2 * ca))


def preco_m2_efetivo(premissas: Premissas) -> float | None:
    """Preço por m² usado no VGV: o preço informado ou, sem ele, ticket ÷ área média (como no antigo)."""
    if premissas.preco_m2 is not None:
        return premissas.preco_m2
    if premissas.ticket_unidade is not None:
        return premissas.ticket_unidade / premissas.area_media_unidade_m2
    return None


def vgv_potencial(area_ref_m2: float, ca: float, preco_m2: float) -> float:
    """VGV potencial arredondado ao real: área computável × preço/m². Fonte única do VGV do app."""
    return float(round(area_computavel(area_ref_m2, ca) * preco_m2))


def calcular(
    area_ref_m2: float,
    ca_teto: float,
    premissas: Premissas,
    cp_max: float | None = None,
) -> AreaUtil:
    """Calcula área computável, unidades estimadas, VGV potencial e, se houver fator, a área útil."""
    a_comp = area_computavel(area_ref_m2, ca_teto)
    passos: list[str] = [
        f"{_m2(area_ref_m2)} × {_num(ca_teto)} = {_m2(a_comp)} (área computável)"
    ]

    unidades = math.floor(a_comp / premissas.area_media_unidade_m2)
    unidades_str = f"{unidades:,}".replace(",", ".")
    passos.append(
        f"{_m2(a_comp)} ÷ {_m2(premissas.area_media_unidade_m2)} = {unidades_str} unidades estimadas"
    )

    vgv: float | None = None
    preco = preco_m2_efetivo(premissas)
    if preco is None:
        passos.append(
            "Preço por m² não informado (nem ticket da unidade): VGV potencial não calculado."
        )
    else:
        if premissas.preco_m2 is None and premissas.ticket_unidade is not None:
            passos.append(
                f"{_brl(premissas.ticket_unidade)} ÷ {_m2(premissas.area_media_unidade_m2)} = "
                f"{_brl(preco)}/m² (preço pelo ticket)"
            )
        vgv = vgv_potencial(area_ref_m2, ca_teto, preco)
        passos.append(f"{_m2(a_comp)} × {_brl(preco)}/m² = {_brl(vgv)} (VGV potencial)")

    a_util: float | None = None
    if premissas.fator_privativo is not None:
        a_util = float(round(a_comp * premissas.fator_privativo))
        passos.append(
            f"{_m2(a_comp)} × {_num(premissas.fator_privativo)} = {_m2(a_util)} "
            "(área útil privativa, informativa: não entra no VGV nem na meta)"
        )

    unidades_min_cota_parte: int | None = None
    if cp_max is not None and cp_max > 0:
        unidades_min_cota_parte = math.ceil(area_ref_m2 / cp_max)
        cp_str = f"{unidades_min_cota_parte:,}".replace(",", ".")
        passos.append(
            f"{_m2(area_ref_m2)} ÷ {_m2(cp_max)} = {cp_str} unidades no mínimo pela cota-parte"
        )

    return AreaUtil(
        a_ref_m2=area_ref_m2,
        ca_teto=ca_teto,
        a_comp=a_comp,
        a_util=a_util,
        unidades=unidades,
        vgv=vgv,
        unidades_min_cota_parte=unidades_min_cota_parte,
        passos=passos,
    )
