"""Módulo de cálculo de entorno e mapa de oportunidades do Raio-X de Terrenos SP.

Identifica lotes individuais e composições (duplas e trincas) que atingem a meta
de VGV dentro da área delimitada, aplicando regras urbanísticas, triagem de
sinais e mitigação de riscos sem scores subjetivos.

As regras seguem o mapa do app antigo (prospeccao-marechal-tito/app.py, linhas 254-600):
lote que toca a área, só fiscais ativos e condomínios com uso informado, CA do
cenário pela zona do ponto representativo, VGV potencial = área × CA × preço/m²,
meta por VGV ou por área mínima, triagem com as seis caixas do antigo, divisa mínima
e duplas/trincas ligáveis. Todos esses parâmetros vêm de Premissas (padrões do antigo,
com a linha de origem em tipos.py). Ver docs/diagnostico_entorno.md.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd
import pyproj
import shapely
import shapely.geometry

from raiox import dados, uso
from raiox.area_util import area_computavel, preco_m2_efetivo, vgv_potencial
from raiox.tipos import Candidato, Entorno, LoteAvaliado, LoteCadastro, Premissas
from raiox.urbanismo._legado_sinais import LIMIAR_ALTA_M, LIMIAR_DUTO_M, texto_alertas
from raiox.urbanismo.contexto import (
    distancia_ate,
    estacao_mais_proxima,
    para_utm,
    pct_sobreposicao,
)
from raiox.urbanismo.geo_engine import SIMPLIFY_TOL, TOL_DIVISA_M, calcular_composicoes_vgv
from raiox.urbanismo.lotes_geom import LotesLazy
from raiox.urbanismo.zoneamento import atribuir_zonas, ca_cenario
from raiox.zona import multiplicadores, texto_multiplicador

# Transformadores de projeção cartográfica
_PARA_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:31983", always_xy=True)
_PARA_WGS = pyproj.Transformer.from_crs("EPSG:31983", "EPSG:4326", always_xy=True)

# Nomes de camadas territoriais do GeoSampa / PDE
_CAMADA_ZONEAMENTO = "perimetro_zona_lei_18177_24"
_CAMADA_DUTO = "transpetro_duto"
_CAMADA_ALTA_TENSAO = "linha_alta_tensao"
_CAMADAS_ESTACAO = (
    "estacao_metro",
    "estacao_trem",
    "estacao_metro_projetada",
    "estacao_trem_projetada",
)

# Sobreposições medidas em % da área do lote: (chave, camadas, rótulo no motivo de esconder)
_SOBREPOSICOES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "publica",
        ("GEOSAMPA_cadastro_area_publica_cidadao", "pde_parque_municipal", "GEOSAMPA_v_praca_largo"),
        "área pública/parque",
    ),
    ("favela", ("habita2geosampa_habi_favela2geosampa",), "favela"),
    (
        "contaminada",
        ("GEOSAMPA_area_contaminada_sigac", "area_contaminada_reabilitada_svma"),
        "área contaminada",
    ),
    ("risco", ("area_risco_geologico",), "risco geológico"),
)

# Caixas da triagem do mapa antigo (app.py:325-353), na mesma ordem. O que vem marcado por
# padrão está em Premissas.triagem_esconde. As quatro sobreposições escondem a partir de
# Premissas.limite_esconder_pct; duto e alta tensão escondem pelo limiar do sinal (app.py:401-408).
TRIAGEM: dict[str, str] = {
    "publica": "Área pública / parque",
    "favela": "Favela",
    "contaminada": "Área contaminada",
    "risco": "Risco geológico",
    "duto": f"Duto (≤ {LIMIAR_DUTO_M:.0f} m)",
    "alta_tensao": "Alta tensão (cruza)",
}

# Situação cadastral aceita: fiscal ativo, ou condomínio (o cadastro deixa a situação em branco)
_SITUACAO_ATIVA = "ATIVO"
_USO_CONDOMINIO = "Condomínio"

# Cache em memória para lookup rápido de lotes por ID sem reoneração de I/O
_lotes_cache: dict[str, LoteCadastro] = {}


def _reprojetar(geom: shapely.Geometry, transformer: pyproj.Transformer) -> shapely.Geometry:
    """Reprojeta uma geometria shapely usando uma função transformer do pyproj."""
    def _transform_coords(coords: np.ndarray) -> np.ndarray:
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    return shapely.transform(geom, _transform_coords)


def _valida(geom: shapely.Geometry) -> shapely.Geometry:
    """Devolve a geometria corrigida quando inválida."""
    return geom if shapely.is_valid(geom) else shapely.make_valid(geom)


def _fmt_num(val: float) -> str:
    """Formata valor numérico no padrão pt-BR (separador de milhar '.' e decimal ',')."""
    if abs(val - round(val)) < 1e-6:
        return f"{int(round(val)):,}".replace(",", ".")
    partes = f"{val:,.2f}".split(".")
    inteiro = partes[0].replace(",", ".")
    decimal = partes[1].rstrip("0").rstrip(",")
    return f"{inteiro},{decimal}" if decimal else inteiro


def _fmt_pct(pct: float) -> str:
    """Formata porcentagem no padrão pt-BR (ex: 50% ou 54,3%)."""
    if abs(pct - round(pct)) < 1e-4:
        return f"{int(round(pct))}%"
    return f"{pct:.1f}%".replace(".", ",")


def _feicoes_validas(
    camadas: Sequence[str],
    bbox: tuple[float, float, float, float],
    margem_m: float,
    avisos: list[str],
) -> list[tuple[shapely.Geometry, dict[str, object]]]:
    """Geometrias válidas e atributos das feições; camada ausente na base vira aviso no resultado."""
    saida: list[tuple[shapely.Geometry, dict[str, object]]] = []
    for camada in camadas:
        try:
            feats = dados.feicoes(camada, bbox, margem_m=margem_m)
        except dados.CamadaAusente:
            aviso = (
                f"A camada '{camada}' não está na base baixada: os sinais e a triagem "
                "que dependem dela ficaram sem essa camada."
            )
            if aviso not in avisos:
                avisos.append(aviso)
            continue
        for f in feats:
            if not f.geometria_wkt:
                continue
            g = shapely.from_wkt(f.geometria_wkt)
            if g is not None and not shapely.is_empty(g):
                saida.append((_valida(g), f.atributos))
    return saida


def _geoms_utm(
    camadas: Sequence[str],
    bbox: tuple[float, float, float, float],
    margem_m: float,
    avisos: list[str],
) -> np.ndarray:
    """Geometrias das camadas reprojetadas para metros (EPSG:31983)."""
    geoms = [g for g, _ in _feicoes_validas(camadas, bbox, margem_m, avisos)]
    return para_utm(geoms, _PARA_UTM) if geoms else np.array([], dtype=object)


def _rotulo_estacao(atributos: dict[str, object]) -> str:
    """Rótulo 'Nome (Linha)' de uma estação de metrô/trem."""
    nome = str(atributos.get("nm_estacao_metro_trem") or atributos.get("nome") or "").strip()
    linha = str(atributos.get("nm_linha_metro_trem") or atributos.get("linha") or "").strip()
    return f"{nome} ({linha})" if nome and linha else (nome or linha or "Estação")


def _lote_aceito(lote: LoteCadastro) -> bool:
    """Mesmo recorte do cadastro do app antigo: fiscal ativo ou condomínio, com uso informado."""
    if lote.uso is None:
        return False
    return lote.situacao == _SITUACAO_ATIVA or (
        lote.situacao is None and lote.uso == _USO_CONDOMINIO
    )


def circulo_wkt(lote: LoteCadastro, raio_m: float) -> str:
    """Gera a geometria WKT em WGS84 de um buffer circular a partir do centroide do lote."""
    centro_utm = _reprojetar(_valida(shapely.from_wkt(lote.geometria_wkt)).centroid, _PARA_UTM)
    return str(_reprojetar(shapely.buffer(centro_utm, raio_m), _PARA_WGS).wkt)


def circulo_ponto_wkt(lon: float, lat: float, raio_m: float) -> str:
    """Círculo (WKT, WGS84) de `raio_m` metros em volta de um ponto qualquer marcado no mapa."""
    centro_utm = _reprojetar(shapely.Point(lon, lat), _PARA_UTM)
    return str(_reprojetar(shapely.buffer(centro_utm, raio_m), _PARA_WGS).wkt)


def _avisos_de_premissas(premissas: Premissas) -> list[str]:
    """Premissas que valem só no Raio-X do lote e que a tabela do entorno não aplica."""
    avisos: list[str] = []
    if premissas.acesso_via_estreita or premissas.vila:
        avisos.append(
            "As caixas 'via de até 10 m' e 'vila' não se aplicam no Prospectar: o cadastro não "
            "traz a largura da via nem a vila de cada lote, então a tabela não rebaixa a zona "
            "(ZEU → ZM / ZPR). Abra o lote no Raio-X para ver o efeito."
        )
    if premissas.retiradas and premissas.base_vgv == "liquida":
        avisos.append(
            "A base líquida (após retiradas) vale só no Raio-X do lote: a tabela do entorno "
            "usa a área do cadastro."
        )
    texto = texto_multiplicador(premissas)
    if texto is not None:
        avisos.append(texto)
    return avisos


def _float_ou_none(valor: float) -> float | None:
    return None if valor != valor else float(valor)


def _motivos_triagem(
    area_m2: float,
    pct: dict[str, float],
    dist_duto: float,
    dist_alta: float,
    premissas: Premissas,
) -> list[str]:
    """Motivos para esconder o lote, como em _motivo_escondido do antigo (app.py:490-507)."""
    m: list[str] = []
    if area_m2 > premissas.area_max_lote_m2:
        m.append(f"acima de {_fmt_num(premissas.area_max_lote_m2)} m²")
    for chave, _, rotulo in _SOBREPOSICOES:
        if chave in premissas.triagem_esconde and pct[chave] >= premissas.limite_esconder_pct:
            m.append(f"{rotulo} ({_fmt_pct(pct[chave])})")
    if "duto" in premissas.triagem_esconde and dist_duto == dist_duto and dist_duto <= LIMIAR_DUTO_M:
        m.append(f"duto a {dist_duto:.0f} m")
    if (
        "alta_tensao" in premissas.triagem_esconde
        and dist_alta == dist_alta
        and dist_alta <= LIMIAR_ALTA_M
    ):
        m.append("alta tensão (cruza)")
    return m


def _bate_meta(area_m2: float, ca: float, vgv: float, premissas: Premissas) -> bool:
    """Meta do antigo (app.py:272-292): VGV potencial ≥ meta, ou área ≥ área mínima; sem CA, não bate."""
    if ca <= 0.0:
        return False
    if premissas.criterio_meta == "area":
        return area_m2 >= premissas.area_minima_m2
    return vgv >= premissas.meta_vgv


def calcular(
    area_wkt: str,
    premissas: Premissas,
    centro_wkt: str | None = None,
    raio_m: float | None = None,
) -> Entorno:
    """Varre a área: avalia todos os lotes e monta as oportunidades (lote, dupla, trinca)."""
    preco_m2 = preco_m2_efetivo(premissas)
    if preco_m2 is None:
        raise ValueError(
            "preencha o preço por m² (ou o ticket da unidade) nas Premissas para avaliar os "
            "lotes pela meta de VGV (VGV potencial = área × CA × preço, como no app antigo)"
        )
    avisos: list[str] = _avisos_de_premissas(premissas)

    area_geom = _valida(shapely.from_wkt(area_wkt))
    if centro_wkt is None:
        centro_wkt = str(shapely.centroid(area_geom).wkt)

    minx, miny, maxx, maxy = shapely.bounds(area_geom)
    bbox = (float(minx), float(miny), float(maxx), float(maxy))

    # Lotes que tocam a área (o app antigo extraía a região por interseção, não pelo centro)
    lotes_bbox = [l for l in dados.lotes_no_bbox(bbox) if _lote_aceito(l)]
    geoms_bbox = shapely.make_valid(
        shapely.from_wkt(np.array([l.geometria_wkt for l in lotes_bbox], dtype=object))
    )
    dentro = shapely.intersects(geoms_bbox, area_geom) if lotes_bbox else np.array([], dtype=bool)
    lotes = [l for l, ok in zip(lotes_bbox, dentro) if ok]
    geoms = list(geoms_bbox[dentro]) if lotes_bbox else []
    if not lotes:
        return Entorno(
            centro_wkt=centro_wkt,
            raio_m=raio_m,
            candidatos=[],
            avisos=avisos + ["Nenhum lote encontrado na área delimitada."],
            lotes=[],
            area_wkt=area_wkt,
        )
    for lote in lotes:
        _lotes_cache[lote.cd_identificador] = lote

    # Zoneamento (ponto representativo do lote) e CA do cenário
    zonas_feats = _feicoes_validas((_CAMADA_ZONEAMENTO,), bbox, 300.0, avisos)
    if zonas_feats:
        zonas = atribuir_zonas(
            geoms,
            [g for g, _ in zonas_feats],
            [str(a.get("cd_zoneamento_perimetro") or "SEM_ZONA") for _, a in zonas_feats],
        )
    else:
        zonas = ["SEM_ZONA"] * len(lotes)
    areas = np.array([l.area_terreno_m2 for l in lotes], dtype=float)
    cas = ca_cenario(
        pd.Series(zonas),
        pd.Series(areas),
        regime=premissas.regime,
        cota_solidariedade=premissas.cota_solidariedade,
        zeup_ativada=premissas.zeup_ativada,
        zem_ca4=premissas.zem_ca4,
        mult=multiplicadores(premissas),
    ).to_numpy(dtype=float)

    # Sinais: sobreposições (%), distâncias a dutos/alta tensão e estação mais próxima
    lotes_utm = para_utm(geoms, _PARA_UTM)
    pct = {
        chave: pct_sobreposicao(lotes_utm, _geoms_utm(camadas, bbox, 0.0, avisos))
        for chave, camadas, _ in _SOBREPOSICOES
    }
    dist_duto = distancia_ate(
        lotes_utm, _geoms_utm((_CAMADA_DUTO,), bbox, 1000.0, avisos), max_m=1000.0
    )
    dist_alta = distancia_ate(
        lotes_utm, _geoms_utm((_CAMADA_ALTA_TENSAO,), bbox, 1000.0, avisos), max_m=1000.0
    )
    estacoes = _feicoes_validas(_CAMADAS_ESTACAO, bbox, 5000.0, avisos)
    dist_estacao, estacao_nome = estacao_mais_proxima(
        lotes_utm,
        para_utm([g for g, _ in estacoes], _PARA_UTM) if estacoes else [],
        [_rotulo_estacao(a) for _, a in estacoes],
    )

    # Cada lote da área com os fatos e as contas (a mesma conta do Raio-X: area_util.vgv_potencial)
    avaliados: list[LoteAvaliado] = []
    for i, lote in enumerate(lotes):
        area_i, ca_i = float(areas[i]), float(cas[i])
        pct_i = {chave: float(pct[chave][i]) for chave, _, _ in _SOBREPOSICOES}
        a_comp = area_computavel(area_i, ca_i)
        vgv = vgv_potencial(area_i, ca_i, preco_m2)
        texto = texto_alertas(
            pct_i["publica"], pct_i["favela"], pct_i["contaminada"], pct_i["risco"],
            dist_duto[i], dist_alta[i],
        )
        construido = (
            float(round(100.0 * lote.area_construida_m2 / area_i))
            if lote.area_construida_m2 is not None and area_i > 0
            else None
        )
        motivos = _motivos_triagem(area_i, pct_i, dist_duto[i], dist_alta[i], premissas)
        avaliados.append(
            LoteAvaliado(
                cadastro=lote,
                zona=zonas[i],
                ca=ca_i,
                area_computavel_m2=a_comp,
                unidades=int(a_comp // premissas.area_media_unidade_m2),
                vgv=vgv,
                bate_meta=_bate_meta(area_i, ca_i, vgv, premissas),
                escondido_por="; ".join(motivos) or None,
                sinais=tuple(texto.split(" · ")) if texto else (),
                pct_publica=pct_i["publica"],
                pct_favela=pct_i["favela"],
                pct_contaminada=pct_i["contaminada"],
                pct_risco=pct_i["risco"],
                dist_duto_m=_float_ou_none(dist_duto[i]),
                dist_alta_tensao_m=_float_ou_none(dist_alta[i]),
                estacao=str(estacao_nome[i]) or None,
                dist_estacao_m=_float_ou_none(dist_estacao[i]),
                pct_construido=construido,
                # No entorno não há largura de via por lote: a frase "via não conferida" fica.
                uso_porte=tuple(
                    uso.avaliar_uso_porte_completo(zonas[i], area_i, a_comp, regime=premissas.regime)
                ),
            )
        )

    candidatos: list[Candidato] = [
        Candidato(
            tipo="lote",
            ids=(a.cadastro.cd_identificador,),
            area_m2=a.cadastro.area_terreno_m2,
            vgv=a.vgv,
            zonas=(a.zona,),
            sinais=a.sinais,
            escondido_por=a.escondido_por,
        )
        for a in avaliados
        if a.bate_meta
    ]
    if premissas.mostrar_duplas or premissas.mostrar_trincas:
        df_source = pd.DataFrame(
            {
                "cd_setor_fiscal": [l.cd_identificador for l in lotes],
                "cd_quadra_fiscal": "",
                "cd_lote": "",
                "qt_area_terreno": areas,
                "ca_maximo": cas,
                "zoneamento": zonas,
                "nm_logradouro_completo": [l.logradouro for l in lotes],
                "dc_tipo_uso_imovel": [l.uso or "" for l in lotes],
                "qt_area_construida": [l.area_construida_m2 or 0.0 for l in lotes],
                "geometry_wkt": [l.geometria_wkt for l in lotes],
                **{f"pct_{chave}": pct[chave] for chave, _, _ in _SOBREPOSICOES},
                "dist_duto_m": dist_duto,
                "dist_alta_tensao_m": dist_alta,
                "dist_estacao_m": dist_estacao,
                "estacao_nome": estacao_nome,
            }
        )
        candidatos.extend(_composicoes(df_source, avaliados, premissas, preco_m2))

    candidatos.sort(key=lambda c: -c.vgv)
    return Entorno(
        centro_wkt=centro_wkt,
        raio_m=raio_m,
        candidatos=candidatos,
        avisos=avisos,
        lotes=avaliados,
        area_wkt=area_wkt,
    )


def _composicoes(
    df_source: pd.DataFrame,
    avaliados: list[LoteAvaliado],
    premissas: Premissas,
    preco_m2: float,
) -> list[Candidato]:
    """Duplas e trincas pelo motor congelado (geo_engine), com os parâmetros das Premissas.

    O motor identifica o lote por setor+quadra+lote, chave que os condomínios repetem; por isso
    `df_source` traz o cd_identificador na coluna do setor (quadra e lote vazios).
    """
    # Entram nas composições os lotes com CA e sem motivo de esconder (app.py:427-433)
    elegiveis = {a.cadastro.cd_identificador for a in avaliados if a.ca > 0.0 and not a.escondido_por}
    por_area = premissas.criterio_meta == "area"
    pares_fc, trincas_fc = calcular_composicoes_vgv(
        df_source=df_source,
        lotes_geom_source=LotesLazy(df_source),
        criterio="area" if por_area else "vgv",
        vgv_alvo=0.0 if por_area else premissas.meta_vgv,
        preco_m2_global=preco_m2,
        area_alvo=premissas.area_minima_m2 if por_area else 0.0,
        sql_filtrados=elegiveis,
        min_divisa_m=premissas.divisa_min_m,
    )
    comp_por_id = {a.cadastro.cd_identificador: a.area_computavel_m2 for a in avaliados}
    saida: list[Candidato] = []
    for tipo, fc, ligado in (
        ("dupla", pares_fc, premissas.mostrar_duplas),
        ("trinca", trincas_fc, premissas.mostrar_trincas),
    ):
        if not ligado:
            continue
        for feat in fc["features"]:
            props = feat["properties"]
            sinais = props["sinais"]
            ids = tuple(props["lids"])
            # VGV potencial da composição = Σ área computável de cada lote (arredondada ao m²,
            # a mesma do Raio-X do lote) × preço/m². O detalhe da composição mostra esta soma.
            a_comp = sum(comp_por_id[i] for i in ids)
            saida.append(
                Candidato(
                    tipo=tipo,
                    ids=ids,
                    area_m2=float(props["area_total"]),
                    vgv=float(round(a_comp * preco_m2)),
                    zonas=tuple(z for z in props["zonas"].split(" | ") if z),
                    sinais=tuple(sinais.split(" · ")) if sinais != "—" else (),
                    escondido_por=None,
                )
            )
    return saida


def divisa_m(wkt_a: str, wkt_b: str) -> float:
    """Comprimento (m) da divisa em comum entre dois lotes, medido como no motor congelado.

    Mesma conta de `_divisa_m` dentro de `geo_engine.calcular_composicoes_vgv` (função interna,
    não importável): polígonos simplificados, escala local em metros e folga de TOL_DIVISA_M.
    A latitude de referência é a dos dois lotes (no motor, a média de todos os candidatos;
    a diferença é de centímetros).
    """
    ga, gb = (
        shapely.simplify(_valida(shapely.from_wkt(w)), SIMPLIFY_TOL, preserve_topology=True)
        for w in (wkt_a, wkt_b)
    )
    lat0 = (ga.centroid.y + gb.centroid.y) / 2.0
    escala = np.array([111320.0 * np.cos(np.radians(lat0)), 110574.0])
    ma, mb = (shapely.transform(g, lambda c: c * escala) for g in (ga, gb))
    a = ma.boundary.intersection(mb.buffer(TOL_DIVISA_M)).length
    b = mb.boundary.intersection(ma.buffer(TOL_DIVISA_M)).length
    return float(min(a, b))


def geojson(entorno: Entorno) -> dict[str, object]:
    """Serializa o resultado de entorno em uma FeatureCollection GeoJSON."""
    features: list[dict[str, object]] = []
    da_area = {a.cadastro.cd_identificador: a.cadastro for a in entorno.lotes}

    for indice, candidato in enumerate(entorno.candidatos):
        lotes_comp: list[LoteCadastro] = []
        for cid in candidato.ids:
            lote = da_area.get(cid) or _lotes_cache.get(cid)
            if lote is None:
                lote = dados.lote_por_id(cid)
            if lote is not None:
                lotes_comp.append(lote)

        if not lotes_comp:
            continue

        geom_unida = shapely.union_all(
            [_valida(shapely.from_wkt(l.geometria_wkt)) for l in lotes_comp]
        )
        props: dict[str, object] = {
            # Mesma chave da tabela (raiox.oportunidades): "l<id>" lote, "c<índice>" composição
            "chave": f"l{candidato.ids[0]}" if candidato.tipo == "lote" else f"c{indice}",
            "tipo": candidato.tipo,
            "ids": list(candidato.ids),
            "area_m2": candidato.area_m2,
            "vgv": candidato.vgv,
            "zonas": list(candidato.zonas),
            "sinais": list(candidato.sinais),
            "escondido_por": candidato.escondido_por,
        }
        features.append({
            "type": "Feature",
            "geometry": shapely.geometry.mapping(geom_unida),
            "properties": props,
        })

    return {
        "type": "FeatureCollection",
        "features": features,
    }
