"""Aba Simulador: outorga onerosa, resíduo do terreno e DRE (motor em `raiox/simulador.py`).

O estado da aba é o terreno escolhido (um lote, ou uma dupla/trinca do Prospectar) e a
última simulação. O terreno vem do Raio-X (`raio_x.consultar_lote`), com as retiradas das
premissas atuais, como no painel do Raio-X do lote. As premissas comuns só dão os valores
iniciais do formulário; a simulação usa exatamente os parâmetros que a tela mandar.

Composição (dupla/trinca), como a view "gleba" do app antigo (prospeccao-marechal-tito/app.py:1180-1197):
área = soma das áreas dos lotes, zona = a do primeiro lote, CA inicial = Σ área computável ÷ Σ área.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import math
import threading
from typing import Any, Mapping

from raiox import dados, oportunidades, raio_x
from raiox.abas.comum import Comum, ErroUsuario
from raiox.area_util import preco_m2_efetivo
from raiox.busca import Achado
from raiox.saidas import excel, resumo
from raiox.simulador import EntradaSimulador, ResultadoSimulador, simular
from raiox.tipos import Candidatos, LoteCadastro, NaoEncontrado, Premissas, RaioX
from raiox.urbanismo.ca_engine import fs_tipologia

MAX_LOTES = 3  # lote, dupla ou trinca (o Prospectar não monta composições de 4)

# Rótulos dos parâmetros (os mesmos da tela, do resumo e do Excel).
ROTULOS: dict[str, str] = {
    "area_liquida_m2": "Área líquida do lote (m²)",
    "regime": "Regime",
    "ca_alvo": "CA alvo",
    "area_computavel_alvo_m2": "Área computável alvo (m²)",
    "area_privativa_media_m2": "Área privativa média (m²/UH)",
    "n_unidades": "Nº de unidades",
    "preco_m2": "Preço por m² (R$)",
    "via_acesso_largura_m": "Largura da via de acesso (m)",
    "v_reais": "Valor do m² (V), Quadro 14 (R$)",
    "fp": "Fator de planejamento (Fp)",
    "fs": "Fator social (Fs)",
    "opcao_sem_vaga": "Opção sem vaga (art. 62)",
    "doacao_calcada_m2": "Doação de calçada (m²)",
    "fruicao_publica_m2": "Fruição pública (m²)",
    "cota_solidariedade": "Cota de solidariedade",
    "area_construida_existente_m2": "Área construída existente (m²)",
    "custo_obra_m2": "Custo de obra (R$/m²)",
    "custo_demolicao_m2": "Custo de demolição (R$/m²)",
    "margem_lucro_desejada": "Margem de lucro desejada",
    "custo_terreno": "Custo do terreno (R$)",
}

_NUMEROS_OBRIGATORIOS = (
    "area_liquida_m2",
    "area_privativa_media_m2",
    "preco_m2",
    "via_acesso_largura_m",
    "v_reais",
    "fp",
    "doacao_calcada_m2",
    "fruicao_publica_m2",
    "area_construida_existente_m2",
    "custo_obra_m2",
    "custo_demolicao_m2",
    "margem_lucro_desejada",
)
_NUMEROS_OPCIONAIS = ("ca_alvo", "area_computavel_alvo_m2", "fs", "custo_terreno")
_BOOLEANOS = ("opcao_sem_vaga", "cota_solidariedade")
_CAMPOS = frozenset(ROTULOS)
_REGIMES = {"R2V_LIVRE": "R2V livre", "EHMP": "EHMP", "EHIS": "EHIS"}

# Padrões do motor (EntradaSimulador documenta a linha de origem de cada um no app antigo).
_PADRAO: dict[str, Any] = {f.name: f.default for f in fields(EntradaSimulador)}


@dataclass(frozen=True)
class _Terreno:
    """O terreno simulado: um lote ou uma composição, com o Raio-X de cada lote."""

    lotes: tuple[LoteCadastro, ...]
    rxs: tuple[RaioX, ...]
    avisos_busca: tuple[str, ...]
    premissas: Premissas


def _numero(campo: str, valor: Any) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        raise ErroUsuario(f"{ROTULOS[campo]}: valor inválido ({valor!r}). Use só números.")
    return float(valor)


def entrada_de_dict(parametros: Mapping[str, Any], zona_base: str, sql: str) -> EntradaSimulador:
    """Converte os parâmetros da tela em EntradaSimulador; todo campo precisa vir (None = vazio)."""
    if not isinstance(parametros, Mapping):
        raise ErroUsuario("Os parâmetros da simulação precisam vir como um conjunto de campos.")
    desconhecidos = sorted(set(parametros) - _CAMPOS)
    if desconhecidos:
        raise ErroUsuario(f"Parâmetro desconhecido: {desconhecidos[0]!r}.")
    faltando = [c for c in ROTULOS if c not in parametros]
    if faltando:
        raise ErroUsuario(f"Falta o parâmetro {ROTULOS[faltando[0]]!r}.")

    kwargs: dict[str, Any] = {"zona_base": zona_base, "sql": sql}
    for campo in _NUMEROS_OBRIGATORIOS:
        valor = parametros[campo]
        if valor is None:
            raise ErroUsuario(f"Preencha {ROTULOS[campo]}.")
        kwargs[campo] = _numero(campo, valor)
    for campo in _NUMEROS_OPCIONAIS:
        valor = parametros[campo]
        kwargs[campo] = None if valor is None else _numero(campo, valor)
    for campo in _BOOLEANOS:
        valor = parametros[campo]
        if not isinstance(valor, bool):
            raise ErroUsuario(f"{ROTULOS[campo]}: marque sim ou não.")
        kwargs[campo] = valor

    regime = parametros["regime"]
    if not isinstance(regime, str) or regime not in _REGIMES:
        raise ErroUsuario(f"Regime inválido: {regime!r}. Opções: R2V livre, EHMP, EHIS.")
    kwargs["regime"] = regime

    n_unid = parametros["n_unidades"]
    if n_unid is None:
        kwargs["n_unidades"] = None
    else:
        numero = _numero("n_unidades", n_unid)
        if not numero.is_integer():
            raise ErroUsuario(f"{ROTULOS['n_unidades']}: use um número inteiro.")
        kwargs["n_unidades"] = int(numero)

    return EntradaSimulador(**kwargs)


def _fs_usado(e: EntradaSimulador) -> float | None:
    """O Fs que o motor usou (para mostrar): EHIS 0; EHMP o informado ou o do Decreto; R2V o informado."""
    if e.regime == "EHIS":
        return fs_tipologia("HIS")
    if e.regime == "EHMP" and e.fs is None:
        # Só é chamada depois de simular() aceitar a entrada (área privativa de EHMP até 70 m²).
        return fs_tipologia("HMP", e.area_privativa_media_m2)
    return e.fs


def _m2(valor: float) -> str:
    return f"{round(valor):,}".replace(",", ".") + " m²"


class AbaSimulador:
    """Estado e ações da aba Simulador."""

    nome = "simulador"

    def __init__(self, comum: Comum) -> None:
        self.trava = threading.Lock()
        self._comum = comum
        self._terreno: _Terreno | None = None
        self._ultima: tuple[EntradaSimulador, ResultadoSimulador] | None = None

    # --- Terreno ---

    def _abrir(self, lotes: list[LoteCadastro], avisos_busca: tuple[str, ...], p: Premissas) -> dict[str, Any]:
        rxs = tuple(raio_x.consultar_lote(l, p, avisos_busca=avisos_busca) for l in lotes)
        self._terreno = _Terreno(lotes=tuple(lotes), rxs=rxs, avisos_busca=avisos_busca, premissas=p)
        self._ultima = None
        return {"tipo": "Terreno", "terreno": self._descrever(self._terreno)}

    def _fechar(self, resultado: Candidatos | NaoEncontrado) -> dict[str, Any]:
        self._terreno = None
        self._ultima = None
        return {"tipo": type(resultado).__name__, "resultado": asdict(resultado)}

    @staticmethod
    def _zona_base(t: _Terreno) -> str:
        return t.rxs[0].zonas[0][0]

    @staticmethod
    def _sql(t: _Terreno) -> str:
        return " + ".join(oportunidades.sql_formatado(l) for l in t.lotes)

    def _descrever(self, t: _Terreno) -> dict[str, Any]:
        """Cabeçalho do terreno + valores iniciais do formulário (com a origem de cada um)."""
        p = t.premissas
        bruta = sum(rx.area.bruta_m2 for rx in t.rxs)
        liquida = sum(rx.area.liquida_m2 for rx in t.rxs)
        a_ref = sum(rx.area_util.a_ref_m2 for rx in t.rxs)
        a_comp = sum(rx.area_util.a_comp for rx in t.rxs)
        ca_lote = round(a_comp / a_ref, 2) if a_ref > 0 else 0.0
        zonas = [rx.zonas[0][0] for rx in t.rxs]
        composicao = len(t.lotes) > 1

        avisos: list[str] = list(t.avisos_busca)
        if composicao:
            avisos.append(
                f"Composição de {len(t.lotes)} lotes simulada como um terreno só (como o app antigo): "
                f"área = soma das áreas, zona = a do primeiro lote ({zonas[0]}), "
                "CA inicial = soma das áreas computáveis ÷ soma das áreas."
            )
            if len(set(zonas)) > 1:
                avisos.append(
                    f"Os lotes estão em zonas diferentes ({', '.join(zonas)}): o simulador usa {zonas[0]}. "
                    "Para comparar, simule cada lote separado."
                )
        for rx in t.rxs:
            for aviso in rx.avisos:
                if aviso.startswith("Lote em ") and aviso not in avisos:  # lote em 2+ zonas
                    avisos.append(aviso)
        ignoradas = [
            nome
            for nome, marcada in (
                ("ZEUP ativada", p.zeup_ativada),
                ("ZEM com CA 4", p.zem_ca4),
                ("vila", p.vila),
            )
            if marcada
        ]
        if ignoradas:
            avisos.append(
                f"Premissa marcada que o simulador não aplica: {', '.join(ignoradas)} "
                "(o motor recebe só a zona base e a via de acesso, como o antigo)."
            )

        existentes = [l.area_construida_m2 for l in t.lotes]
        sem_construida = [
            oportunidades.sql_formatado(l) for l in t.lotes if l.area_construida_m2 is None
        ]
        if sem_construida:
            avisos.append(
                f"Cadastro sem área construída para {', '.join(sem_construida)}: entra 0 m² na demolição."
            )
        area_existente = float(sum(a for a in existentes if a is not None))

        retiradas = [
            {"sql": oportunidades.sql_formatado(rx.lote), "rotulo": r.rotulo, "area_m2": r.area_m2}
            for rx in t.rxs
            for r in rx.area.retiradas
        ]

        via = raio_x.VIA_ESTREITA_M if p.acesso_via_estreita else _PADRAO["via_acesso_largura_m"]
        if p.acesso_via_estreita:
            avisos.append(
                "Premissa “acesso por via de até 10 m” marcada: a largura da via começa em 10 m."
            )
        if ca_lote <= 0:
            avisos.append("O Raio-X deu CA 0 para este terreno (zona sem parâmetro): informe o CA alvo.")
        preco = preco_m2_efetivo(p)

        iniciais: dict[str, Any] = {
            "area_liquida_m2": liquida,
            "regime": p.regime,
            "ca_alvo": ca_lote if ca_lote > 0 else None,
            "area_computavel_alvo_m2": None,
            "area_privativa_media_m2": p.area_media_unidade_m2,
            "n_unidades": None,
            "preco_m2": preco,
            "via_acesso_largura_m": via,
            "v_reais": _PADRAO["v_reais"],
            "fp": _PADRAO["fp"],
            "fs": None,
            "opcao_sem_vaga": _PADRAO["opcao_sem_vaga"],
            "doacao_calcada_m2": _PADRAO["doacao_calcada_m2"],
            "fruicao_publica_m2": _PADRAO["fruicao_publica_m2"],
            "cota_solidariedade": p.cota_solidariedade,
            "area_construida_existente_m2": area_existente,
            "custo_obra_m2": _PADRAO["custo_obra_m2"],
            "custo_demolicao_m2": _PADRAO["custo_demolicao_m2"],
            "margem_lucro_desejada": _PADRAO["margem_lucro_desejada"],
            "custo_terreno": None,
        }
        return {
            "ids": [l.cd_identificador for l in t.lotes],
            "sql": self._sql(t),
            "enderecos": [oportunidades.endereco(l) for l in t.lotes],
            "tipo": {1: "lote", 2: "dupla", 3: "trinca"}[len(t.lotes)],
            "area_bruta_m2": bruta,
            "area_liquida_m2": liquida,
            "retiradas": retiradas,
            "zona_base": zonas[0],
            "zonas": zonas,
            "ca_lote": ca_lote,
            "avisos": avisos,
            "valores_iniciais": iniciais,
            "origem_iniciais": {
                "area_liquida_m2": "Raio-X (área líquida, com as retiradas marcadas)",
                "ca_alvo": "CA do Raio-X (o mesmo do mapa e da tabela)",
                "preco_m2": "⚙ Premissas",
                "area_privativa_media_m2": "⚙ Premissas (área média da unidade)",
                "regime": "⚙ Premissas",
                "cota_solidariedade": "⚙ Premissas",
                "area_construida_existente_m2": "cadastro (soma dos lotes)" if composicao else "cadastro",
                "demais": "padrões do simulador antigo (prospeccao-marechal-tito/app.py)",
            },
        }

    def _exigir_terreno(self, acao: str) -> _Terreno:
        if self._terreno is None:
            raise ErroUsuario(
                f"Escolha um terreno antes de {acao}: busque por SQL, endereço ou identificador, "
                "ou use “Simular” no Raio-X do lote ou no detalhe do Prospectar."
            )
        return self._terreno

    # --- Ações ---

    def buscar(self, texto: str, p: Premissas) -> dict[str, Any]:
        """Acha o terreno pela mesma busca do Raio-X (SQL, endereço ou identificador)."""
        if not isinstance(texto, str) or not texto.strip():
            raise ErroUsuario("Digite um SQL, endereço ou identificador.")
        achado = raio_x.localizar(texto.strip())
        if isinstance(achado, Achado):
            return self._abrir([achado.lote], tuple(achado.avisos), p)
        return self._fechar(achado)

    def abrir(self, ids: Any, p: Premissas) -> dict[str, Any]:
        """Abre um lote ou uma composição (dupla/trinca) pelos identificadores cadastrais."""
        if (
            not isinstance(ids, (list, tuple))
            or not 1 <= len(ids) <= MAX_LOTES
            or any(not isinstance(i, str) or not i.strip() for i in ids)
        ):
            raise ErroUsuario("Informe de 1 a 3 identificadores de lote para simular.")
        limpos = [i.strip() for i in ids]
        if len(set(limpos)) != len(limpos):
            raise ErroUsuario("O mesmo lote apareceu duas vezes na composição.")
        lotes: list[LoteCadastro] = []
        for ident in limpos:
            lote = dados.lote_por_id(ident)
            if lote is None:
                raise ErroUsuario(f"Identificador {ident} não encontrado na base de lotes.")
            lotes.append(lote)
        return self._abrir(lotes, (), p)

    def simular(self, parametros: Mapping[str, Any]) -> dict[str, Any]:
        """Roda o motor com os parâmetros da tela; erro de validação vira a mensagem pt-BR do motor."""
        t = self._exigir_terreno("simular")
        entrada = entrada_de_dict(parametros, self._zona_base(t), self._sql(t))
        try:
            res = simular(entrada)
        except ValueError as exc:
            raise ErroUsuario(str(exc)) from exc
        self._ultima = (entrada, res)
        return {
            "terreno": self._descrever(t),
            "entrada": asdict(entrada),
            "fs_usado": _fs_usado(entrada),
            "resultado": asdict(res),
        }

    def simular_terreno(self, ids: Any, parametros: Mapping[str, Any], p: Premissas) -> dict[str, Any]:
        """Ponto único para outras telas: abre o terreno destes ids e simula com os parâmetros dados."""
        self.abrir(ids, p)
        return self.simular(parametros)

    def _exigir_simulacao(self, acao: str) -> tuple[_Terreno, EntradaSimulador, ResultadoSimulador]:
        t = self._exigir_terreno(acao)
        if self._ultima is None:
            raise ErroUsuario(f"Clique em “Simular” antes de {acao}.")
        return t, self._ultima[0], self._ultima[1]

    def _identificacao(self, t: _Terreno) -> list[tuple[str, object, str | None]]:
        desc = self._descrever(t)
        linhas: list[tuple[str, object, str | None]] = [
            ("Terreno", {"lote": "Lote", "dupla": "Dupla", "trinca": "Trinca"}[desc["tipo"]], None),
            ("SQL", desc["sql"], None),
            ("Endereço", " + ".join(desc["enderecos"]), None),
            ("Área do cadastro (m²)", float(desc["area_bruta_m2"]), "#,##0.00"),
            ("Área líquida do Raio-X (m²)", float(desc["area_liquida_m2"]), "#,##0.00"),
            ("Zona base", desc["zona_base"], None),
        ]
        for r in desc["retiradas"]:
            linhas.append((f"Retirada: {r['rotulo']} ({r['sql']})", float(r["area_m2"]), "#,##0.00"))
        return linhas

    @staticmethod
    def _parametros(e: EntradaSimulador, fs_usado: float | None) -> list[tuple[str, object, str | None]]:
        sim_nao = {True: "Sim", False: "Não"}
        return [
            (ROTULOS["area_liquida_m2"], e.area_liquida_m2, "#,##0.00"),
            (ROTULOS["regime"], _REGIMES[e.regime], None),
            (ROTULOS["ca_alvo"], e.ca_alvo if e.ca_alvo is not None else "pela área computável alvo", "0.00"),
            (
                ROTULOS["area_computavel_alvo_m2"],
                e.area_computavel_alvo_m2 if e.area_computavel_alvo_m2 is not None else "pelo CA alvo",
                "#,##0.00",
            ),
            (ROTULOS["area_privativa_media_m2"], e.area_privativa_media_m2, "#,##0.00"),
            (ROTULOS["n_unidades"], e.n_unidades if e.n_unidades is not None else "automático", "#,##0"),
            (ROTULOS["preco_m2"], e.preco_m2, "#,##0.00"),
            (ROTULOS["via_acesso_largura_m"], e.via_acesso_largura_m, "#,##0.00"),
            (ROTULOS["v_reais"], e.v_reais, "#,##0.00"),
            (ROTULOS["fp"], e.fp, "0.00"),
            (ROTULOS["fs"], fs_usado if fs_usado is not None else "—", "0.00"),
            (ROTULOS["opcao_sem_vaga"], sim_nao[e.opcao_sem_vaga], None),
            (ROTULOS["doacao_calcada_m2"], e.doacao_calcada_m2, "#,##0.00"),
            (ROTULOS["fruicao_publica_m2"], e.fruicao_publica_m2, "#,##0.00"),
            (ROTULOS["cota_solidariedade"], sim_nao[e.cota_solidariedade], None),
            (ROTULOS["area_construida_existente_m2"], e.area_construida_existente_m2, "#,##0.00"),
            (ROTULOS["custo_obra_m2"], e.custo_obra_m2, "#,##0.00"),
            (ROTULOS["custo_demolicao_m2"], e.custo_demolicao_m2, "#,##0.00"),
            (ROTULOS["margem_lucro_desejada"], e.margem_lucro_desejada, "0.0%"),
            (ROTULOS["custo_terreno"], e.custo_terreno if e.custo_terreno is not None else "não informado", "#,##0.00"),
        ]

    def copiar_resumo(self) -> dict[str, Any]:
        t, e, res = self._exigir_simulacao("copiar o resumo")
        desc = self._descrever(t)
        cabecalho = f"{desc['sql']} · {' + '.join(desc['enderecos'])}"
        terreno = f"área líquida {_m2(e.area_liquida_m2)} · zona base {desc['zona_base']}"
        texto = resumo.gerar_simulacao(cabecalho, terreno, _REGIMES[e.regime], e, _fs_usado(e), res)
        return {"texto": texto}

    def exportar_excel(self) -> dict[str, Any]:
        t, e, res = self._exigir_simulacao("exportar o Excel")
        caminho = excel.gerar_simulacao(
            self._identificacao(t),
            self._parametros(e, _fs_usado(e)),
            res,
            self._comum.pasta_saida(),
            "_".join(l.sql or l.cd_identificador for l in t.lotes),
        )
        return {"caminho": str(caminho)}
