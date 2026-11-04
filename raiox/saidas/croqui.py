"""Módulo de geração de croqui vetorial SVG para o Raio-X de Terrenos SP.

Gera visualização cartográfica em projeção métrica EPSG:31983 com enquadramento
automático, escala gráfica, indicador de norte, polígono bruto/líquido,
retiradas hachuradas e feições de zoneamento e restrições recortadas.
"""

from __future__ import annotations

import html
from collections.abc import Sequence

import numpy as np
import pyproj
import shapely

from raiox.tipos import Feicao, RaioX, Retirada

_TRANSFORMER_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:31983", always_xy=True)

# Paleta e metadados oficiais por camada
CAMADAS_INFO: dict[str, dict[str, str]] = {
    "alta_tensao": {
        "rotulo": "Linha de alta tensão (aérea)",
        "cor": "#d97706",
        "tipo": "linha",
        "stroke_width": "2.5",
        "dash": "",
    },
    "alta_tensao_sub": {
        "rotulo": "Linha de alta tensão (subterrânea)",
        "cor": "#b45309",
        "tipo": "linha",
        "stroke_width": "2.5",
        "dash": "5,3",
    },
    "duto": {
        "rotulo": "Duto Transpetro",
        "cor": "#7c3aed",
        "tipo": "linha",
        "stroke_width": "2.5",
        "dash": "",
    },
    "contaminada": {
        "rotulo": "Área contaminada",
        "cor": "#dc2626",
        "tipo": "poligono",
        "stroke_width": "1.5",
        "dash": "",
    },
    "risco": {
        "rotulo": "Risco geológico",
        "cor": "#ea580c",
        "tipo": "poligono",
        "stroke_width": "1.5",
        "dash": "",
    },
    "tombamento": {
        "rotulo": "Tombamento / envoltória",
        "cor": "#475569",
        "tipo": "poligono",
        "stroke_width": "1.5",
        "dash": "",
    },
    "area_publica": {
        "rotulo": "Área pública / parque",
        "cor": "#059669",
        "tipo": "poligono",
        "stroke_width": "1.5",
        "dash": "",
    },
    "favela": {
        "rotulo": "Favela",
        "cor": "#991b1b",
        "tipo": "poligono",
        "stroke_width": "1.5",
        "dash": "",
    },
    "inundacao": {
        "rotulo": "Inundação",
        "cor": "#0284c7",
        "tipo": "poligono",
        "stroke_width": "1.5",
        "dash": "",
    },
    "app": {
        "rotulo": "APP",
        "cor": "#16a34a",
        "tipo": "poligono",
        "stroke_width": "1.5",
        "dash": "",
    },
    "melhoramento": {
        "rotulo": "Melhoramento viário",
        "cor": "#ca8a04",
        "tipo": "poligono",
        "stroke_width": "1.5",
        "dash": "",
    },
    "estacoes": {
        "rotulo": "Estação metrô/trem",
        "cor": "#2563eb",
        "tipo": "ponto",
        "stroke_width": "1.5",
        "dash": "",
    },
}

# Sinônimos de camadas brutas para normalização
ALIAS_CAMADAS: dict[str, str] = {
    "linha_alta_tensao": "alta_tensao",
    "linha_subterranea_alta_tensao": "alta_tensao_sub",
    "transpetro_duto": "duto",
    "mancha_inundacao_100": "inundacao",
    "area_inundavel": "inundacao",
    "area_risco_geologico": "risco",
    "GEOSAMPA_area_contaminada_sigac": "contaminada",
    "area_contaminada_reabilitada_svma": "contaminada",
    "GEOSAMPA_cadastro_area_publica_cidadao": "area_publica",
    "pde_parque_municipal": "area_publica",
    "GEOSAMPA_v_praca_largo": "area_publica",
    "habita2geosampa_habi_favela2geosampa": "favela",
    "app_oida": "app",
    "geoconvias_lei_melhoramento_vigente": "melhoramento",
    "pde_intervencao_pontual_melhoramento_viario": "melhoramento",
    "estacao_metro": "estacoes",
    "estacao_metro_projetada": "estacoes",
    "estacao_trem": "estacoes",
    "estacao_trem_projetada": "estacoes",
    "patrimonio_cultural_area_envoltoria_CONDEPHAAT": "tombamento",
    "patrimonio_cultural_area_envoltoria_CONPRESP": "tombamento",
    "patrimonio_cultural_area_envoltoria_IPHAN": "tombamento",
    "patrimonio_cultural_bem_tombado": "tombamento",
}


