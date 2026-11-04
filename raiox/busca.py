"""Normalização e busca de logradouros e lotes para o Raio-X de Terrenos SP."""
from __future__ import annotations

from dataclasses import dataclass, field
import difflib
import re
import string
import unicodedata

from raiox import dados
from raiox.tipos import Candidatos, LoteCadastro, NaoEncontrado

_PONTUACAO_TABELA = str.maketrans({c: " " for c in string.punctuation})

# Dicionário de formas por extenso para abreviações oficiais do cadastro municipal.
# Cada entrada reflete tokens confirmados em dados.logradouros_unicos() com seu respectivo número de ocorrências.
ABREVIACOES: dict[str, str] = {
    # Tipos de logradouro
    "RUA": "R",  # 34.581 logradouros
    "AVENIDA": "AV",  # 1.270 logradouros
    "ALAMEDA": "AL",  # 114 logradouros
    "TRAVESSA": "TV",  # 3.150 logradouros
    "PRACA": "PC",  # 968 logradouros (PCA tem 0)
    "ESTRADA": "ES",  # 104 logradouros
    "LARGO": "LG",  # 60 logradouros (LGO tem 0)
    "VIADUTO": "VD",  # 5 logradouros (VIAD tem 0)
    "VILA": "VL",  # 6 logradouros
    "PARQUE": "PQ",  # 4 logradouros
    "LADEIRA": "LD",  # 4 logradouros
    "BECO": "BC",  # 1 logradouro
    "PONTE": "PT",  # 1 logradouro (PTE tem 0)
    "CAMINHO": "CM",  # 13 logradouros
    "ACESSO": "AC",  # 12 logradouros
    "PASSAGEM": "PS",  # 193 logradouros
    # Títulos, patentes e honrarias
    "DOUTOR": "DR",  # 1.237 logradouros
    "DOUTORA": "DRA",  # 12 logradouros
    "PROFESSOR": "PROF",  # 613 logradouros
    "PROFESSORA": "PROFA",  # 75 logradouros
    "MARECHAL": "MAL",  # 45 logradouros
    "GENERAL": "GAL",  # 165 logradouros
    "CORONEL": "CEL",  # 251 logradouros
    "ENGENHEIRO": "ENG",  # 211 logradouros
    "ENGENHEIRA": "ENGA",  # 2 logradouros
    "PADRE": "PDE",  # 379 logradouros (PE aparece apenas em 2 logradouros como 'pé')
    "SANTA": "STA",  # 194 logradouros
    "SANTO": "STO",  # 102 logradouros
    "SENADOR": "SEN",  # 45 logradouros
    "DEPUTADO": "DEP",  # 28 logradouros
    "PRESIDENTE": "PRES",  # 26 logradouros
    "VEREADOR": "VER",  # 14 logradouros
    "BRIGADEIRO": "BRIG",  # 29 logradouros
    "CAPITAO": "CAP",  # 129 logradouros
    "TENENTE": "TEN",  # 1 logradouro
    "MONSENHOR": "MONS",  # 66 logradouros
    "CONSELHEIRO": "CONS",  # 29 logradouros
    "DESEMBARGADOR": "DESEM",  # 96 logradouros (DES tem 0)
    "JORNALISTA": "JORN",  # 15 logradouros
    "MINISTRO": "MIN",  # 70 logradouros
    "VISCONDE": "VISC",  # 68 logradouros
    "BARAO": "BR",  # 132 logradouros
    "COMENDADOR": "COMEN",  # 71 logradouros
    "MAESTRO": "MAEST",  # 70 logradouros
    "SOLDADO": "SOLD",  # 94 logradouros
}

TIPOS_LOGRADOURO: frozenset[str] = frozenset(
    {
        "RUA",
        "AVENIDA",
        "ALAMEDA",
        "TRAVESSA",
        "PRACA",
        "ESTRADA",
        "LARGO",
        "VIADUTO",
        "VILA",
        "PARQUE",
        "LADEIRA",
        "BECO",
        "PONTE",
        "CAMINHO",
        "ACESSO",
        "PASSAGEM",
    }
)


@dataclass(frozen=True)
class Achado:
    """Resultado da busca quando um lote específico é identificado."""

    lote: LoteCadastro
    avisos: list[str] = field(default_factory=list)


def normalizar_logradouro(texto: str) -> str:
    """Normaliza nome de logradouro para busca.

    Aplica em sequência:
    1. Sem acento (unicodedata NFKD decomposto, removendo marcas de combinação);
    2. Maiúsculas;
    3. Pontuação vira espaço (caracteres ASCII de pontuação e categorias de pontuação Unicode);
    4. Espaços colapsados e strip nas pontas.
    """
    if not texto:
        return ""

    texto_nfkd = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in texto_nfkd if not unicodedata.combining(c))

    maiusculas = sem_acento.upper()

    limpo = "".join(
        " " if unicodedata.category(c).startswith("P") or c in string.punctuation else c
        for c in maiusculas
    )

    return " ".join(limpo.split())


