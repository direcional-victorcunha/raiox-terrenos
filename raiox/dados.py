"""Módulo de acesso a dados cadastrais e geográficos do Raio-X de Terrenos SP."""
from __future__ import annotations

import datetime
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import shapely
import shapely.geometry

from raiox import camadas_wfs, caminhos, lotes_wfs
from raiox.tipos import Feicao, LoteCadastro


class _CamadaCache:
    """Estrutura interna para cache em memória da tabela e índices de bbox de uma camada."""

    __slots__ = ("tabela", "tem_bbox", "minx", "miny", "maxx", "maxy", "chave")

    def __init__(
        self,
        tabela: pa.Table,
        tem_bbox: bool,
        minx: np.ndarray | None,
        miny: np.ndarray | None,
        maxx: np.ndarray | None,
        maxy: np.ndarray | None,
    ) -> None:
        self.tabela = tabela
        self.tem_bbox = tem_bbox
        self.minx = minx
        self.miny = miny
        self.maxx = maxx
        self.maxy = maxy
        self.chave: Any = None


_dataset_lotes: ds.Dataset | None = None
_dataset_lotes_path: Path | None = None
_coluna_logradouro_norm: pa.ChunkedArray | None = None
_lotes_por_logradouro_cache: dict[str, list[LoteCadastro]] = {}
_logradouros_unicos_cache: list[str] | None = None
_manifesto_cache: dict[str, Any] | None = None
_datas_cache: dict[str, Any] | None = None
_camadas_datasets: dict[str, ds.Dataset] = {}
_camadas_cache: dict[str, _CamadaCache] = {}


def pasta_dados() -> Path:
    """Retorna o caminho da pasta de dados configurada e valida a existência de lotes.parquet."""
    pasta = caminhos.pasta_dados_padrao()

    arquivo_lotes = pasta / "lotes.parquet"
    # Modo instalado: sem lotes.parquet, os lotes vêm de lotes/q_*.parquet (baixados do GeoSampa).
    if not arquivo_lotes.exists() and (
        (pasta / "lotes").is_dir() or pasta == caminhos.pasta_dados_usuario()
    ):
        return pasta
    if not arquivo_lotes.exists():
        raise FileNotFoundError(
            f"Arquivo de lotes não encontrado na pasta de dados: {arquivo_lotes}"
        )
    return pasta


def limpar_caches() -> None:
    """Limpa todos os caches em memória de datasets, manifesto, datas, camadas e logradouros."""
    global _dataset_lotes, _dataset_lotes_path, _coluna_logradouro_norm, _lotes_por_logradouro_cache
    global _logradouros_unicos_cache, _manifesto_cache, _datas_cache, _camadas_datasets, _camadas_cache
    _dataset_lotes = None
    _dataset_lotes_path = None
    _coluna_logradouro_norm = None
    _lotes_por_logradouro_cache.clear()
    _logradouros_unicos_cache = None
    _manifesto_cache = None
    _datas_cache = None
    _camadas_datasets.clear()
    _camadas_cache.clear()


def modo_instalado() -> bool:
    """Verdadeiro quando não há ``lotes.parquet`` da cidade: os lotes vêm dos quadrados baixados."""
    return not (pasta_dados() / "lotes.parquet").exists()


def _obter_dataset_lotes() -> ds.Dataset:
    """Obtém o dataset de lotes mantido em cache de módulo sem carregar os dados na memória."""
    global _dataset_lotes, _dataset_lotes_path, _coluna_logradouro_norm, _logradouros_unicos_cache
    pasta = pasta_dados()
    parquet = pasta / "lotes.parquet"
    if parquet.exists():
        chave: Any = parquet
        arquivos: list[str] | None = None
    else:
        arquivos = sorted(str(p) for p in lotes_wfs.pasta_lotes(pasta).glob("q_*.parquet"))
        chave = tuple(arquivos)
    if _dataset_lotes is None or _dataset_lotes_path != chave:
        if arquivos is None:
            _dataset_lotes = ds.dataset(parquet, format="parquet")
        else:
            _dataset_lotes = ds.dataset(arquivos, schema=lotes_wfs.ESQUEMA, format="parquet")
        _dataset_lotes_path = chave
        # novos quadrados: os índices de rua guardados em memória deixam de valer
        _coluna_logradouro_norm = None
        _logradouros_unicos_cache = None
        _lotes_por_logradouro_cache.clear()
    return _dataset_lotes


