"""Exportação de ficha de viabilidade urbanística em planilha Excel."""

import datetime
from pathlib import Path
import re

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from raiox.dados import data_camada
from raiox.simulador import ResultadoSimulador
from raiox.tipos import Premissas, RaioX

from raiox.__main__ import _formatar_sql


def _sanitizar_sql(sql: str) -> str:
    """Sanitiza o SQL para compor nome de arquivo seguro."""
    return re.sub(r"[^\w.-]", "_", sql.strip())


def _configurar_largura_colunas(ws: openpyxl.worksheet.worksheet.Worksheet) -> None:
    """Ajusta largura das colunas com margem e limites mínimo de 14 e máximo de 60."""
    for col in ws.columns:
        max_len = 0
        primeira_celula = col[0]
        col_letter = get_column_letter(primeira_celula.column)
        for cell in col:
            if cell.value is not None:
                val_str = str(cell.value)
                if len(val_str) > max_len:
                    max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(14, min(60, max_len + 3))


# Estilo das fichas (Raio-X do lote e simulação)
_FONTE_TITULO = Font(name="Calibri", size=13, bold=True, color="1F497D")
_FONTE_SECAO = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
_FILL_SECAO = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
_FONTE_CABECALHO = Font(name="Calibri", size=10, bold=True)
_FILL_CABECALHO = PatternFill(start_color="E9EDF4", end_color="E9EDF4", fill_type="solid")
_FONTE_ROTULO = Font(name="Calibri", size=10, bold=True)
_FONTE_VALOR = Font(name="Calibri", size=10)
_FONTE_ALERTA = Font(name="Calibri", size=10, bold=True, color="B91C1C")


def _salvar(wb: openpyxl.Workbook, pasta: Path, nome_base: str) -> Path:
    """Salva com sufixo _2, _3… se o arquivo estiver aberto (PermissionError) no Excel."""
    caminho = pasta / f"{nome_base}.xlsx"
    idx = 1
    while True:
        try:
            wb.save(caminho)
            return caminho
        except PermissionError:
            idx += 1
            caminho = pasta / f"{nome_base}_{idx}.xlsx"


