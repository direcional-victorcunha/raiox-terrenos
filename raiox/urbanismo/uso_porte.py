# Cópia congelada de prospeccao-marechal-tito/core/uso_porte.py em 2026-10-28.
# NOTA: regras sem fonte na SPEC — HISTORICO item 10.
"""
Validações de uso e porte (subcategorias R2v, via mínima, ZEIS) por regime/produto.

ATENÇÃO: estas regras vieram do app.py e NÃO constam na SPEC_motor_CA_SP.md — os limites
de área (2.500 / 10.000 / 20.000 m²), as listas de zonas por subcategoria e as vias mínimas
precisam ser conferidos na LPUOS (Lei 18.081/2024) antes de qualquer uso decisório.
Mantidas aqui, fora da tela, para serem testáveis e para ter um único lugar a corrigir.
"""

from raiox.urbanismo.ca_engine import EIXO_ZONAS, Alerta

_EIXOS = ["ZEU", "ZEUa", "ZEUP", "ZEUPa", "ZEM", "ZEMP"]
_ZEIS = ["ZEIS-1", "ZEIS-2", "ZEIS-3", "ZEIS-4", "ZEIS-5"]
_R2V4 = _EIXOS + _ZEIS
_R2V3 = _R2V4 + ["ZC", "ZCa", "ZM", "ZMa"]
_R2V2 = _R2V3 + ["ZCOR-3", "ZCORa", "ZDE-1"]
_R2V1 = _R2V2 + ["ZCOR-2"]
ZONAS_POR_SUBCATEGORIA = {
    "R2v-1": _R2V1,
    "R2v-2": _R2V2,
    "R2v-3": _R2V3,
    "R2v-4": _R2V4,
}


def subcategoria_r2v(area_computavel_m2: float) -> str:
    if area_computavel_m2 <= 2500:
        return "R2v-1"
    if area_computavel_m2 <= 10000:
        return "R2v-2"
    if area_computavel_m2 <= 20000:
        return "R2v-3"
    return "R2v-4"


def validar_uso_porte(
    regime: str,
    zona_base: str,
    area_computavel_m2: float,
    area_lote_m2: float,
    via_acesso_m: float,
    opcao_sem_vaga: bool,
) -> list[Alerta]:
    """Devolve alertas de BLOQUEIO de uso/porte (lista vazia = sem impedimento conhecido)."""
    al: list[Alerta] = []

    def bloq(codigo: str, msg: str) -> None:
        al.append(Alerta("BLOQUEIO", codigo, msg))

    if regime == "R2V_LIVRE":
        sub = subcategoria_r2v(area_computavel_m2)
        if zona_base not in ZONAS_POR_SUBCATEGORIA[sub]:
            bloq(
                "USO_NAO_PERMITIDO",
                f"{sub} (Ac ≤ {area_computavel_m2:,.0f} m²) NÃO é permitido na zona {zona_base}.",
            )
        min_via = 8 if sub in ("R2v-1", "R2v-2") else 10
        if via_acesso_m <= min_via:
            bloq("VIA_ESTREITA", f"{sub} exige via > {min_via}m.")
        if not opcao_sem_vaga and zona_base in EIXO_ZONAS and via_acesso_m < 12:
            bloq(
                "VIA_ESTREITA_EIXO_VAGAS",
                "Em eixos, R2V com vagas exige via de 12m (Art. 4A).",
            )
        if "ZEIS" in zona_base and area_lote_m2 > 1000:
            bloq(
                "ZEIS_EXIGE_EZEIS",
                "Lotes > 1.000m² em ZEIS exigem EZEIS (bloqueia R2V livre).",
            )
    elif regime == "EHIS":
        if "ZCOR-1" in zona_base:
            bloq("USO_NAO_PERMITIDO", "EHIS não é permitido em ZCOR-1.")
        if via_acesso_m < 8:
            bloq("VIA_ESTREITA", "EHIS exige via >= 8m.")
    elif regime == "EHMP":
        if zona_base in ("ZPR", "ZER-1", "ZER-2", "ZCOR-1"):
            bloq("USO_NAO_PERMITIDO", f"EHMP não permitido em {zona_base}.")
        if via_acesso_m < 8:
            bloq("VIA_ESTREITA", "EHMP exige via >= 8m.")
    return al
