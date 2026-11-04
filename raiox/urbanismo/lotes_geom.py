# Cópia congelada de prospeccao-marechal-tito/core/lotes_geom.py em 2026-10-28.
"""
Geometria dos lotes sob demanda.

Montar 140 mil polígonos GeoJSON na memória (e varrê-los a cada interação) era o maior custo
do app, mas só ~500 lotes aparecem no mapa. `LotesLazy` guarda o WKT no DataFrame e só
converte os lotes pedidos. `selecionar` aceita também o FeatureCollection completo
(região Marechal Tito, que ainda usa o GeoJSON).
"""

import shapely
from shapely.geometry import mapping

_PROPS = (
    "cd_identificador", "cd_setor_fiscal", "cd_quadra_fiscal", "cd_lote", "nm_logradouro_completo",
    "cd_numero_porta", "qt_area_terreno", "qt_area_construida", "dc_tipo_uso_imovel",
)


def _lid(p) -> str:
    return f"{p.get('cd_setor_fiscal', '')}{p.get('cd_quadra_fiscal', '')}{p.get('cd_lote', '')}"


class LotesLazy:
    def __init__(self, df):
        cols = [c for c in _PROPS if c in df.columns]
        self._wkt = dict(
            zip(
                df["cd_setor_fiscal"].astype(str) + df["cd_quadra_fiscal"].astype(str) + df["cd_lote"].astype(str),
                df["geometry_wkt"],
            )
        )
        self._props = df[cols].astype(object).where(df[cols].notna(), None)
        self._props.index = list(self._wkt)  # mesma ordem do dict acima (chaves únicas)

    def selecionar(self, ids) -> list[dict]:
        ids = [i for i in ids if i in self._wkt]
        if not ids:
            return []
        geoms = shapely.from_wkt([self._wkt[i] for i in ids])
        props = self._props.loc[ids].to_dict("records")
        return [
            {"type": "Feature", "geometry": mapping(g), "properties": p}
            for g, p in zip(geoms, props)
        ]


def selecionar(fonte, ids) -> list[dict]:
    """Feições dos lotes `ids` (chave setor+quadra+lote), de um LotesLazy ou de um FeatureCollection."""
    if isinstance(fonte, LotesLazy):
        return fonte.selecionar(ids)
    ids = set(ids)
    return [f for f in fonte["features"] if _lid(f["properties"]) in ids]
