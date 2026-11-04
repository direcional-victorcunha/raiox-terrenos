"""Ponto de entrada da CLI do Raio-X de Terrenos SP."""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time

from raiox.raio_x import consultar, consultar_lote
from raiox.tipos import Candidatos, NaoEncontrado, Premissas, RaioX


def _formatar_sql(setor: str, quadra: str, lote: str, digito: str | None) -> str:
    """Formata o SQL: sem dígito sai setor.quadra.lote; com dígito sai setor.quadra.lote-digito."""
    base = f"{setor}.{quadra}.{lote}"
    if digito and digito.strip() and digito.strip() != "None":
        return f"{base}-{digito.strip()}"
    return base


def _formatar_premissas(premissas: Premissas) -> str:
    """Formata a linha de premissas usadas em pt-BR."""
    if premissas.regime == "R2V_LIVRE":
        regime_str = "regime R2V livre"
    else:
        regime_str = f"regime {premissas.regime}"

    cota_str = f"cota de solidariedade: {'sim' if premissas.cota_solidariedade else 'não'}"
    zeup_str = f"ZEUP ativada: {'sim' if premissas.zeup_ativada else 'não'}"
    zem_str = f"ZEM CA 4: {'sim' if premissas.zem_ca4 else 'não'}"

    if premissas.fator_privativo is not None:
        fator_str = f"fator privativo {premissas.fator_privativo:.2f}".replace(".", ",")
    else:
        fator_str = "fator privativo não informado"

    area_unid = (
        round(premissas.area_media_unidade_m2)
        if premissas.area_media_unidade_m2.is_integer()
        else premissas.area_media_unidade_m2
    )
    unidade_str = f"unidade {area_unid} m²"

    if premissas.preco_m2 is not None:
        preco_fmt = f"{round(premissas.preco_m2):,}".replace(",", ".")
        preco_str = f"preço R$ {preco_fmt}/m²"
    elif premissas.ticket_unidade is not None:
        ticket_fmt = f"{round(premissas.ticket_unidade):,}".replace(",", ".")
        preco_str = f"ticket R$ {ticket_fmt}"
    else:
        preco_str = "preço não informado"

    partes = [
        regime_str,
        cota_str,
        zeup_str,
        zem_str,
        fator_str,
        unidade_str,
        preco_str,
    ]
    if premissas.acesso_via_estreita:
        partes.append("acesso via estreita: sim")
    if premissas.vila:
        partes.append("vila: sim")

    return f"Premissas usadas: {' · '.join(partes)}"


def _formatar_raiox_texto(raio_x: RaioX, premissas: Premissas) -> str:
    """Formata a saída de um Raio-X em texto legível para terminal em pt-BR."""
    linhas: list[str] = []
    lote = raio_x.lote

    # Cabeçalho
    endereco = f"{lote.logradouro}, {lote.numero_porta}" if lote.numero_porta else lote.logradouro
    sql_fmt = _formatar_sql(lote.setor, lote.quadra, lote.lote, lote.digito)
    area_fmt = f"{round(lote.area_terreno_m2):,}".replace(",", ".") + " m²"
    uso_str = lote.uso or "Não informado"
    zonas_str = ", ".join(f"{sigla} ({round(pct)}%)" for sigla, pct in raio_x.zonas)

    linhas.append("=== Raio-X do Terreno ===")
    linhas.append(f"Endereço: {endereco}")
    linhas.append(f"SQL: {sql_fmt}")
    linhas.append(f"Área do terreno: {area_fmt}")
    if lote.area_construida_m2 is not None and raio_x.pct_construido is not None:
        area_const_fmt = f"{round(lote.area_construida_m2):,}".replace(",", ".") + " m²"
        pct_fmt = f"{round(raio_x.pct_construido)}%"
        linhas.append(f"Área construída: {area_const_fmt} ({pct_fmt} do terreno)")
    elif lote.area_construida_m2 is not None:
        area_const_fmt = f"{round(lote.area_construida_m2):,}".replace(",", ".") + " m²"
        linhas.append(f"Área construída: {area_const_fmt}")
    else:
        linhas.append("Área construída: Não informada")
    linhas.append(f"Uso: {uso_str}")
    linhas.append(f"Zona(s): {zonas_str}")
    linhas.append("")

    # Cadeia de cálculo
    linhas.append("Cadeia de cálculo:")
    for passo in raio_x.area_util.passos:
        linhas.append(f"  • {passo}")
    linhas.append("")

    # Farol
    linhas.append("Farol:")
    presentes = [s for s in raio_x.sinais if s.presente]
    ausentes = [s for s in raio_x.sinais if not s.presente]
    for s in presentes:
        linhas.append(f"  ● {s.rotulo} — {s.medida} — {s.fonte}")
    for s in ausentes:
        linhas.append(f"  ○ {s.rotulo} — {s.medida} — {s.fonte}")
    linhas.append("")

    # Estação mais próxima
    linhas.append("Estação mais próxima:")
    if raio_x.estacao is not None:
        nome_est, dist_m = raio_x.estacao
        dist_fmt = f"{round(dist_m):,}".replace(",", ".") + " m"
        linhas.append(f"  {nome_est} — {dist_fmt}")
    else:
        linhas.append("  Nenhuma estação encontrada em até 5 km.")
    linhas.append("")

    # Avisos
    linhas.append("Avisos:")
    if raio_x.avisos:
        for av in raio_x.avisos:
            linhas.append(f"  • {av}")
    else:
        linhas.append("  (nenhum)")
    linhas.append("")

    # Premissas usadas
    linhas.append(_formatar_premissas(premissas))
    return "\n".join(linhas)


