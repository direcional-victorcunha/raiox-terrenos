"""Módulo de identificação de zoneamento e cálculo de potencial construtivo (CA)."""
from __future__ import annotations

import numpy as np
import pyproj
import shapely

from raiox import dados
from raiox.tipos import LoteCadastro, Premissas
from raiox.urbanismo.ca_engine import MULT_PRODUTO, Lote, limites_ca, resolver_zona_efetiva, ZONAS
from raiox.urbanismo.zoneamento import SEM_ZONA

# Premissa "multiplicador de EHIS/EHMP" desligada (opção; o padrão é ligado desde 30/10, quando o autor
# confirmou CA 6 em EHIS na ZEU): o CA de EHIS/EHMP fica o CA máximo da zona, como o de R2V livre.
SEM_MULTIPLICADOR: dict[str, float] = {regime: 1.0 for regime in MULT_PRODUTO}

CAMADA_ZONEAMENTO = "perimetro_zona_lei_18177_24"
_TRANSFORMER_4326_TO_31983 = pyproj.Transformer.from_crs(
    "EPSG:4326", "EPSG:31983", always_xy=True
)


def _reprojetar_para_31983(geom: shapely.Geometry) -> shapely.Geometry:
    """Reprojeta uma geometria WGS84 (EPSG:4326) para SIRGAS 2000 / UTM 23S (EPSG:31983)."""
    def _transform_coords(coords: np.ndarray) -> np.ndarray:
        x, y = _TRANSFORMER_4326_TO_31983.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    return shapely.transform(geom, _transform_coords)


def zonas_do_lote(lote: LoteCadastro) -> list[tuple[str, float]]:
    """Identifica as zonas que incidem sobre o lote e calcula o percentual de área de cada uma.

    Retorna uma lista de tuplas (sigla_da_zona, pct_area) com a ZONA PRINCIPAL primeiro
    (a que contém o representative_point do lote) e as demais por percentual decrescente.
    Caso nenhuma zona seja encontrada, retorna [(SEM_ZONA, 0.0)].
    """
    if not lote.geometria_wkt:
        return [(SEM_ZONA, 0.0)]

    lote_geom = shapely.from_wkt(lote.geometria_wkt)
    if lote_geom.is_empty:
        return [(SEM_ZONA, 0.0)]

    feicoes_zonas = dados.feicoes(CAMADA_ZONEAMENTO, lote_geom.bounds)
    if not feicoes_zonas:
        return [(SEM_ZONA, 0.0)]

    lote_proj = _reprojetar_para_31983(lote_geom)
    if not lote_proj.is_valid:
        lote_proj = shapely.make_valid(lote_proj)

    area_lote_proj = lote_proj.area
    if area_lote_proj <= 0:
        return [(SEM_ZONA, 0.0)]

    ponto_rep = lote_geom.representative_point()
    ponto_rep_proj = lote_proj.representative_point()

    zona_principal: str | None = None
    geoms_por_sigla: dict[str, list[shapely.Geometry]] = {}

    for feicao in feicoes_zonas:
        sigla = str(feicao.atributos.get("cd_zoneamento_perimetro") or "").strip()
        if not sigla:
            continue
        f_geom = shapely.from_wkt(feicao.geometria_wkt)
        if f_geom.is_empty:
            continue

        if zona_principal is None and (f_geom.contains(ponto_rep) or f_geom.covers(ponto_rep)):
            zona_principal = sigla

        geoms_por_sigla.setdefault(sigla, []).append(f_geom)

    sigla_areas: dict[str, float] = {}
    for sigla, geoms in geoms_por_sigla.items():
        geoms_proj = [_reprojetar_para_31983(g) for g in geoms]
        zona_proj = geoms_proj[0] if len(geoms_proj) == 1 else shapely.union_all(geoms_proj)
        if not zona_proj.is_valid:
            zona_proj = shapely.make_valid(zona_proj)

        if zona_principal is None and (zona_proj.contains(ponto_rep_proj) or zona_proj.covers(ponto_rep_proj)):
            zona_principal = sigla

        inter = lote_proj.intersection(zona_proj)
        if not inter.is_empty and inter.area > 0:
            sigla_areas[sigla] = inter.area

    if not sigla_areas:
        return [(SEM_ZONA, 0.0)]

    sigla_pct = {
        sigla: round((area / area_lote_proj) * 100.0, 1)
        for sigla, area in sigla_areas.items()
    }

    if zona_principal is None or zona_principal not in sigla_pct:
        zona_principal = max(sigla_pct.keys(), key=lambda s: sigla_pct[s])

    principal_tuple = (zona_principal, sigla_pct[zona_principal])
    demais = [item for item in sigla_pct.items() if item[0] != zona_principal]
    demais.sort(key=lambda x: (-x[1], x[0]))

    return [principal_tuple] + demais