def _normalizar_info_camada(camada: str) -> dict[str, str]:
    """Retorna os metadados visuais de uma camada, resolvendo apelidos."""
    c_chave = ALIAS_CAMADAS.get(camada, camada)
    if c_chave in CAMADAS_INFO:
        return CAMADAS_INFO[c_chave]
    return {
        "rotulo": camada.replace("_", " ").capitalize(),
        "cor": "#64748b",
        "tipo": "poligono",
        "stroke_width": "1.5",
        "dash": "",
    }


def _formatar_area(v: float) -> str:
    """Formata valor de área em m² no padrão pt-BR."""
    if abs(v - round(v)) < 0.05:
        return f"{int(round(v)):,}".replace(",", ".") + " m²"
    s = f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return (s[:-2] if s.endswith(",0") else s) + " m²"


def _para_utm(geom: shapely.Geometry) -> shapely.Geometry:
    """Reprojeta geometria de WGS84 para EPSG:31983 (metros)."""
    return shapely.transform(
        geom,
        lambda coords: np.column_stack(
            _TRANSFORMER_UTM.transform(coords[:, 0], coords[:, 1])
        ),
    )


def _garantir_utm(geom: shapely.Geometry) -> shapely.Geometry:
    """Garante que a geometria esteja em coordenadas métricas EPSG:31983."""
    minx, miny, maxx, maxy = geom.bounds
    if -180.0 <= minx <= 180.0 and -90.0 <= miny <= 90.0 and -180.0 <= maxx <= 180.0 and -90.0 <= maxy <= 90.0:
        return _para_utm(geom)
    return geom


def _converter_coords(
    coords: Sequence[tuple[float, float]],
    box_minx: float,
    box_maxy: float,
    escala: float,
    pad: float,
) -> list[tuple[float, float]]:
    """Converte lista de coordenadas métricas (UTM) para coordenadas SVG (pixels)."""
    return [
        (pad + (x - box_minx) * escala, pad + (box_maxy - y) * escala)
        for x, y in coords
    ]


def _linearring_to_d(coords: list[tuple[float, float]]) -> str:
    """Converte coordenadas em comando d de SVG no formato M x0 y0 L x1 y1 ... Z."""
    if not coords:
        return ""
    start = f"M {coords[0][0]:.1f} {coords[0][1]:.1f}"
    rest = " ".join(f"L {x:.1f} {y:.1f}" for x, y in coords[1:])
    return f"{start} {rest} Z" if rest else f"{start} Z"


def _linestring_to_d(coords: list[tuple[float, float]]) -> str:
    """Converte coordenadas de linha em comando d de SVG no formato M x0 y0 L x1 y1 ..."""
    if not coords:
        return ""
    start = f"M {coords[0][0]:.1f} {coords[0][1]:.1f}"
    rest = " ".join(f"L {x:.1f} {y:.1f}" for x, y in coords[1:])
    return f"{start} {rest}" if rest else start