# Aviso de andamento do download de quadrados (a tela registra aqui): f(rotulo, n, total, qtd).
_aviso_download: Any = None


def definir_aviso_download(funcao: Any) -> None:
    global _aviso_download
    _aviso_download = funcao


def garantir_area(bbox: tuple[float, float, float, float], folga_m: float = 300.0) -> int:
    """Modo instalado: baixa os quadrados que faltam para cobrir o bbox (graus). Devolve quantos baixou.

    A folga cobre lotes grandes cujo centro cai no quadrado vizinho mas que tocam o bbox.
    """
    if not modo_instalado():
        return 0
    folga = folga_m / 111_000.0
    minx, miny, maxx, maxy = bbox
    pasta = pasta_dados()
    alvo = lotes_wfs.quadrados_do_bbox(minx - folga, miny - folga, maxx + folga, maxy + folga)
    faltam = [q for q in alvo if not lotes_wfs.caminho_quadrado(pasta, *q).exists()]
    if not faltam:
        return 0
    from concurrent.futures import ThreadPoolExecutor

    def um(item: tuple[int, tuple[int, int]]) -> None:
        n, (ix, iy) = item
        cb = (lambda qtd, n=n: _aviso_download("lotes", n, len(faltam), qtd)) if _aviso_download else None
        lotes_wfs.baixar_quadrado(pasta, ix, iy, cb)

    with ThreadPoolExecutor(max_workers=2) as pool:  # 2 quadrados de cada vez; cada um com a sua pausa de 1 s
        list(pool.map(um, enumerate(faltam)))
    return len(faltam)


def _obter_coluna_logradouro_norm() -> pa.ChunkedArray:
    """Obtém e mantém em cache em memória a coluna logradouro_norm do dataset de lotes."""
    global _coluna_logradouro_norm
    if _coluna_logradouro_norm is None:
        dataset = _obter_dataset_lotes()
        _coluna_logradouro_norm = dataset.to_table(columns=["logradouro_norm"])["logradouro_norm"]
    return _coluna_logradouro_norm


def _linha_para_lote(row: dict[str, Any]) -> LoteCadastro:
    """Converte um dicionário de linha do dataset de lotes em uma instância de LoteCadastro."""
    cd_id = row.get("cd_identificador")
    cd_id_str = str(cd_id) if cd_id is not None else ""

    sql = str(row.get("sql") or "")
    setor = str(row.get("setor") or "")
    quadra = str(row.get("quadra") or "")
    lote = str(row.get("lote") or "")

    digito = row.get("digito")
    digito_str = (
        str(digito).strip()
        if digito is not None and str(digito).strip() not in ("", "None")
        else None
    )

    cd_cond = row.get("cd_condominio")
    cd_cond_str = str(cd_cond) if cd_cond is not None and str(cd_cond).strip() != "" else None

    logradouro = str(row.get("nm_logradouro_completo") or "")

    num_porta = row.get("cd_numero_porta")
    num_porta_str = (
        str(num_porta) if num_porta is not None and str(num_porta).strip() != "" else None
    )

    area_terr = row.get("qt_area_terreno")
    area_terr_flt = float(area_terr) if area_terr is not None else 0.0

    area_const = row.get("qt_area_construida")
    area_const_flt = float(area_const) if area_const is not None else None

    uso = row.get("dc_tipo_uso_imovel")
    uso_str = str(uso) if uso is not None and str(uso).strip() != "" else None

    situacao = row.get("tx_situ_lote")
    situacao_str = str(situacao) if situacao is not None and str(situacao).strip() != "" else None

    geom_wkt = str(row.get("geometry_wkt") or "")

    return LoteCadastro(
        cd_identificador=cd_id_str,
        sql=sql,
        setor=setor,
        quadra=quadra,
        lote=lote,
        digito=digito_str,
        cd_condominio=cd_cond_str,
        logradouro=logradouro,
        numero_porta=num_porta_str,
        area_terreno_m2=area_terr_flt,
        area_construida_m2=area_const_flt,
        uso=uso_str,
        situacao=situacao_str,
        geometria_wkt=geom_wkt,
    )


