"""Avaliação de restrições urbanísticas e cálculo de farol de sinais de lotes."""
from __future__ import annotations

import numpy as np
import pyproj
import shapely

from raiox.camadas import regras_com_uso
from raiox import dados
from raiox.tipos import LoteCadastro, Sinal

_TRANSFORMER_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:31983", always_xy=True)

_CAMADAS_ESTACOES: tuple[str, ...] = (
    "estacao_metro",
    "estacao_trem",
    "estacao_metro_projetada",
    "estacao_trem_projetada",
)


def _para_utm(geom: shapely.Geometry) -> shapely.Geometry:
    """Reprojeta uma geometria WGS84 para EPSG:31983."""
    return shapely.transform(
        geom,
        lambda coords: np.column_stack(
            _TRANSFORMER_UTM.transform(coords[:, 0], coords[:, 1])
        ),
    )


def _chave_bate(val_feicao: object, val_lote: str) -> bool:
    """Verifica correspondência cadastral desconsiderando zeros à esquerda."""
    if val_feicao is None:
        return False
    s_f = str(val_feicao).strip().lstrip("0") or "0"
    s_l = str(val_lote).strip().lstrip("0") or "0"
    return s_f == s_l


def _montar_fonte(camadas: list[str]) -> str:
    """Monta a string de fonte no formato padrão GeoSampa com datas de download."""
    datas = [dados.data_camada(c) for c in camadas]
    datas_validas = list(dict.fromkeys([d for d in datas if d]))
    texto_data = ", ".join(datas_validas) if datas_validas else "data desconhecida"
    return f"GeoSampa · {', '.join(camadas)} · baixado em {texto_data}"