def multiplicadores(premissas: Premissas) -> dict[str, float]:
    """Multiplicador do CA por regime: o do motor (×1,5 EHIS, ×1,25 EHMP) ou 1, conforme a premissa."""
    return dict(MULT_PRODUTO) if premissas.multiplicador_ehis_ehmp else dict(SEM_MULTIPLICADOR)


def texto_multiplicador(premissas: Premissas) -> str | None:
    """Frase que diz qual CA vale para EHIS/EHMP (None em R2V livre, onde o multiplicador é 1)."""
    if premissas.regime not in ("EHIS", "EHMP"):
        return None
    fator = f"×{MULT_PRODUTO[premissas.regime]:g}".replace(".", ",")
    if premissas.multiplicador_ehis_ehmp:
        return (
            f"CA de {premissas.regime} com o multiplicador do motor ({fator}): premissa ligada "
            "(Quadro 2 do Decreto 63.728: EHIS ×1,5, EHMP ×1,25)."
        )
    return (
        f"CA de {premissas.regime} sem o multiplicador do motor ({fator}): premissa desligada "
        "(opção da planilha antiga)."
    )


def ca_do_lote(
    sigla: str, area_m2: float, premissas: Premissas
) -> tuple[float, float | None, list[str]]:
    """Calcula os limites de CA e parâmetros urbanísticos da zona para o lote e premissas.

    Retorna (ca_teto, cp_max, avisos).
    """
    avisos: list[str] = []
    zona = sigla

    if premissas.zeup_ativada:
        zeup_map = {"ZEUP": "ZEU", "ZEUPa": "ZEUa"}
        zona = zeup_map.get(zona, zona)

    if premissas.acesso_via_estreita or premissas.vila:
        lote_motor = Lote(
            sql="",
            area_m2=area_m2,
            zona_base=zona,
            mapa_base="L18081",
            via_acesso_largura_m=10.0 if premissas.acesso_via_estreita else None,
            vila=premissas.vila,
            zeup_ativada=premissas.zeup_ativada,
            zem_ca4=premissas.zem_ca4,
        )
        zona_efetiva, alertas = resolver_zona_efetiva(lote_motor)
        if zona_efetiva:
            for al in alertas:
                if al.codigo == "ACESSO_ESTREITO":
                    avisos.append(
                        f"Zona rebaixada de {zona} para {zona_efetiva} por acesso em via de até 10 m"
                    )
                elif al.codigo == "VILA":
                    avisos.append(
                        f"Zona rebaixada de {zona} para {zona_efetiva} por vila reconhecida (art. 64 VI)"
                    )
                elif al.codigo not in ("ACESSO_NAO_INFORMADO",):
                    avisos.append(al.msg)
            zona = zona_efetiva
    else:
        lote_motor = Lote(
            sql="",
            area_m2=area_m2,
            zona_base=zona,
            mapa_base="L18081",
            zem_ca4=premissas.zem_ca4,
        )

    if zona not in ZONAS:
        avisos.append(
            f"Zona {sigla} fora do Quadro 3 da LPUOS: CA 0 (sem parâmetro no motor)"
        )
        return 0.0, None, avisos

    cp_max_val = ZONAS[zona]["cp_max"]
    cp_max = float(cp_max_val) if cp_max_val is not None else None

    limites = limites_ca(
        zona=zona,
        area_lote=area_m2,
        regime=premissas.regime,
        l=lote_motor,
        cota_solidariedade=premissas.cota_solidariedade,
        mult=multiplicadores(premissas),
    )
    ca_teto = float(limites.ca_teto)

    texto = texto_multiplicador(premissas)
    if texto is not None:
        avisos.append(texto)

    return ca_teto, cp_max, avisos


def avisos_de_zonas(zonas: list[tuple[str, float]]) -> list[str]:
    """Gera aviso informativo se o lote incidir sobre 2 ou mais zonas com mais de 5% de área."""
    relevantes = [z for z in zonas if z[1] > 5.0]
    if len(relevantes) < 2:
        return []

    detalhes = ", ".join(f"{sigla} {round(pct)}%" for sigla, pct in relevantes)
    msg = (
        f"Lote em {len(relevantes)} zonas: {detalhes}. "
        "O CA usa a zona principal (ponto representativo); o CA ponderado não está na regra."
    )
    return [msg]
