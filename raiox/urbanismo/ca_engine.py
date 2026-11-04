# Cópia congelada de prospeccao-marechal-tito/core/ca_engine.py em 2026-10-28.
"""
ca_engine.py — motor de referência: potencial construtivo (CA) e outorga onerosa, São Paulo, USO RESIDENCIAL.
Data-base da legislação: 30/09/2026.  Ver SPEC_motor_CA_SP.md (fonte de verdade das regras e origens).

Princípios:
  1. Parâmetro que não foi verificado em fonte oficial (V, Fp, Fs geral, FQA) NUNCA tem default:
     o motor levanta MissingParameter em vez de devolver número plausível e errado.
  2. Tudo que é [Inferência] está marcado no docstring da função.
  3. O motor devolve (resultado, alertas). Alerta de nível BLOQUEIO impede decisão automática.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal
from math import ceil, floor
from typing import Optional


class MissingParameter(Exception):
    """Parâmetro obrigatório sem valor oficial verificado."""


# ----------------------------------------------------------------------------------------------
# 1. TABELAS DE REFERÊNCIA
# ----------------------------------------------------------------------------------------------
# Quadro 3 da LPUOS (cópia consolidada plpconsulta). ALERTA: art. 72, I da Lei 18.081/2024 altera o quadro
# e não foi lido -> conferir. Campos: ca_bas, ca_max, gab (m; None = sem limite/NA), cp_max (m²/UH; None = NA)
ZONAS = {
    "ZEU": dict(ca_bas=1, ca_max=4, gab=None, cp_max=20),
    "ZEUa": dict(ca_bas=1, ca_max=2, gab=28, cp_max=40),
    "ZEUP": dict(ca_bas=1, ca_max=2, gab=28, cp_max=None),
    "ZEUPa": dict(ca_bas=1, ca_max=1, gab=28, cp_max=None),
    "ZEM": dict(
        ca_bas=1, ca_max=2, gab=28, cp_max=20
    ),  # ca_max 4 nos casos do art. 8º §1º
    "ZEMP": dict(
        ca_bas=1, ca_max=2, gab=28, cp_max=40
    ),  # ca_max 4 nos casos do art. 8º §2º
    "ZC": dict(ca_bas=1, ca_max=2, gab=48, cp_max=None),
    "ZCa": dict(ca_bas=1, ca_max=1, gab=20, cp_max=None),
    "ZC-ZEIS": dict(ca_bas=1, ca_max=2, gab=None, cp_max=None),
    "ZCOR-1": dict(ca_bas=1, ca_max=1, gab=10, cp_max=None),
    "ZCOR-2": dict(ca_bas=1, ca_max=1, gab=10, cp_max=None),
    "ZCOR-3": dict(
        ca_bas=1, ca_max=1, gab=10, cp_max=None
    ),  # Eusébio Matoso/Rebouças: +50% (art. 91 V)
    "ZM": dict(ca_bas=1, ca_max=2, gab=28, cp_max=None),
    "ZMa": dict(ca_bas=1, ca_max=1, gab=15, cp_max=None),
    "ZMIS": dict(ca_bas=1, ca_max=2, gab=28, cp_max=None),
    "ZEIS-1": dict(ca_bas=1, ca_max=2.5, gab=None, cp_max=None),
    "ZEIS-2": dict(ca_bas=1, ca_max=4, gab=None, cp_max=None),
    "ZEIS-3": dict(ca_bas=1, ca_max=4, gab=None, cp_max=None),
    "ZEIS-4": dict(ca_bas=1, ca_max=2, gab=None, cp_max=None),
    "ZEIS-5": dict(ca_bas=1, ca_max=4, gab=None, cp_max=None),
    "ZDE-1": dict(ca_bas=1, ca_max=2, gab=28, cp_max=None),
    "ZDE-2": dict(ca_bas=1, ca_max=2, gab=28, cp_max=None),
    "ZPR": dict(ca_bas=1, ca_max=1, gab=10, cp_max=None),
    "ZER-1": dict(ca_bas=1, ca_max=1, gab=10, cp_max=None),
    "ZER-2": dict(ca_bas=1, ca_max=1, gab=10, cp_max=None),
}
EIXO_ZONAS = {"ZEU", "ZEUa", "ZEUP", "ZEUPa", "ZEM", "ZEMP"}
# Notas de condição do Quadro 3: (zona -> (limite de área do lote, ca_max se lote < limite))
ZEIS_LOTE_PEQUENO = {
    "ZEIS-1": (1000, 2),
    "ZEIS-2": (1000, 2),
    "ZEIS-3": (500, 2),
    "ZEIS-4": (1000, 1),
    "ZEIS-5": (1000, 2),
}

# Lei 18.081/2024 art. 3º §2º. Rebaixamentos de zona quando os parâmetros de eixo não se aplicam.
REBAIXA_ACESSO = {"ZEU": "ZM", "ZEUa": "ZMa", "ZEUP": "ZM", "ZEUPa": "ZMa"}  # inciso IV
REBAIXA_DEMAIS = {
    "ZEU": "ZC",
    "ZEUa": "ZCa",
    "ZEUP": "ZM",
    "ZEUPa": "ZMa",
}  # incisos V–VIII

# Multiplicadores de CAmáx por produto. [Inferência] a partir da nota (b) do Quadro 2 do PDE/2014 e de
# relato técnico do Decreto 63.728/2024. CONFIRMAR no Quadro 2 do decreto (o quadro é imagem no PDF).
MULT_PRODUTO = {"R2V_LIVRE": 1.0, "EHMP": 1.25, "EHIS": 1.5}


# Fs por tipologia com valor oficial verificado (Decreto 63.504 art. 27; Decreto 63.728 arts. 19-20).
def fs_tipologia(tipo: str, area_priv_m2: Optional[float] = None) -> float:
    if tipo == "HIS":
        return 0.0  # isento (EHIS gratuito; HIS em EHMP isento)
    if tipo == "HMP":
        if area_priv_m2 is None:
            raise MissingParameter(
                "HMP exige a área computável privativa da unidade (Fs 0,4 até 50 m²; 0,6 de 50 a 70 m²)."
            )
        if area_priv_m2 <= 50:
            return 0.4
        if area_priv_m2 <= 70:
            return 0.6
        raise ValueError("HMP acima de 70 m² não é HMP (Decreto 63.728 art. 4º).")
    raise MissingParameter(
        f"Fs de '{tipo}' vem do Quadro 5 do PDE (não verificado). Informe manualmente."
    )


# ----------------------------------------------------------------------------------------------
# 2. ENTRADAS
# ----------------------------------------------------------------------------------------------
@dataclass
class Lote:
    sql: str
    area_m2: float  # At
    zona_base: str  # zona do mapa de referência
    mapa_base: str  # "L18081" | "L18177_art8" (ver alerta judicial)
    perimetro_especial: Optional[str] = None  # OUC/PIU/AIU: sai do regime geral
    via_acesso_largura_m: Optional[float] = (
        None  # via do acesso de VEÍCULOS previsto no PROJETO
    )
    acesso_unica_frente_rua_sem_saida: bool = False
    vila: bool = False
    restricoes: set = field(default_factory=set)  # ver RESTRICOES_VALIDAS
    zeup_ativada: bool = False  # decreto/constatação de operação do transporte
    zem_ca4: bool = False  # art. 8º §1º/§2º da Lei 16.402
    zona_alt_mapa: Optional[str] = None  # zona no OUTRO mapa (para status_judicial)


RESTRICOES_VALIDAS = {
    "ZEPEC",
    "PARQUE_PREVISTO",
    "TICP_BIXIGA_INTEGRAL",
    "APP_NASCENTE_GT50",
    "RISCO_INTEGRAL",
    "MATA_GT50",
    "RESERVATORIO_PLUVIAL",
}


@dataclass
class Alerta:
    nivel: str  # BLOQUEIO | ATENCAO | INFO
    codigo: str
    msg: str


# ----------------------------------------------------------------------------------------------
# 3. ZONA EFETIVA
# ----------------------------------------------------------------------------------------------
def resolver_zona_efetiva(l: Lote) -> tuple[Optional[str], list[Alerta]]:
    """Lei 18.081/2024 art. 3º (red. Lei 18.177). Ordem de precedência abaixo. CONFIRMADO."""
    al: list[Alerta] = []
    inval = l.restricoes - RESTRICOES_VALIDAS
    if inval:
        raise ValueError(f"restrições desconhecidas: {inval}")
    if l.perimetro_especial:
        al.append(
            Alerta(
                "BLOQUEIO",
                "PERIMETRO_ESPECIAL",
                f"Lote em {l.perimetro_especial}: usar lei específica (CA, Fp/Fs e estoque próprios).",
            )
        )
        return None, al
    z = l.zona_base
    if z in ("ZEUP", "ZEUPa") and l.zeup_ativada:
        z = {"ZEUP": "ZEU", "ZEUPa": "ZEUa"}[z]
    if "ZEPEC" in l.restricoes:
        al.append(
            Alerta(
                "BLOQUEIO",
                "ZEPEC",
                "ZEPEC: parâmetros de eixo não se aplicam; análise manual.",
            )
        )
        return None, al
    if "PARQUE_PREVISTO" in l.restricoes:
        al.append(
            Alerta("BLOQUEIO", "PARQUE", "Parque previsto: parâmetros de ZEPAM/ZEP.")
        )
        return None, al
    if l.vila:
        return "ZPR", al + [
            Alerta(
                "ATENCAO", "VILA", "Vila reconhecida: parâmetros de ZPR (art. 64 VI)."
            )
        ]
    if "TICP_BIXIGA_INTEGRAL" in l.restricoes:
        return "ZM", al + [
            Alerta(
                "ATENCAO",
                "TICP_BIXIGA",
                "Integralmente no TICP Bixiga: parâmetros de ZM.",
            )
        ]
    if z in REBAIXA_ACESSO:
        acesso_estreito = l.acesso_unica_frente_rua_sem_saida or (
            l.via_acesso_largura_m is not None and l.via_acesso_largura_m <= 10
        )
        if acesso_estreito:
            return REBAIXA_ACESSO[z], al + [
                Alerta(
                    "ATENCAO",
                    "ACESSO_ESTREITO",
                    f"Acesso de veículos por via ≤10 m/rua sem saída: {z} -> {REBAIXA_ACESSO[z]}.",
                )
            ]
        if l.restricoes & {
            "APP_NASCENTE_GT50",
            "RISCO_INTEGRAL",
            "MATA_GT50",
            "RESERVATORIO_PLUVIAL",
        }:
            al.append(
                Alerta(
                    "ATENCAO",
                    "RESTRICAO_AMBIENTAL",
                    f"Restrição ambiental: {z} -> {REBAIXA_DEMAIS[z]}.",
                )
            )
            if l.restricoes == {"RISCO_INTEGRAL"}:
                al.append(
                    Alerta(
                        "INFO",
                        "RISCO_MITIGAVEL",
                        "Área de risco pode manter ZEU com parecer técnico de mitigação (art. 3º §1º).",
                    )
                )
            return REBAIXA_DEMAIS[z], al
        if l.via_acesso_largura_m is None:
            al.append(
                Alerta(
                    "ATENCAO",
                    "ACESSO_NAO_INFORMADO",
                    "Largura da via de acesso não informada: potencial pode estar superestimado.",
                )
            )
    if l.zona_alt_mapa and l.zona_alt_mapa != l.zona_base:
        al.append(
            Alerta(
                "ATENCAO",
                "STATUS_JUDICIAL_MAPA",
                f"Zona difere entre mapas ({l.zona_base} x {l.zona_alt_mapa}); TJSP 26/08/2026.",
            )
        )
    return z, al


# ----------------------------------------------------------------------------------------------
# 4. LIMITES DE CA
# ----------------------------------------------------------------------------------------------
@dataclass
class LimitesCA:
    zona: str
    ca_bas: float
    ca_max_zona: float
    ca_max_produto: float
    acrescimo_cota_solidariedade: float
    ca_teto: float


def limites_ca(
    zona: str,
    area_lote: float,
    regime: str,
    l: Optional[Lote] = None,
    cota_solidariedade: bool = False,
    cs_obrigatoria: bool = False,
    mult: Optional[dict] = None,
) -> LimitesCA:
    """
    CA_max_zona: Quadro 3 + notas de condição.            CONFIRMADO (Quadro 3, notas d–h).
    CA_max_produto = CA_max_zona × MULT_PRODUTO[regime].  [Inferência] — confirmar Quadro 2 do Dec. 63.728.
    Cota de solidariedade: +20% da base; base = CA_max_produto se EHIS/EHMP ou obrigatória; senão CA_max_zona.
                                                          CONFIRMADO (Dec. 63.504 art. 8º; Dec. 64.901/2026).
    """
    mult = mult or MULT_PRODUTO
    if zona not in ZONAS:
        raise KeyError(f"Zona sem parâmetros: {zona}")
    zp = ZONAS[zona]
    ca_max = zp["ca_max"]
    if zona in ZEIS_LOTE_PEQUENO:
        lim, ca_peq = ZEIS_LOTE_PEQUENO[zona]
        if area_lote < lim:
            ca_max = ca_peq
    if zona in ("ZEM", "ZEMP") and l is not None and l.zem_ca4:
        ca_max = 4
    if regime not in mult:
        raise ValueError(f"regime inválido: {regime}")
    ca_prod = ca_max * mult[regime]
    base = ca_prod if (regime in ("EHIS", "EHMP") or cs_obrigatoria) else ca_max
    acr = 0.2 * base if cota_solidariedade else 0.0
    return LimitesCA(zona, zp["ca_bas"], ca_max, ca_prod, acr, ca_prod + acr)


# ----------------------------------------------------------------------------------------------
# 5. COTA-PARTE (Q) E FS MAJORADO
# ----------------------------------------------------------------------------------------------
def fs_por_cota_parte(q: float) -> float:
    """Dec. 63.504 art. 5º: Q arredondado p/ cima em passos de 0,25; Fs = 1 + (Q-20)/10 entre 20 e 30.
    Acima de 30: Fs 3 (Lei 18.157 §10), exceto HIS/HMP. CONFIRMADO. Vale só p/ UH com área computável privativa > 70 m².
    """
    qc = ceil(q * 4 - 1e-9) / 4
    if qc <= 20:
        return 1.0
    if qc <= 30:
        return round(1 + (qc - 20) / 10, 3)
    return 3.0


def cota_parte(
    ca_p: float,
    area_lote: float,
    ca_max_zona: float,
    n_unid: int,
    zona: str,
    regime: str,
) -> tuple[dict, list[Alerta]]:
    """Q = (CAu·At)/(CAmáx·N)  == área computável média por unidade / CAmáx.  CONFIRMADO (Dec. 63.504 art. 4º).
    Aplica-se ao residencial (exceto R1, R2h) em ZEU/ZEUa/ZEM/ZEMP (Dec. 63.884 — fonte SECUNDÁRIA).
    """
    al: list[Alerta] = []
    if zona not in ("ZEU", "ZEUa", "ZEM", "ZEMP"):
        return dict(aplica=False, q=None, fs_maj=1.0), al
    q = ca_p * area_lote / (ca_max_zona * n_unid)
    cp_max = ZONAS[zona]["cp_max"]
    out = dict(
        aplica=True,
        q=q,
        area_media_computavel=q * ca_max_zona,
        cp_max=cp_max,
        fs_maj=1.0,
    )
    if regime in ("EHIS", "EHMP"):
        if q > cp_max:
            al.append(
                Alerta(
                    "BLOQUEIO",
                    "COTA_PARTE_EXCEDIDA",
                    f"Q={q:.2f} > {cp_max} m²/UH em {regime} (Dec. 63.728 art. 14 VI); §§9-10 do art. 79 não se aplicam.",
                )
            )
        return out, al
    if cp_max == 20:
        out["fs_maj"] = fs_por_cota_parte(q)
        if q > 20:
            al.append(
                Alerta(
                    "ATENCAO",
                    "COTA_PARTE_MAJORADA",
                    f"Q={q:.2f}: UH >70 m² computáveis pagam Fs majorado {out['fs_maj']}.",
                )
            )
    else:
        al.append(
            Alerta(
                "ATENCAO",
                "COTA_PARTE_REVISAR",
                f"{zona} tem cota-parte máx. {cp_max}; escalonamento do Fs não verificado para este caso.",
            )
        )
    return out, al


# ----------------------------------------------------------------------------------------------
# 6. OUTORGA
# ----------------------------------------------------------------------------------------------
def _ceil_cent(x: float) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_CEILING))


@dataclass
class Tipologia:
    nome: str
    area_computavel_m2: float
    fs: float


def outorga(
    area_lote: float,
    ca_bas: float,
    tips: list[Tipologia],
    v: Optional[float],
    fp: Optional[float],
) -> dict:
    """
    Decreto 63.504 art. 3º, 6º e 7º.                                                   CONFIRMADO
      C_t      = (At/Ac) · V · Fp · Fs_t                (R$/m² adicional da tipologia t)
      pot_bas_t = At·CAbás · Ac_t/Ac                    (art. 6º I: terreno rateado pela área computável)
      adic_t   = max(0, Ac_t − pot_bas_t)
      total    = Σ C_t · adic_t          (arredondado p/ cima ao centavo)
    Simplificações algébricas:                                                          [Inferência]
      total    = At·V·Fp·(1 − CAbás/CAp)·Fs_médio   (Fs_médio ponderado por Ac_t)
      marginal = V·Fp·Fs_médio·CAbás/CAp²
    """
    if v is None or fp is None:
        raise MissingParameter(
            "V (Quadro 14) e Fp (Quadro 6) precisam vir de fonte oficial vigente."
        )
    ac = sum(t.area_computavel_m2 for t in tips)
    if ac <= 0:
        raise ValueError("área computável total deve ser > 0")
    ca_p = ac / area_lote
    linhas, total, adic_total = [], 0.0, 0.0
    for t in tips:
        pot_bas = area_lote * ca_bas * t.area_computavel_m2 / ac
        adic = max(0.0, t.area_computavel_m2 - pot_bas)
        c = area_lote / ac * v * fp * t.fs
        linhas.append(
            dict(tipologia=t.nome, c_por_m2=c, adicional_m2=adic, valor=c * adic)
        )
        total += c * adic
        adic_total += adic
    fs_med = sum(t.fs * t.area_computavel_m2 for t in tips) / ac
    return dict(
        ac=ac,
        ca_p=ca_p,
        adicional_m2=adic_total,
        total=_ceil_cent(total),
        c_medio_por_m2=(total / adic_total if adic_total else 0.0),
        fs_medio=fs_med,
        marginal_por_m2=v * fp * fs_med * ca_bas / ca_p**2 if ca_p > 0 else 0.0,
        linhas=linhas,
    )


def descontos(
    outorga_total: float,
    area_lote: float,
    ca_p: float,
    ca_bas: float,
    ca_max_zona: float,
    c_medio: float,
    zona: str,
    doacao_calcada_m2: float = 0.0,
    fruicao_publica_m2: float = 0.0,
    fqa: Optional[float] = None,
    usar_qa: bool = False,
    fc_certificacao: Optional[float] = None,
) -> dict:
    """Todos [Inferência] quanto à composição; fórmulas de IQA e IC são CONFIRMADAS (Lei 18.081 arts. 82-83).
    - calçada (eixos): sem outorga sobre o potencial MÁXIMO da área doada  -> c_medio × área × CAmáx_zona
    - fruição pública (lote ≤10.000 m², ≥250 m²): metade do adicional da área -> 0,5 × c_medio × área × (CAmáx − CAbás)
    - IQA = 2(CAp−1)/CAp × FQA × At      (FQA: Quadro 3C — não verificado; obrigatório se usar_qa)
    - IC  = FC × At × CAp,  FC entre R$56 e R$300/m²  (não cumulativo com IQA — conferir se o §10 foi mantido)
    Teto: o desconto total não passa da outorga."""
    d = {}
    if doacao_calcada_m2 and zona in EIXO_ZONAS:
        d["calcada"] = c_medio * doacao_calcada_m2 * ca_max_zona
    if fruicao_publica_m2:
        if fruicao_publica_m2 < 250 or area_lote > 10000:
            raise ValueError(
                "Fruição pública exige área ≥250 m² e lote ≤10.000 m² (LPUOS art. 88)."
            )
        d["fruicao"] = 0.5 * c_medio * fruicao_publica_m2 * (ca_max_zona - ca_bas)
    iqa = ic = 0.0
    if usar_qa:
        if fqa is None:
            raise MissingParameter("FQA (Quadro 3C da LPUOS) não verificado.")
        iqa = 2 * (ca_p - 1) / ca_p * fqa * area_lote
    if fc_certificacao is not None:
        if not 56 <= fc_certificacao <= 300:
            raise ValueError("FC deve estar entre 56 e 300 R$/m² (Lei 18.081 art. 49).")
        ic = fc_certificacao * area_lote * ca_p
    d["qa_ou_certificacao"] = max(iqa, ic)
    bruto = sum(d.values())
    d["total"] = min(bruto, outorga_total)
    d["outorga_liquida"] = _ceil_cent(outorga_total - d["total"])
    return d


# ----------------------------------------------------------------------------------------------
# 7. ÁREAS NÃO COMPUTÁVEIS (camada 2)
# ----------------------------------------------------------------------------------------------
def garagem_nc_max(
    zona: str, areas_computaveis_uh: list[float], area_privativa_total: float
) -> dict:
    """Lei 18.081 art. 34 (novo art. 62 I a). Em eixos: vagas = max(nº UH com ≥30 m² computáveis ; ⌊priv_total/60⌋);
    área não computável de garagem ≤ 32 m² × vagas. Fora dos eixos: garagem integral é não computável
    (limitada só pelo teto de 59%). CONFIRMADO."""
    if zona not in EIXO_ZONAS:
        return dict(vagas=None, area_nc_max=None)
    v1 = sum(1 for a in areas_computaveis_uh if a >= 30)
    v2 = floor(area_privativa_total / 60)
    vagas = max(v1, v2)
    return dict(vagas=vagas, area_nc_max=32.0 * vagas, opcao1=v1, opcao2=v2)


def checar_areas(
    ac: float, nc_ordinaria: float, nc_sustentavel: float = 0.0
) -> tuple[dict, list[Alerta]]:
    """Art. 62 §2º: NC ordinárias (incisos I–VI) ≤ 59% da área construída total sem incentivos (VII–XVI):
        nc_ord ≤ 0,59·(Ac + nc_ord)  <=>  nc_ord ≤ Ac·59/41.        CONFIRMADO (texto) / álgebra [Inferência]
    Art. 10 (Lei 18.081): incentivos sustentáveis somam ≤ 10% de Ac, fora do teto de 59%.
    """
    al: list[Alerta] = []
    nc_max = ac * 59 / 41
    if nc_ordinaria > nc_max + 1e-9:
        al.append(
            Alerta(
                "BLOQUEIO",
                "NC_ACIMA_59",
                f"NC ordinária {nc_ordinaria:.0f} m² > máx. {nc_max:.0f} m².",
            )
        )
    if nc_sustentavel > 0.10 * ac + 1e-9:
        al.append(
            Alerta(
                "BLOQUEIO",
                "NC_SUSTENTAVEL_ACIMA_10",
                f"Incentivos sustentáveis {nc_sustentavel:.0f} m² > 10% de Ac.",
            )
        )
    return (
        dict(
            nc_ord_max=nc_max,
            nc_sust_max=0.10 * ac,
            area_total=ac + nc_ordinaria + nc_sustentavel,
        ),
        al,
    )


# ----------------------------------------------------------------------------------------------
# 8. ORQUESTRAÇÃO
# ----------------------------------------------------------------------------------------------
def avaliar(
    l: Lote,
    regime: str,
    ca_alvo: float,
    n_unid: int,
    tips: list[Tipologia],
    v: Optional[float],
    fp: Optional[float],
    cota_solidariedade: bool = False,
    cs_obrigatoria: bool = False,
) -> dict:
    zona, al = resolver_zona_efetiva(l)
    if zona is None:
        return dict(zona_efetiva=None, alertas=al)
    lim = limites_ca(zona, l.area_m2, regime, l, cota_solidariedade, cs_obrigatoria)
    if ca_alvo > lim.ca_teto + 1e-9:
        al.append(
            Alerta(
                "BLOQUEIO",
                "CA_ACIMA_DO_TETO",
                f"CA alvo {ca_alvo} > teto {lim.ca_teto:.2f}.",
            )
        )
    cp, al2 = cota_parte(ca_alvo, l.area_m2, lim.ca_max_zona, n_unid, zona, regime)
    al += al2
    res = dict(zona_efetiva=zona, limites=lim, cota_parte=cp)
    if regime == "EHIS":
        gratis_ca = lim.ca_max_produto
        if ca_alvo <= gratis_ca + 1e-9:
            res["outorga"] = dict(
                total=0.0,
                nota="EHIS: outorga gratuita até o CAmáx (Dec. 63.728 art. 19).",
            )
        else:
            al.append(
                Alerta(
                    "ATENCAO",
                    "EHIS_EXCEDENTE",
                    "CA acima do CAmáx de EHIS (cota de solidariedade): excedente paga outorga; Fs do excedente NÃO verificado.",
                )
            )
            raise MissingParameter(
                "Fs do excedente em EHIS (acréscimo da cota de solidariedade) não verificado."
            )
    else:
        res["outorga"] = outorga(l.area_m2, lim.ca_bas, tips, v, fp)
    res["alertas"] = al
    return res


# ----------------------------------------------------------------------------------------------
# 9. TESTES (valores esperados calculados à mão a partir das fórmulas dos decretos)
# ----------------------------------------------------------------------------------------------
def _approx(a, b, tol=0.01):
    assert abs(a - b) <= tol, f"{a} != {b}"


def _testes():
    # T1 — zona efetiva: ZEU com acesso de 9 m cai para ZM (CAmáx 2)
    l = Lote("T1", 1000, "ZEU", "L18081", via_acesso_largura_m=9)
    z, _ = resolver_zona_efetiva(l)
    assert z == "ZM"
    assert limites_ca(z, 1000, "R2V_LIVRE").ca_max_zona == 2

    # T2 — ZEU com acesso de 12 m mantém ZEU (CAmáx 4)
    l = Lote("T2", 1000, "ZEU", "L18081", via_acesso_largura_m=12)
    z, _ = resolver_zona_efetiva(l)
    assert z == "ZEU" and limites_ca(z, 1000, "R2V_LIVRE").ca_max_zona == 4

    # T3 — outorga R2V livre: At=1000, CAp=4, V=3000 (exemplo), Fp=1, Fs=1
    r = outorga(1000, 1, [Tipologia("R2V", 4000, 1.0)], 3000, 1.0)
    _approx(r["total"], 2_250_000.00)
    _approx(r["c_medio_por_m2"], 750.0)
    _approx(r["marginal_por_m2"], 187.5)

    # T4 — cota-parte: 45 UH em ZEU, CAp 4 -> Q=22,22 -> Q arred. 22,25 -> Fs 1,225
    cp, _ = cota_parte(4, 1000, 4, 45, "ZEU", "R2V_LIVRE")
    _approx(cp["q"], 22.2222, 0.001)
    assert cp["fs_maj"] == 1.225
    r = outorga(1000, 1, [Tipologia("R2V>70", 4000, cp["fs_maj"])], 3000, 1.0)
    _approx(r["total"], 2_756_250.00)

    # T5 — EHMP em ZEU, CAmáx produto 5 (1,25×4), 100% HMP ≤50 m² (Fs 0,4), At=1000, V=3000, Fp=1
    lim = limites_ca("ZEU", 1000, "EHMP")
    assert lim.ca_max_produto == 5.0
    r = outorga(
        1000, 1, [Tipologia("HMP<=50", 5000, fs_tipologia("HMP", 45))], 3000, 1.0
    )
    _approx(r["total"], 960_000.00)

    # T6 — EHIS em ZEU: CAmáx produto 6, outorga zero até 6
    l = Lote("T6", 1000, "ZEU", "L18081", via_acesso_largura_m=12)
    res = avaliar(l, "EHIS", 6.0, 100, [Tipologia("HIS", 6000, 0.0)], None, None)
    assert res["outorga"]["total"] == 0.0 and res["limites"].ca_max_produto == 6.0

    # T7 — cota de solidariedade opcional em EHIS: +20% de 6 = +1,2 -> teto 7,2
    assert (
        abs(limites_ca("ZEU", 1000, "EHIS", cota_solidariedade=True).ca_teto - 7.2)
        < 1e-9
    )

    # T8 — garagem em eixo: 60 UH com ≥30 m² e 3.200 m² privativos -> opção1=60, opção2=53 -> 60 vagas, 1.920 m²
    g = garagem_nc_max("ZEU", [45.0] * 60, 3200)
    assert g["vagas"] == 60 and g["area_nc_max"] == 1920.0 and g["opcao2"] == 53

    # T9 — teto de 59%: Ac=4000 -> NC ordinária máx = 4000·59/41 = 5756,1
    r, al = checar_areas(4000, 5800)
    _approx(r["nc_ord_max"], 5756.1, 0.1)
    assert any(a.codigo == "NC_ACIMA_59" for a in al)

    # T10 — descontos: IC com FC=56, At=1000, CAp=4 -> R$ 224.000; teto no valor da outorga
    d = descontos(2_250_000, 1000, 4, 1, 4, 750, "ZEU", fc_certificacao=56)
    _approx(d["qa_ou_certificacao"], 224_000.0)
    _approx(d["outorga_liquida"], 2_026_000.00)

    # T11 — falha segura: sem V/Fp o motor não devolve número
    try:
        outorga(1000, 1, [Tipologia("R2V", 4000, 1.0)], None, 1.0)
        raise SystemExit("deveria falhar")
    except MissingParameter:
        pass

    # T12 — perímetro especial bloqueia o regime geral
    z, al = resolver_zona_efetiva(
        Lote("T12", 1000, "ZC", "L18081", perimetro_especial="AIU-SCE")
    )
    assert z is None and al[0].nivel == "BLOQUEIO"
    print("12 testes OK")


if __name__ == "__main__":
    _testes()
