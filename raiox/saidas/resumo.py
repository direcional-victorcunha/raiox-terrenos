from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from raiox.simulador import EntradaSimulador, ResultadoSimulador
    from raiox.tipos import Premissas, RaioX


def _formatar_milhar(valor: float | int) -> str:
    return f"{round(valor):,}".replace(",", ".")


def _formatar_decimal(valor: float, casas: int = 2) -> str:
    fmt = f"{valor:.{casas}f}"
    return fmt.replace(".", ",")


def gerar(rx: RaioX, premissas: Premissas) -> str:
    # Linha 1: Endereço e SQL
    if rx.lote.numero_porta and rx.lote.numero_porta.strip():
        endereco = f"{rx.lote.logradouro}, {rx.lote.numero_porta.strip()}"
    else:
        endereco = rx.lote.logradouro

    if rx.lote.setor and rx.lote.quadra and rx.lote.lote:
        if rx.lote.digito and rx.lote.digito.strip():
            sql_fmt = f"{rx.lote.setor}.{rx.lote.quadra}.{rx.lote.lote}-{rx.lote.digito.strip()}"
        else:
            sql_fmt = f"{rx.lote.setor}.{rx.lote.quadra}.{rx.lote.lote}"
    else:
        sql_fmt = rx.lote.sql

    linha1 = f"*Endereço:* {endereco} · *SQL:* {sql_fmt}"

    # Linha 2: Área do terreno
    bruta = rx.area.bruta_m2 if rx.area.bruta_m2 > 0 else rx.lote.area_terreno_m2
    bruta_fmt = _formatar_milhar(bruta)
    liquida = rx.area.liquida_m2

    if round(liquida) != round(bruta):
        liquida_fmt = _formatar_milhar(liquida)
        linha2 = f"*Área do terreno:* {bruta_fmt} m² (líquida: {liquida_fmt} m²)"
    else:
        linha2 = f"*Área do terreno:* {bruta_fmt} m²"

    # Linha 3: Zona(s)
    if rx.zonas:
        zonas_fmt = ", ".join(f"{sigla} ({round(pct)}%)" for sigla, pct in rx.zonas)
    else:
        zonas_fmt = "Não informada"
    linha3 = f"*Zona(s):* {zonas_fmt}"

    # Linha 4: CA teto
    ca_fmt = _formatar_decimal(rx.area_util.ca_teto, 2)
    linha4 = f"*CA teto:* {ca_fmt}"

    # Linha 5: Área computável
    comp_fmt = _formatar_milhar(rx.area_util.a_comp)
    linha5 = f"*Área computável:* {comp_fmt} m²"

    # Linha 6: Unidades estimadas (área computável ÷ área média)
    linha6 = f"*Unidades estimadas:* {_formatar_milhar(rx.area_util.unidades)}"

    # Linha 7: VGV potencial (área × CA × preço/m², sem fator privativo)
    if rx.area_util.vgv is not None:
        linha7 = f"*VGV potencial:* R$ {_formatar_milhar(rx.area_util.vgv)}"
    else:
        linha7 = "*VGV potencial:* preço não informado"

    # Linha 8: Área útil privativa, só informativa (com o fator)
    if rx.area_util.a_util is not None:
        linha8 = (
            f"*Área útil privativa (informativa, com o fator):* "
            f"{_formatar_milhar(rx.area_util.a_util)} m²"
        )
    else:
        linha8 = "*Área útil privativa (informativa):* fator não informado"

    # Linha 9: Sinais do farol
    sinais_presentes = [s for s in rx.sinais if s.presente]
    if sinais_presentes:
        sinais_str = " · ".join(f"{s.rotulo}: {s.medida}" for s in sinais_presentes)
        linha9 = f"*Sinais do farol:* {sinais_str}"
    else:
        linha9 = "*Sinais do farol:* nenhum"

    # Linha 10: Estação mais próxima
    if rx.estacao is not None:
        nome_estacao, dist_estacao = rx.estacao
        dist_fmt = f"{_formatar_milhar(dist_estacao)} m"
        linha10 = f"*Estação mais próxima:* {nome_estacao} ({dist_fmt})"
    else:
        linha10 = "*Estação mais próxima:* nenhuma em até 5 km"

    # Linha 11: Premissas
    partes_premissas: list[str] = []

    # 1. regime
    if premissas.regime == "R2V_LIVRE":
        partes_premissas.append("regime R2V livre")
    else:
        partes_premissas.append(f"regime {premissas.regime}")

    # 2. cota solidariedade
    partes_premissas.append("cota: sim" if premissas.cota_solidariedade else "cota: não")

    # 3. ZEUP ativada
    partes_premissas.append("ZEUP: sim" if premissas.zeup_ativada else "ZEUP: não")

    # 4. ZEM CA 4
    partes_premissas.append("ZEM CA 4: sim" if premissas.zem_ca4 else "ZEM CA 4: não")

    # 5. fator privativo
    if premissas.fator_privativo is not None:
        partes_premissas.append(f"fator: {_formatar_decimal(premissas.fator_privativo, 2)}")
    else:
        partes_premissas.append("fator: não informado")

    # 6. área média unidade
    if premissas.area_media_unidade_m2.is_integer():
        unid_val: int | float = round(premissas.area_media_unidade_m2)
    else:
        unid_val = premissas.area_media_unidade_m2
    partes_premissas.append(f"unidade: {unid_val} m²")

    # 7. preço m²
    if premissas.preco_m2 is not None:
        partes_premissas.append(f"preço: R$ {_formatar_milhar(premissas.preco_m2)}/m²")
    elif premissas.ticket_unidade is not None:
        partes_premissas.append(
            f"ticket: R$ {_formatar_milhar(premissas.ticket_unidade)} (preço = ticket ÷ área média)"
        )
    else:
        partes_premissas.append("preço: não informado")

    linha11 = f"*Premissas:* {' · '.join(partes_premissas)}"

    # Linha 12: Fonte GeoSampa
    datas_encontradas: list[str] = []
    marcador = "baixado em "
    for s in rx.sinais:
        if marcador in s.fonte:
            pos = s.fonte.find(marcador) + len(marcador)
            data_val = s.fonte[pos:].strip()
            # Se contiver espaço ou outros delimitadores após a data, pegar primeiro token
            data_val = data_val.split()[0].rstrip("·,;")
            if data_val and data_val not in datas_encontradas:
                datas_encontradas.append(data_val)

    if datas_encontradas:
        data_str = ", ".join(datas_encontradas)
    else:
        data_str = "data não informada"

    linha12 = f"Fonte: GeoSampa (dados de {data_str}) · Raio-X de Terrenos SP"

    linhas = [
        linha1,
        linha2,
        linha3,
        linha4,
        linha5,
        linha6,
        linha7,
        linha8,
        linha9,
        linha10,
        linha11,
        linha12,
    ]

    return "\n".join(linhas)