def interpretar_sql(texto: str) -> tuple[str, str, str, str | None] | None:
    """Interpreta texto livre como SQL de São Paulo (setor, quadra, lote, digito).

    Reconhece 10 dígitos (sem dígito verificador) ou 11 dígitos (com dígito verificador),
    aceitando pontos, traços e espaços em qualquer lugar. Texto contendo letras não é SQL.
    """
    if any(c.isalpha() for c in texto):
        return None

    digitos = "".join(c for c in texto if c.isdigit())
    if len(digitos) == 10:
        return digitos[:3], digitos[3:6], digitos[6:10], None
    if len(digitos) == 11:
        return digitos[:3], digitos[3:6], digitos[6:10], digitos[10]
    return None


def _extrair_numero_e_logradouro(texto: str) -> tuple[str, str | None]:
    """Separa o número da porta (último grupo de dígitos) e normaliza o logradouro."""
    matches = list(re.finditer(r"\d+", texto))
    if matches:
        last_m = matches[-1]
        numero = last_m.group()
        prefixo = texto[: last_m.start()]
    else:
        numero = None
        prefixo = texto

    # Remover Nº, NO, N soltos antes do número
    prefixo_limpo = re.sub(r"(?i)(?:\bN[º°O]?|\bNUMERO|\bNUM)\.?\s*$", "", prefixo.strip())
    logradouro_norm = normalizar_logradouro(prefixo_limpo)

    # Substituição por extenso -> abreviação oficial
    # Tipos de logradouro são abreviados apenas na primeira posição para não
    # descaracterizar nomes próprios no meio (ex.: 'Rua Parque do Carmo' ou 'Avenida Vila Ema').
    tokens = logradouro_norm.split()
    tokens_abrev: list[str] = []
    for idx, tok in enumerate(tokens):
        if idx == 0:
            tokens_abrev.append(ABREVIACOES.get(tok, tok))
        else:
            if tok in TIPOS_LOGRADOURO:
                tokens_abrev.append(tok)
            else:
                tokens_abrev.append(ABREVIACOES.get(tok, tok))
    logradouro_final = " ".join(tokens_abrev)

    return logradouro_final, numero


def _lote_numero_mais_proximo(
    lotes: list[LoteCadastro], numero_buscado: str
) -> tuple[LoteCadastro | None, str | None]:
    """Localiza o lote com numeração de porta mais próxima do número buscado."""
    try:
        alvo = int(numero_buscado)
    except ValueError:
        return None, None

    melhor_lote: LoteCadastro | None = None
    melhor_dist = float("inf")
    melhor_num_str: str | None = None

    for lote in lotes:
        if not lote.numero_porta:
            continue
        tokens = re.findall(r"\d+", lote.numero_porta)
        for tok in tokens:
            try:
                val = int(tok)
            except ValueError:
                continue
            dist = abs(val - alvo)
            if dist < melhor_dist:
                melhor_dist = dist
                melhor_lote = lote
                melhor_num_str = tok
            elif dist == melhor_dist and melhor_num_str is not None:
                if val < int(melhor_num_str):
                    melhor_lote = lote
                    melhor_num_str = tok

    return melhor_lote, melhor_num_str


def _escolher_lote_representativo(
    lotes: list[LoteCadastro], numero_buscado: str | None
) -> LoteCadastro | None:
    """Escolhe um lote representativo por logradouro (número mais próximo ou primeiro)."""
    if not lotes:
        return None
    if numero_buscado is not None:
        prox, _ = _lote_numero_mais_proximo(lotes, numero_buscado)
        if prox is not None:
            return prox
    return lotes[0]


def _ordenar_por_numero(lotes: list[LoteCadastro]) -> list[LoteCadastro]:
    """Ordena lotes para apresentação de candidatos.

    Primeiro os de número válido (> 0) em ordem crescente, um por número
    (sem repetir o mesmo número de porta), depois os 'S/N' / 0.
    """
    validos_por_num: dict[int, LoteCadastro] = {}
    sem_numero: list[LoteCadastro] = []

    for lote in lotes:
        nums = re.findall(r"\d+", lote.numero_porta or "")
        if nums:
            try:
                n = int(nums[0])
            except ValueError:
                n = 0
        else:
            n = 0

        if n > 0:
            if n not in validos_por_num:
                validos_por_num[n] = lote
        else:
            sem_numero.append(lote)

    resultado = [validos_por_num[k] for k in sorted(validos_por_num.keys())]
    resultado.extend(sem_numero)
    return resultado