def avaliar(lote: LoteCadastro) -> list[Sinal]:
    """Avalia o lote contra as regras de camadas do catálogo com uso 'sinal'."""
    geom_lote_wgs = shapely.from_wkt(lote.geometria_wkt)
    if not shapely.is_valid(geom_lote_wgs):
        geom_lote_wgs = shapely.make_valid(geom_lote_wgs)

    lote_utm = _para_utm(geom_lote_wgs)
    area_lote_utm = float(shapely.area(lote_utm))

    minx, miny, maxx, maxy = shapely.bounds(geom_lote_wgs)
    bbox_lote = (float(minx), float(miny), float(maxx), float(maxy))

    sinais: list[Sinal] = []

    for reg in regras_com_uso("sinal"):
        if reg.teste == "distancia":
            margem = (reg.limiar if reg.limiar is not None else 0.0) + 100.0
            feicoes_camadas = [
                f
                for camada in reg.camadas_banco
                for f in dados.feicoes(camada, bbox_lote, margem_m=margem)
                if f.geometria_wkt
            ]

            candidatos = []
            for f in feicoes_camadas:
                g = shapely.from_wkt(f.geometria_wkt)
                if g is None or shapely.is_empty(g):
                    continue
                g_utm = _para_utm(shapely.make_valid(g))
                d = float(shapely.distance(lote_utm, g_utm))
                candidatos.append((d, f))

            if candidatos:
                candidatos.sort(key=lambda item: item[0])
                d_min, f_min = candidatos[0]
            else:
                d_min, f_min = float("inf"), None

            limiar = reg.limiar if reg.limiar is not None else 1.0
            presente = d_min <= limiar

            if d_min <= 1.0:
                base_medida = "cruza o lote"
            elif d_min <= 100.0:
                base_medida = f"a {round(d_min)} m"
            else:
                base_medida = "nenhuma a menos de 100 m"

            if f_min is not None and d_min <= 100.0 and reg.atributo_medida:
                valores = [
                    str(f_min.atributos[a]).strip()
                    for a in reg.atributo_medida
                    if f_min.atributos.get(a) is not None
                ]
                medida = f"{base_medida}: {', '.join(valores)}" if valores else base_medida
            else:
                medida = base_medida

            camadas_fonte = [f_min.camada] if (presente and f_min is not None) else list(reg.camadas_banco)
            sinais.append(
                Sinal(
                    rotulo=reg.rotulo,
                    presente=presente,
                    medida=medida,
                    fonte=_montar_fonte(camadas_fonte),
                )
            )

        elif reg.teste == "sobreposicao":
            feicoes_por_camada = {
                camada: dados.feicoes(camada, bbox_lote, margem_m=0.0)
                for camada in reg.camadas_banco
            }

            camadas_que_interceptaram = []
            geoms_todas_utm = []

            for camada in reg.camadas_banco:
                feats = [f for f in feicoes_por_camada.get(camada, []) if f.geometria_wkt]
                geoms_c = [shapely.from_wkt(f.geometria_wkt) for f in feats]
                geoms_c = [g for g in geoms_c if g is not None and not shapely.is_empty(g)]
                if not geoms_c:
                    continue
                geoms_c_utm = [_para_utm(shapely.make_valid(g)) for g in geoms_c]
                geoms_todas_utm.extend(geoms_c_utm)

                uniao_c = shapely.union_all(geoms_c_utm)
                if not shapely.is_empty(uniao_c) and shapely.intersects(lote_utm, uniao_c):
                    inter_c = shapely.intersection(lote_utm, uniao_c)
                    if float(shapely.area(inter_c)) > 0:
                        camadas_que_interceptaram.append(camada)

            if geoms_todas_utm and area_lote_utm > 0:
                uniao_todas = shapely.union_all(geoms_todas_utm)
                inter = shapely.intersection(lote_utm, uniao_todas)
                pct = float(shapely.area(inter)) / area_lote_utm * 100.0
                pct = min(100.0, max(0.0, pct))
            else:
                pct = 0.0

            limiar = reg.limiar if reg.limiar is not None else 10.0
            if limiar == 0.0:
                presente = pct > 0.0001
            else:
                presente = pct >= limiar

            if pct <= 0.0001:
                medida = "não encontrado"
            elif round(pct) == 0:
                medida = f"{pct:.1f}% do lote"
            else:
                medida = f"{round(pct)}% do lote"

            camadas_fonte = (
                camadas_que_interceptaram
                if (presente and camadas_que_interceptaram)
                else list(reg.camadas_banco)
            )
            sinais.append(
                Sinal(
                    rotulo=reg.rotulo,
                    presente=presente,
                    medida=medida,
                    fonte=_montar_fonte(camadas_fonte),
                )
            )

        elif reg.teste == "chave_lote + sobreposicao":
            camada_chave = reg.camadas_banco[0]
            camadas_sobreposicao = reg.camadas_banco[1:] if len(reg.camadas_banco) > 1 else reg.camadas_banco

            feicoes_chave_todas = dados.feicoes(camada_chave, bbox_lote, margem_m=0.0)
            feicoes_chave_casadas = []
            for f in feicoes_chave_todas:
                at = f.atributos
                if (
                    _chave_bate(at.get("cd_setor_fiscal"), lote.setor)
                    and _chave_bate(at.get("cd_quadra_fiscal"), lote.quadra)
                    and _chave_bate(at.get("cd_lote"), lote.lote)
                ):
                    feicoes_chave_casadas.append(f)

            chave_bateu = len(feicoes_chave_casadas) > 0

            camadas_sob_interceptaram = []
            geoms_sob_utm = []

            for camada in camadas_sobreposicao:
                feats = [f for f in dados.feicoes(camada, bbox_lote, margem_m=0.0) if f.geometria_wkt]
                geoms_c = [shapely.from_wkt(f.geometria_wkt) for f in feats]
                geoms_c = [g for g in geoms_c if g is not None and not shapely.is_empty(g)]
                if not geoms_c:
                    continue
                geoms_c_utm = [_para_utm(shapely.make_valid(g)) for g in geoms_c]
                geoms_sob_utm.extend(geoms_c_utm)

                uniao_c = shapely.union_all(geoms_c_utm)
                if not shapely.is_empty(uniao_c) and shapely.intersects(lote_utm, uniao_c):
                    inter_c = shapely.intersection(lote_utm, uniao_c)
                    if float(shapely.area(inter_c)) > 0:
                        camadas_sob_interceptaram.append(camada)

            if geoms_sob_utm and area_lote_utm > 0:
                uniao_sob = shapely.union_all(geoms_sob_utm)
                inter = shapely.intersection(lote_utm, uniao_sob)
                pct = float(shapely.area(inter)) / area_lote_utm * 100.0
                pct = min(100.0, max(0.0, pct))
            else:
                pct = 0.0

            sobreposicao_bateu = pct > 0.0001
            presente = chave_bateu or sobreposicao_bateu

            if not presente:
                medida = "não encontrado"
            elif chave_bateu and not sobreposicao_bateu:
                valores = []
                for a in reg.atributo_medida:
                    for f in feicoes_chave_casadas:
                        v = str(f.atributos.get(a) or "").strip()
                        if v and v not in valores:
                            valores.append(v)
                attr_str = f": {', '.join(valores)}" if valores else ""
                medida = f"pela chave do lote (SQL){attr_str}"
            elif sobreposicao_bateu and not chave_bateu:
                pct_str = f"{pct:.1f}% do lote" if round(pct) == 0 else f"{round(pct)}% do lote"
                medida = f"por sobreposição: {pct_str}"
            else:
                valores = []
                for a in reg.atributo_medida:
                    for f in feicoes_chave_casadas:
                        v = str(f.atributos.get(a) or "").strip()
                        if v and v not in valores:
                            valores.append(v)
                attr_str = f": {', '.join(valores)}" if valores else ""
                pct_str = f"{pct:.1f}% do lote" if round(pct) == 0 else f"{round(pct)}% do lote"
                medida = f"pela chave do lote (SQL){attr_str}; por sobreposição: {pct_str}"

            camadas_que_bateram = []
            if chave_bateu:
                camadas_que_bateram.append(camada_chave)
            if sobreposicao_bateu:
                camadas_que_bateram.extend(camadas_sob_interceptaram)

            camadas_fonte = (
                list(dict.fromkeys(camadas_que_bateram))
                if (presente and camadas_que_bateram)
                else list(reg.camadas_banco)
            )
            sinais.append(
                Sinal(
                    rotulo=reg.rotulo,
                    presente=presente,
                    medida=medida,
                    fonte=_montar_fonte(camadas_fonte),
                )
            )

    sinais_presentes = [s for s in sinais if s.presente]
    sinais_ausentes = [s for s in sinais if not s.presente]
    return sinais_presentes + sinais_ausentes


