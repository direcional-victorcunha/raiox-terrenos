"""Motor do simulador financeiro e urbanístico do Raio-X de Terrenos SP.

Integração dos motores urbanístico (ca_engine, uso_porte) e financeiro (DRE,
resíduo do terreno, outorga onerosa, descontos e margens).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Optional

from raiox.urbanismo.ca_engine import (
    EIXO_ZONAS,
    Alerta,
    LimitesCA,
    Lote,
    MissingParameter,
    Tipologia,
    avaliar,
    checar_areas,
    descontos,
    fs_tipologia,
    garagem_nc_max,
)
from raiox.urbanismo.uso_porte import validar_uso_porte
from raiox.uso import _texto_motor


def _fmt_num(x: float, casas: int = 2) -> str:
    """Formata número no padrão pt-BR: milhar '.' e decimal ','."""
    s = f"{x:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_reais(x: float) -> str:
    """Formata valor monetário: 'R$ 10.000,00'."""
    return f"R$ {_fmt_num(x, 2)}"


def _fmt_pct(x: float, casas: int = 1) -> str:
    """Formata percentual: '12,5%'."""
    return f"{_fmt_num(x, casas)}%"


@dataclass(frozen=True)
class EntradaSimulador:
    area_liquida_m2: float
    zona_base: str
    preco_m2: float
    ca_alvo: float | None = None
    area_computavel_alvo_m2: float | None = None
    via_acesso_largura_m: float = 12.0  # padrão do app antigo (app.py:1217)
    regime: str = "R2V_LIVRE"           # "R2V_LIVRE" (ou "R2V"), "EHIS", "EHMP"
    area_privativa_media_m2: float = 40.0  # padrão do app antigo (app.py:1228)
    n_unidades: int | None = None       # se None, calculado como max(1, round(Ac / area_priv)) (app.py:1221)
    v_reais: float = 2000.0             # padrão do app antigo (app.py:1262)
    fp: float = 1.0                     # padrão do app antigo (app.py:1264)
    fs: float | None = None             # obrigatório em R2V_LIVRE; None gera ValueError
    opcao_sem_vaga: bool = True         # padrão do app antigo (app.py:1244)
    doacao_calcada_m2: float = 0.0      # padrão do app antigo (app.py:1249)
    fruicao_publica_m2: float = 0.0     # padrão do app antigo (app.py:1255)
    cota_solidariedade: bool = False    # padrão do app antigo (app.py:1211)
    area_construida_existente_m2: float = 0.0  # padrão do app antigo (app.py:1184/1188)
    custo_obra_m2: float = 3500.0       # padrão do app antigo (app.py:1387)
    custo_demolicao_m2: float = 200.0   # padrão do app antigo (app.py:1386)
    margem_lucro_desejada: float = 0.15 # padrão do app antigo (app.py:1388: 15%)
    custo_terreno: float | None = None  # opcional: custo de compra do terreno
    sql: str = ""                       # identificador opcional para auditoria


@dataclass(frozen=True)
class LinhaDRE:
    rubrica: str
    valor: float
    percentual_vgv: float | None = None
    detalhe: str = ""


@dataclass(frozen=True)
class ResultadoSimulador:
    zona_base: str
    zona_efetiva: str | None
    ca_basico: float
    ca_max_zona: float
    ca_max_produto: float
    ca_teto: float
    ca_alvo: float
    area_computavel_m2: float
    area_nc_m2: float
    area_total_construida_m2: float
    n_unidades: int
    outorga_bruta: float
    desconto_calcada: float
    desconto_fruicao: float
    descontos_total: float
    outorga_liquida: float
    vgv_total: float
    custo_obra: float
    custo_demolicao: float
    custo_terreno: float | None
    lucro_desejado: float
    residuo_terreno: float
    impostos: float
    lucro_projetado: float
    margem_projetada_pct: float
    dre: list[LinhaDRE]
    alertas: list[str]
    bloqueado: bool


def simular(entrada: EntradaSimulador) -> ResultadoSimulador:
    """Executa a simulação urbanística e financeira integrada."""
    # 0. Nenhum número pode ser NaN ou infinito
    for campo in fields(entrada):
        valor = getattr(entrada, campo.name)
        if isinstance(valor, float) and not math.isfinite(valor):
            raise ValueError(f"Valor inválido em '{campo.name}': informe um número finito.")

    # 1. Validações de parâmetros estritamente maiores que zero (<= 0)
    if entrada.area_liquida_m2 <= 0:
        raise ValueError("Área líquida do lote deve ser maior que zero.")

    if entrada.preco_m2 <= 0:
        raise ValueError("Preço por m² deve ser maior que zero.")

    if entrada.area_privativa_media_m2 <= 0:
        raise ValueError("Área privativa média deve ser maior que zero.")

    if entrada.via_acesso_largura_m <= 0:
        raise ValueError("Largura da via de acesso deve ser maior que zero.")

    # 2. Validações de parâmetros que não podem ser negativos (< 0)
    if entrada.fs is not None and entrada.fs < 0:
        raise ValueError("Fator Social (Fs) não pode ser negativo.")

    if entrada.fp < 0:
        raise ValueError("Fator de planejamento (Fp) não pode ser negativo.")

    if entrada.v_reais < 0:
        raise ValueError("Valor de metro quadrado de terreno (V) não pode ser negativo.")

    if entrada.custo_obra_m2 < 0:
        raise ValueError("Custo de obra por m² não pode ser negativo.")

    if entrada.custo_demolicao_m2 < 0:
        raise ValueError("Custo de demolição por m² não pode ser negativo.")

    if entrada.custo_terreno is not None and entrada.custo_terreno < 0:
        raise ValueError("Custo do terreno não pode ser negativo.")

    if entrada.margem_lucro_desejada < 0:
        raise ValueError("Margem de lucro desejada não pode ser negativa.")

    if entrada.area_construida_existente_m2 < 0:
        raise ValueError("Área construída existente não pode ser negativa.")

    if entrada.doacao_calcada_m2 < 0:
        raise ValueError("Área de doação de calçada não pode ser negativa.")

    if entrada.fruicao_publica_m2 < 0:
        raise ValueError("Área de fruição pública não pode ser negativa.")

    # 3. Número de unidades (validação de sinal quando fornecido)
    if entrada.n_unidades is not None and entrada.n_unidades <= 0:
        raise ValueError("Número de unidades deve ser maior que zero.")

    # 4. Validação do Regime
    regime_str = (entrada.regime or "").strip().upper()
    if regime_str == "R2V":
        regime_str = "R2V_LIVRE"

    if regime_str not in ("R2V_LIVRE", "EHIS", "EHMP"):
        raise ValueError(
            f"Regime inválido: '{entrada.regime}'. Regimes aceitos: 'R2V_LIVRE' (ou 'R2V'), 'EHIS', 'EHMP'."
        )

    # 5. CA alvo vs Área computável alvo
    if entrada.ca_alvo is not None and entrada.area_computavel_alvo_m2 is not None:
        raise ValueError("Informe ca_alvo ou area_computavel_alvo_m2, não ambos.")
    elif entrada.ca_alvo is not None:
        ca_alvo = float(entrada.ca_alvo)
        area_comp_total = ca_alvo * float(entrada.area_liquida_m2)
    elif entrada.area_computavel_alvo_m2 is not None:
        area_comp_total = float(entrada.area_computavel_alvo_m2)
        ca_alvo = area_comp_total / float(entrada.area_liquida_m2)
    else:
        raise ValueError("É obrigatório informar ca_alvo ou area_computavel_alvo_m2.")

    if ca_alvo <= 0 or area_comp_total <= 0:
        raise ValueError("CA alvo e área computável alvo devem ser maiores que zero.")

    # 6. Número de unidades (cálculo automático se None)
    if entrada.n_unidades is not None:
        n_unidades = int(entrada.n_unidades)
    else:
        n_unidades = max(1, round(area_comp_total / entrada.area_privativa_media_m2))

    # 7. Resolução do Fator Social (Fs)
    if regime_str == "EHIS":
        fs_usado = 0.0
    elif regime_str == "EHMP":
        if entrada.area_privativa_media_m2 > 70.0:
            raise ValueError("Área privativa média para EHMP não pode exceder 70 m².")
        if entrada.fs is not None:
            fs_usado = float(entrada.fs)
        else:
            fs_usado = fs_tipologia("HMP", entrada.area_privativa_media_m2)
    else:  # R2V_LIVRE (regime já validado no passo 4)
        if entrada.fs is None:
            raise ValueError("Fator Social (Fs) é obrigatório para regime R2V Livre (Quadro 5 do PDE).")
        fs_usado = float(entrada.fs)

    # 8. Validação de Uso e Porte
    alertas_uso = validar_uso_porte(
        regime=regime_str,
        zona_base=entrada.zona_base,
        area_computavel_m2=area_comp_total,
        area_lote_m2=entrada.area_liquida_m2,
        via_acesso_m=entrada.via_acesso_largura_m,
        opcao_sem_vaga=entrada.opcao_sem_vaga,
    )

    # 9. Avaliação Urbanística (ca_engine)
    lote = Lote(
        sql=entrada.sql,
        area_m2=entrada.area_liquida_m2,
        zona_base=entrada.zona_base,
        mapa_base="L18081",
        via_acesso_largura_m=entrada.via_acesso_largura_m,
    )
    tips = [Tipologia(nome="Principal", area_computavel_m2=area_comp_total, fs=fs_usado)]

    try:
        res_aval = avaliar(
            l=lote,
            regime=regime_str,
            ca_alvo=ca_alvo,
            n_unid=n_unidades,
            tips=tips,
            v=entrada.v_reais,
            fp=entrada.fp,
            cota_solidariedade=entrada.cota_solidariedade,
        )
    except (KeyError, MissingParameter) as err:
        res_aval = {
            "zona_efetiva": None,
            "limites": None,
            "outorga": {},
            "alertas": [
                Alerta(
                    nivel="BLOQUEIO",
                    codigo="PARAMETRO_INVALIDO",
                    msg=str(err),
                )
            ],
        }

    zona_efetiva = res_aval.get("zona_efetiva")
    limites: Optional[LimitesCA] = res_aval.get("limites")
    alertas_aval: list[Alerta] = res_aval.get("alertas") or []
    outorga_dict: dict = res_aval.get("outorga") or {}

    if zona_efetiva is None:
        ca_basico = 0.0
        ca_max_zona = 0.0
        ca_max_produto = 0.0
        ca_teto = 0.0
        outorga_bruta = 0.0
        c_medio = 0.0
    else:
        ca_basico = float(limites.ca_bas) if limites else 0.0
        ca_max_zona = float(limites.ca_max_zona) if limites else 0.0
        ca_max_produto = float(limites.ca_max_produto) if limites else 0.0
        ca_teto = float(limites.ca_teto) if limites else 0.0
        outorga_bruta = float(outorga_dict.get("total", 0.0))
        c_medio = float(outorga_dict.get("c_medio_por_m2", 0.0))

    # 10. Descontos da Outorga Onerosa
    desconto_calcada = 0.0
    desconto_fruicao = 0.0
    descontos_total = 0.0
    outorga_liquida = outorga_bruta
    alertas_descontos: list[str] = []

    zona_para_desc = zona_efetiva or entrada.zona_base

    if entrada.doacao_calcada_m2 > 0 and (zona_para_desc not in EIXO_ZONAS):
        alertas_descontos.append("Doação de calçada só gera desconto em zonas de eixo.")

    if outorga_bruta > 0 and (entrada.doacao_calcada_m2 > 0 or entrada.fruicao_publica_m2 > 0):
        try:
            desc = descontos(
                outorga_total=outorga_bruta,
                area_lote=entrada.area_liquida_m2,
                ca_p=ca_alvo,
                ca_bas=ca_basico,
                ca_max_zona=ca_max_zona,
                c_medio=c_medio,
                zona=zona_para_desc,
                doacao_calcada_m2=entrada.doacao_calcada_m2,
                fruicao_publica_m2=entrada.fruicao_publica_m2,
            )
            desconto_calcada = float(desc.get("calcada", 0.0) or 0.0)
            desconto_fruicao = float(desc.get("fruicao", 0.0) or 0.0)
            descontos_total = float(desc.get("total", 0.0) or 0.0)
            outorga_liquida = float(desc.get("outorga_liquida", outorga_bruta))
        except ValueError as e:
            alertas_descontos.append(f"[INFO] (FRUICAO_INVALIDA): {e}")
            if entrada.doacao_calcada_m2 > 0 and (zona_para_desc in EIXO_ZONAS):
                try:
                    desc_c = descontos(
                        outorga_total=outorga_bruta,
                        area_lote=entrada.area_liquida_m2,
                        ca_p=ca_alvo,
                        ca_bas=ca_basico,
                        ca_max_zona=ca_max_zona,
                        c_medio=c_medio,
                        zona=zona_para_desc,
                        doacao_calcada_m2=entrada.doacao_calcada_m2,
                        fruicao_publica_m2=0.0,
                    )
                    desconto_calcada = float(desc_c.get("calcada", 0.0) or 0.0)
                    descontos_total = float(desc_c.get("total", 0.0) or 0.0)
                    outorga_liquida = float(desc_c.get("outorga_liquida", outorga_bruta))
                except ValueError as err_c:
                    alertas_descontos.append(f"Desconto de calçada não aplicado: {err_c}")

    soma_descontos = desconto_calcada + desconto_fruicao
    if soma_descontos > outorga_bruta:
        alertas_descontos.append(
            f"Descontos ({_fmt_reais(soma_descontos)}) maiores que a outorga bruta "
            f"({_fmt_reais(outorga_bruta)}): a outorga líquida fica em zero; confira as áreas de calçada e fruição."
        )

    # 11. Estimativa de Área Não Computável e Checagem de Áreas
    area_priv_total = entrada.area_privativa_media_m2 * n_unidades
    if entrada.opcao_sem_vaga:
        nc_ord = area_comp_total * 0.10
    elif zona_efetiva and (zona_efetiva in EIXO_ZONAS):
        g = garagem_nc_max(
            zona_efetiva,
            [entrada.area_privativa_media_m2] * n_unidades,
            area_priv_total,
        )
        nc_ord = float(g.get("area_nc_max", 0.0))
    else:
        nc_ord = 32.0 * float(n_unidades)

    area_total_construida = area_comp_total + nc_ord
    _, alertas_areas = checar_areas(area_comp_total, nc_ord)

    # 12. Consolidação dos Alertas e Bloqueios
    alertas_finais: list[str] = []
    todos_alertas_obj = list(alertas_uso) + list(alertas_aval) + list(alertas_areas)

    bloqueado = (zona_efetiva is None) or any(
        a.nivel == "BLOQUEIO" for a in todos_alertas_obj
    )

    for a in todos_alertas_obj:
        alertas_finais.append(f"[{a.nivel}] ({a.codigo}): {_texto_motor(a.msg)}")

    for msg in alertas_descontos:
        alertas_finais.append(_texto_motor(msg))
        if msg.startswith("[BLOQUEIO]"):
            bloqueado = True

    if bloqueado:
        alertas_finais.append("Resultado com bloqueio legal: confira antes de usar os números")

    # 13. Cálculos Financeiros e DRE Simplificada
    vgv_total = round(area_comp_total * entrada.preco_m2, 2)
    custo_demolicao = round(
        entrada.area_construida_existente_m2 * entrada.custo_demolicao_m2, 2
    )
    custo_obra = round(area_total_construida * entrada.custo_obra_m2, 2)
    lucro_desejado = round(vgv_total * entrada.margem_lucro_desejada, 2)
    residuo_terreno = round(
        vgv_total - custo_obra - outorga_liquida - custo_demolicao - lucro_desejado, 2
    )
    impostos = 0.0

    if entrada.custo_terreno is not None:
        custo_terreno = float(entrada.custo_terreno)
        custo_total = custo_obra + outorga_liquida + custo_demolicao + custo_terreno
        lucro_projetado = round(vgv_total - custo_total, 2)
        margem_projetada_pct = (
            round((lucro_projetado / vgv_total * 100.0), 4) if vgv_total > 0 else 0.0
        )
    else:
        custo_terreno = None
        lucro_projetado = lucro_desejado
        margem_projetada_pct = round(entrada.margem_lucro_desejada * 100.0, 4)

    def _pct(v: float) -> float | None:
        return round((v / vgv_total * 100.0), 2) if vgv_total > 0 else 0.0

    dre = [
        LinhaDRE(
            rubrica="Receita Bruta (VGV)",
            valor=vgv_total,
            percentual_vgv=100.0,
            detalhe=f"{_fmt_num(area_comp_total, 2)} m² computáveis a {_fmt_reais(entrada.preco_m2)}/m²",
        ),
        LinhaDRE(
            rubrica="Custo de Obra",
            valor=custo_obra,
            percentual_vgv=_pct(custo_obra),
            detalhe=f"{_fmt_num(area_total_construida, 2)} m² totais a {_fmt_reais(entrada.custo_obra_m2)}/m²",
        ),
        LinhaDRE(
            rubrica="Outorga Onerosa Líquida",
            valor=outorga_liquida,
            percentual_vgv=_pct(outorga_liquida),
            detalhe=f"Bruta {_fmt_reais(outorga_bruta)} - Descontos {_fmt_reais(descontos_total)}",
        ),
        LinhaDRE(
            rubrica="Custo de Demolição",
            valor=custo_demolicao,
            percentual_vgv=_pct(custo_demolicao),
            detalhe=f"{_fmt_num(entrada.area_construida_existente_m2, 2)} m² existentes a {_fmt_reais(entrada.custo_demolicao_m2)}/m²",
        ),
        LinhaDRE(
            rubrica="Impostos",
            valor=0.0,
            percentual_vgv=0.0,
            detalhe="Modelo simplificado (impostos inclusos na margem líquida)",
        ),
    ]

    if custo_terreno is not None:
        dre.append(
            LinhaDRE(
                rubrica="Custo do Terreno",
                valor=custo_terreno,
                percentual_vgv=_pct(custo_terreno),
                detalhe="Custo de aquisição informado",
            )
        )

    dre.append(
        LinhaDRE(
            rubrica="Lucro Projetado",
            valor=lucro_projetado,
            percentual_vgv=round(margem_projetada_pct, 2),
            detalhe=(
                f"Margem projetada de {_fmt_pct(margem_projetada_pct, 1)} sobre VGV"
                if custo_terreno is not None
                else f"Margem desejada de {_fmt_pct(entrada.margem_lucro_desejada * 100, 1)} sobre VGV"
            ),
        )
    )

    dre.append(
        LinhaDRE(
            rubrica="Resíduo do Terreno",
            valor=residuo_terreno,
            percentual_vgv=_pct(residuo_terreno),
            detalhe="Capacidade máxima de pagamento pelo terreno considerando margem desejada",
        )
    )

    return ResultadoSimulador(
        zona_base=entrada.zona_base,
        zona_efetiva=zona_efetiva,
        ca_basico=ca_basico,
        ca_max_zona=ca_max_zona,
        ca_max_produto=ca_max_produto,
        ca_teto=ca_teto,
        ca_alvo=round(ca_alvo, 4),
        area_computavel_m2=round(area_comp_total, 2),
        area_nc_m2=round(nc_ord, 2),
        area_total_construida_m2=round(area_total_construida, 2),
        n_unidades=n_unidades,
        outorga_bruta=round(outorga_bruta, 2),
        desconto_calcada=round(desconto_calcada, 2),
        desconto_fruicao=round(desconto_fruicao, 2),
        descontos_total=round(descontos_total, 2),
        outorga_liquida=round(outorga_liquida, 2),
        vgv_total=vgv_total,
        custo_obra=custo_obra,
        custo_demolicao=custo_demolicao,
        custo_terreno=custo_terreno,
        lucro_desejado=lucro_desejado,
        residuo_terreno=residuo_terreno,
        impostos=impostos,
        lucro_projetado=lucro_projetado,
        margem_projetada_pct=margem_projetada_pct,
        dre=dre,
        alertas=alertas_finais,
        bloqueado=bloqueado,
    )