def gerar(rx: RaioX, premissas: Premissas, pasta: Path) -> Path:
    """Gera ficha de viabilidade urbanística de 1 aba em Excel com openpyxl e retorna o Path do arquivo."""
    pasta.mkdir(parents=True, exist_ok=True)
    hoje = datetime.date.today().isoformat()
    sql_seguro = _sanitizar_sql(rx.lote.sql)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Raio-X"
    ws.views.sheetView[0].showGridLines = True
    ws.freeze_panes = "A2"

    fonte_titulo_principal = _FONTE_TITULO
    fonte_secao = _FONTE_SECAO
    fill_secao = _FILL_SECAO
    fonte_cabecalho_tabela = _FONTE_CABECALHO
    fill_cabecalho_tabela = _FILL_CABECALHO
    fonte_rotulo = _FONTE_ROTULO
    fonte_valor = _FONTE_VALOR

    formato_decimal = "#,##0.00"
    formato_inteiro = "#,##0"

    linha = 1

    # Cabeçalho Principal
    celula_topo = ws.cell(row=linha, column=1, value="FICHA DE VIABILIDADE URBANÍSTICA — RAIO-X DE TERRENOS SP")
    celula_topo.font = fonte_titulo_principal
    linha += 2

    def adicionar_titulo_bloco(titulo: str) -> None:
        nonlocal linha
        ws.cell(row=linha, column=1, value=titulo).font = fonte_secao
        ws.cell(row=linha, column=1).fill = fill_secao
        for c in range(2, 5):
            ws.cell(row=linha, column=c).fill = fill_secao
        linha += 1

    # Bloco 1 — Identificação
    adicionar_titulo_bloco("1. IDENTIFICAÇÃO DO LOTE")

    numero = rx.lote.numero_porta if rx.lote.numero_porta else "s/n"
    endereco_completo = f"{rx.lote.logradouro}, {numero}"

    if rx.lote.setor and rx.lote.quadra and rx.lote.lote:
        sql_formatado = _formatar_sql(rx.lote.setor, rx.lote.quadra, rx.lote.lote, rx.lote.digito)
    else:
        sql_formatado = rx.lote.sql

    if rx.zonas:
        partes_zonas = []
        for z, pct in rx.zonas:
            if pct.is_integer():
                partes_zonas.append(f"{z} ({pct:.0f}%)")
            else:
                pct_str = f"{pct:.1f}%".replace(".", ",")
                partes_zonas.append(f"{z} ({pct_str})")
        zonas_fmt = ", ".join(partes_zonas)
    else:
        zonas_fmt = "Não informada"

    identificacao_dados: list[tuple[str, object, str | None]] = [
        ("Endereço", endereco_completo, None),
        ("SQL", sql_formatado, None),
        ("Área do terreno (m²)", float(rx.lote.area_terreno_m2), formato_decimal),
        ("Área geométrica (m²)", int(round(rx.area.geometrica_m2)), formato_inteiro),
        ("Uso cadastral", rx.lote.uso if rx.lote.uso else "Não informado", None),
        ("Situação cadastral", rx.lote.situacao if rx.lote.situacao else "Não informada", None),
        ("Zoneamento incidente (%)", zonas_fmt, None),
    ]

    for rotulo, valor, fmt in identificacao_dados:
        c1 = ws.cell(row=linha, column=1, value=rotulo)
        c1.font = fonte_rotulo
        c2 = ws.cell(row=linha, column=2, value=valor)
        c2.font = fonte_valor
        if fmt and isinstance(valor, (int, float)):
            c2.number_format = fmt
        linha += 1

    linha += 1

    # Bloco 2 — Premissas
    adicionar_titulo_bloco("2. PREMISSAS ADOTADAS")

    regime_desc = "R2V livre" if premissas.regime == "R2V_LIVRE" else premissas.regime.replace("_", " ")

    if premissas.base_vgv == "referencia_ca":
        base_vgv_desc = "Área de referência do CA (bruta)"
    elif premissas.base_vgv == "liquida":
        base_vgv_desc = "Área líquida (após retiradas)"
    else:
        base_vgv_desc = str(premissas.base_vgv)

    premissas_dados: list[tuple[str, object, str | None]] = [
        ("Regime urbanístico", regime_desc, None),
        ("Cota de solidariedade", "Sim" if premissas.cota_solidariedade else "Não", None),
        ("ZEUP ativada", "Sim" if premissas.zeup_ativada else "Não", None),
        ("ZEM CA 4", "Sim" if premissas.zem_ca4 else "Não", None),
        (
            "Fator privativo",
            float(premissas.fator_privativo) if premissas.fator_privativo is not None else "Não informado",
            formato_decimal if premissas.fator_privativo is not None else None,
        ),
        ("Área média da unidade (m²)", float(premissas.area_media_unidade_m2), formato_decimal),
        (
            "Preço por m²",
            float(premissas.preco_m2) if premissas.preco_m2 is not None else "Não informado",
            formato_decimal if premissas.preco_m2 is not None else None,
        ),
        ("Base do VGV", base_vgv_desc, None),
    ]

    for rotulo, valor, fmt in premissas_dados:
        c1 = ws.cell(row=linha, column=1, value=rotulo)
        c1.font = fonte_rotulo
        c2 = ws.cell(row=linha, column=2, value=valor)
        c2.font = fonte_valor
        if fmt and isinstance(valor, (int, float)):
            c2.number_format = fmt
        linha += 1

    linha += 1

    # Bloco 3 — Retiradas
    adicionar_titulo_bloco("3. RETIRADAS E DEDUÇÕES DE ÁREA")

    c_h1 = ws.cell(row=linha, column=1, value="Camada / Rótulo")
    c_h2 = ws.cell(row=linha, column=2, value="Área deduzida (m²)")
    c_h1.font = fonte_cabecalho_tabela
    c_h2.font = fonte_cabecalho_tabela
    c_h1.fill = fill_cabecalho_tabela
    c_h2.fill = fill_cabecalho_tabela
    linha += 1

    if rx.area.retiradas:
        for r in rx.area.retiradas:
            c1 = ws.cell(row=linha, column=1, value=f"{r.rotulo} ({r.camada})")
            c1.font = fonte_valor
            c2 = ws.cell(row=linha, column=2, value=float(r.area_m2))
            c2.font = fonte_valor
            c2.number_format = formato_decimal
            linha += 1
    else:
        c1 = ws.cell(row=linha, column=1, value="(nenhuma retirada aplicada)")
        c1.font = fonte_valor
        c2 = ws.cell(row=linha, column=2, value=0.0)
        c2.font = fonte_valor
        c2.number_format = formato_decimal
        linha += 1

    c_b1 = ws.cell(row=linha, column=1, value="Área Bruta (m²)")
    c_b1.font = fonte_rotulo
    c_b2 = ws.cell(row=linha, column=2, value=float(rx.area.bruta_m2))
    c_b2.font = fonte_valor
    c_b2.number_format = formato_decimal
    linha += 1

    c_l1 = ws.cell(row=linha, column=1, value="Área Líquida (m²)")
    c_l1.font = fonte_rotulo
    c_l2 = ws.cell(row=linha, column=2, value=float(rx.area.liquida_m2))
    c_l2.font = fonte_valor
    c_l2.number_format = formato_decimal
    linha += 2

    # Bloco 4 — Cadeia de cálculo
    adicionar_titulo_bloco("4. CADEIA DE CÁLCULO E POTENCIAL CONSTRUTIVO")

    ws.cell(row=linha, column=1, value="Passos do cálculo:").font = fonte_rotulo
    linha += 1
    for passo in rx.area_util.passos:
        ws.cell(row=linha, column=1, value=f"• {passo}").font = fonte_valor
        linha += 1

    linha += 1

    metricas_dados: list[tuple[str, object, str | None]] = [
        ("CA máximo / teto", float(rx.area_util.ca_teto), formato_decimal),
        ("Área computável (m²)", float(rx.area_util.a_comp), formato_decimal),
        ("Unidades estimadas", int(rx.area_util.unidades), formato_inteiro),
        (
            "VGV potencial",
            float(rx.area_util.vgv) if rx.area_util.vgv is not None else "Preço não informado",
            formato_decimal if rx.area_util.vgv is not None else None,
        ),
        (
            "Área útil privativa (informativa, m²)",
            float(rx.area_util.a_util) if rx.area_util.a_util is not None else "Fator não informado",
            formato_decimal if rx.area_util.a_util is not None else None,
        ),
        (
            "Unidades mínimas cota-parte",
            int(rx.area_util.unidades_min_cota_parte)
            if rx.area_util.unidades_min_cota_parte is not None
            else "Não se aplica",
            formato_inteiro if rx.area_util.unidades_min_cota_parte is not None else None,
        ),
    ]

    for rotulo, valor, fmt in metricas_dados:
        c1 = ws.cell(row=linha, column=1, value=rotulo)
        c1.font = fonte_rotulo
        c2 = ws.cell(row=linha, column=2, value=valor)
        c2.font = fonte_valor
        if fmt and isinstance(valor, (int, float)):
            c2.number_format = fmt
        linha += 1

    linha += 1

    # Bloco 5 — Farol
    adicionar_titulo_bloco("5. FAROL DE CONDICIONANTES URBANÍSTICAS E AMBIENTAIS")

    farol_colunas = ["Condição / Camada", "Presente", "Medida / Incidência", "Fonte"]
    for col_idx, nome_col in enumerate(farol_colunas, start=1):
        c = ws.cell(row=linha, column=col_idx, value=nome_col)
        c.font = fonte_cabecalho_tabela
        c.fill = fill_cabecalho_tabela
    linha += 1

    if rx.sinais:
        for s in rx.sinais:
            ws.cell(row=linha, column=1, value=s.rotulo).font = fonte_valor
            ws.cell(row=linha, column=2, value="Sim" if s.presente else "Não").font = fonte_valor
            ws.cell(row=linha, column=3, value=s.medida).font = fonte_valor
            ws.cell(row=linha, column=4, value=s.fonte).font = fonte_valor
            linha += 1
    else:
        ws.cell(row=linha, column=1, value="(nenhum sinal registrado)").font = fonte_valor
        linha += 1

    linha += 1

    # Bloco 6 — Estação mais próxima
    adicionar_titulo_bloco("6. TRANSPORTE PÚBLICO E ESTAÇÃO MAIS PRÓXIMA")

    if rx.estacao is not None:
        nome_estacao, dist_m = rx.estacao
        c1 = ws.cell(row=linha, column=1, value="Estação de referência")
        c1.font = fonte_rotulo
        c2 = ws.cell(row=linha, column=2, value=nome_estacao)
        c2.font = fonte_valor
        linha += 1

        c3 = ws.cell(row=linha, column=1, value="Distância (m)")
        c3.font = fonte_rotulo
        c4 = ws.cell(row=linha, column=2, value=float(dist_m))
        c4.font = fonte_valor
        c4.number_format = formato_decimal
        linha += 1
    else:
        c1 = ws.cell(row=linha, column=1, value="Estação de referência")
        c1.font = fonte_rotulo
        c2 = ws.cell(row=linha, column=2, value="Nenhuma estação encontrada em até 5 km.")
        c2.font = fonte_valor
        linha += 1

    linha += 1

    # Bloco 7 — Avisos
    adicionar_titulo_bloco("7. AVISOS E OBSERVAÇÕES")

    if rx.avisos:
        for aviso in rx.avisos:
            ws.cell(row=linha, column=1, value=f"• {aviso}").font = fonte_valor
            linha += 1
    else:
        ws.cell(row=linha, column=1, value="(nenhum)").font = fonte_valor
        linha += 1

    linha += 1

    # Bloco 8 — Fontes e data
    adicionar_titulo_bloco("8. FONTES E REFERÊNCIAS")

    fontes_dados: list[tuple[str, str]] = [
        ("Data de emissão", hoje),
        ("Origem dos dados espaciais", "GeoSampa / SMUL / PMSP"),
        ("Base legal e urbanística", "PDE (Lei 16.050/14), LPUOS (Lei 16.402/16), Revisão PDE (Lei 17.975/23 e Lei 18.177/24)"),
    ]

    for camada in ("lotes", "zoneamento", "inundacao", "estacoes", "patrimonio_historico"):
        dt = data_camada(camada)
        if dt:
            fontes_dados.append((f"Data da camada '{camada}'", dt))

    for rotulo, valor in fontes_dados:
        c1 = ws.cell(row=linha, column=1, value=rotulo)
        c1.font = fonte_rotulo
        c2 = ws.cell(row=linha, column=2, value=valor)
        c2.font = fonte_valor
        linha += 1

    _configurar_largura_colunas(ws)

    return _salvar(wb, pasta, f"RaioX_{sql_seguro}_{hoje}")


