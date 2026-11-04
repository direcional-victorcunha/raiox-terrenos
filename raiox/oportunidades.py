"""Tabela de oportunidades do Prospectar: linhas, filtro, ordem, páginas, CSV e detalhe.

Funções puras sobre um `Entorno` já calculado (nada de disco além do CSV pedido).
Fatos e contas, sem nota: a ordem padrão é por VGV potencial, como no antigo
(prospeccao-marechal-tito/app.py:1100-1117, "Melhores oportunidades").

Dois modos de exibição:
- "oportunidades": lotes que batem a meta, duplas, trincas e os escondidos (cinza, com motivo);
- "todos": todo lote da área (com VGV potencial e a marca "bate a meta") + duplas e trincas.
"""

from __future__ import annotations

from dataclasses import dataclass
import itertools
import math
from pathlib import Path
import re
from typing import Any, Callable

import pandas as pd

from raiox import entorno as entorno_mod
from raiox import uso
from raiox.tipos import Candidato, Entorno, LoteAvaliado, LoteCadastro, Premissas

MODOS: tuple[str, ...] = ("oportunidades", "todos")
FILTROS: tuple[str, ...] = ("todas", "lote", "dupla", "trinca", "escondidos")
TOP_PADRAO = 15  # app.py:1116-1117: "Ver todas" desmarcado mostra as 15 primeiras (head(15))
POR_PAGINA_MAX = 500

# Cabeçalho do CSV do app antigo (app.py:1040-1098 + df.to_csv na linha 1137), na mesma ordem
# e com os mesmos nomes. Colunas novas só no fim (decisão antiga: "não mexer no CSV").
COLUNAS_CSV_ANTIGO: tuple[str, ...] = (
    "Tipo",
    "Área (m²)",
    "CA",
    "Potencial (m²)",
    "Unidades (est.)",
    "VGV (R$)",
    "Zona",
    "Uso",
    "Estação",
    "Dist. (m)",
    "Construído (%)",
    "Sinais",
    "Endereço",
)
COLUNAS_CSV_NOVAS: tuple[str, ...] = (
    "SQL",
    "Identificadores",
    "Escondido por",
    "Bate a meta",
    "Uso e porte (motor antigo)",
)
# Rótulos da coluna Tipo do antigo (app.py:1043, 1062, 1080-1081); o último é novo (modo todos).
_TIPO_CSV = {
    "lote": "🔵 Lote",
    "escondido": "⚪ Escondido",
    "dupla": "🟢 Dupla",
    "trinca": "🟡 Trinca",
    "abaixo": "Lote abaixo da meta",
}

# Frase curta para a tabela, pelo código do alerta do motor (urbanismo/uso_porte.py)
_USO_CURTO = {
    "ZEIS_EXIGE_EZEIS": "ZEIS > 1.000 m²: R2V livre bloqueado (exige EZEIS)",
    "USO_NAO_PERMITIDO": "porte não listado para a zona",
    "VIA_ESTREITA": "via mínima não atendida",
    "VIA_ESTREITA_EIXO_VAGAS": "via de 12 m em eixo com vagas",
    "REGIME_DESCONHECIDO": "regime não reconhecido",
}
_CODIGO = re.compile(r"\((\w+)\)$")


@dataclass(frozen=True)
class Linha:
    """Uma linha da tabela (lote, dupla ou trinca). `chave`: "l<id>" lote, "c<n>" composição."""

    chave: str
    tipo: str
    ids: tuple[str, ...]
    sql: str
    endereco: str
    area_m2: float
    zonas: str
    ca: str
    area_computavel_m2: float
    unidades: int
    vgv: float
    pct_meta: float
    uso: str
    estacao: str | None
    dist_estacao_m: float | None
    pct_construido: float | None
    sinais: tuple[str, ...]
    escondido_por: str | None
    bate_meta: bool
    uso_porte: tuple[str, ...]
    uso_porte_bloqueios: tuple[str, ...]


