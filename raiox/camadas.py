"""Definições e regras de camadas territoriais do Raio-X de Terrenos SP."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegraCamada:
    """Configuração e limiares de uma regra de camada territorial."""

    id: str
    rotulo: str
    camadas_banco: tuple[str, ...]
    usos: frozenset[str]
    teste: str | None
    limiar: float | None
    origem_do_limiar: str
    faixa_m: float | None = None
    chaves: tuple[str, ...] = ()
    atributo_medida: tuple[str, ...] = ()


REGRAS: tuple[RegraCamada, ...] = (
    RegraCamada(
        id="lotes",
        rotulo="Lotes",
        camadas_banco=("lotes",),
        usos=frozenset({"ver"}),
        teste=None,
        limiar=None,
        origem_do_limiar="",
    ),
    RegraCamada(
        id="zoneamento",
        rotulo="Zoneamento",
        camadas_banco=("perimetro_zona_lei_18177_24",),
        usos=frozenset({"ver"}),
        teste=None,
        limiar=None,
        origem_do_limiar="",
    ),
    RegraCamada(
        id="alta_tensao",
        rotulo="Linha de alta tensão (aérea)",
        camadas_banco=("linha_alta_tensao",),
        usos=frozenset({"ver", "sinal", "retirar"}),
        teste="distancia",
        limiar=1.0,
        origem_do_limiar="Aria, 28/10 (cruza o lote, tolerância 1 m)",
        faixa_m=30.0,
    ),
    RegraCamada(
        id="alta_tensao_sub",
        rotulo="Linha de alta tensão (subterrânea)",
        camadas_banco=("linha_subterranea_alta_tensao",),
        usos=frozenset({"ver", "sinal"}),
        teste="distancia",
        limiar=1.0,
        origem_do_limiar="Aria, 28/10",
        atributo_medida=("nm_linha_subterranea_alta_tensao",),
    ),
    RegraCamada(
        id="duto",
        rotulo="Duto Transpetro",
        camadas_banco=("transpetro_duto",),
        usos=frozenset({"ver", "sinal", "retirar"}),
        teste="distancia",
        limiar=30.0,
        origem_do_limiar="Aria (sem fonte); faixa de 20 m: Transpetro/Dec. 79.803/77/TJ-SP",
        faixa_m=20.0,
    ),
    RegraCamada(
        id="contaminada",
        rotulo="Área contaminada",
        camadas_banco=(
            "GEOSAMPA_area_contaminada_sigac",
            "area_contaminada_reabilitada_svma",
        ),
        usos=frozenset({"ver", "sinal"}),
        teste="chave_lote + sobreposicao",
        limiar=0.0,
        origem_do_limiar="qualquer ocorrência",
        chaves=("cd_setor_fiscal", "cd_quadra_fiscal", "cd_lote"),
        atributo_medida=("dc_tipo_situacao",),
    ),
    RegraCamada(
        id="risco",
        rotulo="Risco geológico",
        camadas_banco=("area_risco_geologico",),
        usos=frozenset({"ver", "sinal", "retirar"}),
        teste="sobreposicao",
        limiar=10.0,
        origem_do_limiar="motor antigo (LIMIAR_PCT)",
    ),
    RegraCamada(
        id="tombamento",
        rotulo="Tombamento / envoltória",
        camadas_banco=(
            "patrimonio_cultural_bem_tombado",
            "patrimonio_cultural_area_envoltoria_CONPRESP",
            "patrimonio_cultural_area_envoltoria_CONDEPHAAT",
            "patrimonio_cultural_area_envoltoria_IPHAN",
        ),
        usos=frozenset({"ver", "sinal"}),
        teste="chave_lote + sobreposicao",
        limiar=0.0,
        origem_do_limiar="qualquer ocorrência",
        chaves=("cd_setor_fiscal", "cd_quadra_fiscal", "cd_lote"),
        atributo_medida=("nm_area_tombada", "tx_situacao_tombamento"),
    ),
    RegraCamada(
        id="area_publica",
        rotulo="Área pública / parque / praça",
        camadas_banco=(
            "GEOSAMPA_cadastro_area_publica_cidadao",
            "pde_parque_municipal",
            "GEOSAMPA_v_praca_largo",
        ),
        usos=frozenset({"ver", "sinal", "retirar"}),
        teste="sobreposicao",
        limiar=10.0,
        origem_do_limiar="motor antigo (LIMIAR_PCT)",
    ),
    RegraCamada(
        id="favela",
        rotulo="Favela",
        camadas_banco=("habita2geosampa_habi_favela2geosampa",),
        usos=frozenset({"ver", "sinal"}),
        teste="sobreposicao",
        limiar=10.0,
        origem_do_limiar="motor antigo (LIMIAR_PCT)",
    ),
    RegraCamada(
        id="inundacao",
        rotulo="Inundação",
        camadas_banco=("mancha_inundacao_100", "area_inundavel"),
        usos=frozenset({"ver", "sinal"}),
        teste="sobreposicao",
        limiar=10.0,
        origem_do_limiar="motor antigo (LIMIAR_PCT)",
    ),
    RegraCamada(
        id="agua",
        rotulo="Corpos d'água e córregos",
        camadas_banco=("massa_d_agua", "drenagem", "represa_nivel_maximo"),
        usos=frozenset({"ver"}),
        teste=None,
        limiar=None,
        origem_do_limiar="",
    ),
    RegraCamada(
        id="app",
        rotulo="Áreas prioritárias OIDA (não é APP; aposentada)",
        camadas_banco=("app_oida",),
        # Aposentada em 30/10 a pedido do autor: sem usos, não aparece nas camadas nem nas retiradas.
        usos=frozenset(),
        teste="sobreposicao",
        limiar=10.0,
        origem_do_limiar="motor antigo (LIMIAR_PCT)",
    ),
    RegraCamada(
        id="melhoramento",
        rotulo="Melhoramento viário (informativo: não reduz o CA)",
        camadas_banco=(
            "pde_intervencao_pontual_melhoramento_viario",
            "geoconvias_lei_melhoramento_vigente",
        ),
        usos=frozenset({"ver", "sinal", "retirar"}),
        teste="sobreposicao",
        limiar=0.0,
        origem_do_limiar="informativo (PDE art. 81)",
    ),
    RegraCamada(
        id="estacoes",
        rotulo="Estações de metrô e trem",
        camadas_banco=(
            "estacao_metro",
            "estacao_trem",
            "estacao_metro_projetada",
            "estacao_trem_projetada",
        ),
        usos=frozenset({"ver"}),
        teste="mais_proxima",
        limiar=5000.0,
        origem_do_limiar="Aria",
        atributo_medida=(
            "nm_estacao_metro_trem",
            "nm_linha_metro_trem",
            "nm_empresa_metro_trem",
            "tx_situacao_metro_trem",
        ),
    ),
)

_REGRAS_POR_ID: dict[str, RegraCamada] = {r.id: r for r in REGRAS}


def regra(id: str) -> RegraCamada:
    """Retorna a regra cadastrada com o identificador informado ou levanta KeyError."""
    if id not in _REGRAS_POR_ID:
        raise KeyError(f"Regra de camada desconhecida: '{id}'")
    return _REGRAS_POR_ID[id]


def regras_com_uso(uso: str) -> list[RegraCamada]:
    """Retorna todas as regras associadas ao uso informado, preservando a ordem oficial."""
    return [r for r in REGRAS if uso in r.usos]
