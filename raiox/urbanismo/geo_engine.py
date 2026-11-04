# Cópia congelada de prospeccao-marechal-tito/core/geo_engine.py em 2026-10-28.
from collections import defaultdict

import numpy as np
from shapely import simplify as shapely_simplify
from shapely import transform as shapely_transform
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.strtree import STRtree

from raiox.urbanismo._legado_sinais import SINAIS_ORDEM, texto_alertas
from raiox.urbanismo.lotes_geom import selecionar

MIN_SHARE = 0.10  # Regra dos 10%
TOL_DIVISA_M = 1.5  # folga do cadastro entre lotes vizinhos ao medir a divisa em comum
SIMPLIFY_TOL = 5e-6  # ~0.5m em WGS84 — simplifica vértices p/ renderização


def _brl(valor: float) -> str:
    return f"R$ {valor:,.0f}".replace(",", ".")


def _poligonos(geom) -> list:
    """Achata Polygon/MultiPolygon em lista de Polygon (MultiPolygon não aceita MultiPolygon)."""
    if isinstance(geom, Polygon):
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]


def calcular_composicoes_vgv(
    df_source,
    lotes_geom_source,
    criterio="vgv",
    vgv_alvo=50000000,
    preco_m2_global=7000.0,
    area_alvo=1500.0,
    sql_filtrados=None,
    progresso=None,
    min_divisa_m=0.0,
):
    """
    Retorna (pares_fc, trincas_fc) — FeatureCollections separadas, com TODAS as possibilidades:
    um mesmo lote pode aparecer em várias duplas/trincas (o app mostra as opções de cada lote).
    Pares   (verde):   2 lotes vizinhos que batem a meta juntos.
    Trincas (amarelo): 3 lotes ligados entre si, mas só se nenhuma dupla válida dentro deles já
                       bate a meta (preferência sempre para a dupla).
    Vizinhos = divisa em comum de pelo menos `min_divisa_m` metros (0 = basta encostar).
    Regra dos 10%: nenhum lote pode contribuir < 10% do total da composição, medido na
    mesma unidade da meta (VGV potencial no critério "vgv"; área no critério "area").
    Azul: lotes que já batem sozinhos — excluídos das composições.
    Lotes com CA 0 (zona fora do Quadro 3) são ignorados.
    """
    def _p(frac, texto):
        if progresso:
            progresso(frac, texto)

    _p(0.05, "Separando os lotes candidatos...")
    # 1. Dados por lote (dict simples: evita .loc linha a linha)
    cols = [
        "cd_setor_fiscal",
        "cd_quadra_fiscal",
        "cd_lote",
        "qt_area_terreno",
        "ca_maximo",
        "zoneamento",
        "nm_logradouro_completo",
        "dc_tipo_uso_imovel",
    ]
    # contexto opcional (scripts/calcular_contexto.py): se faltar, as composições saem sem ele
    cols += [
        c
        for c in (
            "qt_area_construida",
            "pct_publica",
            "pct_favela",
            "pct_contaminada",
            "pct_risco",
            "dist_estacao_m",
            "estacao_nome",
            "dist_duto_m",
            "dist_alta_tensao_m",
        )
        if c in df_source.columns
    ]
    info = {}
    for r in df_source[cols].itertuples(index=False):
        lid = f"{r[0]}{r[1]}{r[2]}"
        if sql_filtrados is None or lid in sql_filtrados:
            info[lid] = r

    usa_vgv = criterio == "vgv"
    meta = vgv_alvo if usa_vgv else area_alvo
    fator = preco_m2_global if usa_vgv else 0.0

    def valor(area, ca):
        return area * ca * fator if usa_vgv else area

    lote_dict = {}
    geometries = []
    valid_ids = []

    for feat in selecionar(lotes_geom_source, info):
        p = feat["properties"]
        lid = (
            str(p.get("cd_setor_fiscal", ""))
            + str(p.get("cd_quadra_fiscal", ""))
            + str(p.get("cd_lote", ""))
        )
        r = info.get(lid)
        if r is None or lid in lote_dict:
            continue

        area = float(r[3] or 0)
        ca = float(r[4] or 0)
        if area <= 0 or ca <= 0:
            continue

        contrib = valor(area, ca)
        # Azul: já bate a meta sozinho -> fora das composições
        if contrib >= meta:
            continue
        # Pré-filtro (condição necessária da regra dos 10%): contribuição ≥ 10% da meta
        if contrib < MIN_SHARE * meta:
            continue

        geom = shapely_simplify(
            shape(feat["geometry"]), SIMPLIFY_TOL, preserve_topology=True
        )
        if geom.is_empty:
            continue
        def _num(nome, padrao=0.0):
            v = getattr(r, nome, padrao)
            return padrao if v is None or v != v else float(v)

        lote_dict[lid] = {
            "geom": geom,
            "construida": _num("qt_area_construida"),
            "dist": _num("dist_estacao_m", float("nan")),
            "estacao": str(getattr(r, "estacao_nome", "") or ""),
            "sinais": texto_alertas(
                _num("pct_publica"),
                _num("pct_favela"),
                _num("pct_contaminada"),
                _num("pct_risco"),
                _num("dist_duto_m", float("nan")),
                _num("dist_alta_tensao_m", float("nan")),
            ),
            "area": area,
            "ca": ca,
            "contrib": contrib,
            "zona": str(r[5] or "N/A"),
            "endereco": str(r[6] or ""),
            "uso": str(r[7] or ""),
        }
        geometries.append(geom)
        valid_ids.append(lid)

    if not geometries:
        empty = {"type": "FeatureCollection", "features": []}
        return empty, empty

    _p(0.3, "Procurando lotes vizinhos...")
    # 2. Adjacência espacial via STRtree (Shapely 2.0 vetorizado)
    tree = STRtree(geometries)
    # 1e-5 em WGS84 = ~1.1 metros. Suficiente para falhas de desenho do GeoSampa,
    # mas pequeno o suficiente para não pular ruas (que têm >5m).
    dist_tol = 1e-5
    idx1, idx2 = tree.query(geometries, predicate="dwithin", distance=dist_tol)

    adj = defaultdict(set)
    for i, j in zip(idx1, idx2):
        if i != j:
            adj[int(i)].add(int(j))

    # 2b. Divisa em comum mínima: lotes que só se encostam numa quina não formam composição
    divisa = {}
    if min_divisa_m > 0 and adj:
        lat0 = float(np.mean([g.centroid.y for g in geometries]))
        kx, ky = 111320.0 * np.cos(np.radians(lat0)), 110574.0
        metricas = [
            shapely_transform(g, lambda c: c * np.array([kx, ky])) for g in geometries
        ]

        def _divisa_m(i, j):
            # comprimento do contorno de um lote voltado para o outro (menor dos dois sentidos)
            a = metricas[i].boundary.intersection(metricas[j].buffer(TOL_DIVISA_M)).length
            b = metricas[j].boundary.intersection(metricas[i].buffer(TOL_DIVISA_M)).length
            return min(a, b)

        adj_ok = defaultdict(set)
        for i in list(adj):
            for j in adj[i]:
                if i < j:
                    d = _divisa_m(i, j)
                    if d >= min_divisa_m:
                        adj_ok[i].add(j)
                        adj_ok[j].add(i)
                        divisa[(i, j)] = d
        adj = adj_ok

    # 3. Funções auxiliares
    contribs = [lote_dict[lid]["contrib"] for lid in valid_ids]
    areas = [lote_dict[lid]["area"] for lid in valid_ids]

    def bate_meta(indices):
        total = sum(contribs[i] for i in indices)
        if total < meta:
            return False
        return all(contribs[i] / total >= MIN_SHARE for i in indices)

    def montar_feature(indices):
        ids = [valid_ids[i] for i in indices]
        polys = [p for i in indices for p in _poligonos(geometries[i])]
        geom = MultiPolygon(polys)
        total_area = sum(areas[i] for i in indices)
        potencial = sum(areas[i] * lote_dict[valid_ids[i]]["ca"] for i in indices)
        zonas = list(dict.fromkeys(lote_dict[lid]["zona"] for lid in ids))
        cas = list(dict.fromkeys(f"{lote_dict[lid]['ca']:g}" for lid in ids))
        _presentes = {x for lid in ids for x in lote_dict[lid]["sinais"].split(" · ") if x}
        sinais = [x for x in SINAIS_ORDEM if x in _presentes]  # ordem fixa
        perto = min(
            ids,
            key=lambda lid: (
                lote_dict[lid]["dist"] if lote_dict[lid]["dist"] == lote_dict[lid]["dist"] else float("inf")
            ),
        )
        d_est, n_est = lote_dict[perto]["dist"], lote_dict[perto]["estacao"]
        tem_est = bool(n_est) and d_est == d_est
        construida = sum(lote_dict[lid]["construida"] for lid in ids)
        return {
            "type": "Feature",
            "geometry": geom.__geo_interface__,
            "properties": {
                "id_par": " + ".join(ids),
                "lids": ids,
                "tipo": "dupla" if len(ids) == 2 else "trinca",
                "n_lotes": len(ids),
                "area_total": round(total_area, 2),
                "potencial_total": round(potencial, 2),
                "vgv_estimado": (
                    _brl(potencial * preco_m2_global) if potencial > 0 else "N/A"
                ),
                "zonas": " | ".join(zonas),
                "ca_max": " | ".join(cas),
                "enderecos": " + ".join(lote_dict[lid]["endereco"] for lid in ids),
                "usos": " + ".join(lote_dict[lid]["uso"] for lid in ids),
                "sinais": " · ".join(sinais) if sinais else "—",
                "estacao_nome": n_est if tem_est else "",
                "dist_estacao_m": round(d_est) if tem_est else None,
                "estacao_txt": (
                    f"{n_est} · {d_est:,.0f} m".replace(",", ".") if tem_est else "—"
                ),
                "construido_pct": round(100.0 * construida / total_area),
            },
        }

    _p(0.6, "Testando duplas e trincas contra a meta...")
    # 4. Busca exaustiva: todas as duplas e trincas que batem a meta
    candidatos = []
    pares_ok = set()

    for i in range(len(geometries)):
        for j in adj[i]:
            if i < j and bate_meta([i, j]):
                pares_ok.add((i, j))
                candidatos.append((areas[i] + areas[j], [i, j], "par"))

    # Trincas conectadas: todo trio conectado tem um par adjacente (i,j) e um terceiro k
    # vizinho de i ou de j. Coletar em conjunto de tuplas ordenadas evita perder trios
    # (independe de qual lote é o central) e duplicatas.
    trios = set()
    for i in range(len(geometries)):
        for j in adj[i]:
            if i >= j:
                continue
            for k in (adj[i] | adj[j]) - {i, j}:
                trios.add(tuple(sorted((i, j, k))))

    for i, j, k in trios:
        # Se algum sub-par já bate a meta, a trinca é redundante (aparece como Dupla)
        if (i, j) in pares_ok or (i, k) in pares_ok or (j, k) in pares_ok:
            continue
        if bate_meta([i, j, k]):
            candidatos.append((areas[i] + areas[j] + areas[k], [i, j, k], "trinca"))

    _p(0.9, "Montando as possibilidades...")
    # Todas as possibilidades, da maior área para a menor (ordem determinística)
    candidatos.sort(key=lambda x: (-x[0], x[1]))
    pares_features = [montar_feature(ix) for _, ix, tipo in candidatos if tipo == "par"]
    trincas_features = [montar_feature(ix) for _, ix, tipo in candidatos if tipo == "trinca"]

    _p(1.0, "Pronto")
    return (
        {"type": "FeatureCollection", "features": pares_features},
        {"type": "FeatureCollection", "features": trincas_features},
    )