def _geometria_para_svg(
    geom: shapely.Geometry,
    box_minx: float,
    box_maxy: float,
    escala: float,
    pad: float,
    attrs: dict[str, str],
) -> list[str]:
    """Converte geometria Shapely em elementos SVG puros (<path>, <circle>)."""
    elementos: list[str] = []
    if geom.is_empty:
        return elementos

    geom_type = shapely.get_type_id(geom)
    attr_str = " ".join(f'{k}="{v}"' for k, v in attrs.items() if v)

    if geom_type == shapely.GeometryType.POLYGON:
        ext_coords = _converter_coords(geom.exterior.coords, box_minx, box_maxy, escala, pad)
        d_parts = [_linearring_to_d(ext_coords)]
        for interior in geom.interiors:
            int_coords = _converter_coords(interior.coords, box_minx, box_maxy, escala, pad)
            d_parts.append(_linearring_to_d(int_coords))
        d = " ".join(d_parts)
        elementos.append(f'<path d="{d}" {attr_str} fill-rule="evenodd" />')

    elif geom_type == shapely.GeometryType.MULTIPOLYGON:
        for poly in geom.geoms:
            elementos.extend(_geometria_para_svg(poly, box_minx, box_maxy, escala, pad, attrs))

    elif geom_type in (shapely.GeometryType.LINESTRING, shapely.GeometryType.LINEARRING):
        coords = _converter_coords(geom.coords, box_minx, box_maxy, escala, pad)
        d = _linestring_to_d(coords)
        line_attrs = dict(attrs)
        line_attrs["fill"] = "none"
        l_attr_str = " ".join(f'{k}="{v}"' for k, v in line_attrs.items() if v)
        elementos.append(f'<path d="{d}" {l_attr_str} />')

    elif geom_type == shapely.GeometryType.MULTILINESTRING:
        for ls in geom.geoms:
            elementos.extend(_geometria_para_svg(ls, box_minx, box_maxy, escala, pad, attrs))

    elif geom_type == shapely.GeometryType.POINT:
        cx = pad + (geom.x - box_minx) * escala
        cy = pad + (box_maxy - geom.y) * escala
        r = attrs.get("r", "5")
        circle_attrs = {k: v for k, v in attrs.items() if k not in ("d", "fill-rule", "r")}
        c_attr_str = " ".join(f'{k}="{v}"' for k, v in circle_attrs.items() if v)
        elementos.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" {c_attr_str} />')

    elif geom_type == shapely.GeometryType.MULTIPOINT:
        for pt in geom.geoms:
            elementos.extend(_geometria_para_svg(pt, box_minx, box_maxy, escala, pad, attrs))

    elif geom_type == shapely.GeometryType.GEOMETRYCOLLECTION:
        for sub_geom in geom.geoms:
            elementos.extend(_geometria_para_svg(sub_geom, box_minx, box_maxy, escala, pad, attrs))

    return elementos


def _renderizar_feicao(
    geom: shapely.Geometry,
    info: dict[str, str],
    box_minx: float,
    box_maxy: float,
    escala: float,
    pad: float,
) -> list[str]:
    """Gera elementos SVG estilizados para uma feição de acordo com seu tipo geométrico."""
    cor = info.get("cor", "#64748b")
    dash = info.get("dash", "")
    stroke_width = info.get("stroke_width", "1.5")

    geom_type = shapely.get_type_id(geom)
    if geom_type in (shapely.GeometryType.POLYGON, shapely.GeometryType.MULTIPOLYGON):
        attrs = {
            "fill": cor,
            "fill-opacity": "0.35",
            "stroke": cor,
            "stroke-width": stroke_width,
        }
        if dash:
            attrs["stroke-dasharray"] = dash
        return _geometria_para_svg(geom, box_minx, box_maxy, escala, pad, attrs)

    if geom_type in (shapely.GeometryType.LINESTRING, shapely.GeometryType.MULTILINESTRING, shapely.GeometryType.LINEARRING):
        attrs = {
            "fill": "none",
            "stroke": cor,
            "stroke-width": stroke_width or "2.5",
        }
        if dash:
            attrs["stroke-dasharray"] = dash
        return _geometria_para_svg(geom, box_minx, box_maxy, escala, pad, attrs)

    if geom_type in (shapely.GeometryType.POINT, shapely.GeometryType.MULTIPOINT):
        attrs = {
            "fill": cor,
            "stroke": "#ffffff",
            "stroke-width": "1.5",
            "r": "6",
        }
        return _geometria_para_svg(geom, box_minx, box_maxy, escala, pad, attrs)

    if geom_type == shapely.GeometryType.GEOMETRYCOLLECTION:
        elementos: list[str] = []
        for g in geom.geoms:
            elementos.extend(_renderizar_feicao(g, info, box_minx, box_maxy, escala, pad))
        return elementos

    return []