def gerar_simulacao(
    identificacao: list[tuple[str, object, str | None]],
    parametros: list[tuple[str, object, str | None]],
    res: ResultadoSimulador,
    pasta: Path,
    nome_terreno: str,
) -> Path:
    """Ficha da simulação em 1 aba: terreno, parâmetros, CA e áreas, outorga, DRE e alertas."""
    pasta.mkdir(parents=True, exist_ok=True)
    hoje = datetime.date.today().isoformat()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Simulação"
    ws.freeze_panes = "A2"
    ws.cell(row=1, column=1, value="SIMULAÇÃO DE VIABILIDADE — RAIO-X DE TERRENOS SP").font = _FONTE_TITULO
    linha = 3

    def titulo(texto: str) -> None:
        nonlocal linha
        for c in range(1, 5):
            ws.cell(row=linha, column=c).fill = _FILL_SECAO
        ws.cell(row=linha, column=1, value=texto).font = _FONTE_SECAO
        linha += 1

    def pares(dados_bloco: list[tuple[str, object, str | None]]) -> None:
        nonlocal linha
        for rotulo, valor, formato in dados_bloco:
            ws.cell(row=linha, column=1, value=rotulo).font = _FONTE_ROTULO
            c = ws.cell(row=linha, column=2, value=valor)
            c.font = _FONTE_VALOR
            if formato and isinstance(valor, (int, float)) and not isinstance(valor, bool):
                c.number_format = formato
            linha += 1
        linha += 1

    if res.bloqueado:
        ws.cell(row=linha, column=1, value="Resultado com bloqueio legal: confira antes de usar os números").font = _FONTE_ALERTA
        linha += 2

    titulo("1. TERRENO SIMULADO")
    pares(identificacao)
    titulo("2. PARÂMETROS DA SIMULAÇÃO")
    pares(parametros)

    titulo("3. LIMITES DE CA E ÁREAS")
    pares([
        ("Zona base", res.zona_base, None),
        ("Zona efetiva", res.zona_efetiva if res.zona_efetiva else "nenhuma (bloqueado)", None),
        ("CA básico", res.ca_basico, "0.00"),
        ("CA máximo da zona", res.ca_max_zona, "0.00"),
        ("CA máximo do produto", res.ca_max_produto, "0.00"),
        ("CA teto", res.ca_teto, "0.00"),
        ("CA alvo", res.ca_alvo, "0.00"),
        ("Área computável (m²)", res.area_computavel_m2, "#,##0.00"),
        ("Área não computável, estimada (m²)", res.area_nc_m2, "#,##0.00"),
        ("Área total construída (m²)", res.area_total_construida_m2, "#,##0.00"),
        ("Nº de unidades", res.n_unidades, "#,##0"),
    ])

    titulo("4. OUTORGA ONEROSA")
    pares([
        ("Outorga bruta (R$)", res.outorga_bruta, "#,##0.00"),
        ("Desconto por doação de calçada (R$)", res.desconto_calcada, "#,##0.00"),
        ("Desconto por fruição pública (R$)", res.desconto_fruicao, "#,##0.00"),
        ("Descontos (total, R$)", res.descontos_total, "#,##0.00"),
        ("Outorga líquida (R$)", res.outorga_liquida, "#,##0.00"),
    ])

    titulo("5. DRE SIMPLIFICADA")
    for col, nome in enumerate(("Rubrica", "Valor (R$)", "% do VGV", "Detalhe"), start=1):
        c = ws.cell(row=linha, column=col, value=nome)
        c.font = _FONTE_CABECALHO
        c.fill = _FILL_CABECALHO
    linha += 1
    for item in res.dre:
        ws.cell(row=linha, column=1, value=item.rubrica).font = _FONTE_ROTULO
        c_valor = ws.cell(row=linha, column=2, value=item.valor)
        c_valor.font = _FONTE_VALOR
        c_valor.number_format = "#,##0.00"
        if item.percentual_vgv is not None:
            c_pct = ws.cell(row=linha, column=3, value=item.percentual_vgv / 100.0)
            c_pct.font = _FONTE_VALOR
            c_pct.number_format = "0.00%"
        ws.cell(row=linha, column=4, value=item.detalhe).font = _FONTE_VALOR
        linha += 1
    linha += 1

    titulo("6. ALERTAS DO MOTOR")
    for alerta in res.alertas or ["(nenhum)"]:
        ws.cell(row=linha, column=1, value=f"• {alerta}").font = _FONTE_VALOR
        linha += 1
    linha += 1

    titulo("7. FONTES")
    pares([
        ("Data de emissão", hoje, None),
        ("Motor", "ca_engine + uso_porte (congelados do prospeccao-marechal-tito) + DRE do simulador antigo", None),
        ("Base legal", "PDE (Lei 16.050/14), LPUOS (Lei 16.402/16), Lei 18.081/24, Dec. 63.728", None),
    ])

    _configurar_largura_colunas(ws)
    return _salvar(wb, pasta, f"Simulacao_{_sanitizar_sql(nome_terreno)}_{hoje}")
