import datetime
from pathlib import Path
import re
import xml.sax.saxutils
import zipfile

import numpy as np
import pyproj
import shapely
import shapely.errors
import shapely.geometry

from raiox import camadas, dados, retiradas
from raiox.oportunidades import endereco, sql_formatado
from raiox.saidas.resumo import gerar as gerar_resumo
from raiox.tipos import Candidato, Entorno, Premissas, RaioX

CAMADAS_ESTACOES: tuple[str, ...] = camadas.regra("estacoes").camadas_banco


_TRANSFORMER_TO_UTM = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:31983", always_xy=True)
_TRANSFORMER_TO_WGS = pyproj.Transformer.from_crs("EPSG:31983", "EPSG:4326", always_xy=True)


def _formatar_br(valor: float, casas_decimais: int = 2) -> str:
    """Formata número com separador de milhar '.' e decimal ','."""
    texto = f"{valor:,.{casas_decimais}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _transformar(
    geom: shapely.geometry.base.BaseGeometry, tf: pyproj.Transformer
) -> shapely.geometry.base.BaseGeometry:
    return shapely.transform(geom, lambda c: np.column_stack(tf.transform(c[:, 0], c[:, 1])))


def _para_wgs84(geom: shapely.geometry.base.BaseGeometry) -> shapely.geometry.base.BaseGeometry:
    """Garante que a geometria esteja em WGS84 (EPSG:4326)."""
    bounds = geom.bounds
    if abs(bounds[0]) > 180 or abs(bounds[1]) > 90:
        return _transformar(geom, _TRANSFORMER_TO_WGS)
    return geom


def _gerar_coords_anel(coords: list[tuple[float, ...]] | tuple[tuple[float, ...], ...]) -> str:
    return " ".join(f"{c[0]:.6f},{c[1]:.6f},0" for c in coords)


def _gerar_kml_polygon(poly: shapely.geometry.Polygon) -> str:
    ext_coords = _gerar_coords_anel(list(poly.exterior.coords))
    partes = [
        "<Polygon>",
        "  <outerBoundaryIs>",
        "    <LinearRing>",
        f"      <coordinates>{ext_coords}</coordinates>",
        "    </LinearRing>",
        "  </outerBoundaryIs>",
    ]
    for interior in poly.interiors:
        int_coords = _gerar_coords_anel(list(interior.coords))
        partes.extend([
            "  <innerBoundaryIs>",
            "    <LinearRing>",
            f"      <coordinates>{int_coords}</coordinates>",
            "    </LinearRing>",
            "  </innerBoundaryIs>",
        ])
    partes.append("</Polygon>")
    return "\n".join(partes)


def _gerar_kml_geometria(geom: shapely.geometry.base.BaseGeometry) -> str:
    """Converte geometria Shapely em tags XML de Polygon ou MultiGeometry KML 2.2."""
    if isinstance(geom, shapely.geometry.Polygon):
        return _gerar_kml_polygon(geom)
    elif isinstance(geom, shapely.geometry.MultiPolygon):
        partes = ["<MultiGeometry>"]
        for poly in geom.geoms:
            partes.append(_gerar_kml_polygon(poly))
        partes.append("</MultiGeometry>")
        return "\n".join(partes)
    elif isinstance(geom, shapely.geometry.GeometryCollection):
        partes = ["<MultiGeometry>"]
        for g in geom.geoms:
            if isinstance(g, (shapely.geometry.Polygon, shapely.geometry.MultiPolygon)):
                partes.append(_gerar_kml_geometria(g))
        partes.append("</MultiGeometry>")
        return "\n".join(partes)
    return ""


def _buscar_coordenadas_estacao(
    estacao_info: tuple[str, float],
    geom_bruta_wgs: shapely.geometry.base.BaseGeometry,
) -> tuple[float, float] | None:
    """Busca as coordenadas (lon, lat) da estação mais próxima nas camadas de dados."""
    nome_procurado, dist_m = estacao_info
    nome_norm = nome_procurado.strip().lower()
    margem = dist_m + 500.0

    for camada in CAMADAS_ESTACOES:
        feicoes_estacoes = dados.feicoes(camada, geom_bruta_wgs.bounds, margem_m=margem)
        for f in feicoes_estacoes:
            if not f.geometria_wkt:
                continue
            atrib_nome = str(f.atributos.get("nm_estacao_metro_trem") or f.atributos.get("nome") or "").strip().lower()
            if atrib_nome and (atrib_nome in nome_norm or nome_norm in atrib_nome):
                try:
                    pt = shapely.from_wkt(f.geometria_wkt)
                except (shapely.errors.GEOSException, ValueError):
                    continue
                pt_wgs = _para_wgs84(pt)
                return (float(pt_wgs.x), float(pt_wgs.y))

    return None