def lote_por_sql(setor: str, quadra: str, lote: str) -> list[LoteCadastro]:
    """Busca lotes pelo código SQL estruturado (setor, quadra, lote), ignorando o dígito."""
    s = setor.strip().zfill(3)
    q = quadra.strip().zfill(3)
    l = lote.strip().zfill(4)

    dataset = _obter_dataset_lotes()
    filtro = (ds.field("setor") == s) & (ds.field("quadra") == q) & (ds.field("lote") == l)
    tabela = dataset.to_table(filter=filtro)
    return [_linha_para_lote(row) for row in tabela.to_pylist()]


def lotes_da_quadra(setor: str, quadra: str) -> list[LoteCadastro]:
    """Retorna todos os lotes pertencentes a uma quadra e setor específicos."""
    s = setor.strip().zfill(3)
    q = quadra.strip().zfill(3)

    dataset = _obter_dataset_lotes()
    filtro = (ds.field("setor") == s) & (ds.field("quadra") == q)
    tabela = dataset.to_table(filter=filtro)
    return [_linha_para_lote(row) for row in tabela.to_pylist()]


def lote_por_id(cd_identificador: str) -> LoteCadastro | None:
    """Busca um lote único pelo seu identificador cadastral."""
    dataset = _obter_dataset_lotes()
    tipo_campo = dataset.schema.field("cd_identificador").type
    if pa.types.is_integer(tipo_campo):
        try:
            val_id: object = int(cd_identificador)
        except ValueError:
            return None
    else:
        val_id = cd_identificador

    filtro = ds.field("cd_identificador") == val_id
    tabela = dataset.to_table(filter=filtro)
    if len(tabela) == 0:
        return None
    return _linha_para_lote(tabela.to_pylist()[0])


def lotes_por_ids(ids: list[str]) -> dict[str, LoteCadastro]:
    """Vários lotes pelo identificador numa leitura só do parquet (id ausente fica de fora)."""
    if not ids:
        return {}
    dataset = _obter_dataset_lotes()
    if pa.types.is_integer(dataset.schema.field("cd_identificador").type):
        valores: list[object] = [int(i) for i in ids if i.isdigit()]
    else:
        valores = list(ids)
    if not valores:
        return {}
    tabela = dataset.to_table(filter=ds.field("cd_identificador").isin(valores))
    lotes = [_linha_para_lote(row) for row in tabela.to_pylist()]
    return {l.cd_identificador: l for l in lotes}


def lotes_por_logradouro(logradouro_norm: str) -> list[LoteCadastro]:
    """Busca lotes por igualdade exata na coluna logradouro_norm usando índice em memória."""
    if logradouro_norm in _lotes_por_logradouro_cache:
        return _lotes_por_logradouro_cache[logradouro_norm]

    coluna = _obter_coluna_logradouro_norm()
    dataset = _obter_dataset_lotes()
    posicoes = pc.indices_nonzero(pc.equal(coluna, logradouro_norm))
    if len(posicoes) == 0:
        _lotes_por_logradouro_cache[logradouro_norm] = []
        return []

    tabela = dataset.take(posicoes)
    resultado = [_linha_para_lote(row) for row in tabela.to_pylist()]
    _lotes_por_logradouro_cache[logradouro_norm] = resultado
    return resultado