def _reais(valor: float) -> str:
    sinal = "-" if valor < 0 else ""
    return f"{sinal}R$ {_formatar_milhar(abs(valor))}"


def gerar_simulacao(
    cabecalho: str,
    terreno: str,
    regime: str,
    entrada: EntradaSimulador,
    fs_usado: float | None,
    res: ResultadoSimulador,
) -> str:
    """Resumo da simulação (WhatsApp/Teams): terreno, CA, outorga, DRE, resíduo, alertas e parâmetros."""
    zona = res.zona_efetiva if res.zona_efetiva else "nenhuma (bloqueado)"
    linhas = [
        f"*Simulação:* {cabecalho}",
        f"*Terreno:* {terreno} · zona efetiva {zona}",
        (
            f"*Projeto:* {regime} · CA alvo {_formatar_decimal(res.ca_alvo)} · "
            f"área computável {_formatar_milhar(res.area_computavel_m2)} m² · "
            f"total construída {_formatar_milhar(res.area_total_construida_m2)} m² · "
            f"{_formatar_milhar(res.n_unidades)} unidades"
        ),
        (
            f"*CA:* básico {_formatar_decimal(res.ca_basico)} · máx. da zona {_formatar_decimal(res.ca_max_zona)} · "
            f"produto {_formatar_decimal(res.ca_max_produto)} · teto {_formatar_decimal(res.ca_teto)}"
        ),
        (
            f"*Outorga:* bruta {_reais(res.outorga_bruta)} · descontos {_reais(res.descontos_total)} · "
            f"líquida {_reais(res.outorga_liquida)}"
        ),
    ]
    for linha in res.dre:
        pct = "" if linha.percentual_vgv is None else f" ({_formatar_decimal(linha.percentual_vgv, 1)}% do VGV)"
        linhas.append(f"• {linha.rubrica}: {_reais(linha.valor)}{pct}")
    if res.alertas:
        linhas.append("*Alertas:*")
        linhas.extend(f"• {a}" for a in res.alertas)
    else:
        linhas.append("*Alertas:* nenhum")
    fs = "—" if fs_usado is None else _formatar_decimal(fs_usado)
    custo_terreno = "não informado" if entrada.custo_terreno is None else _reais(entrada.custo_terreno)
    linhas.append(
        f"*Parâmetros:* preço {_reais(entrada.preco_m2)}/m² · área privativa {_formatar_decimal(entrada.area_privativa_media_m2, 1)} m² · "
        f"V {_reais(entrada.v_reais)} · Fp {_formatar_decimal(entrada.fp)} · Fs {fs} · "
        f"via {_formatar_decimal(entrada.via_acesso_largura_m, 1)} m · sem vaga: {'sim' if entrada.opcao_sem_vaga else 'não'} · "
        f"calçada {_formatar_milhar(entrada.doacao_calcada_m2)} m² · fruição {_formatar_milhar(entrada.fruicao_publica_m2)} m² · "
        f"cota: {'sim' if entrada.cota_solidariedade else 'não'} · obra {_reais(entrada.custo_obra_m2)}/m² · "
        f"demolição {_reais(entrada.custo_demolicao_m2)}/m² sobre {_formatar_milhar(entrada.area_construida_existente_m2)} m² · "
        f"margem {_formatar_decimal(entrada.margem_lucro_desejada * 100, 1)}% · terreno {custo_terreno}"
    )
    linhas.append("Raio-X de Terrenos SP · simulador (fatos e contas; quem julga é o analista)")
    return "\n".join(linhas)