def _formatar_candidatos_texto(candidatos: Candidatos) -> str:
    """Formata lista de candidatos em texto pt-BR."""
    linhas: list[str] = [
        f"Múltiplas opções encontradas para '{candidatos.texto}':",
    ]
    for i, op in enumerate(candidatos.opcoes, start=1):
        num = op.numero_porta or "s/n"
        sql_fmt = _formatar_sql(op.setor, op.quadra, op.lote, op.digito)
        area_fmt = f"{round(op.area_terreno_m2):,}".replace(",", ".") + " m²"
        linhas.append(f"  [{i}] {op.logradouro}, {num} — SQL {sql_fmt} — {area_fmt}")

    linhas.append("Use --escolher N para detalhar um candidato.")
    if candidatos.avisos:
        linhas.append("Avisos:")
        for av in candidatos.avisos:
            linhas.append(f"  • {av}")
    return "\n".join(linhas)


def _formatar_nao_encontrado_texto(ne: NaoEncontrado) -> str:
    """Formata resultado não encontrado em texto pt-BR."""
    return f"Não encontrado para '{ne.texto}'.\nMotivo: {ne.motivo}"


def main() -> None:
    """Execução principal da CLI."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Raio-X de Terrenos SP — Consulta de viabilidade urbanística de lotes."
    )
    parser.add_argument("texto", help="Endereço ou SQL do lote a ser consultado")
    parser.add_argument("--json", action="store_true", help="Retorna saída estruturada em JSON")
    parser.add_argument(
        "--regime",
        choices=["R2V_LIVRE", "EHMP", "EHIS"],
        default="R2V_LIVRE",
        help="Regime urbanístico para limites de CA",
    )
    parser.add_argument(
        "--cota",
        action="store_true",
        default=False,
        help="Aplica benefício de cota de solidariedade",
    )
    parser.add_argument(
        "--zeup",
        action="store_true",
        default=False,
        help="Considera ZEUP como ativada",
    )
    parser.add_argument(
        "--zem-ca4",
        action="store_true",
        default=False,
        help="Considera ZEM com CA máximo 4,0",
    )
    parser.add_argument(
        "--via-estreita",
        action="store_true",
        default=False,
        help="Considera via de acesso de até 10 m (rebaixamento de eixo para ZM/ZMa)",
    )
    parser.add_argument(
        "--vila",
        action="store_true",
        default=False,
        help="Considera lote em vila reconhecida (rebaixamento para ZPR)",
    )
    parser.add_argument(
        "--fator",
        type=float,
        default=None,
        help="Fator privativo para cálculo da área útil",
    )
    parser.add_argument(
        "--area-unidade",
        type=float,
        default=40.0,
        help="Área média privativa da unidade em m² (padrão: 40)",
    )
    parser.add_argument(
        "--preco",
        type=float,
        default=None,
        help="Preço estimado de venda por m² privativo",
    )
    parser.add_argument(
        "--ticket",
        type=float,
        default=None,
        help="Ticket médio estimado por unidade em R$ (calcula preço/m² se este não for informado)",
    )
    parser.add_argument(
        "--escolher",
        type=int,
        default=None,
        help="Escolhe o N-ésimo candidato retornado pela busca",
    )

    args = parser.parse_args()

    premissas = Premissas(
        regime=args.regime,
        cota_solidariedade=args.cota,
        zeup_ativada=args.zeup,
        zem_ca4=args.zem_ca4,
        fator_privativo=args.fator,
        area_media_unidade_m2=args.area_unidade,
        preco_m2=args.preco,
        acesso_via_estreita=args.via_estreita,
        vila=args.vila,
        ticket_unidade=args.ticket,
    )

    t0 = time.perf_counter()
    resultado = consultar(args.texto, premissas)

    if isinstance(resultado, Candidatos) and args.escolher is not None:
        idx = args.escolher - 1
        if 0 <= idx < len(resultado.opcoes):
            lote_escolhido = resultado.opcoes[idx]
            resultado = consultar_lote(
                lote_escolhido,
                premissas,
                avisos_busca=resultado.avisos,
            )
        else:
            print(
                f"Opção --escolher {args.escolher} inválida. Escolha entre 1 e {len(resultado.opcoes)}."
            )
            sys.exit(1)

    delta_ms = round((time.perf_counter() - t0) * 1000)

    if args.json:
        dados_resultado = dataclasses.asdict(resultado)
        dados_resultado["tipo"] = type(resultado).__name__
        print(json.dumps(dados_resultado, ensure_ascii=False, indent=2))
    else:
        if isinstance(resultado, RaioX):
            print(_formatar_raiox_texto(resultado, premissas))
        elif isinstance(resultado, Candidatos):
            print(_formatar_candidatos_texto(resultado))
        elif isinstance(resultado, NaoEncontrado):
            print(_formatar_nao_encontrado_texto(resultado))

    print(f"(consulta em {delta_ms} ms)")


if __name__ == "__main__":
    main()