def estacao_mais_proxima(lote: LoteCadastro) -> tuple[str, float] | None:
    """Calcula a estação mais próxima dentro de 5 km em linha reta a partir do lote."""
    geom_lote_wgs = shapely.from_wkt(lote.geometria_wkt)
    if not shapely.is_valid(geom_lote_wgs):
        geom_lote_wgs = shapely.make_valid(geom_lote_wgs)

    lote_utm = _para_utm(geom_lote_wgs)
    minx, miny, maxx, maxy = shapely.bounds(geom_lote_wgs)
    bbox_lote = (float(minx), float(miny), float(maxx), float(maxy))

    candidatos = []

    for camada in _CAMADAS_ESTACOES:
        feicoes_camada = dados.feicoes(camada, bbox_lote, margem_m=5000.0)
        for f in feicoes_camada:
            if not f.geometria_wkt:
                continue
            g = shapely.from_wkt(f.geometria_wkt)
            if g is None or shapely.is_empty(g):
                continue
            g_utm = _para_utm(shapely.make_valid(g))
            dist = float(shapely.distance(lote_utm, g_utm))
            if dist <= 5000.0:
                candidatos.append((dist, f, camada))

    if not candidatos:
        return None

    candidatos.sort(key=lambda item: item[0])
    menor_dist, f_est, camada_est = candidatos[0]

    estacao = str(
        f_est.atributos.get("nm_estacao_metro_trem")
        or f_est.atributos.get("nome")
        or ""
    ).strip()
    linha = str(
        f_est.atributos.get("nm_linha_metro_trem")
        or f_est.atributos.get("linha")
        or ""
    ).strip()
    empresa = str(
        f_est.atributos.get("nm_empresa_metro_trem")
        or f_est.atributos.get("empresa")
        or ""
    ).strip()

    if linha and empresa:
        detalhes = f" ({linha}, {empresa})"
    elif linha:
        detalhes = f" ({linha})"
    elif empresa:
        detalhes = f" ({empresa})"
    else:
        detalhes = ""

    nome = f"{estacao}{detalhes}"
    if camada_est.endswith("_projetada"):
        nome = f"{nome} (projetada)"

    return nome, menor_dist
