// Parte comum às abas: ponte com o Python, formatação pt-BR, premissas, TERRENO EM FOCO
// (a seleção compartilhada), mapa-base, registro das abas (cada uma inicia sozinha e mostra os
// próprios erros) e autoteste. Só a seleção é compartilhada: o estado de cada aba é dela.
(function () {
  "use strict";

  const ESRI_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
  const ZOOM_MIN_CAMADAS = 14;
  const CENTRO_SP = [-23.5505, -46.6333];
  const COR = { lote: "#2463c9", dupla: "#1f9d55", trinca: "#d4a017", escondido: "#9aa3a0", foco: "#d9480f", focoSuave: "#fde7dc" };

  const CATEGORIA_CAMADA = {
    agua: "💧 Água",
    inundacao: "💧 Água",
    app: "💧 Água",
    melhoramento: "🛣️ Viário",
    alta_tensao: "⚡ Energia",
    alta_tensao_sub: "⚡ Energia",
    duto: "🛢️ Duto",
    contaminada: "⚠️ Ambiental",
    risco: "⚠️ Ambiental",
    tombamento: "🏛️ Restrição",
    area_publica: "🏛️ Restrição",
    favela: "🏛️ Restrição",
    estacoes: "🚇 Transporte",
    zoneamento: "📐 Base",
    lotes: "📐 Base"
  };

  const fmt = {
    inteiro: new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 }),
    ca: new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    moeda: new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 0, maximumFractionDigits: 0 }),
    decimal: new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 4 }),
    pct: new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 }),
    pct1: new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
    km2: new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  };

  const ESTILOS_CAMADAS = {
    lotes: { color: "#f1f5f9", weight: 1, fillOpacity: 0 },
    zoneamento: { color: "#a78bfa", weight: 1.5, fillColor: "#a78bfa", fillOpacity: 0.08 },
    alta_tensao: { color: "#f97316", weight: 3 },
    alta_tensao_sub: { color: "#fb923c", weight: 3, dashArray: "6 4" },
    duto: { color: "#d946ef", weight: 3 },
    contaminada: { color: "#84cc16", weight: 2, fillColor: "#84cc16", fillOpacity: 0.2 },
    risco: { color: "#b45309", weight: 2, fillColor: "#b45309", fillOpacity: 0.2 },
    tombamento: { color: "#8b5cf6", weight: 2, fillColor: "#8b5cf6", fillOpacity: 0.15 },
    area_publica: { color: "#22c55e", weight: 2, fillColor: "#22c55e", fillOpacity: 0.15 },
    favela: { color: "#ef4444", weight: 2, fillColor: "#ef4444", fillOpacity: 0.15 },
    agua: { color: "#0284c7", weight: 2, fillColor: "#38bdf8", fillOpacity: 0.45 },
    inundacao: { color: "#38bdf8", weight: 0.6, opacity: 0.6, fillColor: "#38bdf8", fillOpacity: 0.18 },
    app: { color: "#14b8a6", weight: 2, fillColor: "#14b8a6", fillOpacity: 0.15 },
    melhoramento: { color: "#f43f5e", weight: 2, fillColor: "#f43f5e", fillOpacity: 0.2 },
    padrao: { color: "#94a3b8", weight: 1.5, fillOpacity: 0.1 }
  };

  // --- Utilidades de DOM e texto ---
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function mensagemDeErro(e) {
    return e && e.message ? e.message : String(e);
  }

  function formatarSQL(setor, quadra, lote, digito, sqlReserva) {
    if (setor && quadra && lote) {
      let s = setor + "." + quadra + "." + lote;
      if (digito != null && String(digito).trim() !== "") s += "-" + String(digito).trim();
      return s;
    }
    return sqlReserva || "—";
  }

  // Lê número digitado no padrão pt-BR ("1.500", "0,75", "R$ 7.000"); vazio = null; inválido = NaN.
  function parsearNumeroDigitado(texto) {
    if (texto == null) return null;
    let s = String(texto).replace(/R\$/g, "").replace(/m²/g, "").replace(/%/g, "").trim();
    if (s === "") return null;
    if (s.includes(",")) s = s.replace(/\./g, "").replace(",", ".");
    else if (/^\d{1,3}(\.\d{3})+$/.test(s)) s = s.replace(/\./g, "");
    const n = Number(s);
    return Number.isFinite(n) ? n : NaN;
  }

  // Mensagem de um painel: tipo "ok" | "erro" | "aviso".
  function mostrarMsg(elemento, texto, tipo) {
    elemento.textContent = texto;
    elemento.className = "msg" + (tipo === "erro" ? " erro" : tipo === "aviso" ? " aviso" : "");
  }

  function esconderMsg(elemento) {
    elemento.textContent = "";
    elemento.className = "msg hidden";
  }

  function carregandoLinha(texto) {
    const d = el("div", "carregando-linha");
    d.appendChild(el("span", "giro"));
    d.appendChild(el("span", null, texto));
    return d;
  }

  // Lista de opções (candidatos da busca): cada uma chama `aoEscolher(op)`.
  function listaOpcoes(ctx, titulo, opcoes, aoEscolher) {
    const caixa = el("div", "bloco");
    caixa.appendChild(el("p", "nota", titulo));
    const lista = el("div", "opcoes");
    for (const op of opcoes) {
      const b = el("button", "opcao");
      b.type = "button";
      b.appendChild(el("div", null, (op.logradouro || "") + (op.numero_porta ? ", " + op.numero_porta : "")));
      b.appendChild(el("div", "sub-op", "SQL " + formatarSQL(op.setor, op.quadra, op.lote, op.digito, op.sql) +
        " · " + fmt.inteiro.format(op.area_terreno_m2) + " m² · " + (op.uso || "uso não informado")));
      b.addEventListener("click", ctx.proteger(() => aoEscolher(op)));
      lista.appendChild(b);
    }
    caixa.appendChild(lista);
    return caixa;
  }

  // --- Ponte com o Python: toda chamada devolve {ok, ...} ou {ok: false, erro, aba} ---
  async function chamar(metodo, ...args) {
    if (!window.pywebview || !window.pywebview.api || typeof window.pywebview.api[metodo] !== "function") {
      return { ok: false, erro: "A ponte com o Python ainda não está pronta. Tente de novo em instantes." };
    }
    acompanharChamada(+1);
    try {
      const r = await window.pywebview.api[metodo](...args);
      if (r && typeof r === "object" && "ok" in r) return r;
      return { ok: false, erro: "Resposta inesperada do Python em " + metodo + "." };
    } catch (e) {
      return { ok: false, erro: "Erro ao chamar " + metodo + ": " + mensagemDeErro(e) };
    } finally {
      acompanharChamada(-1);
    }
  }

  // --- Download de dados do GeoSampa (programa instalado): enquanto há chamada esperando, consulta o
  // andamento e mostra uma faixa. Fora do modo instalado o Python nunca avisa e a faixa não aparece.
  let chamadasPendentes = 0;
  let timerDownload = null;

  function acompanharChamada(delta) {
    chamadasPendentes += delta;
    if (chamadasPendentes > 0 && !timerDownload) {
      timerDownload = setInterval(consultarDownload, 900);
    } else if (chamadasPendentes <= 0 && timerDownload) {
      clearInterval(timerDownload);
      timerDownload = null;
      const f = document.getElementById("faixa-download");
      if (f) f.hidden = true;
    }
  }

  async function consultarDownload() {
    const f = document.getElementById("faixa-download");
    if (!f || !window.pywebview || !window.pywebview.api || !window.pywebview.api.estado_download) return;
    try {
      const r = await window.pywebview.api.estado_download();
      if (!r || !r.ativo) { f.hidden = true; return; }
      const o = r.rotulo === "lotes" ? "lotes" : "camada " + r.rotulo;
      f.textContent = "Baixando dados do GeoSampa (só na primeira vez nesta área): " + o +
        " · parte " + r.n + " de " + r.total + (r.qtd ? " · " + fmt.inteiro.format(r.qtd) + " itens" : "") + ". Aguarde…";
      f.hidden = false;
    } catch (e) { /* a faixa é só um aviso */ }
  }

  function mostrarFaixa(texto) {
    const f = document.getElementById("faixa-download");
    if (!f) return;
    f.textContent = texto;
    f.hidden = false;
    setTimeout(() => { if (chamadasPendentes <= 0) f.hidden = true; }, 7000);
  }

  // Aviso (nunca automático): dados baixados há mais de 30 dias.
  async function avisoDadosAntigos() {
    const faixa = document.getElementById("faixa-atualizar");
    if (!faixa) return;
    const r = await chamar("dados_estado");
    if (!r.ok || !r.instalado || !r.antigos) return;
    document.getElementById("faixa-atualizar-texto").textContent =
      r.antigos + " de " + r.total + " blocos de dados do GeoSampa têm mais de " + r.dias_limite +
      " dias (o mais velho, " + r.mais_antigo_dias + "). Quer atualizar?";
    faixa.hidden = false;
    document.getElementById("faixa-atualizar-depois").onclick = () => { faixa.hidden = true; };
    document.getElementById("faixa-atualizar-sim").onclick = async () => {
      faixa.hidden = true;
      const res = await chamar("dados_atualizar");
      mostrarFaixa(res.ok ? "Dados atualizados (" + res.atualizados + " blocos). Refaça a consulta para usar os novos." : "Não consegui atualizar: " + res.erro);
    };
  }

  // --- Registro das abas ---
  const definicoes = [];              // { nome, rotulo, iniciar }
  const abas = new Map();             // nome -> { ctx, api, erroInicio }
  let abaAtiva = null;

  function registrarAba(nome, rotulo, iniciar) {
    definicoes.push({ nome, rotulo, iniciar });
  }

  function criarContexto(nome, rotulo) {
    const raiz = document.getElementById("aba-" + nome);
    const faixa = raiz.querySelector("[data-erro-aba]");
    const textoFaixa = faixa.querySelector(".aba-erro-texto");
    faixa.querySelector(".aba-erro-fechar").addEventListener("click", () => faixa.classList.add("hidden"));

    const ctx = {
      nome,
      raiz,
      ativa: () => abaAtiva === nome,
      falha(e) {
        textoFaixa.textContent = "Erro na aba " + rotulo + ": " + mensagemDeErro(e) +
          ". As outras abas continuam funcionando.";
        faixa.classList.remove("hidden");
        console.error("[aba " + nome + "]", e);
      },
      // Embrulha um tratador de evento: erro (síncrono ou de promessa) vira faixa nesta aba.
      proteger(fn) {
        return function (...args) {
          try {
            const r = fn.apply(this, args);
            if (r && typeof r.then === "function") r.catch((e) => ctx.falha(e));
            return r;
          } catch (e) {
            ctx.falha(e);
            return undefined;
          }
        };
      },
      $(id) {
        const achado = document.getElementById(id);
        if (!achado) throw new Error("elemento #" + id + " não existe na tela");
        return achado;
      }
    };
    return ctx;
  }

  function chamarGancho(nome, gancho, ...args) {
    const aba = abas.get(nome);
    if (!aba || !aba.api || typeof aba.api[gancho] !== "function") return undefined;
    return aba.ctx.proteger(aba.api[gancho])(...args);
  }

  // Pede algo a outra aba (ex.: o foco pede "Ver entorno" ao Prospectar). Erro fica na aba de destino.
  function pedir(nomeDestino, metodo, ...args) {
    const aba = abas.get(nomeDestino);
    if (!aba || !aba.api) {
      throw new Error("a aba " + nomeDestino + " não iniciou" + (aba && aba.erroInicio ? " (" + aba.erroInicio + ")" : ""));
    }
    ativarAba(nomeDestino);
    return chamarGancho(nomeDestino, metodo, ...args);
  }

  function ativarAba(nome) {
    if (!abas.has(nome)) return undefined;
    abaAtiva = nome;
    document.querySelectorAll(".aba-botao").forEach((b) => {
      b.setAttribute("aria-selected", b.dataset.aba === nome ? "true" : "false");
    });
    document.querySelectorAll("main#abas > .aba").forEach((s) => {
      s.classList.toggle("hidden", s.id !== "aba-" + nome);
    });
    return chamarGancho(nome, "aoAtivar");
  }

  function iniciarAbas() {
    for (const def of definicoes) {
      const ctx = criarContexto(def.nome, def.rotulo);
      const registro = { ctx, api: null, erroInicio: null };
      abas.set(def.nome, registro);
      try {
        registro.api = def.iniciar(ctx) || {};
      } catch (e) {
        registro.erroInicio = mensagemDeErro(e);
        ctx.falha(e);
      }
    }
    // Aba cujo script nem carregou (erro de sintaxe): mostra a faixa nela e deixa o botão ativável.
    document.querySelectorAll("main#abas > .aba").forEach((secao) => {
      const nome = secao.dataset.aba;
      if (abas.has(nome)) return;
      const ctx = criarContexto(nome, nome);
      abas.set(nome, { ctx, api: null, erroInicio: "o script da aba não carregou" });
      ctx.falha(new Error("o script da aba não carregou"));
    });
    document.querySelectorAll(".aba-botao").forEach((b) => {
      b.addEventListener("click", () => ativarAba(b.dataset.aba));
    });
    ativarAba("prospectar");
  }

  // --- Premissas (uma só para todas as abas; guardadas em disco pelo Python) ---
  const premissasForm = {};
  let premissas = null;   // null até a ponte responder ler_premissas

  function camposPremissas() {
    const ids = {
      regime: "prem-regime", multiplicador: "prem-multiplicador", cota: "prem-cota-solidariedade",
      zeup: "prem-zeup-ativada", zem: "prem-zem-ca4", via: "prem-acesso-via-estreita", vila: "prem-vila",
      fator: "prem-fator-privativo", fatorErro: "prem-fator-erro",
      preco: "prem-preco-m2", precoErro: "prem-preco-erro",
      ticket: "prem-ticket-unidade", ticketErro: "prem-ticket-erro",
      area: "prem-area-media", areaErro: "prem-area-erro",
      divergencia: "prem-divergencia", divergenciaErro: "prem-divergencia-erro",
      status: "premissas-status", gaveta: "gaveta-premissas", botao: "btn-premissas",
      rapRegime: "rap-regime", rapPreco: "rap-preco", rapMeta: "rap-meta", btnTema: "btn-tema"
    };
    for (const [chave, id] of Object.entries(ids)) {
      const e = document.getElementById(id);
      if (!e) throw new Error("campo #" + id + " das premissas não existe na tela");
      premissasForm[chave] = e;
    }
  }

  function sincronizarFormularioPremissas() {
    if (!premissas) return;
    const f = premissasForm;
    f.regime.value = premissas.regime;
    f.multiplicador.checked = Boolean(premissas.multiplicador_ehis_ehmp);
    f.cota.checked = Boolean(premissas.cota_solidariedade);
    f.zeup.checked = Boolean(premissas.zeup_ativada);
    f.zem.checked = Boolean(premissas.zem_ca4);
    f.via.checked = Boolean(premissas.acesso_via_estreita);
    f.vila.checked = Boolean(premissas.vila);
    f.fator.value = premissas.fator_privativo != null ? fmt.decimal.format(premissas.fator_privativo) : "";
    f.preco.value = premissas.preco_m2 != null ? fmt.inteiro.format(premissas.preco_m2) : "";
    f.ticket.value = premissas.ticket_unidade != null ? fmt.inteiro.format(premissas.ticket_unidade) : "";
    f.area.value = fmt.decimal.format(premissas.area_media_unidade_m2);
    f.divergencia.value = fmt.decimal.format(premissas.limite_divergencia_area_pct);
    if (f.rapRegime) f.rapRegime.value = premissas.regime;
    if (f.rapPreco) f.rapPreco.value = premissas.preco_m2 != null ? fmt.inteiro.format(premissas.preco_m2) : "";
    if (f.rapMeta) f.rapMeta.value = fmt.decimal.format(premissas.meta_vgv / 1e6);
    atualizarStatusPremissas();
  }

  // O que falta para o VGV potencial existir (mostrado na gaveta e usado pelas abas).
  function faltandoParaVgv() {
    if (!premissas) return ["as premissas ainda não foram lidas"];
    if (premissas.preco_m2 == null && premissas.ticket_unidade == null) {
      return ["preço por m² ou ticket da unidade"];
    }
    return [];
  }

  function atualizarStatusPremissas() {
    const falta = faltandoParaVgv();
    if (falta.length) {
      mostrarMsg(premissasForm.status, "Falta preencher: " + falta.join(", ") + ". Sem isso não há VGV potencial nem entorno.", "erro");
    } else {
      mostrarMsg(premissasForm.status, "VGV potencial = área × CA × preço/m². Meta de VGV: " + fmt.moeda.format(premissas.meta_vgv) + ".", "ok");
    }
  }

  function validarFormularioPremissas() {
    const f = premissasForm;
    const pares = [[f.fator, f.fatorErro], [f.preco, f.precoErro], [f.ticket, f.ticketErro], [f.area, f.areaErro], [f.divergencia, f.divergenciaErro]];
    pares.forEach(([i, e]) => { i.classList.remove("campo-com-erro"); e.textContent = ""; e.classList.add("hidden"); });

    const fator = parsearNumeroDigitado(f.fator.value);
    const preco = parsearNumeroDigitado(f.preco.value);
    const ticket = parsearNumeroDigitado(f.ticket.value);
    const area = parsearNumeroDigitado(f.area.value);
    const divergencia = parsearNumeroDigitado(f.divergencia.value);

    let valido = true;
    function marcar(input, erro, texto) {
      valido = false;
      input.classList.add("campo-com-erro");
      erro.textContent = texto;
      erro.classList.remove("hidden");
    }
    if (fator !== null && (Number.isNaN(fator) || fator <= 0)) marcar(f.fator, f.fatorErro, "Use um número maior que zero, ex.: 0,75.");
    if (preco !== null && (Number.isNaN(preco) || preco <= 0)) marcar(f.preco, f.precoErro, "Use um número maior que zero, ex.: 9.000.");
    if (ticket !== null && (Number.isNaN(ticket) || ticket <= 0)) marcar(f.ticket, f.ticketErro, "Use um número maior que zero, ex.: 350.000.");
    if (area === null || Number.isNaN(area) || area <= 0) marcar(f.area, f.areaErro, "Informe a área média em m², ex.: 40.");
    if (divergencia === null || Number.isNaN(divergencia) || divergencia <= 0 || divergencia > 100) marcar(f.divergencia, f.divergenciaErro, "Use um % entre 0 e 100, ex.: 5.");

    return valido ? {
      regime: f.regime.value,
      multiplicador_ehis_ehmp: f.multiplicador.checked,
      cota_solidariedade: f.cota.checked,
      zeup_ativada: f.zeup.checked,
      zem_ca4: f.zem.checked,
      acesso_via_estreita: f.via.checked,
      vila: f.vila.checked,
      fator_privativo: fator,
      preco_m2: preco,
      ticket_unidade: ticket,
      area_media_unidade_m2: area,
      limite_divergencia_area_pct: divergencia
    } : null;
  }

  // Grava a mudança e, salvo se `recalcular` for false, avisa as abas para refazer o que está aberto.
  async function alterarPremissas(parcial, recalcular) {
    if (!premissas) throw new Error("as premissas ainda não foram lidas");
    const novas = Object.assign({}, premissas, parcial);
    const res = await chamar("salvar_premissas", novas);
    if (!res.ok) {
      mostrarMsg(premissasForm.status, "Não salvei as premissas: " + res.erro, "erro");
      return false;
    }
    premissas = res.premissas;
    sincronizarFormularioPremissas();
    // "alteracao": as abas refazem o que está aberto; "sincronizar": só atualizam os campos na tela.
    if (recalcular !== false) await atualizarFoco();
    for (const nome of abas.keys()) chamarGancho(nome, "aoMudarPremissas", recalcular !== false ? "alteracao" : "sincronizar");
    return true;
  }

  async function aoMudarFormulario() {
    const novas = validarFormularioPremissas();
    if (novas) await alterarPremissas(novas, true);
  }

  function abrirGaveta(abrir) {
    premissasForm.gaveta.classList.toggle("hidden", !abrir);
    premissasForm.botao.setAttribute("aria-expanded", abrir ? "true" : "false");
  }

  function aplicarTema(escuro) {
    document.body.classList.toggle("tema-escuro", Boolean(escuro));
    if (premissasForm.btnTema) {
      premissasForm.btnTema.textContent = escuro ? "☀️" : "🌙";
      premissasForm.btnTema.setAttribute("aria-pressed", escuro ? "true" : "false");
      premissasForm.btnTema.title = escuro ? "Mudar para modo claro" : "Mudar para modo escuro";
    }
    try { localStorage.setItem("raiox_tema_escuro", escuro ? "1" : "0"); } catch (e) { /* sem localStorage */ }
  }

  function aplicarEscala(valor) {
    const sel = document.getElementById("sel-escala");
    const opcoes = Array.from(sel.options).map((o) => Number(o.value));
    const v = opcoes.includes(Number(valor)) ? Number(valor) : 1;
    document.documentElement.style.setProperty("--esc", String(v));
    sel.value = String(v);
    try { localStorage.setItem("raiox_escala_ui", String(v)); } catch (e) { /* sem localStorage */ }
    window.dispatchEvent(new Event("resize")); // o Leaflet recalcula o tamanho do mapa
  }

  function iniciarEscala() {
    let salva = 1;
    try { salva = Number(localStorage.getItem("raiox_escala_ui")) || 1; } catch (e) { salva = 1; }
    aplicarEscala(salva);
    document.getElementById("sel-escala").addEventListener("change", (e) => aplicarEscala(e.target.value));
  }

  async function aoMudarRapidas() {
    const f = premissasForm;
    if (!premissas) return;
    const parcial = { regime: f.rapRegime.value };
    const preco = parsearNumeroDigitado(f.rapPreco.value);
    if (preco === null || (!Number.isNaN(preco) && preco > 0)) parcial.preco_m2 = preco;
    const meta = parsearNumeroDigitado(f.rapMeta.value);
    if (meta !== null && !Number.isNaN(meta) && meta > 0) parcial.meta_vgv = meta * 1e6;
    await alterarPremissas(parcial, true);
  }

  function iniciarPremissas() {
    camposPremissas();
    const f = premissasForm;
    [f.regime, f.multiplicador, f.cota, f.zeup, f.zem, f.via, f.vila].forEach((c) => c.addEventListener("change", aoMudarFormulario));
    [f.fator, f.preco, f.ticket, f.area, f.divergencia].forEach((inp) => {
      inp.addEventListener("change", aoMudarFormulario);
      inp.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); aoMudarFormulario(); }
      });
    });
    f.rapRegime.addEventListener("change", aoMudarRapidas);
    [f.rapPreco, f.rapMeta].forEach((inp) => {
      inp.addEventListener("change", aoMudarRapidas);
      inp.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); aoMudarRapidas(); }
      });
    });
    let temaSalvo = true; // padrão: modo noturno; vale a escolha salva do analista
    try {
      const guardado = localStorage.getItem("raiox_tema_escuro");
      if (guardado !== null) temaSalvo = guardado === "1";
    } catch (e) { temaSalvo = true; }
    aplicarTema(temaSalvo);
    iniciarEscala();
    f.btnTema.addEventListener("click", () => aplicarTema(!document.body.classList.contains("tema-escuro")));
    f.botao.addEventListener("click", () => abrirGaveta(f.gaveta.classList.contains("hidden")));
    document.getElementById("btn-fechar-premissas").addEventListener("click", () => abrirGaveta(false));
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !f.gaveta.classList.contains("hidden")) abrirGaveta(false);
    });
  }

  // --- Terreno em foco: um lote, uma dupla ou uma trinca, o mesmo em todas as abas ---
  // O Python descreve o foco (SQL, endereço, área, zona, CA, geometria); as abas reagem pelo
  // gancho aoMudarFoco(foco, origem) e carregam quando abertas.
  let foco = null;
  let contadorFoco = 0;
  const barra = {};

  function textoFoco(f) {
    const frag = document.createDocumentFragment();
    // Área, zona e CA antes do endereço: numa janela estreita (150%) quem é cortado é o endereço.
    if (f.tipo !== "lote") frag.appendChild(el("span", "foco-tipo", f.tipo));
    frag.appendChild(el("span", "foco-sql", f.sql));
    frag.appendChild(el("span", "foco-meta", fmt.inteiro.format(f.area_m2) + " m² · " + f.zona + " · CA " + fmt.ca.format(f.ca) + " · " + f.endereco));
    return frag;
  }

  function desenharBarraFoco() {
    barra.caixa.classList.toggle("vazio", !foco);
    for (const b of [barra.entorno, barra.raiox, barra.simular, barra.tirar]) b.disabled = !foco;
    if (!foco) {
      barra.conteudo.replaceChildren(el("span", "foco-meta", "nenhum · escolha um lote em qualquer aba"));
      barra.conteudo.title = "";
      return;
    }
    barra.conteudo.replaceChildren(textoFoco(foco));
    barra.conteudo.title = foco.sql + " · " + foco.endereco;
  }

  function avisarAbas(origem) {
    for (const nome of abas.keys()) chamarGancho(nome, "aoMudarFoco", foco, origem);
  }

  // Põe em foco os ids (1 a 3) e avisa as abas. Devolve o foco ou lança o erro do Python.
  async function definirFoco(ids, origem) {
    if (!premissas) throw new Error("as premissas ainda não foram lidas");
    const meu = ++contadorFoco;
    const res = await chamar("foco_definir", ids, premissas);
    if (meu !== contadorFoco) return foco;
    if (!res.ok) throw new Error(res.erro);
    foco = res.foco;
    desenharBarraFoco();
    avisarAbas(origem);
    return foco;
  }

  async function limparFoco() {
    ++contadorFoco;
    const res = await chamar("foco_limpar");
    if (!res.ok) throw new Error(res.erro);
    foco = null;
    desenharBarraFoco();
    avisarAbas("barra");
  }

  // Premissa trocada: o CA do foco pode mudar (regime, multiplicador, cota).
  async function atualizarFoco() {
    if (!foco) return;
    const res = await chamar("foco_atual");
    if (!res.ok) throw new Error(res.erro);
    foco = res.foco;
    desenharBarraFoco();
  }

  function mesmosIds(a, b) {
    return Boolean(a && b) && a.length === b.length && a.every((x, i) => x === b[i]);
  }

  function iniciarBarraFoco() {
    for (const [chave, id] of Object.entries({ caixa: "foco", conteudo: "foco-conteudo", entorno: "foco-entorno", raiox: "foco-raiox", simular: "foco-simular", tirar: "foco-tirar" })) {
      barra[chave] = document.getElementById(id);
      if (!barra[chave]) throw new Error("elemento #" + id + " da barra do foco não existe na tela");
    }
    const erroComum = (e) => mostrarErroComum("Terreno em foco: " + mensagemDeErro(e));
    barra.entorno.addEventListener("click", () => { Promise.resolve(pedir("prospectar", "verEntornoDoFoco")).catch(erroComum); });
    barra.raiox.addEventListener("click", () => ativarAba("lote"));
    barra.simular.addEventListener("click", () => ativarAba("simulador"));
    barra.tirar.addEventListener("click", () => { limparFoco().catch(erroComum); });
    desenharBarraFoco();
  }

  function mostrarErroComum(texto) {
    const faixa = document.getElementById("comum-erro");
    faixa.textContent = texto;
    faixa.classList.remove("hidden");
  }

  // --- Catálogo de camadas (pedido uma vez, usado pelos mapas de todas as abas) ---
  let catalogoPromessa = null;
  function catalogoCamadas() {
    if (!catalogoPromessa) {
      catalogoPromessa = chamar("lista_camadas").then((res) => {
        if (!res.ok) { catalogoPromessa = null; throw new Error(res.erro); }
        return res.camadas;
      });
    }
    return catalogoPromessa;
  }

  // --- Mapa-base: satélite + camadas para ver. Cada aba cria o seu (estado separado). ---
  // `ligadasPadrao`: ids das camadas "ver" que começam marcadas.
  function criarMapa(ctx, prefixo, ligadasPadrao) {
    const elMapa = ctx.$(prefixo + "-mapa");
    const elAviso = ctx.$(prefixo + "-mapa-aviso");
    const elTiles = ctx.$(prefixo + "-tile-aviso");
    const chkSatelite = ctx.$(prefixo + "-chk-satelite");
    const listaVer = ctx.$(prefixo + "-camadas-ver");
    const erroCamadas = ctx.$(prefixo + "-camadas-erro");
    const btnCamadas = ctx.$(prefixo + "-btn-camadas");
    const painelCamadas = ctx.$(prefixo + "-camadas-painel");

    const map = L.map(elMapa, { preferCanvas: true, zoomControl: false, attributionControl: false }).setView(CENTRO_SP, 12);
    L.control.zoom({ position: "topright", zoomInTitle: "Aproximar", zoomOutTitle: "Afastar" }).addTo(map);
    L.control.attribution({ position: "bottomright", prefix: false }).addTo(map);
    const escala = L.control.scale({ position: "bottomleft", imperial: false, maxWidth: 110 }).addTo(map);
    // Onde há pilha própria (Prospectar), a escala vai para dentro dela: legenda e escala empilham, sem cruzar.
    const pilhaBL = document.getElementById(prefixo + "-legenda");
    if (pilhaBL) pilhaBL.querySelector(".leg-escala").appendChild(escala.getContainer());
    const satelite = L.tileLayer(ESRI_URL, { attribution: "Esri", maxZoom: 19 });
    let tilesCarregados = false;
    satelite.on("tileload", () => { tilesCarregados = true; elTiles.classList.add("hidden"); });
    satelite.on("tileerror", () => { if (!tilesCarregados) elTiles.classList.remove("hidden"); });
    satelite.addTo(map);

    map.createPane("camadas").style.zIndex = 410;
    map.createPane("destaque").style.zIndex = 450;
    map.createPane("foco").style.zIndex = 460;
    const rendCamadas = L.canvas({ pane: "camadas" });
    const rendDestaque = L.canvas({ pane: "destaque" });
    const rendFoco = L.canvas({ pane: "foco" });

    const vetoriais = new Map();
    const catalogo = new Map();
    let contador = 0;
    let timer = null;
    const aoRedimensionar = [];

    // O mapa acompanha o tamanho do painel (janela maximizada, escala do Windows, grade).
    new ResizeObserver(() => {
      if (!elMapa.offsetWidth || !elMapa.offsetHeight) return;
      map.invalidateSize();
      for (const fn of aoRedimensionar) ctx.proteger(fn)();
    }).observe(elMapa);

    btnCamadas.addEventListener("click", () => {
      const abrir = painelCamadas.classList.contains("hidden");
      painelCamadas.classList.toggle("hidden", !abrir);
      btnCamadas.setAttribute("aria-expanded", abrir ? "true" : "false");
    });

    chkSatelite.addEventListener("change", () => {
      if (chkSatelite.checked) { if (!map.hasLayer(satelite)) satelite.addTo(map); }
      else if (map.hasLayer(satelite)) map.removeLayer(satelite);
    });

    function idsLigados() {
      return Array.from(listaVer.querySelectorAll("input[data-layer-id]")).filter((c) => c.checked).map((c) => c.dataset.layerId);
    }

    function remover(id) {
      const c = vetoriais.get(id);
      if (c && map.hasLayer(c)) map.removeLayer(c);
      vetoriais.delete(id);
    }

    function popup(feature, id) {
      const caixa = el("div", "popup-camada");
      const info = catalogo.get(id);
      caixa.appendChild(el("strong", null, info ? info.rotulo : id));
      const props = feature && feature.properties;
      if (props && typeof props === "object") {
        for (const [k, v] of Object.entries(props)) {
          if (v == null || String(v).trim() === "") continue;
          caixa.appendChild(el("div", null, k + ": " + String(v)));
        }
      }
      return caixa;
    }

    function aviso(texto) {
      elAviso.textContent = texto || "";
      elAviso.classList.toggle("hidden", !texto);
    }

    async function carregarVisiveis() {
      const zoom = map.getZoom();
      const ligados = idsLigados();
      if (zoom < ZOOM_MIN_CAMADAS) {
        for (const id of Array.from(vetoriais.keys())) remover(id);
        aviso(ligados.length ? "Aproxime o mapa para ver as camadas." : "");
        return;
      }
      aviso("");
      for (const id of Array.from(vetoriais.keys())) if (!ligados.includes(id)) remover(id);
      if (ligados.length === 0) return;

      const b = map.getBounds();
      const meu = ++contador;
      aviso("Carregando camadas…");
      const res = await chamar("camadas_mapa", [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()], ligados, zoom);
      if (meu !== contador) return;
      aviso("");
      if (!res.ok) { aviso("Não consegui carregar as camadas: " + res.erro); return; }
      for (const id of ligados) {
        remover(id);
        const gj = (res.camadas || {})[id];
        if (!gj || !gj.type) continue;
        const estilo = ESTILOS_CAMADAS[id] || ESTILOS_CAMADAS.padrao;
        const grupo = L.geoJSON(gj, {
          pane: "camadas",
          renderer: rendCamadas,
          interactive: id !== "lotes",
          style: () => estilo,
          pointToLayer: (f, latlng) => id === "estacoes"
            ? L.circleMarker(latlng, { pane: "camadas", renderer: rendCamadas, radius: 6, color: "#ffffff", weight: 2, fillColor: "#0ea5e9", fillOpacity: 1 })
            : L.circleMarker(latlng, { pane: "camadas", renderer: rendCamadas, radius: 4, ...estilo }),
          onEachFeature: (f, layer) => { if (id !== "lotes") layer.bindPopup(popup(f, id)); }
        }).addTo(map);
        vetoriais.set(id, grupo);
      }
    }

    map.on("moveend", ctx.proteger(() => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(ctx.proteger(carregarVisiveis), 400);
    }));

    // Legenda: só as camadas ligadas, com a mesma cor do menu. Cresce com o número de camadas e rola
    // quando não cabe; o título recolhe a lista.
    let legendaRecolhida = false;
    function atualizarLegenda() {
      if (!pilhaBL) return;
      const caixa = pilhaBL.querySelector(".leg-caixa");
      const itens = Array.from(listaVer.querySelectorAll("label.camada-item")).filter((l) => l.querySelector("input").checked);
      caixa.replaceChildren();
      caixa.classList.toggle("hidden", itens.length === 0);
      if (!itens.length) return;
      const topo = el("button", "leg-topo", "Legenda (" + itens.length + ") " + (legendaRecolhida ? "▸" : "▾"));
      topo.type = "button";
      topo.title = legendaRecolhida ? "Mostrar a legenda" : "Recolher a legenda";
      topo.addEventListener("click", () => { legendaRecolhida = !legendaRecolhida; atualizarLegenda(); });
      caixa.appendChild(topo);
      if (legendaRecolhida) return;
      const lista = el("div", "leg-lista");
      for (const l of itens) {
        const linha = el("div", "leg-item");
        const cor = el("i", "cor-camada");
        cor.style.background = l.querySelector(".cor-camada").style.background;
        linha.appendChild(cor);
        linha.appendChild(el("span", null, l.querySelector(".camada-rot").textContent));
        lista.appendChild(linha);
      }
      caixa.appendChild(lista);
    }

    function atualizarRotuloBtnCamadas() {
      const n = idsLigados().length;
      btnCamadas.textContent = n > 0 ? "Camadas (" + n + ") ▾" : "Camadas ▾";
      atualizarLegenda();
    }

    // Monta a lista "ver no mapa" quando a ponte estiver pronta.
    async function montarListaVer() {
      let lista;
      try {
        lista = await catalogoCamadas();
      } catch (e) {
        erroCamadas.textContent = "Erro ao carregar a lista de camadas: " + mensagemDeErro(e);
        erroCamadas.classList.remove("hidden");
        return [];
      }
      erroCamadas.classList.add("hidden");
      listaVer.replaceChildren();
      catalogo.clear();
      for (const c of lista) {
        catalogo.set(c.id, c);
        if (!(c.usos || []).includes("ver")) continue;
        const label = el("label", "camada-item");
        const chk = el("input");
        chk.type = "checkbox";
        chk.dataset.layerId = c.id;
        chk.checked = ligadasPadrao.includes(c.id);
        chk.addEventListener("change", ctx.proteger(() => {
          atualizarRotuloBtnCamadas();
          if (chk.checked) return carregarVisiveis();
          remover(c.id);
          return undefined;
        }));
        const cor = el("i", "cor-camada");
        const est = ESTILOS_CAMADAS[c.id] || ESTILOS_CAMADAS.padrao;
        cor.style.background = c.id === "estacoes" ? "#0ea5e9" : (est.fillColor || est.color || "#94a3b8");
        const rot = el("span", "camada-rot", c.rotulo || c.id);
        rot.title = c.rotulo || c.id;
        const tag = el("span", "camada-tag", CATEGORIA_CAMADA[c.id] || "📐 Base");
        label.appendChild(chk);
        label.appendChild(cor);
        label.appendChild(rot);
        label.appendChild(tag);
        listaVer.appendChild(label);
      }
      atualizarRotuloBtnCamadas();
      carregarVisiveis();
      return lista;
    }

    // Marca exatamente estas camadas "ver" (o Raio-X liga as restrições presentes no lote).
    function ligarSomente(ids) {
      listaVer.querySelectorAll("input[data-layer-id]").forEach((c) => { c.checked = ids.includes(c.dataset.layerId); });
      atualizarRotuloBtnCamadas();
      return carregarVisiveis();
    }

    return {
      map,
      rendDestaque,
      rendFoco,
      montarListaVer,
      ligarSomente,
      idDaCamadaPeloRotulo(rotulo) {
        for (const c of catalogo.values()) if (c.rotulo === rotulo) return c.id;
        return null;
      },
      aoRedimensionar(fn) { aoRedimensionar.push(fn); },
      invalidar() { map.invalidateSize(); },
      tilesOk() { return tilesCarregados; }
    };
  }

  // Lê arquivo .kmz/.kml como base64 (sem o prefixo data:).
  function lerArquivoBase64(arquivo) {
    return new Promise((resolve, reject) => {
      const leitor = new FileReader();
      leitor.onload = () => {
        const url = leitor.result;
        const b64 = typeof url === "string" ? url.split(",")[1] : "";
        if (b64) resolve(b64); else reject(new Error("não foi possível ler o arquivo " + arquivo.name));
      };
      leitor.onerror = () => reject(new Error("não foi possível ler o arquivo " + arquivo.name));
      leitor.readAsDataURL(arquivo);
    });
  }

  // Arrastar e soltar: o arquivo vai para a aba ativa (gancho soltarArquivo).
  function iniciarSoltar() {
    window.addEventListener("dragenter", (e) => { e.preventDefault(); document.body.classList.add("arrastando"); });
    window.addEventListener("dragover", (e) => { e.preventDefault(); document.body.classList.add("arrastando"); });
    window.addEventListener("dragleave", (e) => {
      e.preventDefault();
      if (e.clientX <= 0 || e.clientY <= 0) document.body.classList.remove("arrastando");
    });
    window.addEventListener("drop", (e) => {
      e.preventDefault();
      document.body.classList.remove("arrastando");
      const arquivos = e.dataTransfer && e.dataTransfer.files;
      const arquivo = arquivos && arquivos.length ? arquivos[0] : null;
      if (abaAtiva) chamarGancho(abaAtiva, "soltarArquivo", arquivo);
    });
  }

  // --- Autoteste da janela (python -m raiox.app --autoteste) ---
  const proximoQuadro = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

  // Painéis com rolagem horizontal na aba ativa (a tabela de resultados e a DRE podem rolar: são tabelas).
  function rolagemHorizontal() {
    const achados = [];
    const doc = document.documentElement;
    if (doc.scrollWidth > doc.clientWidth + 1) achados.push({ painel: "página", largura: doc.scrollWidth, visivel: doc.clientWidth, permitido: false });
    const raiz = document.getElementById("aba-" + abaAtiva);
    const paineis = [document.querySelector(".topo"), ...raiz.querySelectorAll(".painel, .tabela-container, .sm-dre-container, .dica, .res-topo")];
    for (const p of paineis) {
      if (!p || !p.offsetWidth) continue;
      if (p.scrollWidth > p.clientWidth + 1) {
        achados.push({
          painel: p.id || p.className, largura: p.scrollWidth, visivel: p.clientWidth,
          permitido: p.classList.contains("tabela-container") || p.classList.contains("sm-dre-container")
        });
      }
    }
    return achados;
  }

  // Confere a ponte, as três abas, o envelope, o círculo de 1.500 m do 7238009, VGV painel = tabela,
  // o foco atravessando as 3 abas, o quarteirão, as ferramentas L/R/D, as áreas prontas e a rolagem.
  // --- Teste de sobreposição do HUD do Prospectar: mede os retângulos de tudo o que flutua sobre o mapa ---
  const aguardarLayout = () => new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(ok, 80))));

  function medirSobreposicoesProspectar() {
    const raiz = document.getElementById("aba-prospectar");
    const alvos = [
      ["ferramentas", ".ferr"], ["opções da ferramenta", ".ferr-opcoes"], ["botão Camadas", "#pr-btn-camadas"],
      ["menu Camadas", "#pr-camadas-painel"], ["zoom", ".leaflet-control-zoom"], ["escala do mapa", "#pr-legenda .leg-escala"],
      ["créditos", ".leaflet-control-attribution"], ["legenda", "#pr-legenda .leg-caixa"], ["dica", "#pr-dica"],
      ["painel de busca", "#pr-painel-passos"], ["painel de detalhe", "#pr-painel-detalhe"], ["tabela", "#pr-painel-resultados"]
    ];
    const caixas = [];
    for (const [nome, sel] of alvos) {
      const e = raiz.querySelector(sel);
      if (!e || e.classList.contains("hidden")) continue;
      const b = e.getBoundingClientRect();
      if (b.width < 2 || b.height < 2) continue;
      caixas.push({ nome, l: b.left, t: b.top, r: b.right, b: b.bottom });
    }
    raiz.querySelectorAll(".avisos-mapa > :not(.hidden)").forEach((e) => {
      const b = e.getBoundingClientRect();
      if (b.width >= 2 && b.height >= 2) caixas.push({ nome: "aviso do mapa", l: b.left, t: b.top, r: b.right, b: b.bottom });
    });
    const colisoes = [];
    // texto cortado: reticências ativas com conteúdo maior que a caixa, ou faixa de controles que não cabe
    raiz.querySelectorAll("*").forEach((e) => {
      if (!e.offsetWidth || !e.textContent.trim() || e.title) return;  // com title, o texto inteiro está no balão
      const estilo = getComputedStyle(e);
      const cortado = estilo.textOverflow === "ellipsis" && e.scrollWidth > e.clientWidth + 1;
      const faixaCortada = e.classList.contains("res-topo") && e.scrollWidth > e.clientWidth + 1;
      if (cortado || faixaCortada) colisoes.push("texto cortado: " + (e.className || e.tagName) + " «" + e.textContent.trim().slice(0, 28) + "» [0,0,0,0]");
    });
    for (let i = 0; i < caixas.length; i++) {
      for (let j = i + 1; j < caixas.length; j++) {
        const a = caixas[i], c = caixas[j];
        const w = Math.min(a.r, c.r) - Math.max(a.l, c.l);
        const h = Math.min(a.b, c.b) - Math.max(a.t, c.t);
        if (w > 2 && h > 2) colisoes.push(a.nome + " × " + c.nome + " [" + [a, c].map((x) => Math.round(x.l) + "," + Math.round(x.t) + "," + Math.round(x.r) + "," + Math.round(x.b)).join(" | ") + "]");
      }
    }
    return colisoes;
  }

  async function testarSobreposicoesHud() {
    const raiz = document.getElementById("aba-prospectar");
    const selEscala = document.getElementById("sel-escala");
    const trocarPainel = (idPainel, idSeta, recolher) => {
      const p = document.getElementById(idPainel);
      if (p.classList.contains("recolhido") !== recolher) document.getElementById(idSeta).click();
    };
    const botaoRaio = raiz.querySelector('[data-ferramenta="raio"]');
    const botaoLote = raiz.querySelector('[data-ferramenta="lote"]');
    const btnCamadas = document.getElementById("pr-btn-camadas");
    const menuCamadas = document.getElementById("pr-camadas-painel");
    const problemas = {};
    let combinacoes = 0;
    for (const escala of Array.from(selEscala.options).map((o) => o.value)) {
      selEscala.value = escala;
      selEscala.dispatchEvent(new Event("change"));
      for (let m = 0; m < 16; m++) {
        trocarPainel("pr-painel-passos", "pr-seta-passos", Boolean(m & 1));
        trocarPainel("pr-painel-detalhe", "pr-seta-detalhe", Boolean(m & 2));
        trocarPainel("pr-painel-resultados", "pr-seta-resultados", Boolean(m & 4));
        const extra = Boolean(m & 8); // ferramenta raio ligada + menu Camadas aberto
        (extra ? botaoRaio : botaoLote).click();
        if (menuCamadas.classList.contains("hidden") === extra) btnCamadas.click();
        await aguardarLayout();
        combinacoes += 1;
        for (const c of medirSobreposicoesProspectar()) {
          const chave = c.replace(/ \[.*\]$/, "");
          (problemas[chave] = problemas[chave] || []).push(c.replace(/^.*?(\[.*\])$/, "$1") + "@" + Math.round(Number(escala) * 100) + "%/" + m);
        }
      }
    }
    // volta ao estado inicial da tela
    selEscala.value = "1"; selEscala.dispatchEvent(new Event("change"));
    trocarPainel("pr-painel-passos", "pr-seta-passos", false);
    trocarPainel("pr-painel-detalhe", "pr-seta-detalhe", true);
    trocarPainel("pr-painel-resultados", "pr-seta-resultados", false);
    botaoLote.click();
    if (!menuCamadas.classList.contains("hidden")) btnCamadas.click();
    await aguardarLayout();
    return { combinacoes, problemas };
  }

  async function autoteste() {
    const r = { inicio: new Date().toISOString(), ponte: true, abas: {}, falhas: [] };
    const falha = (t) => r.falhas.push(t);
    for (const [nome, aba] of abas) {
      r.abas[nome] = { iniciou: Boolean(aba.api), erro: aba.erroInicio };
      if (!aba.api) falha("aba " + nome + " não iniciou: " + aba.erroInicio);
    }
    r.premissas_lidas = premissas !== null;
    r.viewport = { largura: window.innerWidth, altura: window.innerHeight, escala: window.devicePixelRatio };
    try { r.camadas = (await catalogoCamadas()).length; } catch (e) { falha("camadas: " + mensagemDeErro(e)); }

    const sim = await chamar("simulador_simular", {});
    r.envelope_simulador = sim;
    if (sim.ok !== false || sim.aba !== "simulador") falha("o envelope do simulador não devolveu ok=false/aba=simulador");

    // Contas com premissas de teste explícitas (não grava em disco): círculo de 1.500 m do 7238009.
    const teste = Object.assign({}, premissas, {
      preco_m2: 7000, ticket_unidade: null, fator_privativo: 0.7, retiradas: [], base_vgv: "referencia_ca",
      acesso_via_estreita: false, vila: false, meta_vgv: 100000000, criterio_meta: "vgv", area_max_lote_m2: 50000,
      limite_esconder_pct: 50, triagem_esconde: ["publica", "favela"], divisa_min_m: 20, mostrar_duplas: true, mostrar_trincas: true,
      regime: "R2V_LIVRE", multiplicador_ehis_ehmp: false, limite_divergencia_area_pct: 5
    });
    const centro = await chamar("prospectar_escolher_centro", "7238009");
    const ent = centro.ok ? await chamar("prospectar_entorno", 1500, teste) : centro;
    if (ent.ok) {
      const cs = ent.entorno.candidatos;
      const vis = cs.filter((c) => !c.escondido_por);
      r.entorno_1500 = {
        lotes: vis.filter((c) => c.tipo === "lote").length,
        escondidos: cs.filter((c) => c.escondido_por).length,
        duplas: vis.filter((c) => c.tipo === "dupla").length,
        trincas: vis.filter((c) => c.tipo === "trinca").length
      };
      const lote = await chamar("lote_escolher", "7238009", teste);
      const linha = cs.find((c) => c.tipo === "lote" && c.ids[0] === "7238009");
      r.vgv_painel = lote.ok ? lote.resultado.area_util.vgv : lote.erro;
      r.vgv_tabela = linha ? linha.vgv : null;
      if (r.vgv_painel !== r.vgv_tabela) falha("VGV do painel diferente do VGV da tabela");
    } else {
      r.entorno_1500 = { erro: ent.erro };
      falha("entorno: " + ent.erro);
    }

    // Fluxos da tela com as premissas de teste só em memória; o raio continua o salvo.
    const originais = premissas;
    premissas = Object.assign({}, teste, { raio_entorno_m: originais.raio_entorno_m });
    try {
      // 1. Foco pelo clique no mapa (ferramenta L) sobre o 7238009, depois o círculo de 1.500 m.
      const ponto = await chamar("foco_definir", ["7238009"], premissas);
      if (!ponto.ok) throw new Error(ponto.erro);
      await limparFoco();
      ativarAba("prospectar");
      await chamarGancho("prospectar", "teclar", "l");
      await chamarGancho("prospectar", "clicarMapaEm", ponto.foco.ponto[0], ponto.foco.ponto[1]);
      r.foco_pelo_clique = foco ? foco.ids : null;
      if (!foco || !mesmosIds(foco.ids, ["7238009"])) falha("o clique com a ferramenta L não pôs o 7238009 em foco");
      r.barra_foco = barra.conteudo.textContent;
      if (!r.barra_foco.includes("133.280.0000") || !r.barra_foco.includes("CA 2,00")) falha("a barra do foco não mostrou SQL e CA: " + r.barra_foco);
      await chamarGancho("prospectar", "verEntornoDoFoco", 1500);
      const circ = chamarGancho("prospectar", "estadoTela");
      r.tela_circulo = { contagens: circ.contagens, area: circ.area, linhas: circ.linhas };
      if (JSON.stringify(circ.contagens) !== JSON.stringify({ lotes: 15, duplas: 5, trincas: 0, escondidos: 5 })) falha("círculo de 1.500 m pela tela diferente de 15 · 5 · 0 · 5: " + JSON.stringify(circ.contagens));

      // 2. Raio-X do lote: só o quarteirão do foco, travado; Simulador recebe o mesmo terreno.
      await ativarAba("lote");
      const lt = chamarGancho("lote", "estadoTela");
      r.tela_lote = lt;
      if (!lt.aberto || lt.aberto !== "7238009") falha("o Raio-X não abriu o lote em foco");
      if (!(lt.quarteirao.n >= 1) || !lt.quarteirao.todos_da_quadra) falha("o mapa do Raio-X mostrou lote fora da quadra do foco");
      if (!lt.quarteirao.aberto_destacado) falha("o lote em foco não ficou destacado no quarteirão");
      if (!lt.travado) falha("o mapa do Raio-X não ficou travado na quadra");
      if (!lt.texto.includes("R$ 296.310.000")) falha("o Raio-X não mostrou o VGV potencial de R$ 296.310.000");
      if (!lt.texto.includes("Área do desenho")) falha("o Raio-X não mostrou a área do desenho ao lado do cadastro");
      await ativarAba("simulador");
      const sm1 = chamarGancho("simulador", "estadoTela");
      r.tela_simulador_foco = sm1.terreno;
      if (!sm1.terreno || !mesmosIds(sm1.terreno.ids, ["7238009"])) falha("o Simulador não recebeu o lote em foco");

      // 3. Foco numa dupla escolhida na tabela do Prospectar: atravessa o Raio-X e o Simulador.
      await ativarAba("prospectar");
      await chamarGancho("prospectar", "filtrar", "dupla");
      r.dupla_escolhida = await chamarGancho("prospectar", "selecionarPrimeira", "dupla");
      await chamarGancho("prospectar", "filtrar", "todas");
      r.foco_dupla = foco ? { tipo: foco.tipo, ids: foco.ids } : null;
      if (!foco || foco.tipo !== "dupla") falha("a linha da dupla não pôs a dupla em foco");
      const idsDupla = foco ? foco.ids : [];
      await ativarAba("lote");
      const ltDupla = chamarGancho("lote", "estadoTela");
      r.tela_lote_dupla = { aberto: ltDupla.aberto, composicao: ltDupla.composicao };
      if (ltDupla.aberto !== idsDupla[0] || ltDupla.composicao !== 2) falha("o Raio-X não mostrou a dupla em foco (lote 1 de 2)");
      await ativarAba("simulador");
      const smDupla = chamarGancho("simulador", "estadoTela");
      r.tela_simulador_dupla = smDupla.terreno;
      if (!smDupla.terreno || smDupla.terreno.tipo !== "dupla" || !mesmosIds(smDupla.terreno.ids, idsDupla)) falha("o Simulador não recebeu a dupla em foco");

      // 4. Áreas prontas: faixa da Av. Marechal Tito, detalhe da dupla, modo "Todos os lotes".
      await ativarAba("prospectar");
      let t0 = performance.now();
      await chamarGancho("prospectar", "usarFaixaMarechal");
      r.tempo_faixa_marechal_s = Math.round((performance.now() - t0) / 100) / 10;
      const mt = chamarGancho("prospectar", "estadoTela");
      r.tela_faixa_marechal = { contagens: mt.contagens, area: mt.area, resumo_passo: mt.resumo_area };
      if (!mt.area.includes("Marechal Tito") || !mt.area.includes("km²")) falha("a barra do mapa não diz a área usada e o tamanho");
      if (JSON.stringify(mt.contagens) !== JSON.stringify({ lotes: 143, duplas: 51, trincas: 23, escondidos: 21 })) falha("faixa da Marechal Tito diferente de 143 · 51 · 23 · 21: " + JSON.stringify(mt.contagens));
      await chamarGancho("prospectar", "filtrar", "dupla");
      await chamarGancho("prospectar", "selecionarPrimeira", "dupla");
      await chamarGancho("prospectar", "filtrar", "todas");
      const det = chamarGancho("prospectar", "estadoTela").selecionado;
      if (!det.includes("Lotes que compõem") || !det.includes("Soma da área computável")) falha("o detalhe da dupla não abriu com a conta");
      t0 = performance.now();
      await chamarGancho("prospectar", "definirModo", "todos");
      r.tempo_modo_todos_s = Math.round((performance.now() - t0) / 100) / 10;
      const todos = chamarGancho("prospectar", "estadoTela");
      r.tela_modo_todos = { linhas: todos.linhas, total_filtrado: todos.total_filtrado };
      if (!(todos.linhas === 100 && todos.total_filtrado > 70000)) falha("o modo 'Todos os lotes' não paginou a área inteira");
      r.tela_todos_mapa_z17 = await chamarGancho("prospectar", "desenharTodosEm", -23.50, -46.42, 17);
      if (!(r.tela_todos_mapa_z17.lotes_desenhados > 1000)) falha("o mapa do modo 'Todos os lotes' não desenhou os lotes no zoom 17");
      // HUD sem sobreposição em todos os tamanhos e combinações de painéis
      await chamarGancho("prospectar", "definirModo", "oportunidades");
      r.hud_sobreposicoes = await testarSobreposicoesHud();
      for (const [par, onde] of Object.entries(r.hud_sobreposicoes.problemas)) falha("HUD sobreposto: " + par + " (" + onde.length + " casos, ex.: " + onde.slice(0, 2).join("; ") + ")");
      await chamarGancho("prospectar", "definirModo", "oportunidades");
      const volta = chamarGancho("prospectar", "estadoTela");
      if (volta.linhas !== 15) falha("'Só oportunidades' não voltou às 15 primeiras: " + volta.linhas);

      // 5. Ferramentas pelo teclado: R marca o raio (clicar e ir), D desenha, L volta.
      await chamarGancho("prospectar", "teclar", "r");
      const comR = chamarGancho("prospectar", "estadoTela");
      r.ferramenta_r = { ferramenta: comR.ferramenta, cursor: comR.cursor };
      if (comR.ferramenta !== "raio" || comR.cursor !== "crosshair") falha("a tecla R não ligou 'Marcar raio' com cursor de mira");
      r.ponto_previa_ok = await chamarGancho("prospectar", "marcarPontoEm", -23.495, -46.415, 1000);
      const pt = chamarGancho("prospectar", "estadoTela");
      r.tela_ponto = { area: pt.area, contagens: pt.contagens };
      if (!r.ponto_previa_ok) falha("o círculo do ponto marcado não apareceu com o raio pedido");
      if (!pt.area.includes("ponto marcado") || !pt.area.includes("3,14 km²")) falha("a barra do mapa não diz o círculo do ponto marcado: " + pt.area);
      await chamarGancho("prospectar", "teclar", "d");
      const comD = chamarGancho("prospectar", "estadoTela");
      r.ferramenta_d = { ferramenta: comD.ferramenta, cursor: comD.cursor };
      if (comD.ferramenta !== "desenho" || comD.cursor !== "crosshair") falha("a tecla D não ligou 'Desenhar área'");
      const quadrado = [[-23.490, -46.420], [-23.490, -46.410], [-23.500, -46.410], [-23.500, -46.420]];
      r.desenho_vertices = await chamarGancho("prospectar", "desenharAreaEm", quadrado, "Autoteste desenho");
      const ds = chamarGancho("prospectar", "estadoTela");
      r.tela_desenho = { area: ds.area, ferramenta_depois: ds.ferramenta };
      if (r.desenho_vertices !== 4) falha("o desenho deveria ter 4 pontos (o duplo clique não pode repetir ponto), teve " + r.desenho_vertices);
      if (!ds.area.includes("área desenhada") || !ds.area.includes("km²")) falha("a barra do mapa não diz a área desenhada: " + ds.area);
      const regs = await chamar("prospectar_listar_regioes");
      r.desenho_salvo = regs.ok && regs.regioes.some((x) => x.id === "autoteste-desenho");
      if (!r.desenho_salvo) falha("a área desenhada não foi salva como região");
      await chamar("prospectar_excluir_regiao", "autoteste-desenho");
      await chamarGancho("prospectar", "teclar", "l");
      const comL = chamarGancho("prospectar", "estadoTela");
      if (comL.ferramenta !== "lote") falha("a tecla L não voltou para 'Escolher lote'");
    } catch (e) {
      falha("fluxo da tela: " + mensagemDeErro(e));
    } finally {
      premissas = originais;
    }

    // Simulador pela busca da aba (põe o lote em foco): Fs vazio em R2V marca o campo; Fs 1 simula.
    premissas = Object.assign({}, teste, { raio_entorno_m: originais.raio_entorno_m });
    try {
      await ativarAba("simulador");
      await chamarGancho("simulador", "buscar", "7238009");
      if (!foco || !mesmosIds(foco.ids, ["7238009"])) falha("a busca do Simulador não pôs o lote em foco");
      chamarGancho("simulador", "definirCampo", "fs", "");
      await chamarGancho("simulador", "simular");
      const semFs = chamarGancho("simulador", "estadoTela");
      r.simulador_sem_fs = { mensagem: semFs.mensagem, campos_com_erro: semFs.campos_com_erro };
      if (!semFs.mensagem.includes("Fator Social (Fs)") || !semFs.campos_com_erro.includes("fs")) falha("simulador: Fs vazio em R2V não marcou o campo Fs");
      chamarGancho("simulador", "definirCampo", "fs", "1");
      await chamarGancho("simulador", "simular");
      const sm = chamarGancho("simulador", "estadoTela");
      r.simulador = { terreno: sm.terreno, linhas_dre: sm.linhas_dre, exportar_habilitado: sm.exportar_habilitado, mensagem: sm.mensagem };
      if (!sm.terreno || !sm.terreno.zona || !(sm.terreno.area_liquida_m2 > 21000)) falha("simulador: o topo não mostrou o terreno do 7238009");
      if (!(sm.linhas_dre >= 7) || !sm.exportar_habilitado || !sm.resultado.replace(/\s/g, " ").includes("R$ 296.310.000")) falha("simulador: o resultado do 7238009 não apareceu com a DRE e o VGV de R$ 296.310.000");
    } catch (e) {
      falha("simulador pela tela: " + mensagemDeErro(e));
    } finally {
      premissas = originais;
    }

    // Rolagem horizontal de cada painel, aba por aba (só tabelas podem rolar de lado).
    r.rolagem_horizontal = {};
    for (const nome of abas.keys()) {
      await ativarAba(nome);
      await proximoQuadro();
      const achados = rolagemHorizontal();
      r.rolagem_horizontal[nome] = achados;
      for (const a of achados) if (!a.permitido) falha("rolagem horizontal na aba " + nome + ": " + a.painel + " (" + a.largura + " > " + a.visivel + " px)");
    }

    // Volta o backend às premissas da tela e tira o foco de teste.
    if (premissas) await chamar("lote_recalcular", premissas);
    await limparFoco();
    await ativarAba("prospectar");
    r.faixas_de_erro_visiveis = Array.from(document.querySelectorAll("[data-erro-aba]:not(.hidden), #comum-erro:not(.hidden)")).map((f) => f.textContent);
    r.fim = new Date().toISOString();
    r.ok = r.falhas.length === 0 && r.faixas_de_erro_visiveis.length === 0;
    await chamar("registrar_autoteste", r);
  }

  // --- Início ---
  async function aoPonteProntas() {
    const modo = await chamar("modo");
    const emAutoteste = Boolean(modo.ok && modo.autoteste);
    const res = await chamar("ler_premissas");
    if (res.ok) {
      premissas = res.premissas;
      if (!emAutoteste) {
        const iniciais = {};
        if (premissas.preco_m2 == null && premissas.ticket_unidade == null) iniciais.preco_m2 = 7000;
        if (!Array.isArray(premissas.retiradas) || premissas.retiradas.length === 0) {
          iniciais.retiradas = ["melhoramento", "alta_tensao", "duto"];
        }
        if (Object.keys(iniciais).length > 0) {
          const salvou = await chamar("salvar_premissas", Object.assign({}, premissas, iniciais));
          if (salvou.ok) premissas = salvou.premissas;
        }
      }
      sincronizarFormularioPremissas();
    } else {
      mostrarMsg(premissasForm.status, "Não consegui ler as premissas salvas: " + res.erro, "erro");
    }
    for (const nome of abas.keys()) chamarGancho(nome, "aoPonteProntas");
    if (premissas) for (const nome of abas.keys()) chamarGancho(nome, "aoMudarPremissas", "carga");

    if (!emAutoteste) avisoDadosAntigos();
    if (emAutoteste) await autoteste();
  }

  window.addEventListener("error", (e) => mostrarErroComum("Erro inesperado na tela: " + (e.message || "desconhecido")));

  document.addEventListener("DOMContentLoaded", () => {
    try {
      iniciarPremissas();
      iniciarBarraFoco();
    } catch (e) {
      mostrarErroComum("A parte comum não iniciou: " + mensagemDeErro(e));
    }
    iniciarAbas();
    iniciarSoltar();
    let ponteIniciada = false;
    const iniciarPonte = () => { if (!ponteIniciada) { ponteIniciada = true; aoPonteProntas(); } };
    if (window.pywebview && window.pywebview.api) iniciarPonte();
    else window.addEventListener("pywebviewready", iniciarPonte, { once: true });
  });

  window.RaioX = {
    el, fmt, COR, formatarSQL, parsearNumeroDigitado, mostrarMsg, esconderMsg, mensagemDeErro, carregandoLinha, listaOpcoes,
    chamar, registrarAba, pedir, ativarAba, criarMapa, lerArquivoBase64,
    premissas: {
      atuais() { return premissas ? Object.assign({}, premissas) : null; },
      alterar: alterarPremissas,
      faltandoParaVgv
    },
    foco: {
      atual() { return foco; },
      definir: definirFoco,
      limpar: limparFoco,
      mesmosIds
    }
  };
})();