def logradouros_unicos() -> list[str]:
    """Retorna a lista ordenada de nomes normalizados de logradouro distintos com cache em memória."""
    global _logradouros_unicos_cache
    if _logradouros_unicos_cache is not None:
        return _logradouros_unicos_cache

    coluna = _obter_coluna_logradouro_norm()
    unicos = pc.unique(coluna).to_pylist()
    resultado = sorted([str(x) for x in unicos if x is not None and str(x).strip() != ""])
    _logradouros_unicos_cache = resultado
    return resultado


def lotes_no_bbox(
    bbox: tuple[float, float, float, float], limite: int | None = None
) -> list[LoteCadastro]:
    """Retorna lotes cujos bounding boxes interceptam o bbox fornecido (minx, miny, maxx, maxy)."""
    if limite is not None and limite <= 0:
        return []

    minx, miny, maxx, maxy = bbox
    garantir_area(bbox)
    dataset = _obter_dataset_lotes()
    filtro = (
        (ds.field("minx") <= maxx)
        & (ds.field("maxx") >= minx)
        & (ds.field("miny") <= maxy)
        & (ds.field("maxy") >= miny)
    )

    scanner = dataset.scanner(filter=filtro)
    if limite is not None:
        resultado: list[LoteCadastro] = []
        for batch in scanner.to_batches():
            t = pa.Table.from_batches([batch])
            for row in t.to_pylist():
                resultado.append(_linha_para_lote(row))
                if len(resultado) >= limite:
                    return resultado
        return resultado
    else:
        tabela = scanner.to_table()
        return [_linha_para_lote(row) for row in tabela.to_pylist()]


class CamadaAusente(ValueError):
    """A camada pedida não está no pacote de dados baixado (data/camadas/<id>.parquet)."""


def garantir_camada(camada: str, bbox: tuple[float, float, float, float]) -> int:
    """Modo instalado: baixa os quadrados da camada que faltam para cobrir o bbox (graus)."""
    if not modo_instalado():
        return 0
    try:
        return camadas_wfs.garantir_quadrados(
            pasta_dados(),
            camada,
            *bbox,
            progresso=(lambda n, t, q: _aviso_download(camada, n, t, q)) if _aviso_download else None,
        )
    except camadas_wfs.CamadaNaoExiste as exc:
        raise CamadaAusente(str(exc)) from exc


def pre_baixar_camadas(pares: list[tuple[str, float]], bbox: tuple[float, float, float, float]) -> None:
    """Modo instalado: baixa várias camadas ao mesmo tempo (3 por vez) antes de lê-las uma a uma.

    ``pares`` = (camada, margem em metros). Falhas ficam para quem ler a camada (``feicoes``), que as
    trata como camada ausente ou erro de rede.
    """
    if not modo_instalado() or len(pares) < 2:
        return
    from concurrent.futures import ThreadPoolExecutor

    minx, miny, maxx, maxy = bbox

    def um(par: tuple[str, float]) -> None:
        camada, margem_m = par
        d = margem_m / 111_000.0
        try:
            garantir_camada(camada, (minx - d, miny - d, maxx + d, maxy + d))
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(um, pares))


def _tabela_camada_instalada(camada: str) -> pa.Table:
    """Junta os quadrados já baixados da camada, sem a duplicata das feições que cruzam a divisa."""
    arquivos = sorted(camadas_wfs.pasta_camada(pasta_dados(), camada).glob("q_*.parquet"))
    if not arquivos:
        return pa.table({"geometry_wkt": pa.array([], pa.string())})
    tabela = pa.concat_tables([pq.read_table(a) for a in arquivos], promote_options="permissive")
    _, primeiros = np.unique(tabela["geometry_wkt"].to_numpy(zero_copy_only=False), return_index=True)
    if len(primeiros) < len(tabela):
        tabela = tabela.take(np.sort(primeiros))
    return tabela


