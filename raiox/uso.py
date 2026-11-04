from __future__ import annotations

import re

from raiox.urbanismo.uso_porte import (
    ZONAS_POR_SUBCATEGORIA,
    subcategoria_r2v,
    validar_uso_porte,
)

_TEXTO_SUBCATEGORIA: dict[str, str] = {
    "R2v-1": "Subcategoria pela área computável: R2v-1 (até 2.500 m²)",
    "R2v-2": "Subcategoria pela área computável: R2v-2 (até 10.000 m²)",
    "R2v-3": "Subcategoria pela área computável: R2v-3 (até 20.000 m²)",
    "R2v-4": "Subcategoria pela área computável: R2v-4 (acima de 20.000 m²)",
}

_VIA_NAO_CONFERIDA = (
    "Atenção: regra de via mínima não foi conferida "
    "(largura da via de acesso não informada)"
)
_MILHAR_EN = re.compile(r"\d{1,3}(?:,\d{3})+(?!\d)")


def _texto_motor(msg: str) -> str:
    """O motor congelado formata milhar com vírgula (42,330); a tela usa ponto (42.330)."""
    return _MILHAR_EN.sub(lambda m: m.group(0).replace(",", "."), msg)


def avaliar_uso_porte(sigla_zona: str, area_computavel_m2: float) -> list[str]:
    """Avalia enquadramento factual de uso e porte residencial (R2v) em pt-BR."""
    sub = subcategoria_r2v(area_computavel_m2)
    frase_subcategoria = _TEXTO_SUBCATEGORIA[sub]

    zonas_permitidas = ZONAS_POR_SUBCATEGORIA.get(sub, [])
    if sigla_zona in zonas_permitidas:
        frase_enquadramento = f"{sub} permitido em {sigla_zona}"
    else:
        frase_enquadramento = (
            f"{sub} não listado para {sigla_zona} na regra do motor antigo "
            "(regra sem fonte na SPEC; confira)"
        )

    return [frase_subcategoria, frase_enquadramento]


def avaliar_uso_porte_completo(
    sigla_zona: str,
    area_terreno_m2: float,
    area_computavel_m2: float,
    regime: str = "R2V",
    via_acesso_m: float | None = None,
    opcao_sem_vaga: bool = True,
) -> list[str]:
    """Avalia uso e porte completo via motor urbanístico consolidado."""
    sub = subcategoria_r2v(area_computavel_m2)
    linha_sub = _TEXTO_SUBCATEGORIA.get(
        sub, f"Subcategoria pela área computável: {sub}"
    )

    regime_upper = regime.upper()
    if regime_upper in ("R2V", "R2V_LIVRE"):
        regime_interno = "R2V_LIVRE"
        rotulo = sub
    elif regime_upper in ("EHIS", "EHMP"):
        regime_interno = regime_upper
        rotulo = regime_upper
    else:
        resultado = [
            linha_sub,
            f"Bloqueia: Regime '{regime}' não reconhecido pelo motor. (REGIME_DESCONHECIDO)",
        ]
        if via_acesso_m is None:
            resultado.append(_VIA_NAO_CONFERIDA)
        return resultado

    via_efetiva = 999.0 if via_acesso_m is None else float(via_acesso_m)
    alertas = validar_uso_porte(
        regime=regime_interno,
        zona_base=sigla_zona,
        area_computavel_m2=area_computavel_m2,
        area_lote_m2=area_terreno_m2,
        via_acesso_m=via_efetiva,
        opcao_sem_vaga=opcao_sem_vaga,
    )

    frases_motor: list[str] = []
    tem_bloqueio = any(a.nivel == "BLOQUEIO" for a in alertas)

    if tem_bloqueio:
        for a in alertas:
            if a.nivel == "BLOQUEIO":
                frases_motor.append(f"Bloqueia: {_texto_motor(a.msg)} ({a.codigo})")
            elif a.nivel == "ATENCAO":
                frases_motor.append(f"Atenção: {_texto_motor(a.msg)} ({a.codigo})")
    else:
        frases_motor.append(f"{rotulo} permitido em {sigla_zona} pela regra do motor")
        for a in alertas:
            if a.nivel == "ATENCAO":
                frases_motor.append(f"Atenção: {_texto_motor(a.msg)} ({a.codigo})")

    resultado = [linha_sub]
    resultado.extend(frases_motor)
    if via_acesso_m is None:
        resultado.append(_VIA_NAO_CONFERIDA)

    return resultado