def _obter_geometrias_retiradas(
    geom_lote_utm: shapely.Geometry,
    geom_liq_utm: shapely.Geometry | None,
    retiradas: Sequence[Retirada],
    feicoes: Sequence[Feicao],
) -> list[tuple[Retirada, shapely.Geometry]]:
    """Determina a geometria em UTM para cada retirada presente no lote."""
    if not retiradas:
        return []

    diff_total: shapely.Geometry | None = None
    if geom_liq_utm is not None and not geom_liq_utm.is_empty:
        d = shapely.difference(geom_lote_utm, geom_liq_utm)
        if not d.is_empty:
            diff_total = shapely.make_valid(d) if not shapely.is_valid(d) else d

    sub_poligonos_diff: list[shapely.Geometry] = []
    if diff_total is not None and not diff_total.is_empty:
        geom_type = shapely.get_type_id(diff_total)
        if geom_type == shapely.GeometryType.MULTIPOLYGON:
            sub_poligonos_diff = list(diff_total.geoms)
        elif geom_type == shapely.GeometryType.GEOMETRYCOLLECTION:
            sub_poligonos_diff = [
                g for g in diff_total.geoms
                if shapely.get_type_id(g) in (shapely.GeometryType.POLYGON, shapely.GeometryType.MULTIPOLYGON)
            ]
        elif geom_type == shapely.GeometryType.POLYGON:
            sub_poligonos_diff = [diff_total]

    resultado: list[tuple[Retirada, shapely.Geometry]] = []

    for idx, ret in enumerate(retiradas):
        camada_alvo = ALIAS_CAMADAS.get(ret.camada, ret.camada)
        feicoes_corresp = [
            f for f in feicoes
            if ALIAS_CAMADAS.get(f.camada, f.camada) == camada_alvo
        ]

        geom_ret: shapely.Geometry | None = None

        if feicoes_corresp:
            partes_inter: list[shapely.Geometry] = []
            for f in feicoes_corresp:
                g_f = _garantir_utm(shapely.from_wkt(f.geometria_wkt))
                inter = shapely.intersection(geom_lote_utm, g_f)
                if not inter.is_empty:
                    partes_inter.append(inter)
            if partes_inter:
                geom_ret = shapely.union_all(partes_inter) if len(partes_inter) > 1 else partes_inter[0]

        if geom_ret is None or geom_ret.is_empty:
            if len(retiradas) == 1:
                geom_ret = diff_total
            else:
                if sub_poligonos_diff and idx < len(sub_poligonos_diff):
                    geom_ret = sub_poligonos_diff[idx]
                else:
                    geom_ret = diff_total

        if geom_ret is not None and not geom_ret.is_empty:
            if not shapely.is_valid(geom_ret):
                geom_ret = shapely.make_valid(geom_ret)
            if not geom_ret.is_empty:
                resultado.append((ret, geom_ret))

    return resultado