def buscar(texto: str) -> Achado | Candidatos | NaoEncontrado:
    """Busca um lote por SQL ou endereço livre."""
    t = texto.strip()
    if not t:
        return NaoEncontrado(texto=texto, motivo="Texto de busca vazio.")

    # 1. Tentar interpretar como SQL
    sql_info = interpretar_sql(t)
    if sql_info is not None:
        setor, quadra, lote, digito_informado = sql_info
        lotes_encontrados = dados.lote_por_sql(setor, quadra, lote)
        if lotes_encontrados:
            lote_cad = lotes_encontrados[0]
            avisos: list[str] = []
            if (
                digito_informado is not None
                and lote_cad.digito is not None
                and digito_informado != lote_cad.digito
            ):
                avisos.append(
                    f"Dígito informado ({digito_informado}) diferente do cadastro ({lote_cad.digito}); confira o SQL."
                )
            if lote_cad.cd_condominio and lote_cad.cd_condominio != "00":
                avisos.append("Lote de condomínio: a área é a do terreno inteiro do condomínio.")
            return Achado(lote=lote_cad, avisos=avisos)

        # Não achou: verificar se a quadra tem lote de condomínio
        lotes_quadra = dados.lotes_da_quadra(setor, quadra)
        lotes_condo = [
            l
            for l in lotes_quadra
            if l.lote == "0000" or (bool(l.cd_condominio) and l.cd_condominio != "00")
        ]
        if lotes_condo:
            return Candidatos(
                texto=texto,
                opcoes=lotes_condo,
                avisos=[
                    "Pode ser o SQL de uma unidade em condomínio; o cadastro de lotes guarda só o lote do condomínio. Confira o endereço."
                ],
            )

        return NaoEncontrado(
            texto=texto,
            motivo="SQL não encontrado no cadastro de lotes (não encontrado na base não quer dizer que não existe).",
        )

    # 2. Busca por endereço (o programa instalado não tem o cadastro da cidade inteira)
    if dados.modo_instalado():
        return NaoEncontrado(
            texto=texto,
            motivo=(
                "Neste programa não há busca por endereço: marque o terreno no mapa, desenhe a área ou "
                "solte um KMZ. O SQL só é achado em áreas que você já abriu."
            ),
        )
    logradouro_proc, numero_buscado = _extrair_numero_e_logradouro(t)
    if not logradouro_proc:
        return NaoEncontrado(texto=texto, motivo="Logradouro não informado ou inválido.")

    avisos_endereco: list[str] = []
    lotes = dados.lotes_por_logradouro(logradouro_proc)

    if not lotes:
        matches = difflib.get_close_matches(
            logradouro_proc, dados.logradouros_unicos(), n=5, cutoff=0.75
        )
        if not matches:
            return NaoEncontrado(
                texto=texto,
                motivo=f"Logradouro '{logradouro_proc}' não encontrado no cadastro.",
            )
        if len(matches) > 1:
            opcoes: list[LoteCadastro] = []
            for cand in matches:
                cand_lotes = dados.lotes_por_logradouro(cand)
                rep = _escolher_lote_representativo(cand_lotes, numero_buscado)
                if rep:
                    opcoes.append(rep)
            return Candidatos(
                texto=texto,
                opcoes=opcoes,
                avisos=["Mais de um logradouro parecido; escolha um."],
            )

        logradouro_escolhido = matches[0]
        avisos_endereco.append(f"Logradouro aproximado: usei {logradouro_escolhido}.")
        lotes = dados.lotes_por_logradouro(logradouro_escolhido)
        if not lotes:
            return NaoEncontrado(
                texto=texto,
                motivo=f"Logradouro '{logradouro_escolhido}' não encontrado no cadastro.",
            )

    # Casos de número
    if numero_buscado is None:
        lotes_ord = _ordenar_por_numero(lotes)
        return Candidatos(texto=texto, opcoes=lotes_ord[:10], avisos=avisos_endereco)

    exatos = [
        l
        for l in lotes
        if l.numero_porta and numero_buscado in re.findall(r"\d+", l.numero_porta)
    ]
    if len(exatos) == 1:
        lote_cad = exatos[0]
        if lote_cad.cd_condominio and lote_cad.cd_condominio != "00":
            avisos_endereco.append("Lote de condomínio: a área é a do terreno inteiro do condomínio.")
        return Achado(lote=lote_cad, avisos=avisos_endereco)
    elif len(exatos) > 1:
        avisos_cand = list(avisos_endereco)
        setores = {l.setor for l in exatos}
        if len(setores) > 1:
            avisos_cand.append(
                "Mais de um lote com este número em setores diferentes (logradouros homônimos); escolha um."
            )
        else:
            avisos_cand.append("Mais de um lote encontrado para este número; escolha um.")
        return Candidatos(texto=texto, opcoes=exatos, avisos=avisos_cand)
    else:
        lote_prox, n_cad = _lote_numero_mais_proximo(lotes, numero_buscado)
        if lote_prox is None:
            lotes_ord = _ordenar_por_numero(lotes)
            return Candidatos(texto=texto, opcoes=lotes_ord[:10], avisos=avisos_endereco)

        avisos_endereco.append(
            f"Número aproximado: o cadastro tem {n_cad} (você buscou {numero_buscado})."
        )
        if lote_prox.cd_condominio and lote_prox.cd_condominio != "00":
            avisos_endereco.append("Lote de condomínio: a área é a do terreno inteiro do condomínio.")
        return Achado(lote=lote_prox, avisos=avisos_endereco)