def _salvar_kmz(pasta: Path, nome_base: str, conteudo_kml: str) -> Path:
    """Grava o arquivo KMZ, tratando colisões de nome e PermissionError com numeração incremental."""
    pasta.mkdir(parents=True, exist_ok=True)
    idx = 1
    while True:
        nome_arquivo = f"{nome_base}.kmz" if idx == 1 else f"{nome_base}_{idx}.kmz"
        caminho = pasta / nome_arquivo
        if caminho.exists():
            idx += 1
            continue
        try:
            with zipfile.ZipFile(caminho, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("doc.kml", conteudo_kml.encode("utf-8"))
            return caminho
        except PermissionError:
            idx += 1
            if idx > 1000:
                raise


def _gerar_geom_area_busca(centro_wkt: str, raio_m: float | None) -> shapely.geometry.base.BaseGeometry:
    """Gera a geometria da área de busca em WGS84, aplicando buffer métrico se raio_m > 0."""
    geom = shapely.from_wkt(centro_wkt)
    geom_wgs = _para_wgs84(geom)
    if raio_m is not None and raio_m > 0:
        centro_utm = _transformar(geom_wgs.centroid, _TRANSFORMER_TO_UTM)
        buffer_utm = shapely.buffer(centro_utm, raio_m)
        return _para_wgs84(buffer_utm)
    return geom_wgs


def gerar_entorno(entorno: Entorno, premissas: Premissas, pasta: Path, nome_base: str) -> Path:
    """Gera arquivo KMZ com a área de busca e os candidatos classificados em 4 pastas."""
    pasta.mkdir(parents=True, exist_ok=True)

    # A área calculada vem no Entorno; sem ela (Entorno montado à mão), centro + raio.
    geom_area_busca = (
        shapely.from_wkt(entorno.area_wkt)
        if entorno.area_wkt is not None
        else _gerar_geom_area_busca(entorno.centro_wkt, entorno.raio_m)
    )
    kml_area_busca = _gerar_kml_geometria(geom_area_busca)

    placemark_area_busca = f"""    <Placemark>
      <name>Área de busca</name>
      <styleUrl>#estilo_area_busca</styleUrl>
      {kml_area_busca}
    </Placemark>"""

    candidatos_meta: list[Candidato] = []
    candidatos_duplas: list[Candidato] = []
    candidatos_trincas: list[Candidato] = []
    candidatos_escondidos: list[Candidato] = []

    for c in entorno.candidatos:
        if c.escondido_por is not None:
            candidatos_escondidos.append(c)
        elif c.tipo == "dupla":
            candidatos_duplas.append(c)
        elif c.tipo == "trinca":
            candidatos_trincas.append(c)
        else:
            candidatos_meta.append(c)

    # Lotes dos candidatos: os da área já estão no Entorno; os que faltarem, numa leitura só
    # (antes era uma leitura do parquet por lote: 118 s na faixa da Marechal Tito).
    lotes_por_id = {a.cadastro.cd_identificador: a.cadastro for a in entorno.lotes}
    faltando = sorted({cid for c in entorno.candidatos for cid in c.ids if cid not in lotes_por_id})
    lotes_por_id.update(dados.lotes_por_ids(faltando))

    def _gerar_placemark_candidato(candidato: Candidato, style_url: str) -> str:
        lotes_comp = [lotes_por_id[cid] for cid in candidato.ids if cid in lotes_por_id]

        if not lotes_comp:
            # Mesmo critério do entorno.geojson: candidato sem lote na base não vira Placemark
            return ""
        geom_unida = shapely.union_all(
            [shapely.make_valid(shapely.from_wkt(l.geometria_wkt)) for l in lotes_comp]
        )
        kml_geom = _gerar_kml_geometria(_para_wgs84(geom_unida))

        partes_desc: list[str] = [
            f"<b>Tipo:</b> {xml.sax.saxutils.escape(candidato.tipo)}<br/>",
            f"<b>SQL:</b> {xml.sax.saxutils.escape(' + '.join(sql_formatado(l) for l in lotes_comp))}<br/>",
            f"<b>Endereço:</b> {xml.sax.saxutils.escape(' + '.join(dict.fromkeys(endereco(l) for l in lotes_comp)))}<br/>",
            f"<b>Área:</b> {_formatar_br(candidato.area_m2)} m²<br/>",
            f"<b>Zonas:</b> {xml.sax.saxutils.escape(', '.join(candidato.zonas)) if candidato.zonas else '—'}<br/>",
        ]
        partes_desc.append(f"<b>VGV potencial:</b> R$ {_formatar_br(candidato.vgv)}<br/>")

        if candidato.sinais:
            partes_desc.append(f"<b>Sinais:</b> {xml.sax.saxutils.escape(', '.join(candidato.sinais))}<br/>")

        if candidato.escondido_por:
            partes_desc.append(f"<b>Motivo do escondido:</b> {xml.sax.saxutils.escape(candidato.escondido_por)}<br/>")

        desc_html = "".join(partes_desc)

        return f"""      <Placemark>
        <name>{xml.sax.saxutils.escape(' + '.join(sql_formatado(l) for l in lotes_comp))}</name>
        <styleUrl>{style_url}</styleUrl>
        <description><![CDATA[{desc_html}]]></description>
        {kml_geom}
      </Placemark>"""

    def _gerar_folder(nome: str, candidatos: list[Candidato], style_url: str) -> str:
        pls = [pl for c in candidatos if (pl := _gerar_placemark_candidato(c, style_url))]
        pls_str = ("\n" + "\n".join(pls)) if pls else ""
        return f"""    <Folder>
      <name>{xml.sax.saxutils.escape(nome)}</name>{pls_str}
    </Folder>"""

    folder_meta = _gerar_folder("Lotes que batem a meta", candidatos_meta, "#estilo_meta")
    folder_duplas = _gerar_folder("Duplas", candidatos_duplas, "#estilo_duplas")
    folder_trincas = _gerar_folder("Trincas", candidatos_trincas, "#estilo_trincas")
    folder_escondidos = _gerar_folder("Escondidos", candidatos_escondidos, "#estilo_escondidos")

    titulo_doc = f"Entorno - {nome_base}"

    kml_conteudo = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{xml.sax.saxutils.escape(titulo_doc)}</name>
    <Style id="estilo_area_busca">
      <LineStyle>
        <color>ff2257ff</color>
        <width>2</width>
      </LineStyle>
      <PolyStyle>
        <fill>0</fill>
        <outline>1</outline>
      </PolyStyle>
    </Style>
    <Style id="estilo_meta">
      <LineStyle>
        <color>ff4a2000</color>
        <width>2</width>
      </LineStyle>
      <PolyStyle>
        <color>7ffd6e0d</color>
        <fill>1</fill>
        <outline>1</outline>
      </PolyStyle>
    </Style>
    <Style id="estilo_duplas">
      <LineStyle>
        <color>ff155724</color>
        <width>2</width>
      </LineStyle>
      <PolyStyle>
        <color>7f45a728</color>
        <fill>1</fill>
        <outline>1</outline>
      </PolyStyle>
    </Style>
    <Style id="estilo_trincas">
      <LineStyle>
        <color>ff046485</color>
        <width>2</width>
      </LineStyle>
      <PolyStyle>
        <color>7f07c1ff</color>
        <fill>1</fill>
        <outline>1</outline>
      </PolyStyle>
    </Style>
    <Style id="estilo_escondidos">
      <LineStyle>
        <color>ff495057</color>
        <width>2</width>
      </LineStyle>
      <PolyStyle>
        <color>7fbdb5ad</color>
        <fill>1</fill>
        <outline>1</outline>
      </PolyStyle>
    </Style>
{placemark_area_busca}
{folder_meta}
{folder_duplas}
{folder_trincas}
{folder_escondidos}
  </Document>
</kml>
"""

    return _salvar_kmz(pasta, nome_base, kml_conteudo)


def gerar_terreno(rx: RaioX, premissas: Premissas, pasta: Path) -> Path:
    """Gera arquivo KMZ (KML 2.2 zipado) com o terreno bruto, líquido, retiradas e estação mais próxima."""
    pasta.mkdir(parents=True, exist_ok=True)

    data_iso = datetime.date.today().isoformat()
    sql_sanitizado = re.sub(r"[^\w\-]", "", rx.lote.sql) or "lote"
    nome_base = f"RaioX_{sql_sanitizado}_{data_iso}"

    if rx.lote.logradouro and rx.lote.numero_porta:
        endereco = f"{rx.lote.logradouro}, {rx.lote.numero_porta}"
    elif rx.lote.logradouro:
        endereco = rx.lote.logradouro
    else:
        endereco = rx.lote.sql

    titulo_doc = f"Raio-X {endereco}"
    geom_bruta = shapely.from_wkt(rx.lote.geometria_wkt)
    geom_bruta_wgs = _para_wgs84(geom_bruta)

    area = rx.area
    if not area.retiradas and premissas.retiradas:
        area = retiradas.calcular(rx.lote, premissas.retiradas)

    geom_liquida_wgs: shapely.geometry.base.BaseGeometry | None = None
    if area.geometria_liquida_wkt:
        geom_liq = shapely.from_wkt(area.geometria_liquida_wkt)
        geom_liquida_wgs = _para_wgs84(geom_liq)

    texto_resumo = gerar_resumo(rx, premissas)
    kml_bruta = _gerar_kml_geometria(geom_bruta_wgs)

    placemarks: list[str] = []

    # 1. Placemark Lote Bruto
    placemark_bruto = f"""      <Placemark>
        <name>Lote bruto</name>
        <styleUrl>#estilo_lote_bruto</styleUrl>
        <description><![CDATA[<h3>Raio-X Urbanístico</h3><pre style="white-space: pre-wrap;">{texto_resumo}</pre>]]></description>
        {kml_bruta}
      </Placemark>"""
    placemarks.append(placemark_bruto)

    # 2. Placemark Lote Líquido (se houver retiradas aplicadas)
    tem_retiradas = any(r.area_m2 > 0 for r in area.retiradas) or (
        area.geometria_liquida_wkt != rx.lote.geometria_wkt
    )
    if tem_retiradas and geom_liquida_wgs is not None and not geom_liquida_wgs.is_empty:
        kml_liquida = _gerar_kml_geometria(geom_liquida_wgs)
        placemark_liquido = f"""      <Placemark>
        <name>Lote líquido</name>
        <styleUrl>#estilo_lote_liquido</styleUrl>
        {kml_liquida}
      </Placemark>"""
        placemarks.append(placemark_liquido)

    # 3. Placemarks das Retiradas
    qtd_retiradas_pos = sum(1 for r in area.retiradas if r.area_m2 > 0)
    for ret in area.retiradas:
        if ret.area_m2 <= 0:
            continue
        area_camada = retiradas.calcular(rx.lote, (ret.camada,))
        g_camada_liq = _para_wgs84(shapely.from_wkt(area_camada.geometria_liquida_wkt))
        geom_ret = shapely.difference(geom_bruta_wgs, g_camada_liq)

        # Caso sintético de borda: se area_camada.geometria_liquida_wkt == rx.lote.geometria_wkt
        # (comum em testes unitários sem banco de dados mocked), mas geom_liquida_wgs fornecido
        # diferir de geom_bruta_wgs e houver uma única retirada positiva:
        if (
            area_camada.geometria_liquida_wkt == rx.lote.geometria_wkt
            and geom_liquida_wgs is not None
            and qtd_retiradas_pos == 1
        ):
            diff_direta = shapely.difference(geom_bruta_wgs, geom_liquida_wgs)
            if not diff_direta.is_empty:
                geom_ret = diff_direta

        if geom_ret is not None and not geom_ret.is_empty:
            kml_ret = _gerar_kml_geometria(geom_ret)
            if kml_ret:
                area_fmt = _formatar_br(ret.area_m2, 2)
                nome_ret = f"{ret.rotulo} - {area_fmt} m²"
                placemark_ret = f"""      <Placemark>
        <name>{xml.sax.saxutils.escape(nome_ret)}</name>
        <styleUrl>#estilo_retirada</styleUrl>
        {kml_ret}
      </Placemark>"""
                placemarks.append(placemark_ret)

    # 4. Marcador da Estação mais próxima
    if rx.estacao is not None:
        nome_estacao, dist_m = rx.estacao
        coords_estacao = _buscar_coordenadas_estacao(rx.estacao, geom_bruta_wgs)
        if coords_estacao is not None:
            lon, lat = coords_estacao
            dist_fmt = _formatar_br(dist_m, 1) if dist_m % 1 != 0 else _formatar_br(dist_m, 0)
            placemark_estacao = f"""      <Placemark>
        <name>{xml.sax.saxutils.escape(nome_estacao)}</name>
        <description><![CDATA[Distância em linha reta: {dist_fmt} m]]></description>
        <Point>
          <coordinates>{lon:.6f},{lat:.6f},0</coordinates>
        </Point>
      </Placemark>"""
            placemarks.append(placemark_estacao)

    placemarks_str = "\n".join(placemarks)

    kml_conteudo = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{xml.sax.saxutils.escape(titulo_doc)}</name>
    <Style id="estilo_lote_bruto">
      <LineStyle>
        <color>ffffffff</color>
        <width>2</width>
      </LineStyle>
      <PolyStyle>
        <fill>0</fill>
        <outline>1</outline>
      </PolyStyle>
    </Style>
    <Style id="estilo_lote_liquido">
      <LineStyle>
        <color>ff00ffff</color>
        <width>3</width>
      </LineStyle>
      <PolyStyle>
        <color>3300ffff</color>
        <fill>1</fill>
        <outline>1</outline>
      </PolyStyle>
    </Style>
    <Style id="estilo_retirada">
      <LineStyle>
        <color>ff0000ff</color>
        <width>2</width>
      </LineStyle>
      <PolyStyle>
        <color>590000ff</color>
        <fill>1</fill>
        <outline>1</outline>
      </PolyStyle>
    </Style>
    <Folder>
      <name>{xml.sax.saxutils.escape(titulo_doc)}</name>
{placemarks_str}
    </Folder>
  </Document>
</kml>
"""

    return _salvar_kmz(pasta, nome_base, kml_conteudo)
