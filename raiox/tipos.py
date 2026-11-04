"""Contratos e modelos de dados do Raio-X de Terrenos SP."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Premissas:
    """Premissas e parâmetros configuráveis para a análise de viabilidade e busca."""
    regime: str = "R2V_LIVRE"
    cota_solidariedade: bool = False
    zeup_ativada: bool = False
    zem_ca4: bool = False
    fator_privativo: float | None = None
    area_media_unidade_m2: float = 40.0
    preco_m2: float | None = None
    retiradas: tuple[str, ...] = ()
    base_vgv: str = "referencia_ca"
    # Padrões do Prospectar copiados do mapa do app antigo (prospeccao-marechal-tito/app.py):
    raio_entorno_m: float = 1500.0          # o "raio" antigo era a faixa de 1.500 m (buffer.geojson)
    meta_vgv: float = 100_000_000.0         # app.py:280 "VGV mínimo (R$ milhões)", value=100
    area_max_lote_m2: float = 50_000.0      # app.py:304-307 "Área máxima do lote", value=50_000
    limite_esconder_pct: float = 50.0       # app.py:315-319 slider da triagem, 10 a 100, value=50
    acesso_via_estreita: bool = False
    vila: bool = False
    ticket_unidade: float | None = None
    faixa_alta_tensao_m: float = 30.0
    criterio_meta: str = "vgv"              # app.py:272 "VGV mínimo" | "Área mínima" ("vgv" | "area")
    area_minima_m2: float = 1_500.0         # app.py:291 "Área mínima (m²)", value=1500.0
    # app.py:325-353: só "área pública/parque" e "favela" vêm marcadas para esconder
    triagem_esconde: tuple[str, ...] = ("publica", "favela")
    divisa_min_m: float = 20.0              # app.py:361-365 slider 0 a 60 m, value=20
    mostrar_duplas: bool = True             # app.py:359 "Duplas (2 lotes)", value=True
    mostrar_trincas: bool = True            # app.py:360 "Trincas (3 lotes)", value=True
    # Decisões do autor na Fase C (29/10), ver ARQUITETURA §9 e "Tela e foco compartilhado":
    # o multiplicador de EHIS/EHMP do motor (×1,5/×1,25, ca_engine.MULT_PRODUTO) é opção. Era desligada
    # (a planilha não multiplicava); em 30/10 o autor confirmou CA 6 em EHIS na ZEU (4 × 1,5, Quadro 2 do
    # Decreto 63.728), então o padrão passou a ligado.
    multiplicador_ehis_ehmp: bool = True
    # Área cadastro × desenho: acima deste % de diferença o Raio-X avisa (ARQUITETURA §9, 5%).
    limite_divergencia_area_pct: float = 5.0

    def __post_init__(self) -> None:
        if self.area_media_unidade_m2 <= 0:
            raise ValueError("A área média da unidade deve ser maior que zero.")


@dataclass(frozen=True)
class LoteCadastro:
    """Informações cadastrais e geométricas de um lote urbano."""
    cd_identificador: str
    sql: str
    setor: str
    quadra: str
    lote: str
    digito: str | None
    cd_condominio: str | None
    logradouro: str
    numero_porta: str | None
    area_terreno_m2: float
    area_construida_m2: float | None
    uso: str | None
    situacao: str | None
    geometria_wkt: str


@dataclass(frozen=True)
class Feicao:
    """Representação genérica de feição geográfica com atributos e geometria."""
    camada: str
    atributos: dict[str, object]
    geometria_wkt: str


@dataclass(frozen=True)
class Sinal:
    """Indicação factual sobre incidência ou presença de determinada camada/condição."""
    rotulo: str
    presente: bool
    medida: str
    fonte: str


@dataclass(frozen=True)
class Retirada:
    """Faixa ou porção de área a ser deduzida do lote."""
    camada: str
    rotulo: str
    area_m2: float


@dataclass(frozen=True)
class AreaLote:
    """Discriminação de áreas bruta, geométrica e líquida após deduções."""
    bruta_m2: float
    geometrica_m2: float
    liquida_m2: float
    retiradas: list[Retirada]
    geometria_liquida_wkt: str


@dataclass(frozen=True)
class AreaUtil:
    """Área computável, unidades estimadas e VGV potencial (área × CA × preço/m², sem fator).

    `a_util` é a área útil privativa (com o fator), só informativa; `vgv` fica None sem preço.
    """
    a_ref_m2: float
    ca_teto: float
    a_comp: float
    a_util: float | None
    unidades: int
    vgv: float | None
    unidades_min_cota_parte: int | None
    passos: list[str]


@dataclass(frozen=True)
class RaioX:
    """Resultado completo da análise individual de um lote."""
    lote: LoteCadastro
    zonas: list[tuple[str, float]]
    area: AreaLote
    area_util: AreaUtil
    sinais: list[Sinal]
    estacao: tuple[str, float] | None
    avisos: list[str]
    pct_construido: float | None = None
    uso_porte: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Candidatos:
    """Múltiplas opções encontradas para determinado critério de busca textual."""
    texto: str
    opcoes: list[LoteCadastro]
    avisos: list[str]


@dataclass(frozen=True)
class NaoEncontrado:
    """Resultado indicando que o lote ou endereço pesquisado não foi localizado."""
    texto: str
    motivo: str


@dataclass(frozen=True)
class Candidato:
    """Lote ou combinação de lotes avaliados na busca de entorno."""
    tipo: str
    ids: tuple[str, ...]
    area_m2: float
    vgv: float
    zonas: tuple[str, ...]
    sinais: tuple[str, ...]
    escondido_por: str | None


@dataclass(frozen=True)
class LoteAvaliado:
    """Um lote da área de prospecção com os fatos e as contas (bata ou não a meta).

    `bate_meta` compara o VGV potencial (ou a área, no critério "área mínima") com a meta;
    `escondido_por` é o motivo da triagem/limite de área (None = visível), valha a meta ou não.
    `uso_porte` são as frases de `uso.avaliar_uso_porte_completo` (via de acesso não conferida).
    """
    cadastro: LoteCadastro
    zona: str
    ca: float
    area_computavel_m2: float
    unidades: int
    vgv: float
    bate_meta: bool
    escondido_por: str | None
    sinais: tuple[str, ...]
    pct_publica: float
    pct_favela: float
    pct_contaminada: float
    pct_risco: float
    dist_duto_m: float | None
    dist_alta_tensao_m: float | None
    estacao: str | None
    dist_estacao_m: float | None
    pct_construido: float | None
    uso_porte: tuple[str, ...]


@dataclass(frozen=True)
class Entorno:
    """Resultado de varredura e triagem de oportunidades no entorno de um ponto.

    `candidatos` são as oportunidades (lotes que batem a meta, duplas, trincas e os escondidos);
    `lotes` são todos os lotes da área, para o modo "Todos os lotes" e o detalhe das composições.
    """
    centro_wkt: str
    raio_m: float | None
    candidatos: list[Candidato]
    avisos: list[str]
    lotes: list[LoteAvaliado] = field(default_factory=list)
    # Polígono da área de busca (WGS84). None só em Entorno montado à mão (testes antigos do KMZ):
    # aí o KMZ desenha a área por centro_wkt + raio_m.
    area_wkt: str | None = None


Resultado = RaioX | Candidatos | NaoEncontrado