@dataclass(frozen=True)
class Consulta:
    """O que a tela pede à tabela: modo, filtro, ordem e página."""

    modo: str = "oportunidades"
    filtro: str = "todas"
    ordem: str = "vgv"
    decrescente: bool = True
    ver_todas: bool = False
    pagina: int = 1
    por_pagina: int = 100
    zona: str | None = None
    uso: str | None = None


# --- Formatação pt-BR ---


def _milhar(valor: float) -> str:
    return f"{round(valor):,}".replace(",", ".")


def _m2(valor: float) -> str:
    return f"{_milhar(valor)} m²"


def _brl(valor: float) -> str:
    return f"R$ {_milhar(valor)}"


def _decimal(valor: float) -> str:
    """Uma casa decimal com vírgula (ex.: 25,4)."""
    return f"{valor:.1f}".replace(".", ",")


def _ca_txt(ca: float) -> str:
    return f"{ca:.2f}".replace(".", ",")


def sql_formatado(lote: LoteCadastro) -> str:
    """SQL legível (setor.quadra.lote-dígito), ou o SQL cru se faltar alguma parte."""
    if lote.setor and lote.quadra and lote.lote:
        texto = f"{lote.setor}.{lote.quadra}.{lote.lote}"
        return f"{texto}-{lote.digito}" if lote.digito else texto
    return lote.sql or lote.cd_identificador


def endereco(lote: LoteCadastro) -> str:
    return f"{lote.logradouro}, {lote.numero_porta}" if lote.numero_porta else lote.logradouro


def _bloqueios(frases: tuple[str, ...]) -> tuple[str, ...]:
    """Só os bloqueios do motor de uso e porte, em frase curta para a coluna da tabela."""
    saida: list[str] = []
    for f in frases:
        if not f.startswith("Bloqueia:"):
            continue
        achado = _CODIGO.search(f)
        curto = _USO_CURTO.get(achado.group(1), f) if achado else f
        if curto not in saida:
            saida.append(curto)
    return tuple(saida)


def _unicos(valores: list[str], sep: str) -> str:
    return sep.join(dict.fromkeys(v for v in valores if v))


def _pct_meta(vgv: float, area_m2: float, premissas: Premissas) -> float:
    if premissas.criterio_meta == "area":
        return 100.0 * area_m2 / premissas.area_minima_m2
    return 100.0 * vgv / premissas.meta_vgv


# --- Linhas ---


def _linha_lote(a: LoteAvaliado, premissas: Premissas) -> Linha:
    lote = a.cadastro
    return Linha(
        chave=f"l{lote.cd_identificador}",
        tipo="lote",
        ids=(lote.cd_identificador,),
        sql=sql_formatado(lote),
        endereco=endereco(lote),
        area_m2=lote.area_terreno_m2,
        zonas=a.zona,
        ca=f"{a.ca:g}",
        area_computavel_m2=a.area_computavel_m2,
        unidades=a.unidades,
        vgv=a.vgv,
        pct_meta=_pct_meta(a.vgv, lote.area_terreno_m2, premissas),
        uso=lote.uso or "",
        estacao=a.estacao,
        dist_estacao_m=a.dist_estacao_m,
        pct_construido=a.pct_construido,
        sinais=a.sinais,
        escondido_por=a.escondido_por,
        bate_meta=a.bate_meta,
        uso_porte=a.uso_porte,
        uso_porte_bloqueios=_bloqueios(a.uso_porte),
    )