def _obter_dataset_camada(camada: str) -> ds.Dataset:
    """Abre e mantém em cache o dataset de uma camada específica em data/camadas/<id>.parquet."""
    pasta_camadas = pasta_dados() / "camadas"
    caminho = pasta_camadas / f"{camada}.parquet"
    if not caminho.exists():
        camadas_disp = (
            sorted([p.stem for p in pasta_camadas.glob("*.parquet")])
            if pasta_camadas.exists()
            else []
        )
        raise CamadaAusente(
            f"Camada '{camada}' não encontrada. Camadas disponíveis: {camadas_disp}"
        )

    if camada not in _camadas_datasets:
        _camadas_datasets[camada] = ds.dataset(caminho, format="parquet")
    return _camadas_datasets[camada]


def _obter_cache_camada(
    camada: str, bbox: tuple[float, float, float, float] | None = None
) -> _CamadaCache:
    """Obtém ou inicializa em memória o cache de tabela e bboxes numpy de uma camada geográfica.

    No modo instalado, ``bbox`` (graus) manda baixar o que faltar e o cache vale para os quadrados
    que existem em disco naquele momento.
    """
    instalado = modo_instalado()
    if instalado:
        if bbox is not None:
            garantir_camada(camada, bbox)
        arquivos = tuple(
            (a.name, a.stat().st_mtime_ns)
            for a in sorted(camadas_wfs.pasta_camada(pasta_dados(), camada).glob("q_*.parquet"))
        )
        chave = (camada, arquivos)
        antigo = _camadas_cache.get(camada)
        if antigo is not None and getattr(antigo, "chave", None) == chave:
            return antigo
        tabela = _tabela_camada_instalada(camada)
    else:
        if camada in _camadas_cache:
            return _camadas_cache[camada]
        chave = None
        tabela = _obter_dataset_camada(camada).to_table()

    tem_bbox = all(col in tabela.column_names for col in ("minx", "miny", "maxx", "maxy"))
    if tem_bbox:
        minx = tabela["minx"].to_numpy()
        miny = tabela["miny"].to_numpy()
        maxx = tabela["maxx"].to_numpy()
        maxy = tabela["maxy"].to_numpy()
    else:
        minx = miny = maxx = maxy = None

    cache_obj = _CamadaCache(
        tabela=tabela,
        tem_bbox=tem_bbox,
        minx=minx,
        miny=miny,
        maxx=maxx,
        maxy=maxy,
    )
    cache_obj.chave = chave
    _camadas_cache[camada] = cache_obj
    return cache_obj


def feicoes(
    camada: str, bbox: tuple[float, float, float, float], margem_m: float = 0.0
) -> list[Feicao]:
    """Lê feições da camada geográfica que interceptam o bbox expandido pela margem em metros."""
    minx, miny, maxx, maxy = bbox

    if margem_m > 0:
        lat_ref = max(abs(miny), abs(maxy))
        cos_lat = max(math.cos(math.radians(lat_ref)), 0.1)
        d_lat = margem_m / 110_000.0
        d_lon = margem_m / (110_000.0 * cos_lat)
        minx -= d_lon
        maxx += d_lon
        miny -= d_lat
        maxy += d_lat

    cache_camada = _obter_cache_camada(camada, (minx, miny, maxx, maxy))

    if cache_camada.tem_bbox:
        assert cache_camada.minx is not None
        assert cache_camada.miny is not None
        assert cache_camada.maxx is not None
        assert cache_camada.maxy is not None

        mask = (
            (cache_camada.minx <= maxx)
            & (cache_camada.maxx >= minx)
            & (cache_camada.miny <= maxy)
            & (cache_camada.maxy >= miny)
        )
        idx = np.flatnonzero(mask)
        if len(idx) == 0:
            return []
        tabela = cache_camada.tabela.take(idx)
    else:
        tabela = cache_camada.tabela

    colunas_excluidas = {"geometry_wkt", "minx", "miny", "maxx", "maxy"}
    resultado: list[Feicao] = []
    for row in tabela.to_pylist():
        geom_wkt = str(row.get("geometry_wkt") or "")
        atributos = {k: v for k, v in row.items() if k not in colunas_excluidas}
        resultado.append(Feicao(camada=camada, atributos=atributos, geometria_wkt=geom_wkt))
    return resultado