def gerar(rx: RaioX, feicoes: Sequence[Feicao] = ()) -> str:
    """Gera croqui vetorial SVG (largura 600, altura proporcional) em projeção métrica EPSG:31983."""
    # 1. Carregar e reprojetar geometria do lote bruto
    geom_lote_wgs = shapely.from_wkt(rx.lote.geometria_wkt)
    geom_lote_utm = _garantir_utm(geom_lote_wgs)

    # 2. Avaliar geometria líquida e retiradas
    retiradas_lista = list(rx.area.retiradas) if (rx.area and rx.area.retiradas) else []
    tem_retiradas = len(retiradas_lista) > 0

    geom_liq_utm: shapely.Geometry | None = None
    liquido_diferente = False
    if rx.area and rx.area.geometria_liquida_wkt:
        geom_liq_raw = shapely.from_wkt(rx.area.geometria_liquida_wkt)
        if not geom_liq_raw.is_empty:
            geom_liq_cand = _garantir_utm(geom_liq_raw)
            diff_area = abs(geom_lote_utm.area - geom_liq_cand.area)
            if tem_retiradas or not geom_liq_cand.equals_exact(geom_lote_utm, tolerance=0.1) or diff_area > 1.0:
                geom_liq_utm = geom_liq_cand
                liquido_diferente = True

    # 3. Extrair geometrias das retiradas
    geoms_retiradas = _obter_geometrias_retiradas(
        geom_lote_utm, geom_liq_utm, retiradas_lista, feicoes
    )

    # 4. Enquadramento e Moldura
    minx, miny, maxx, maxy = geom_lote_utm.bounds
    dx = maxx - minx
    dy = maxy - miny
    margem_m = max(20.0, 0.15 * max(dx, dy))
    box_minx = minx - margem_m
    box_miny = miny - margem_m
    box_maxx = maxx + margem_m
    box_maxy = maxy + margem_m
    moldura = shapely.box(box_minx, box_miny, box_maxx, box_maxy)

    # 5. Recorte das Feições do Entorno
    feicoes_validas: list[tuple[str, shapely.Geometry, dict[str, str]]] = []
    for f in feicoes:
        g = shapely.from_wkt(f.geometria_wkt)
        g_utm = _garantir_utm(g)
        g_rec = shapely.intersection(g_utm, moldura)
        if not g_rec.is_empty:
            info = _normalizar_info_camada(f.camada)
            feicoes_validas.append((f.camada, g_rec, info))

    # 6. Escala e Coordenadas do SVG
    largura_total = 600
    pad = 30.0
    w_util = largura_total - 2 * pad  # 540 px
    largura_m = box_maxx - box_minx
    altura_m = box_maxy - box_miny
    escala = w_util / max(largura_m, 1.0)
    h_util = altura_m * escala

    # 7. Estruturação da Legenda
    itens_legenda: list[tuple[str, str, str, str]] = []  # (rotulo, cor, tipo, dash)

    if not tem_retiradas:
        itens_legenda.append(("Lote cadastral", "#1e293b", "borda", ""))
        if liquido_diferente:
            itens_legenda.append(("Lote líquido", "#0284c7", "poligono_liq", "4,2"))
        itens_legenda.append(("sem retiradas", "#64748b", "texto_puro", ""))

        rotulos_vistos_sem: set[str] = set()
        for _c_nome, _g_rec, info in feicoes_validas:
            rot = info.get("rotulo", "")
            if rot and rot not in rotulos_vistos_sem:
                rotulos_vistos_sem.add(rot)
                cor = info.get("cor", "#64748b")
                tipo = info.get("tipo", "poligono")
                dash = info.get("dash", "")
                itens_legenda.append((rot, cor, tipo, dash))
    else:
        bruta_m2 = rx.area.bruta_m2 if (rx.area and rx.area.bruta_m2 > 0) else rx.lote.area_terreno_m2
        itens_legenda.append((f"Área bruta: {_formatar_area(bruta_m2)}", "#1e293b", "borda", ""))

        for ret in retiradas_lista:
            nome_ret = ret.rotulo if ret.rotulo else _normalizar_info_camada(ret.camada)["rotulo"]
            cor_ret = _normalizar_info_camada(ret.camada)["cor"]
            itens_legenda.append((f"{nome_ret}: {_formatar_area(ret.area_m2)}", cor_ret, f"retirada_{ret.camada}", ""))

        if geom_liq_utm is not None and not geom_liq_utm.is_empty:
            liquida_m2 = geom_liq_utm.area
        elif rx.area and rx.area.liquida_m2 > 0:
            liquida_m2 = rx.area.liquida_m2
        else:
            liquida_m2 = bruta_m2 - sum(r.area_m2 for r in retiradas_lista)

        itens_legenda.append((f"Área líquida: {_formatar_area(liquida_m2)}", "#0284c7", "liquida_destaque", ""))

        rotulos_ret_nomes = {
            (r.rotulo if r.rotulo else _normalizar_info_camada(r.camada)["rotulo"])
            for r in retiradas_lista
        }
        rotulos_vistos_com: set[str] = set(rotulos_ret_nomes)
        for _c_nome, _g_rec, info in feicoes_validas:
            rot = info.get("rotulo", "")
            if rot and rot not in rotulos_vistos_com:
                rotulos_vistos_com.add(rot)
                cor = info.get("cor", "#64748b")
                tipo = info.get("tipo", "poligono")
                dash = info.get("dash", "")
                itens_legenda.append((rot, cor, tipo, dash))

    max_char_len = max(len(rot) for rot, _, _, _ in itens_legenda) if itens_legenda else 12
    leg_largura = max(240.0, max_char_len * 7.2 + 44.0)
    leg_altura = 28.0 + len(itens_legenda) * 20.0
    altura_total = max(round(h_util + 2 * pad), 400, int(leg_altura + 2 * pad + 20))
    leg_x = largura_total - pad - leg_largura
    leg_y = altura_total - pad - leg_altura

    elementos_svg: list[str] = []

    # 8. Tag <defs> com Patterns de Hachura para Retiradas
    defs_patterns: list[str] = []
    seen_patterns: set[str] = set()
    for ret in retiradas_lista:
        pattern_id = f"hatch-{ret.camada}"
        if pattern_id not in seen_patterns:
            seen_patterns.add(pattern_id)
            info_ret = _normalizar_info_camada(ret.camada)
            cor_ret = info_ret.get("cor", "#ca8a04")
            defs_patterns.append(
                f'    <pattern id="{pattern_id}" width="8" height="8" '
                f'patternTransform="rotate(45 0 0)" patternUnits="userSpaceOnUse">\n'
                f'      <line x1="0" y1="0" x2="0" y2="8" stroke="{cor_ret}" stroke-width="2" />\n'
                '    </pattern>'
            )

    if defs_patterns:
        elementos_svg.append("<defs>\n" + "\n".join(defs_patterns) + "\n  </defs>")

    # Fundo do mapa
    elementos_svg.append('<rect width="100%" height="100%" fill="#f8fafc" />')

    # Grade sutil de fundo
    elementos_svg.append(
        f'<rect x="{pad}" y="{pad}" width="{w_util:.1f}" height="{h_util:.1f}" '
        'fill="#ffffff" stroke="#e2e8f0" stroke-width="1" />'
    )

    # 9. Desenho do Lote Bruto (Preenchimento Base)
    attrs_lote_base = {
        "fill": "#f1f5f9",
        "fill-opacity": "0.6",
        "stroke": "none",
    }
    elementos_svg.extend(
        _geometria_para_svg(geom_lote_utm, box_minx, box_maxy, escala, pad, attrs_lote_base)
    )

    # 10. Desenho do Lote Líquido (se houver retiradas ou líquido diferente)
    if tem_retiradas and geom_liq_utm is not None and not geom_liq_utm.is_empty:
        attrs_lote_liq = {
            "fill": "#e0f2fe",
            "fill-opacity": "0.6",
            "stroke": "#0284c7",
            "stroke-width": "2.5",
        }
        elementos_svg.extend(
            _geometria_para_svg(geom_liq_utm, box_minx, box_maxy, escala, pad, attrs_lote_liq)
        )
    elif liquido_diferente and geom_liq_utm is not None:
        attrs_lote_liq = {
            "fill": "#e0f2fe",
            "fill-opacity": "0.7",
            "stroke": "#0284c7",
            "stroke-width": "1.8",
            "stroke-dasharray": "4,2",
        }
        elementos_svg.extend(
            _geometria_para_svg(geom_liq_utm, box_minx, box_maxy, escala, pad, attrs_lote_liq)
        )

    # 11. Desenho das Feições Recortadas do Entorno
    for _camada, g_rec, info in feicoes_validas:
        elementos_svg.extend(
            _renderizar_feicao(g_rec, info, box_minx, box_maxy, escala, pad)
        )

    # 12. Desenho das Retiradas com Hachura Diagonal
    rotulos_retiradas_svg: list[str] = []
    for ret, geom_ret in geoms_retiradas:
        info_ret = _normalizar_info_camada(ret.camada)
        cor_ret = info_ret.get("cor", "#ca8a04")

        attrs_fundo = {
            "fill": cor_ret,
            "fill-opacity": "0.15",
            "stroke": "none",
        }
        elementos_svg.extend(
            _geometria_para_svg(geom_ret, box_minx, box_maxy, escala, pad, attrs_fundo)
        )

        attrs_hatch = {
            "fill": f"url(#hatch-{ret.camada})",
            "stroke": cor_ret,
            "stroke-width": "1.5",
        }
        elementos_svg.extend(
            _geometria_para_svg(geom_ret, box_minx, box_maxy, escala, pad, attrs_hatch)
        )

        nome_ret = ret.rotulo if ret.rotulo else info_ret.get("rotulo", ret.camada)
        area_ret_fmt = _formatar_area(ret.area_m2)
        txt_rotulo = f"{nome_ret} · {area_ret_fmt}"

        pt_ret = shapely.point_on_surface(geom_ret)
        rx_pt = pad + (pt_ret.x - box_minx) * escala
        ry_pt = pad + (box_maxy - pt_ret.y) * escala
        w_badge = max(len(txt_rotulo) * 6.8 + 16.0, 75.0)
        half_w = w_badge / 2.0

        rotulos_retiradas_svg.append(
            f'<g class="rotulo-retirada" transform="translate({rx_pt:.1f}, {ry_pt:.1f})">'
            f'<rect x="-{half_w:.1f}" y="-11" width="{w_badge:.1f}" height="22" rx="4" '
            f'fill="#ffffff" fill-opacity="0.92" stroke="{cor_ret}" stroke-width="1" />'
            f'<text x="0" y="1" text-anchor="middle" dominant-baseline="central" '
            f'font-family="system-ui, -apple-system, sans-serif" font-size="10.5" '
            f'font-weight="600" fill="#0f172a">{html.escape(txt_rotulo)}</text>'
            '</g>'
        )

    # 13. Contorno Escuro do Lote Bruto
    attrs_lote_borda = {
        "fill": "none",
        "stroke": "#1e293b",
        "stroke-width": "2.5",
    }
    elementos_svg.extend(
        _geometria_para_svg(geom_lote_utm, box_minx, box_maxy, escala, pad, attrs_lote_borda)
    )

    # 14. Rótulos das Retiradas
    elementos_svg.extend(rotulos_retiradas_svg)

    # 15. Área do Lote no Centro
    pt_interior = (
        shapely.point_on_surface(geom_liq_utm)
        if (geom_liq_utm is not None and not geom_liq_utm.is_empty)
        else shapely.point_on_surface(geom_lote_utm)
    )
    cx = pad + (pt_interior.x - box_minx) * escala
    cy = pad + (box_maxy - pt_interior.y) * escala
    area_fmt = _formatar_area(rx.lote.area_terreno_m2)
    w_box_centro = max(len(area_fmt) * 8.5 + 24.0, 96.0)
    half_box_w = w_box_centro / 2.0

    elementos_svg.append(
        f'<g id="rotulo-area" transform="translate({cx:.1f}, {cy:.1f})">'
        f'<rect x="-{half_box_w:.1f}" y="-12" width="{w_box_centro:.1f}" height="24" rx="4" '
        'fill="#ffffff" fill-opacity="0.88" stroke="#cbd5e1" stroke-width="1" />'
        f'<text x="0" y="1" text-anchor="middle" dominant-baseline="central" '
        f'font-family="system-ui, -apple-system, sans-serif" font-size="13" '
        f'font-weight="bold" fill="#0f172a">{html.escape(area_fmt)}</text>'
        '</g>'
    )

    # 16. Seta do Norte
    elementos_svg.append(
        '<g id="norte" transform="translate(560, 42)">'
        '<circle cx="0" cy="0" r="16" fill="#ffffff" fill-opacity="0.9" stroke="#cbd5e1" stroke-width="1" />'
        '<polygon points="0,-12 4,2 0,-1 -4,2" fill="#0f172a" />'
        '<polygon points="0,1 4,2 0,10 -4,2" fill="#94a3b8" />'
        '<text x="0" y="-14" text-anchor="middle" font-family="system-ui, -apple-system, sans-serif" '
        'font-size="11" font-weight="bold" fill="#0f172a">N</text>'
        '</g>'
    )

    # 17. Barra de Escala com Número Redondo
    candidatos_m = [10, 20, 50, 100, 200, 500]
    dentro = [c for c in candidatos_m if 50.0 <= c * escala <= 150.0]
    if dentro:
        d_m = min(dentro, key=lambda c: abs(c * escala - 80.0))
    else:
        d_m = min(candidatos_m, key=lambda c: abs(c * escala - 80.0))

    bar_px = d_m * escala
    bx = pad + 10.0
    by = altura_total - 25.0

    elementos_svg.append(
        f'<g id="escala" transform="translate({bx:.1f}, {by:.1f})">'
        f'<rect x="-6" y="-18" width="{bar_px + 12:.1f}" height="26" rx="4" '
        'fill="#ffffff" fill-opacity="0.85" stroke="#cbd5e1" stroke-width="1" />'
        f'<line x1="0" y1="0" x2="{bar_px:.1f}" y2="0" stroke="#0f172a" stroke-width="2" />'
        '<line x1="0" y1="-4" x2="0" y2="4" stroke="#0f172a" stroke-width="2" />'
        f'<line x1="{bar_px:.1f}" y1="-4" x2="{bar_px:.1f}" y2="4" stroke="#0f172a" stroke-width="2" />'
        f'<text x="{bar_px / 2:.1f}" y="-7" text-anchor="middle" '
        'font-family="system-ui, -apple-system, sans-serif" font-size="11" '
        f'font-weight="600" fill="#0f172a">{d_m} m</text>'
        '</g>'
    )

    # 18. Renderização da Legenda
    leg_partes = [
        f'<g id="legenda" transform="translate({leg_x:.1f}, {leg_y:.1f})">',
        f'<rect x="0" y="0" width="{leg_largura:.1f}" height="{leg_altura:.1f}" rx="5" '
        'fill="#ffffff" fill-opacity="0.92" stroke="#cbd5e1" stroke-width="1" />',
        '<text x="12" y="18" font-family="system-ui, -apple-system, sans-serif" '
        'font-size="10.5" font-weight="bold" fill="#334155" letter-spacing="0.5">LEGENDA</text>',
    ]

    for i, (rot, cor, tipo, dash) in enumerate(itens_legenda):
        iy = 36.0 + i * 20.0
        rot_escapado = html.escape(rot)
        dash_attr = f'stroke-dasharray="{dash}"' if dash else ""

        if tipo == "borda":
            simbolo = (
                f'<rect x="12" y="{iy - 9:.1f}" width="14" height="11" rx="2" '
                'fill="#f1f5f9" stroke="#1e293b" stroke-width="2" />'
            )
            texto = (
                f'<text x="32" y="{iy}" font-family="system-ui, -apple-system, sans-serif" '
                f'font-size="10.5" font-weight="600" fill="#1e293b">{rot_escapado}</text>'
            )
        elif tipo == "liquida_destaque":
            simbolo = (
                f'<rect x="12" y="{iy - 9:.1f}" width="14" height="11" rx="2" '
                'fill="#e0f2fe" stroke="#0284c7" stroke-width="2" />'
            )
            texto = (
                f'<text x="32" y="{iy}" font-family="system-ui, -apple-system, sans-serif" '
                f'font-size="10.5" font-weight="600" fill="#0284c7">{rot_escapado}</text>'
            )
        elif tipo.startswith("retirada_"):
            camada_nome = tipo.removeprefix("retirada_")
            simbolo = (
                f'<rect x="12" y="{iy - 9:.1f}" width="14" height="11" rx="2" '
                f'fill="url(#hatch-{camada_nome})" stroke="{cor}" stroke-width="1.5" />'
            )
            texto = (
                f'<text x="32" y="{iy}" font-family="system-ui, -apple-system, sans-serif" '
                f'font-size="10.5" fill="#1e293b">{rot_escapado}</text>'
            )
        elif tipo == "poligono_liq":
            simbolo = (
                f'<rect x="12" y="{iy - 9:.1f}" width="14" height="11" rx="2" '
                'fill="#e0f2fe" stroke="#0284c7" stroke-width="1.8" stroke-dasharray="4,2" />'
            )
            texto = (
                f'<text x="32" y="{iy}" font-family="system-ui, -apple-system, sans-serif" '
                f'font-size="10.5" fill="#1e293b">{rot_escapado}</text>'
            )
        elif tipo == "linha":
            simbolo = (
                f'<line x1="12" y1="{iy - 4:.1f}" x2="26" y2="{iy - 4:.1f}" '
                f'stroke="{cor}" stroke-width="2.5" {dash_attr} />'
            )
            texto = (
                f'<text x="32" y="{iy}" font-family="system-ui, -apple-system, sans-serif" '
                f'font-size="10.5" fill="#1e293b">{rot_escapado}</text>'
            )
        elif tipo == "ponto":
            simbolo = (
                f'<circle cx="19" cy="{iy - 4:.1f}" r="4.5" '
                f'fill="{cor}" stroke="#ffffff" stroke-width="1.2" />'
            )
            texto = (
                f'<text x="32" y="{iy}" font-family="system-ui, -apple-system, sans-serif" '
                f'font-size="10.5" fill="#1e293b">{rot_escapado}</text>'
            )
        elif tipo == "texto_puro":
            simbolo = f'<circle cx="19" cy="{iy - 4:.1f}" r="2" fill="#94a3b8" />'
            texto = (
                f'<text x="32" y="{iy}" font-family="system-ui, -apple-system, sans-serif" '
                f'font-size="10" font-style="italic" fill="#64748b">{rot_escapado}</text>'
            )
        else:
            simbolo = (
                f'<rect x="12" y="{iy - 9:.1f}" width="14" height="11" rx="2" '
                f'fill="{cor}" fill-opacity="0.45" stroke="{cor}" stroke-width="1.5" {dash_attr} />'
            )
            texto = (
                f'<text x="32" y="{iy}" font-family="system-ui, -apple-system, sans-serif" '
                f'font-size="10.5" fill="#1e293b">{rot_escapado}</text>'
            )

        leg_partes.append(f"{simbolo}{texto}")

    leg_partes.append("</g>")
    elementos_svg.append("\n".join(leg_partes))

    # 19. Montagem final do SVG
    corpo = "\n  ".join(elementos_svg)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 600 {altura_total}" width="600" height="{altura_total}">\n'
        f"  {corpo}\n"
        "</svg>"
    )