def uso_porte_composicao(membros: list[LoteAvaliado], premissas: Premissas) -> tuple[str, ...]:
    """Uso e porte da composição: área total e computável somadas, em cada zona dos lotes.

    A regra de ZEIS do motor olha a área do lote; numa dupla de dois lotes de 600 m² em ZEIS
    o terreno juntado passa de 1.000 m², e é isso que vale para a composição.
    """
    area_total = sum(m.cadastro.area_terreno_m2 for m in membros)
    comp_total = sum(m.area_computavel_m2 for m in membros)
    frases: list[str] = []
    for zona in dict.fromkeys(m.zona for m in membros):
        for f in uso.avaliar_uso_porte_completo(zona, area_total, comp_total, regime=premissas.regime):
            if f not in frases:
                frases.append(f)
    return tuple(frases)


def _linha_composicao(
    indice: int, c: Candidato, membros: list[LoteAvaliado], premissas: Premissas
) -> Linha:
    comp = sum(m.area_computavel_m2 for m in membros)
    area = sum(m.cadastro.area_terreno_m2 for m in membros)
    com_estacao = [m for m in membros if m.dist_estacao_m is not None]
    perto = min(com_estacao, key=lambda m: m.dist_estacao_m or 0.0) if com_estacao else None
    construida = [m.cadastro.area_construida_m2 for m in membros]
    frases = uso_porte_composicao(membros, premissas)
    return Linha(
        chave=f"c{indice}",
        tipo=c.tipo,
        ids=c.ids,
        sql=" + ".join(sql_formatado(m.cadastro) for m in membros),
        endereco=_unicos([endereco(m.cadastro) for m in membros], " + "),
        area_m2=c.area_m2,
        zonas=_unicos([m.zona for m in membros], " | "),
        ca=_unicos([f"{m.ca:g}" for m in membros], " | "),
        area_computavel_m2=comp,
        unidades=int(comp // premissas.area_media_unidade_m2),
        vgv=c.vgv,
        pct_meta=_pct_meta(c.vgv, area, premissas),
        uso=_unicos([m.cadastro.uso or "" for m in membros], " + "),
        estacao=perto.estacao if perto else None,
        dist_estacao_m=perto.dist_estacao_m if perto else None,
        pct_construido=(
            float(round(100.0 * sum(x or 0.0 for x in construida) / area))
            if area > 0 and any(x is not None for x in construida)
            else None
        ),
        sinais=c.sinais,
        escondido_por=c.escondido_por,
        bate_meta=True,
        uso_porte=frases,
        uso_porte_bloqueios=_bloqueios(frases),
    )


def linhas(entorno: Entorno, premissas: Premissas, modo: str) -> list[Linha]:
    """Todas as linhas do modo, na ordem do entorno (sem filtro nem ordenação)."""
    if modo not in MODOS:
        raise ValueError(f"modo de exibição desconhecido: {modo!r} (use {', '.join(MODOS)})")
    por_id = {a.cadastro.cd_identificador: a for a in entorno.lotes}
    saida: list[Linha] = []
    if modo == "todos":
        saida.extend(_linha_lote(a, premissas) for a in entorno.lotes)
    for i, c in enumerate(entorno.candidatos):
        if c.tipo == "lote":
            if modo == "oportunidades":
                saida.append(_linha_lote(por_id[c.ids[0]], premissas))
            continue
        saida.append(_linha_composicao(i, c, [por_id[x] for x in c.ids], premissas))
    return saida


def _passa_filtro(linha: Linha, consulta: Consulta) -> bool:
    if consulta.zona and consulta.zona not in linha.zonas.split(" | "):
        return False
    if consulta.uso and consulta.uso not in linha.uso.split(" + "):
        return False
    if consulta.filtro == "escondidos":
        return linha.escondido_por is not None
    # Modo oportunidades: "Todas" e "Lotes" deixam os escondidos de fora, como no antigo
    # (app.py:1107-1112). Modo todos: mostra todo lote da área, o escondido em cinza.
    if consulta.modo == "oportunidades" and linha.escondido_por is not None:
        return False
    return consulta.filtro == "todas" or linha.tipo == consulta.filtro


_CHAVES_ORDEM: dict[str, Callable[[Linha], Any]] = {
    "tipo": lambda l: l.tipo,
    "sql": lambda l: l.sql,
    "endereco": lambda l: l.endereco,
    "area_m2": lambda l: l.area_m2,
    "zonas": lambda l: l.zonas,
    "ca": lambda l: l.ca,
    "area_computavel_m2": lambda l: l.area_computavel_m2,
    "unidades": lambda l: l.unidades,
    "vgv": lambda l: l.vgv,
    "uso": lambda l: l.uso,
    "estacao": lambda l: l.estacao,
    "dist_estacao_m": lambda l: l.dist_estacao_m,
    "pct_construido": lambda l: l.pct_construido,
    "sinais": lambda l: " · ".join(l.sinais),
    "uso_porte": lambda l: " · ".join(l.uso_porte_bloqueios),
    "escondido_por": lambda l: l.escondido_por,
}


def validar(consulta: Consulta) -> None:
    """Levanta ValueError em pt-BR se a consulta da tela vier com valor desconhecido."""
    if consulta.modo not in MODOS:
        raise ValueError(f"Modo de exibição desconhecido: {consulta.modo!r}.")
    if consulta.filtro not in FILTROS:
        raise ValueError(f"Filtro desconhecido: {consulta.filtro!r}.")
    if consulta.ordem not in _CHAVES_ORDEM:
        raise ValueError(f"Coluna de ordenação desconhecida: {consulta.ordem!r}.")
    if consulta.pagina < 1 or not 1 <= consulta.por_pagina <= POR_PAGINA_MAX:
        raise ValueError("Página inválida.")


def filtrar_e_ordenar(todas: list[Linha], consulta: Consulta) -> list[Linha]:
    """Filtro da tela + ordenação pela coluna (vazios sempre no fim)."""
    validar(consulta)
    chave = _CHAVES_ORDEM[consulta.ordem]
    filtradas = [l for l in todas if _passa_filtro(l, consulta)]
    com_valor = [l for l in filtradas if chave(l) not in (None, "")]
    sem_valor = [l for l in filtradas if chave(l) in (None, "")]
    com_valor.sort(key=lambda l: (chave(l), l.chave), reverse=consulta.decrescente)
    return com_valor + sem_valor


def exibidas(ordenadas: list[Linha], consulta: Consulta) -> list[Linha]:
    """O que o CSV e a tela mostram: as 15 primeiras, ou todas com "Ver todas"."""
    return ordenadas if consulta.ver_todas else ordenadas[:TOP_PADRAO]


def pagina(ordenadas: list[Linha], consulta: Consulta) -> dict[str, Any]:
    """Uma página da tabela já filtrada e ordenada, com os totais."""
    visiveis = exibidas(ordenadas, consulta)
    n_paginas = max(1, math.ceil(len(visiveis) / consulta.por_pagina))
    p = min(consulta.pagina, n_paginas)
    ini = (p - 1) * consulta.por_pagina
    return {
        "linhas": visiveis[ini : ini + consulta.por_pagina],
        "total_filtrado": len(ordenadas),
        "total_exibido": len(visiveis),
        "pagina": p,
        "n_paginas": n_paginas,
        "por_pagina": consulta.por_pagina,
    }


def resumo(entorno: Entorno) -> dict[str, int]:
    """Contagens da faixa de baixo (as mesmas quatro do antigo, app.py:640-647) e da área."""
    cs = entorno.candidatos
    return {
        "lotes": sum(1 for c in cs if c.tipo == "lote" and c.escondido_por is None),
        "escondidos": sum(1 for c in cs if c.tipo == "lote" and c.escondido_por is not None),
        "duplas": sum(1 for c in cs if c.tipo == "dupla"),
        "trincas": sum(1 for c in cs if c.tipo == "trinca"),
        "lotes_area": len(entorno.lotes),
        "abaixo_da_meta": sum(1 for a in entorno.lotes if not a.bate_meta),
    }


def cortes_meta(premissas: Premissas, preco_m2: float) -> str:
    """Linha do painel Meta do antigo (app.py:282-288): área que bate a meta sozinha por CA."""
    if premissas.criterio_meta == "area":
        return f"Bate a meta o lote com pelo menos {_m2(premissas.area_minima_m2)} (e CA maior que zero)."
    cortes = " · ".join(
        f"CA {ca:g} → {_m2(premissas.meta_vgv / (ca * preco_m2))}" for ca in (4, 2, 1)
    )
    return f"Área mínima do lote para bater a meta sozinho: {cortes}"


def opcoes_filtro(todas: list[Linha]) -> dict[str, list[str]]:
    """Zonas e usos presentes, para os filtros da tabela (equivalem aos Filtros do antigo)."""
    zonas = sorted({z for l in todas for z in l.zonas.split(" | ") if z})
    usos = sorted({u for l in todas for u in l.uso.split(" + ") if u})
    return {"zonas": zonas, "usos": usos}


# --- CSV ---


def _tipo_csv(linha: Linha) -> str:
    if linha.tipo != "lote":
        return _TIPO_CSV[linha.tipo]
    if linha.escondido_por is not None:
        return _TIPO_CSV["escondido"]
    return _TIPO_CSV["lote"] if linha.bate_meta else _TIPO_CSV["abaixo"]


def gravar_csv(caminho: Path, linhas_csv: list[Linha]) -> None:
    """CSV no formato do antigo: pandas.to_csv(index=False), vírgula, ponto decimal, UTF-8."""
    registros = [
        {
            "Tipo": _tipo_csv(l),
            "Área (m²)": l.area_m2,
            "CA": l.ca,
            "Potencial (m²)": l.area_computavel_m2,
            "Unidades (est.)": l.unidades,
            "VGV (R$)": l.vgv,
            "Zona": l.zonas,
            "Uso": l.uso,
            "Estação": l.estacao or "",
            "Dist. (m)": None if l.dist_estacao_m is None else round(l.dist_estacao_m),
            "Construído (%)": None if l.pct_construido is None else round(l.pct_construido),
            "Sinais": (
                "Escondido: " + l.escondido_por
                if l.escondido_por is not None
                else (" · ".join(l.sinais) or "—")
            ),
            "Endereço": l.endereco,
            "SQL": l.sql,
            "Identificadores": " + ".join(l.ids),
            "Escondido por": l.escondido_por or "",
            "Bate a meta": "sim" if l.bate_meta else "não",
            "Uso e porte (motor antigo)": " · ".join(l.uso_porte_bloqueios),
        }
        for l in linhas_csv
    ]
    df = pd.DataFrame(registros, columns=list(COLUNAS_CSV_ANTIGO + COLUNAS_CSV_NOVAS))
    caminho.write_bytes(df.to_csv(index=False).encode("utf-8"))


# --- Detalhe (lote, dupla ou trinca) ---


def _lote_detalhe(a: LoteAvaliado) -> dict[str, Any]:
    lote = a.cadastro
    return {
        "cd_identificador": lote.cd_identificador,
        "sql": sql_formatado(lote),
        "endereco": endereco(lote),
        "area_m2": lote.area_terreno_m2,
        "zona": a.zona,
        "ca": a.ca,
        "area_computavel_m2": a.area_computavel_m2,
        "vgv": a.vgv,
        "uso": lote.uso,
        "pct_construido": a.pct_construido,
        "estacao": a.estacao,
        "dist_estacao_m": a.dist_estacao_m,
        "sinais": list(a.sinais),
        "escondido_por": a.escondido_por,
        "bate_meta": a.bate_meta,
        "uso_porte": list(a.uso_porte),
    }


def _conta(membros: list[LoteAvaliado], vgv: float, preco_m2: float, premissas: Premissas) -> list[str]:
    """A conta do VGV potencial passo a passo, lote a lote, em pt-BR."""
    passos = [
        f"{sql_formatado(m.cadastro)}: {_m2(m.cadastro.area_terreno_m2)} × CA {_ca_txt(m.ca)} = "
        f"{_m2(m.area_computavel_m2)} computáveis"
        for m in membros
    ]
    comp = sum(m.area_computavel_m2 for m in membros)
    if len(membros) > 1:
        area = sum(m.cadastro.area_terreno_m2 for m in membros)
        passos.append(
            "Soma da área: " + " + ".join(_milhar(m.cadastro.area_terreno_m2) for m in membros)
            + f" = {_m2(area)}"
        )
        passos.append(
            "Soma da área computável: " + " + ".join(_milhar(m.area_computavel_m2) for m in membros)
            + f" = {_m2(comp)}"
        )
    passos.append(f"{_m2(comp)} × {_brl(preco_m2)}/m² = {_brl(vgv)} (VGV potencial)")
    passos.append(
        f"{_m2(comp)} ÷ {_m2(premissas.area_media_unidade_m2)} = "
        f"{_milhar(int(comp // premissas.area_media_unidade_m2))} unidades estimadas"
    )
    if premissas.criterio_meta == "area":
        area = sum(m.cadastro.area_terreno_m2 for m in membros)
        passos.append(
            f"{_m2(area)} ÷ área mínima {_m2(premissas.area_minima_m2)} = "
            f"{100.0 * area / premissas.area_minima_m2:.0f}% da meta"
        )
    else:
        passos.append(
            f"{_brl(vgv)} ÷ meta {_brl(premissas.meta_vgv)} = "
            f"{100.0 * vgv / premissas.meta_vgv:.0f}% da meta"
        )
    return passos


def detalhe(entorno: Entorno, premissas: Premissas, preco_m2: float, chave: str) -> dict[str, Any]:
    """Fatos e conta de uma linha: lotes que compõem, área, CA, computável, soma, VGV e divisas."""
    por_id = {a.cadastro.cd_identificador: a for a in entorno.lotes}
    if chave.startswith("l") and chave[1:] in por_id:
        a = por_id[chave[1:]]
        tipo = "lote"
        membros = [a]
        vgv = a.vgv
        sinais = list(a.sinais)
        escondido = a.escondido_por
        frases = list(a.uso_porte)
    elif chave.startswith("c") and chave[1:].isdigit() and int(chave[1:]) < len(entorno.candidatos):
        c = entorno.candidatos[int(chave[1:])]
        tipo = c.tipo
        membros = [por_id[x] for x in c.ids]
        vgv = c.vgv
        sinais = list(c.sinais)
        escondido = c.escondido_por
        frases = list(uso_porte_composicao(membros, premissas))
    else:
        raise ValueError(f"Linha {chave!r} não está no entorno atual (recalcule e clique de novo).")

    divisas = [
        {
            "ids": [x.cadastro.cd_identificador, y.cadastro.cd_identificador],
            "texto": (
                f"{sql_formatado(x.cadastro)} × {sql_formatado(y.cadastro)}: "
                f"{_decimal(entorno_mod.divisa_m(x.cadastro.geometria_wkt, y.cadastro.geometria_wkt))} m "
                "de divisa em comum"
            ),
        }
        for x, y in itertools.combinations(membros, 2)
    ]
    return {
        "tipo": tipo,
        "chave": chave,
        "lotes": [_lote_detalhe(m) for m in membros],
        "area_m2": sum(m.cadastro.area_terreno_m2 for m in membros),
        "area_computavel_m2": sum(m.area_computavel_m2 for m in membros),
        "vgv": vgv,
        "conta": _conta(membros, vgv, preco_m2, premissas),
        "divisas": divisas,
        "divisa_minima_m": premissas.divisa_min_m,
        "sinais": sinais,
        "escondido_por": escondido,
        "uso_porte": frases,
    }