def _obter_manifesto() -> dict[str, Any]:
    """Lê e armazena em cache o manifesto das camadas geográficas."""
    global _manifesto_cache
    if _manifesto_cache is not None:
        return _manifesto_cache

    caminho = pasta_dados() / "camadas" / "_manifesto.json"
    if not caminho.exists():
        _manifesto_cache = {}
        return _manifesto_cache

    with open(caminho, "r", encoding="utf-8") as f:
        _manifesto_cache = json.load(f)
    return _manifesto_cache


def _obter_datas() -> dict[str, Any]:
    """Lê e armazena em cache o dicionário de datas das camadas (_datas.json)."""
    global _datas_cache
    if _datas_cache is not None:
        return _datas_cache

    caminho = pasta_dados() / "camadas" / "_datas.json"
    if not caminho.exists():
        _datas_cache = {}
        return _datas_cache

    with open(caminho, "r", encoding="utf-8") as f:
        _datas_cache = json.load(f)
    return _datas_cache


def data_camada(camada: str) -> str | None:
    """Retorna a data de download de uma camada a partir de _datas.json ou do manifesto.

    No modo instalado vale a do quadrado mais antigo baixado (é ela que pede atualização).
    """
    if modo_instalado():
        pasta = camadas_wfs.pasta_camada(pasta_dados(), camada)
        feitos = list(pasta.glob("q_*.*")) if pasta.exists() else []
        if not feitos:
            return None
        mais_antigo = min(p.stat().st_mtime for p in feitos)
        return datetime.date.fromtimestamp(mais_antigo).isoformat()
    datas = _obter_datas()
    if datas and camada in datas and datas[camada]:
        return str(datas[camada])

    manifesto = _obter_manifesto()
    if not manifesto or camada not in manifesto:
        return None

    info = manifesto[camada]
    if isinstance(info, str):
        return info

    if isinstance(info, dict):
        for chave in (
            "data",
            "data_download",
            "download_data",
            "data_extracao",
            "data_carga",
            "data_hora",
        ):
            if chave in info and info[chave] is not None:
                return str(info[chave])
        for chave, valor in info.items():
            if "data" in chave.lower() and valor is not None:
                return str(valor)

    return None


class RegiaoProntaAusente(FileNotFoundError):
    """A área pronta (data/regioes/<nome>.geojson) não está no pacote de dados."""


def regiao_pronta(nome: str) -> str:
    """Polígono (WKT, WGS84) de uma área pronta do pacote de dados: data/regioes/<nome>.geojson.

    Hoje só há "marechal-tito": a faixa de 1.500 m em volta da Av. Marechal Tito do app antigo
    (prospeccao-marechal-tito/data/regioes/marechal-tito/buffer.geojson, feita sobre o traçado
    da via; 43,8 km²). Vários polígonos no arquivo viram a união deles.
    """
    caminho = pasta_dados() / "regioes" / f"{nome}.geojson"
    if not caminho.exists():
        raise RegiaoProntaAusente(
            f"A área pronta '{nome}' não está no pacote de dados ({caminho}). "
            "Copie o buffer.geojson do app antigo para esse caminho."
        )
    with open(caminho, "r", encoding="utf-8") as f:
        conteudo = json.load(f)
    geoms = [shapely.geometry.shape(feat["geometry"]) for feat in conteudo["features"]]
    return str(shapely.union_all(geoms).wkt)
