// Aba "Prospectar": passos à esquerda (1 área de busca · 2 meta · 3 filtros e triagem), mapa com a
// barra de ferramentas (Escolher lote [L] · Marcar raio [R] · Desenhar área [D]: clicar e ir),
// detalhe à direita e resultados embaixo (contadores, modo, tabela paginada do Python, CSV, KMZ).
// A tela não calcula nada: mostra o que vem do Python. O estado desta aba é só dela; só o
// terreno em foco (RaioX.foco) é compartilhado com as outras abas.
(function () {
  "use strict";
  const { el, fmt, COR, mostrarMsg, esconderMsg, chamar, parsearNumeroDigitado, carregandoLinha, listaOpcoes } = window.RaioX;
  const focoComum = window.RaioX.foco;

  const ROTULO_TIPO = { lote: "Lote", dupla: "Dupla", trinca: "Trinca" };
  const TECLAS = { l: "lote", r: "raio", d: "desenho" };
  const DICAS = {
    lote: "Clique num lote para escolhê-lo (ele vai para o foco).",
    raio: "Clique no mapa para marcar o centro; arraste ou mude o raio para refazer.",
    desenho: "Clique os cantos da área. Duplo clique ou “Fechar e calcular” termina."
  };
  const RAIO_MIN = 100, RAIO_MAX = 5000;
  const ZOOM_MIN_TODOS = 15;
  const POR_PAGINA = 100;
  const umaCasa = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

  function estiloCandidato(feature) {
    const p = (feature && feature.properties) || {};
    if (p.escondido_por) return { color: "#4b5553", weight: 1.5, dashArray: "4 3", fillColor: COR.escondido, fillOpacity: 0.45 };
    if (p.tipo === "dupla") return { color: "#0f5c31", weight: 2, fillColor: COR.dupla, fillOpacity: 0.5 };
    if (p.tipo === "trinca") return { color: "#7a5c00", weight: 2, fillColor: COR.trinca, fillOpacity: 0.5 };
    return { color: "#0d2f66", weight: 1.5, fillColor: COR.lote, fillOpacity: 0.55 };
  }

  function estiloTodos(feature) {
    const p = (feature && feature.properties) || {};
    if (p.escondido_por) return { color: "#4b5553", weight: 1, dashArray: "3 3", fillColor: COR.escondido, fillOpacity: 0.3 };
    if (p.bate_meta) return { color: COR.lote, weight: 2, fillColor: COR.lote, fillOpacity: 0.25 };
    return { color: "#e2e8f0", weight: 0.8, fillColor: "#ffffff", fillOpacity: 0.05 };
  }

  function iniciar(ctx) {
    const $ = ctx.$;
    const elMapa = $("pr-mapa");
    const botoesFerramenta = ctx.raiz.querySelectorAll(".ferr button[data-ferramenta]");
    const dicaTexto = $("pr-dica-texto");
    const raioControle = $("pr-raio-controle");
    const rangeRaio = $("pr-raio-range");
    const inputRaio = $("pr-raio");
    const raioKm2 = $("pr-raio-km2");
    const desenhoControle = $("pr-desenho-controle");
    const btnDesfazerPonto = $("pr-btn-desfazer-ponto");
    const btnLimparDesenho = $("pr-btn-limpar-desenho");
    const inputDesenhoNome = $("pr-desenho-nome");
    const btnFecharArea = $("pr-btn-fechar-area");
    const areaInfoEl = $("pr-area-info");
    const carregandoEl = $("pr-carregando");
    const carregandoTexto = $("pr-carregando-texto");
    const avisoTodos = $("pr-todos-aviso");
    // Passo 1
    const resArea = $("pr-res-area");
    const inputCentro = $("pr-busca");
    const centroOpcoes = $("pr-centro-opcoes");
    const btnEntorno = $("pr-btn-entorno");
    const btnMarechal = $("pr-btn-marechal");
    const selRegioes = $("pr-regioes");
    const btnRegiao = $("pr-btn-regiao");
    const btnExcluirRegiao = $("pr-btn-excluir-regiao");
    const confirmaExcluir = $("pr-excluir-confirma");
    const textoExcluir = $("pr-excluir-texto");
    const inputRua = $("pr-faixa-rua");
    const inputLargura = $("pr-faixa-largura");
    const btnFaixa = $("pr-btn-faixa");
    const faixaSugestoes = $("pr-faixa-sugestoes");
    const inputArquivo = $("pr-arquivo-kmz");
    const btnKmz = $("pr-btn-kmz");
    // Passos 2 e 3 (premissas comuns, editadas aqui)
    const campo = {
      criterio: $("pr-p-criterio"), meta: $("pr-p-meta"), areaMin: $("pr-p-area-min"), preco: $("pr-p-preco"),
      areaMax: $("pr-p-area-max"), limite: $("pr-p-limite"), triagem: $("pr-p-triagem"),
      duplas: $("pr-p-duplas"), trincas: $("pr-p-trincas"), divisa: $("pr-p-divisa"),
      divisaValor: $("pr-p-divisa-valor"), cortes: $("pr-p-cortes"), erro: $("pr-p-erro")
    };
    const resMeta = $("pr-res-meta");
    const resFiltros = $("pr-res-filtros");
    const linhasCriterio = ctx.raiz.querySelectorAll("[data-criterio]");
    // Detalhe, resultados e painéis flutuantes
    const painelPassos = $("pr-painel-passos");
    const setaPassos = $("pr-seta-passos");
    const passoArea = $("pr-passo-area");
    const passoMeta = $("pr-passo-meta");
    const painelDetalhe = $("pr-painel-detalhe");
    const setaDetalhe = $("pr-seta-detalhe");
    const painelResultados = $("pr-painel-resultados");
    const setaResultados = $("pr-seta-resultados");
    const detalheEl = $("pr-detalhe");
    const contadores = ctx.raiz.querySelectorAll(".contadores .filtro[data-tipo]");
    const selZona = $("pr-filtro-zona");
    const selUso = $("pr-filtro-uso");
    const botoesModo = ctx.raiz.querySelectorAll(".modo button[data-modo]");
    const chkVerTodas = $("pr-ver-todas");
    const rotuloVerTodas = $("pr-ver-todas-rotulo");
    const btnPagAnt = $("pr-pag-ant");
    const btnPagProx = $("pr-pag-prox");
    const pagInfo = $("pr-pag-info");
    const btnCsv = $("pr-btn-csv");
    const btnKmzEntorno = $("pr-btn-kmz-entorno");
    const msgEntorno = $("pr-entorno-msg");
    const corpoTabela = $("pr-tabela-corpo");
    const cabecalhos = ctx.raiz.querySelectorAll("#pr-tabela-cabecalho th");

    const mapa = window.RaioX.criarMapa(ctx, "pr", ["agua", "melhoramento", "alta_tensao"]);

    function definirPainelRecolhido(painel, botao, recolher, setaAberto, setaFechado) {
      painel.classList.toggle("recolhido", Boolean(recolher));
      botao.textContent = recolher ? setaFechado : setaAberto;
      botao.setAttribute("aria-expanded", recolher ? "false" : "true");
    }
    setaPassos.addEventListener("click", () => definirPainelRecolhido(painelPassos, setaPassos, !painelPassos.classList.contains("recolhido"), "◀", "▶"));
    setaDetalhe.addEventListener("click", () => definirPainelRecolhido(painelDetalhe, setaDetalhe, !painelDetalhe.classList.contains("recolhido"), "▶", "◀"));
    setaResultados.addEventListener("click", () => definirPainelRecolhido(painelResultados, setaResultados, !painelResultados.classList.contains("recolhido"), "▼", "▲"));
    // A tabela recolhida muda de altura conforme a largura (os controles quebram de linha): os cantos do
    // mapa se afastam pela altura REAL dela, medida aqui, e não por um valor chutado no CSS.
    const gradeProspectar = ctx.raiz.querySelector(".grade-prospectar");
    new ResizeObserver(() => {
      const h = painelResultados.getBoundingClientRect().height;
      if (h > 0) gradeProspectar.style.setProperty("--ofs-baixo", Math.ceil(h + 12) + "px");
    }).observe(painelResultados);

    let ferramenta = "lote";
    let dados = null;             // última resposta do entorno
    let tabela = null;            // última página da tabela
    let selecionado = null;       // chave da linha selecionada
    let detalheAtual = null;      // último detalhe mostrado (para o estado "em foco")
    let calculando = false;
    let contadorArea = 0, contadorTabela = 0, contadorTodos = 0, contadorDetalhe = 0;
    let camadaArea = null, camadaCandidatos = null, camadaTodos = null, camadaFoco = null;
    let timerTodos = null;
    const camadasPorChave = new Map();
    let pontoMarcado = null, marcadorPonto = null, circuloPrevia = null;
    let vertices = [];
    let camadaDesenho = null;
    const consulta = { modo: "oportunidades", filtro: "todas", ordem: "vgv", decrescente: true, ver_todas: false, pagina: 1, por_pagina: POR_PAGINA, zona: null, uso: null };

    const msgE = (t, tipo) => mostrarMsg(msgEntorno, t, tipo);
    const limparMsgE = () => esconderMsg(msgEntorno);

    function premissasOuErro() {
      const p = window.RaioX.premissas.atuais();
      if (!p) throw new Error("as premissas ainda não foram lidas; aguarde a ponte com o Python");
      return p;
    }

    function carregando(texto) {
      carregandoTexto.textContent = texto || "";
      carregandoEl.classList.toggle("hidden", !texto);
    }

    function atualizarBotoes() {
      const f = focoComum.atual();
      btnEntorno.disabled = calculando || !f;
      for (const b of [btnFaixa, btnMarechal, btnKmz]) b.disabled = calculando;
      btnRegiao.disabled = calculando || !selRegioes.value;
      btnExcluirRegiao.disabled = calculando || !selRegioes.value;
      btnCsv.disabled = calculando || !dados;
      btnKmzEntorno.disabled = calculando || !dados;
      btnFecharArea.disabled = calculando || vertices.length < 3;
      btnDesfazerPonto.disabled = calculando || !vertices.length;
      btnLimparDesenho.disabled = calculando || !vertices.length;
    }

    // --- Ferramentas do mapa (clicar e ir) ---
    function escolherFerramenta(f) {
      ferramenta = f;
      botoesFerramenta.forEach((b) => b.setAttribute("aria-pressed", b.dataset.ferramenta === f ? "true" : "false"));
      elMapa.classList.remove("ferr-lote", "ferr-raio", "ferr-desenho");
      elMapa.classList.add("ferr-" + f);
      if (f === "desenho") mapa.map.doubleClickZoom.disable(); else mapa.map.doubleClickZoom.enable();
      atualizarDica();
    }
    botoesFerramenta.forEach((b) => b.addEventListener("click", ctx.proteger(() => escolherFerramenta(b.dataset.ferramenta))));

    function aoTeclar(e) {
      if (!ctx.ativa() || e.ctrlKey || e.altKey || e.metaKey) return;
      const alvo = e.target;
      if (alvo && alvo.closest && alvo.closest("input, select, textarea, [contenteditable]")) return;
      const f = TECLAS[String(e.key).toLowerCase()];
      if (!f) return;
      e.preventDefault();
      escolherFerramenta(f);
    }
    document.addEventListener("keydown", ctx.proteger(aoTeclar));

    function areaCircular() {
      return Boolean(dados) && (dados.area.tipo === "circulo" || dados.area.tipo === "ponto");
    }

    function atualizarDica() {
      dicaTexto.textContent = DICAS[ferramenta];
      raioControle.classList.toggle("hidden", !(ferramenta === "raio" || (ferramenta === "lote" && areaCircular())));
      desenhoControle.classList.toggle("hidden", ferramenta !== "desenho");
      if (ferramenta === "desenho") {
        dicaTexto.textContent = vertices.length
          ? vertices.length + " ponto(s). " + (vertices.length >= 3 ? "Duplo clique ou “Fechar e calcular” termina." : "Faltam " + (3 - vertices.length) + " para fechar.")
          : DICAS.desenho;
      }
      atualizarBotoes();
    }

    // --- Raio (círculo em volta do foco ou do ponto marcado) ---
    function escreverRaio(v) {
      inputRaio.value = fmt.inteiro.format(v);
      rangeRaio.value = String(Math.min(RAIO_MAX, Math.max(RAIO_MIN, v)));
      raioKm2.textContent = "m · " + fmt.km2.format(Math.PI * (v / 1000) ** 2) + " km²";
    }

    function raioDigitado() {
      const v = parsearNumeroDigitado(inputRaio.value);
      if (v === null || Number.isNaN(v) || v < RAIO_MIN || v > RAIO_MAX) {
        throw new Error("o raio precisa ficar entre 100 e 5.000 m (ex.: 1.500)");
      }
      return v;
    }

    function centroDaPrevia() {
      if (pontoMarcado && (ferramenta === "raio" || (dados && dados.area.tipo === "ponto"))) return pontoMarcado;
      const f = focoComum.atual();
      return f && dados && dados.area.tipo === "circulo" ? L.latLng(f.ponto[0], f.ponto[1]) : null;
    }

    function atualizarPrevia(raio) {
      const c = centroDaPrevia();
      if (!c) { if (circuloPrevia) { mapa.map.removeLayer(circuloPrevia); circuloPrevia = null; } return; }
      if (!circuloPrevia) {
        circuloPrevia = L.circle(c, { radius: raio, color: COR.foco, weight: 2, dashArray: "8 5", fillColor: COR.foco, fillOpacity: 0.05, interactive: false }).addTo(mapa.map);
      } else {
        circuloPrevia.setLatLng(c);
        circuloPrevia.setRadius(raio);
      }
    }

    async function aplicarRaio() {
      let raio;
      try { raio = raioDigitado(); } catch (e) { msgE("Raio inválido: " + window.RaioX.mensagemDeErro(e) + ".", "erro"); return; }
      escreverRaio(raio);
      atualizarPrevia(raio);
      const p = premissasOuErro();
      if (p.raio_entorno_m !== raio) await window.RaioX.premissas.alterar({ raio_entorno_m: raio }, false);
      if (dados && dados.area.tipo === "circulo") await calcularCirculoFoco();
      else if (pontoMarcado && (ferramenta === "raio" || (dados && dados.area.tipo === "ponto"))) await calcularPonto();
    }

    rangeRaio.addEventListener("input", ctx.proteger(() => {
      const v = Number(rangeRaio.value);
      inputRaio.value = fmt.inteiro.format(v);
      raioKm2.textContent = "m · " + fmt.km2.format(Math.PI * (v / 1000) ** 2) + " km²";
      atualizarPrevia(v);
    }));
    rangeRaio.addEventListener("change", ctx.proteger(aplicarRaio));
    inputRaio.addEventListener("change", ctx.proteger(aplicarRaio));
    inputRaio.addEventListener("keydown", ctx.proteger((e) => { if (e.key === "Enter") { e.preventDefault(); return aplicarRaio(); } return undefined; }));

    // --- Clique no mapa ---
    function aoClicarMapa(latlng) {
      if (calculando) return undefined;
      if (ferramenta === "raio") { marcarPonto(latlng); return calcularPonto(); }
      if (ferramenta === "desenho") { adicionarVertice(latlng); return undefined; }
      return escolherNoPonto(latlng);
    }
    mapa.map.on("click", ctx.proteger((e) => aoClicarMapa(e.latlng)));
    mapa.map.on("dblclick", ctx.proteger((e) => {
      if (ferramenta !== "desenho") return undefined;
      L.DomEvent.stop(e);
      return fecharArea();
    }));

    // Ferramenta L: o lote do cadastro sob o clique vai para o foco (e abre o detalhe, se estiver na área).
    async function escolherNoPonto(latlng) {
      const res = await chamar("prospectar_lote_no_ponto", latlng.lng, latlng.lat);
      if (!res.ok) { detalheEl.replaceChildren(el("p", "msg erro", res.erro)); return; }
      if (res.tipo === "Nenhum") {
        detalheEl.replaceChildren(el("p", "vazio-painel", "Nenhum lote do cadastro neste ponto (rua, praça ou fora da base). Clique dentro de um lote."));
        return;
      }
      if (res.tipo === "Candidatos") {
        detalheEl.replaceChildren(listaOpcoes(ctx, fmt.inteiro.format(res.opcoes.length) + " lotes neste ponto (condomínio no mesmo lote fiscal). Escolha um:",
          res.opcoes, (op) => escolherLote(op.cd_identificador, res.chaves[op.cd_identificador])));
        return;
      }
      if (res.tipo !== "Lote") throw new Error("tipo de resposta desconhecido: " + res.tipo);
      await escolherLote(res.lote.cd_identificador, res.chave);
    }

    async function escolherLote(cd, chave) {
      if (chave) { await selecionar(chave, true); return; }
      detalheAtual = null;
      const f = await focoComum.definir([cd], "prospectar");
      selecionado = null;
      marcarLinhas();
      mostrarCartaoFoco(f, dados ? "Este lote fica fora da área calculada." : "Escolha a área de busca para ver as oportunidades em volta.");
    }

    // --- Marcar raio (círculo em volta de um ponto) ---
    function marcarPonto(latlng) {
      pontoMarcado = L.latLng(latlng.lat, latlng.lng);
      if (!marcadorPonto) {
        marcadorPonto = L.marker(pontoMarcado, { draggable: true, title: "Centro do círculo (arraste para mudar)" }).addTo(mapa.map);
        marcadorPonto.on("drag", () => { pontoMarcado = marcadorPonto.getLatLng(); atualizarPrevia(raioSeguro()); });
        marcadorPonto.on("dragend", ctx.proteger(() => { pontoMarcado = marcadorPonto.getLatLng(); return calcularPonto(); }));
      } else {
        marcadorPonto.setLatLng(pontoMarcado);
      }
      atualizarPrevia(raioSeguro());
    }

    function raioSeguro() {
      try { return raioDigitado(); } catch (e) { return Number(rangeRaio.value); }
    }

    function limparPonto() {
      for (const c of [marcadorPonto, circuloPrevia]) if (c) mapa.map.removeLayer(c);
      marcadorPonto = circuloPrevia = null;
      pontoMarcado = null;
    }

    async function calcularPonto() {
      if (!pontoMarcado) { msgE("Clique no mapa para marcar o centro do círculo.", "erro"); return; }
      let raio;
      try { raio = raioDigitado(); } catch (e) { msgE("Raio inválido: " + window.RaioX.mensagemDeErro(e) + ".", "erro"); return; }
      await executarArea("Calculando o círculo de " + fmt.inteiro.format(raio) + " m do ponto marcado…", "prospectar_ponto",
        [pontoMarcado.lng, pontoMarcado.lat, raio, premissasOuErro()]);
    }

    // --- Desenhar área ---
    function desenharRascunho() {
      if (camadaDesenho) mapa.map.removeLayer(camadaDesenho);
      camadaDesenho = null;
      if (vertices.length) {
        camadaDesenho = L.layerGroup([
          L.polyline(vertices.concat(vertices.length > 2 ? [vertices[0]] : []), { color: COR.foco, weight: 2, dashArray: "5 4", interactive: false }),
          ...vertices.map((v) => L.circleMarker(v, { radius: 4, color: "#ffffff", weight: 2, fillColor: COR.foco, fillOpacity: 1, interactive: false }))
        ]).addTo(mapa.map);
      }
      atualizarDica();
    }

    function adicionarVertice(latlng) {
      const ultimo = vertices[vertices.length - 1];
      // O duplo clique também dispara dois cliques no mesmo lugar: não repete o ponto.
      if (ultimo && ultimo.distanceTo(latlng) < 0.5) return;
      vertices.push(L.latLng(latlng.lat, latlng.lng));
      desenharRascunho();
    }

    function limparDesenho() {
      vertices = [];
      desenharRascunho();
    }

    async function fecharArea() {
      if (vertices.length < 3) { msgE("Desenhe pelo menos 3 pontos para fechar a área.", "erro"); return; }
      const nome = inputDesenhoNome.value.trim() || null;
      await executarArea("Calculando a área desenhada…", "prospectar_desenho", [vertices.map((v) => [v.lng, v.lat]), nome, premissasOuErro()]);
      if (dados && dados.area.tipo === "desenho") {
        limparDesenho();
        inputDesenhoNome.value = "";
        escolherFerramenta("lote");
        if (nome) await atualizarRegioes();
      }
    }

    btnFecharArea.addEventListener("click", ctx.proteger(fecharArea));
    btnDesfazerPonto.addEventListener("click", ctx.proteger(() => { vertices.pop(); desenharRascunho(); }));
    btnLimparDesenho.addEventListener("click", ctx.proteger(limparDesenho));

    // --- Passos 2 e 3: meta, preço, triagem e composições ---
    function montarTriagem(opcoes) {
      campo.triagem.replaceChildren();
      for (const op of opcoes) {
        const label = el("label", "chk");
        const chk = el("input");
        chk.type = "checkbox";
        chk.dataset.triagem = op.id;
        chk.dataset.rotulo = op.rotulo.toLowerCase();
        chk.addEventListener("change", ctx.proteger(aoMudarMeta));
        label.appendChild(chk);
        label.appendChild(el("span", null, "Esconder " + op.rotulo.toLowerCase()));
        campo.triagem.appendChild(label);
      }
    }

    function resumoMeta(p) {
      const preco = p.preco_m2 != null ? fmt.moeda.format(p.preco_m2) + "/m²" : (p.ticket_unidade != null ? "pelo ticket" : "sem preço");
      return (p.criterio_meta === "area" ? "área ≥ " + fmt.inteiro.format(p.area_minima_m2) + " m²" : "VGV ≥ " + fmt.moeda.format(p.meta_vgv)) + " · " + preco;
    }

    function resumoFiltros(p) {
      const escondem = Array.from(campo.triagem.querySelectorAll("input[data-triagem]")).filter((c) => p.triagem_esconde.includes(c.dataset.triagem)).map((c) => c.dataset.rotulo.split(" ")[0]);
      const comp = [p.mostrar_duplas ? "duplas" : null, p.mostrar_trincas ? "trincas" : null].filter(Boolean).join(" e ") || "sem composições";
      return fmt.inteiro.format(p.limite_esconder_pct) + "% · " + (escondem.length ? escondem.join(", ") : "não esconde") + " · " + comp;
    }

    function sincronizarMeta() {
      const p = window.RaioX.premissas.atuais();
      if (!p) return;
      campo.criterio.value = p.criterio_meta;
      linhasCriterio.forEach((l) => l.classList.toggle("hidden", l.dataset.criterio !== p.criterio_meta));
      campo.meta.value = fmt.decimal.format(p.meta_vgv / 1e6);
      campo.areaMin.value = fmt.inteiro.format(p.area_minima_m2);
      campo.preco.value = p.preco_m2 != null ? fmt.inteiro.format(p.preco_m2) : "";
      campo.areaMax.value = fmt.inteiro.format(p.area_max_lote_m2);
      campo.limite.value = fmt.inteiro.format(p.limite_esconder_pct);
      campo.triagem.querySelectorAll("input[data-triagem]").forEach((c) => { c.checked = p.triagem_esconde.includes(c.dataset.triagem); });
      campo.duplas.checked = Boolean(p.mostrar_duplas);
      campo.trincas.checked = Boolean(p.mostrar_trincas);
      campo.divisa.value = String(p.divisa_min_m);
      campo.divisaValor.textContent = fmt.inteiro.format(p.divisa_min_m);
      resMeta.textContent = resumoMeta(p);
      resFiltros.textContent = resumoFiltros(p);
    }

    function lerMeta() {
      const erros = [];
      const numero = (input, rotulo, opcional) => {
        const v = parsearNumeroDigitado(input.value);
        if (opcional && v === null) return null;
        if (v === null || Number.isNaN(v) || v <= 0) { erros.push(rotulo + " precisa ser um número maior que zero"); input.classList.add("campo-com-erro"); return null; }
        input.classList.remove("campo-com-erro");
        return v;
      };
      const meta = numero(campo.meta, "A meta de VGV");
      const areaMin = numero(campo.areaMin, "A área mínima");
      const preco = numero(campo.preco, "O preço por m²", true);
      const areaMax = numero(campo.areaMax, "A área máxima");
      const limite = numero(campo.limite, "O limite da triagem");
      if (erros.length) {
        campo.erro.textContent = erros.join("; ") + ".";
        campo.erro.classList.remove("hidden");
        return null;
      }
      campo.erro.classList.add("hidden");
      return {
        criterio_meta: campo.criterio.value,
        meta_vgv: meta * 1e6,
        area_minima_m2: areaMin,
        preco_m2: preco,
        area_max_lote_m2: areaMax,
        limite_esconder_pct: limite,
        triagem_esconde: Array.from(campo.triagem.querySelectorAll("input[data-triagem]")).filter((c) => c.checked).map((c) => c.dataset.triagem),
        mostrar_duplas: campo.duplas.checked,
        mostrar_trincas: campo.trincas.checked,
        divisa_min_m: Number(campo.divisa.value)
      };
    }

    async function aoMudarMeta() {
      const parcial = lerMeta();
      if (parcial) await window.RaioX.premissas.alterar(parcial, true);
    }

    campo.criterio.addEventListener("change", ctx.proteger(aoMudarMeta));
    for (const c of [campo.meta, campo.areaMin, campo.preco, campo.areaMax, campo.limite]) {
      c.addEventListener("change", ctx.proteger(aoMudarMeta));
      c.addEventListener("keydown", ctx.proteger((e) => { if (e.key === "Enter") { e.preventDefault(); return aoMudarMeta(); } return undefined; }));
    }
    for (const c of [campo.duplas, campo.trincas]) c.addEventListener("change", ctx.proteger(aoMudarMeta));
    campo.divisa.addEventListener("input", () => { campo.divisaValor.textContent = fmt.inteiro.format(Number(campo.divisa.value)); });
    campo.divisa.addEventListener("change", ctx.proteger(aoMudarMeta));

    // --- Terreno em foco no mapa ---
    function desenharFoco(f) {
      if (camadaFoco) mapa.map.removeLayer(camadaFoco);
      camadaFoco = null;
      if (!f) return;
      camadaFoco = L.geoJSON(f.geojson, {
        pane: "foco", renderer: mapa.rendFoco, interactive: false,
        style: { color: COR.foco, weight: 3, opacity: 1, fillColor: COR.foco, fillOpacity: 0.12 }
      }).addTo(mapa.map);
    }

    function enquadrarFoco(f) {
      const b = L.geoJSON(f.geojson).getBounds();
      if (b.isValid()) mapa.map.fitBounds(b, { padding: [60, 60], maxZoom: 17 });
    }

    // --- Passo 1: círculo em volta do foco, faixa, Marechal Tito, regiões e KMZ ---
    async function calcularCirculoFoco() {
      const f = focoComum.atual();
      if (!f) { msgE("Ponha um lote em foco (clique nele no mapa ou busque o SQL no passo 1).", "erro"); return; }
      let raio;
      try { raio = raioDigitado(); } catch (e) { msgE("Raio inválido: " + window.RaioX.mensagemDeErro(e) + ".", "erro"); return; }
      limparPonto();
      const centro = await chamar("prospectar_escolher_centro", f.ids[0]);
      if (!centro.ok) { msgE(centro.erro, "erro"); return; }
      if (centro.tipo !== "Centro") { msgE(centro.resultado.motivo || "Lote em foco não encontrado na base.", "erro"); return; }
      await executarArea("Calculando o círculo de " + fmt.inteiro.format(raio) + " m em volta de " + f.sql + "…", "prospectar_entorno", [raio, premissasOuErro()]);
    }

    async function buscarCentro(texto) {
      centroOpcoes.replaceChildren(carregandoLinha("Procurando o lote…"));
      const res = await chamar("prospectar_buscar_centro", texto);
      centroOpcoes.replaceChildren();
      if (!res.ok) { centroOpcoes.appendChild(el("p", "msg erro", res.erro)); return; }
      if (res.tipo === "Centro") {
        for (const a of res.avisos || []) centroOpcoes.appendChild(el("p", "nota", a));
        await focarECalcular(res.lote.cd_identificador);
      } else if (res.tipo === "Candidatos") {
        centroOpcoes.appendChild(listaOpcoes(ctx, fmt.inteiro.format(res.resultado.opcoes.length) + " opções para “" + res.resultado.texto + "”. Qual é o lote?",
          res.resultado.opcoes, (op) => { centroOpcoes.replaceChildren(); return focarECalcular(op.cd_identificador); }));
      } else if (res.tipo === "NaoEncontrado") {
        centroOpcoes.appendChild(el("p", "msg erro", "Não encontrado: " + res.resultado.motivo + " Isso não prova que o lote não exista: confira a grafia ou tente pelo SQL."));
      } else {
        throw new Error("tipo de resposta desconhecido: " + res.tipo);
      }
    }

    async function focarECalcular(cd) {
      const f = await focoComum.definir([cd], "prospectar");
      enquadrarFoco(f);
      await calcularCirculoFoco();
    }

    function metrosDigitados(input, rotulo) {
      const v = parsearNumeroDigitado(input.value);
      if (v === null || Number.isNaN(v) || v <= 0) throw new Error(rotulo + " precisa ser um número de metros maior que zero (ex.: 1.500)");
      return v;
    }

    async function verFaixa(texto) {
      let largura;
      try { largura = metrosDigitados(inputLargura, "a largura da faixa"); } catch (e) { msgE("Largura inválida: " + window.RaioX.mensagemDeErro(e) + ".", "erro"); return; }
      if (!texto) { msgE("Digite o nome da rua ou avenida (ex.: AV MAL TITO).", "erro"); return; }
      faixaSugestoes.replaceChildren();
      limparPonto();
      await executarArea("Montando a faixa ao longo de " + texto + "… (área grande pode levar mais de um minuto)", "prospectar_faixa", [texto, largura, premissasOuErro()]);
    }

    async function faixaMarechal() {
      limparPonto();
      await executarArea("Calculando a faixa da Av. Marechal Tito (43,8 km²)… pode levar uns 15 s", "prospectar_faixa_marechal_tito", [premissasOuErro()]);
    }

    function mostrarSugestoes(res) {
      faixaSugestoes.replaceChildren(el("p", "msg erro", res.mensagem));
      if (!(res.sugestoes || []).length) return;
      faixaSugestoes.appendChild(el("p", "nota", "Quis dizer:"));
      const lista = el("div", "opcoes");
      for (const nome of res.sugestoes) {
        const b = el("button", "opcao", nome);
        b.type = "button";
        b.addEventListener("click", ctx.proteger(() => { inputRua.value = nome; return verFaixa(nome); }));
        lista.appendChild(b);
      }
      faixaSugestoes.appendChild(lista);
    }

    async function atualizarRegioes() {
      const res = await chamar("prospectar_listar_regioes");
      if (!res.ok) { msgE(res.erro, "erro"); return; }
      const atual = selRegioes.value;
      selRegioes.replaceChildren();
      const vazio = el("option", null, res.regioes.length ? "Escolher…" : "— nenhuma salva —");
      vazio.value = "";
      selRegioes.appendChild(vazio);
      for (const r of res.regioes) {
        const o = el("option", null, r.nome + " (" + fmt.km2.format(r.area_km2) + " km²)");
        o.value = r.id;
        selRegioes.appendChild(o);
      }
      selRegioes.value = res.regioes.some((r) => r.id === atual) ? atual : "";
      confirmaExcluir.classList.add("hidden");
      atualizarBotoes();
    }
    selRegioes.addEventListener("change", ctx.proteger(() => { confirmaExcluir.classList.add("hidden"); atualizarBotoes(); }));

    function nomeRegiao() { return selRegioes.options[selRegioes.selectedIndex].textContent; }
    btnRegiao.addEventListener("click", ctx.proteger(() => {
      limparPonto();
      return executarArea("Calculando a região " + nomeRegiao() + "…", "prospectar_abrir_regiao", [selRegioes.value, premissasOuErro()]);
    }));
    btnExcluirRegiao.addEventListener("click", ctx.proteger(() => {
      textoExcluir.textContent = "Excluir a região salva " + nomeRegiao() + "? O KMZ original não é apagado.";
      confirmaExcluir.classList.remove("hidden");
    }));
    $("pr-btn-excluir-nao").addEventListener("click", () => confirmaExcluir.classList.add("hidden"));
    $("pr-btn-excluir-sim").addEventListener("click", ctx.proteger(async () => {
      const res = await chamar("prospectar_excluir_regiao", selRegioes.value);
      if (!res.ok) { msgE(res.erro, "erro"); return; }
      await atualizarRegioes();
    }));

    async function carregarArquivo(arquivo) {
      if (!arquivo || !/\.(kmz|kml)$/i.test(arquivo.name)) { msgE("Solte um arquivo .kmz ou .kml válido.", "erro"); return; }
      const b64 = await window.RaioX.lerArquivoBase64(arquivo);
      limparPonto();
      await executarArea("Carregando " + arquivo.name + "… (região grande pode levar mais de um minuto)", "prospectar_carregar_kmz", [arquivo.name, b64, premissasOuErro()]);
      if (dados && dados.area.tipo === "kmz") await atualizarRegioes();
    }
    btnKmz.addEventListener("click", () => inputArquivo.click());
    inputArquivo.addEventListener("change", ctx.proteger(async (e) => {
      const arq = e.target.files && e.target.files[0];
      inputArquivo.value = "";
      if (arq) await carregarArquivo(arq);
    }));

    inputCentro.addEventListener("keydown", ctx.proteger((e) => {
      if (e.key !== "Enter") return undefined;
      e.preventDefault();
      const texto = inputCentro.value.trim();
      return texto ? buscarCentro(texto) : undefined;
    }));
    btnEntorno.addEventListener("click", ctx.proteger(calcularCirculoFoco));
    btnFaixa.addEventListener("click", ctx.proteger(() => verFaixa(inputRua.value.trim())));
    inputRua.addEventListener("keydown", ctx.proteger((e) => {
      if (e.key !== "Enter") return undefined;
      e.preventDefault();
      return verFaixa(inputRua.value.trim());
    }));
    btnMarechal.addEventListener("click", ctx.proteger(faixaMarechal));

    // --- Cálculo das áreas ---
    async function executarArea(texto, metodo, args) {
      const meu = ++contadorArea;
      calculando = true;
      atualizarBotoes();
      carregando(texto);
      limparMsgE();
      try {
        const res = await chamar(metodo, ...args);
        if (meu !== contadorArea) return;
        if (res.ok && res.tipo === "FaixaNaoEncontrada") { mostrarSugestoes(res); return; }
        await processarEntorno(res);
      } finally {
        if (meu === contadorArea) {
          calculando = false;
          carregando(null);
          atualizarBotoes();
        }
      }
    }

    function limparEntorno() {
      dados = null;
      tabela = null;
      selecionado = null;
      camadasPorChave.clear();
      for (const c of [camadaArea, camadaCandidatos, camadaTodos]) if (c) mapa.map.removeLayer(c);
      camadaArea = camadaCandidatos = camadaTodos = null;
      avisoTodos.classList.add("hidden");
      areaInfoEl.textContent = "";
      resArea.textContent = "nenhuma";
      campo.cortes.textContent = "";
      for (const c of contadores) c.querySelector("b").textContent = "0";
      corpoTabela.replaceChildren(linhaVazia("Escolha a área de busca: clique no mapa com uma ferramenta ou use o passo 1."));
      pagInfo.textContent = "";
      atualizarBotoes();
      atualizarDica();
    }

    function rotuloCurtoArea(a) {
      const tipos = { circulo: "círculo · " + fmt.inteiro.format(a.raio_m) + " m", ponto: "ponto · " + fmt.inteiro.format(a.raio_m) + " m", faixa: "faixa", kmz: "região", desenho: "desenho" };
      return (tipos[a.tipo] || a.tipo) + " · " + fmt.km2.format(a.area_km2) + " km²";
    }

    async function processarEntorno(res) {
      if (!res.ok) {
        limparEntorno();
        msgE(res.erro, "erro");
        return;
      }
      if (res.tipo === "Vazio") return;
      if (res.tipo !== "Entorno") throw new Error("tipo de resposta desconhecido: " + res.tipo);
      const enquadrar = !dados || JSON.stringify(dados.area) !== JSON.stringify(res.area);
      const chaveAnterior = selecionado;
      limparEntorno();
      dados = res;

      const a = res.area;
      areaInfoEl.textContent = a.rotulo + " · " + fmt.km2.format(a.area_km2) + " km² · " + fmt.inteiro.format(a.n_lotes) + " lotes · " + umaCasa.format(res.tempo_s) + " s";
      resArea.textContent = rotuloCurtoArea(a);
      campo.cortes.textContent = res.cortes_meta || "";
      for (const c of contadores) c.querySelector("b").textContent = fmt.inteiro.format(res.resumo[c.querySelector("b").dataset.n]);
      if ((res.avisos || []).length) msgE(res.avisos.join(" · "), "aviso");
      if (a.raio_m != null) escreverRaio(a.raio_m);
      atualizarDica();
      atualizarPrevia(a.raio_m != null ? a.raio_m : raioSeguro());
      if (circuloPrevia && a.tipo !== "ponto") { mapa.map.removeLayer(circuloPrevia); circuloPrevia = null; }

      camadaArea = L.geoJSON(res.area_geojson, {
        pane: "camadas", interactive: false,
        style: { color: COR.foco, weight: 2.5, dashArray: "8 5", fillColor: COR.foco, fillOpacity: 0.05 }
      }).addTo(mapa.map);
      camadaCandidatos = L.geoJSON(res.geojson, {
        style: estiloCandidato,
        onEachFeature: (f, layer) => {
          const p = f.properties || {};
          camadasPorChave.set(p.chave, layer);
          const idTxt = (ROTULO_TIPO[p.tipo] || p.tipo || "Lote") + (Array.isArray(p.ids) && p.ids.length ? " " + p.ids.join("+") : "");
          const zonaTxt = Array.isArray(p.zonas) && p.zonas.length ? p.zonas.join("/") : "—";
          const vgvTxt = p.vgv != null ? "R$ " + umaCasa.format(p.vgv / 1e6) + " mi" : "—";
          layer.bindTooltip(idTxt + " · " + fmt.inteiro.format(p.area_m2 || 0) + " m² · " + zonaTxt + " · " + vgvTxt, { sticky: true, className: "tooltip-min" });
          layer.on("click", ctx.proteger((e) => {
            L.DomEvent.stopPropagation(e);
            if (ferramenta !== "lote") return aoClicarMapa(e.latlng);
            return selecionar(p.chave, true);
          }));
        }
      }).addTo(mapa.map);
      // Suprime automaticamente os passos 1 e 2 após calcular a área para liberar espaço visual
      passoArea.open = false;
      passoMeta.open = false;
      if (ferramenta === "raio") escolherFerramenta("lote");
      if (enquadrar) {
        const b = camadaArea.getBounds();
        if (b.isValid()) mapa.map.fitBounds(b, { padding: [30, 30] });
      }
      consulta.pagina = 1;
      await pedirTabela();
      agendarTodos();
      // O detalhe acompanha: a linha que estava aberta, ou o lote em foco se ele estiver na área.
      const f = focoComum.atual();
      // (a chave de dupla/trinca é a posição na lista e muda a cada cálculo: só a de lote é reaproveitada)
      const chave = chaveAnterior && chaveAnterior.startsWith("l") ? chaveAnterior
        : (f && f.tipo === "lote" ? "l" + f.ids[0] : null);
      if (chave) await selecionar(chave, true, true);
      else if (f) mostrarCartaoFoco(f, "O terreno em foco é uma composição: escolha a linha dela na tabela.");
      else detalheEl.replaceChildren(el("p", "vazio-painel", "Clique num lote no mapa (L) ou numa linha da tabela para ver o detalhe aqui."));
    }

    // --- Tabela (paginada no Python) ---
    function linhaVazia(texto) {
      const tr = el("tr");
      const td = el("td", "vazio", texto);
      td.colSpan = cabecalhos.length;
      tr.appendChild(td);
      return tr;
    }

    function preencherOpcoes(sel, valores, rotuloTodos, atual) {
      sel.replaceChildren(el("option", null, rotuloTodos));
      sel.firstChild.value = "";
      for (const v of valores) {
        const o = el("option", null, v);
        o.value = v;
        sel.appendChild(o);
      }
      sel.value = valores.includes(atual) ? atual : "";
    }

    async function pedirTabela() {
      if (!dados) return;
      const meu = ++contadorTabela;
      const res = await chamar("prospectar_tabela", Object.assign({}, consulta));
      if (meu !== contadorTabela) return;
      if (!res.ok) { msgE(res.erro, "erro"); return; }
      tabela = res;
      renderizarTabela();
    }

    function celula(tr, texto, cls) {
      const td = el("td", cls || null, texto);
      td.title = texto == null ? "" : String(texto);  // célula é cortada com reticências: o texto inteiro fica no balão
      tr.appendChild(td);
    }

    function marcarLinhas() {
      corpoTabela.querySelectorAll("tr[data-chave]").forEach((tr) => tr.classList.toggle("sel", tr.dataset.chave === selecionado));
    }

    function renderizarTabela() {
      preencherOpcoes(selZona, tabela.opcoes.zonas, "Zona: todas", consulta.zona);
      preencherOpcoes(selUso, tabela.opcoes.usos, "Uso: todos", consulta.uso);
      rotuloVerTodas.textContent = "Ver todas (" + fmt.inteiro.format(tabela.total_filtrado) + ")";
      chkVerTodas.checked = consulta.ver_todas;
      pagInfo.textContent = consulta.ver_todas
        ? "página " + tabela.pagina + " de " + tabela.n_paginas
        : "as " + Math.min(tabela.top_padrao, tabela.total_filtrado) + " primeiras";
      btnPagAnt.disabled = !consulta.ver_todas || tabela.pagina <= 1;
      btnPagProx.disabled = !consulta.ver_todas || tabela.pagina >= tabela.n_paginas;
      cabecalhos.forEach((th) => {
        if (th.dataset.ordem === consulta.ordem) th.setAttribute("aria-sort", consulta.decrescente ? "descending" : "ascending");
        else th.removeAttribute("aria-sort");
      });
      contadores.forEach((c) => c.setAttribute("aria-pressed", c.dataset.tipo === consulta.filtro ? "true" : "false"));
      if (!tabela.linhas.length) {
        corpoTabela.replaceChildren(linhaVazia(dados.entorno.candidatos.length || consulta.modo === "todos"
          ? "Nenhuma linha para o filtro escolhido." : "Nenhuma oportunidade com a meta e a triagem atuais."));
        return;
      }
      const frag = document.createDocumentFragment();
      for (const l of tabela.linhas) {
        const tr = el("tr");
        tr.dataset.chave = l.chave;
        tr.tabIndex = 0;
        if (l.escondido_por) tr.classList.add("escondida");
        else if (l.tipo === "lote" && !l.bate_meta) tr.classList.add("abaixo");
        if (l.chave === selecionado) tr.classList.add("sel");
        const tdTipo = el("td");
        const cat = l.escondido_por ? "escondido" : l.tipo;
        const bola = el("span", "bola");
        bola.style.background = COR[cat] || COR.lote;
        tdTipo.appendChild(bola);
        tdTipo.appendChild(document.createTextNode(l.escondido_por ? "Escondido" : (l.tipo === "lote" && !l.bate_meta ? "Abaixo da meta" : ROTULO_TIPO[l.tipo] || l.tipo)));
        tdTipo.classList.add("tipo-" + l.tipo);
        tr.appendChild(tdTipo);
        celula(tr, l.sql, "n-sql");
        celula(tr, l.endereco);
        celula(tr, fmt.inteiro.format(l.area_m2), "n");
        celula(tr, l.zonas);
        celula(tr, l.ca.replace(".", ","), "n");
        celula(tr, fmt.inteiro.format(l.area_computavel_m2), "n");
        celula(tr, fmt.inteiro.format(l.unidades), "n");
        celula(tr, fmt.moeda.format(l.vgv), "n");
        celula(tr, l.uso || "—");
        celula(tr, l.estacao || "—");
        celula(tr, l.dist_estacao_m == null ? "—" : fmt.inteiro.format(l.dist_estacao_m), "n");
        celula(tr, l.pct_construido == null ? "—" : fmt.inteiro.format(l.pct_construido) + "%", "n");
        celula(tr, l.sinais.length ? l.sinais.join(" · ") : "—");
        const tdUso = el("td", l.uso_porte_bloqueios.length ? "marca-uso" : null, l.uso_porte_bloqueios.length ? l.uso_porte_bloqueios.join(" · ") : "—");
        if (l.uso_porte.length) tdUso.title = l.uso_porte.join("\n");
        tdUso.title = tdUso.textContent;
        tr.appendChild(tdUso);
        celula(tr, l.escondido_por || "—");
        tr.title = l.sql + " · " + l.endereco;
        tr.addEventListener("click", ctx.proteger(() => selecionar(l.chave, false)));
        tr.addEventListener("keydown", ctx.proteger((e) => { if (e.key === "Enter") { e.preventDefault(); return selecionar(l.chave, false); } return undefined; }));
        frag.appendChild(tr);
      }
      corpoTabela.replaceChildren(frag);
    }

    cabecalhos.forEach((th) => th.addEventListener("click", ctx.proteger(() => {
      const col = th.dataset.ordem;
      if (consulta.ordem === col) consulta.decrescente = !consulta.decrescente;
      else { consulta.ordem = col; consulta.decrescente = ["area_m2", "area_computavel_m2", "unidades", "vgv", "pct_construido"].includes(col); }
      consulta.pagina = 1;
      return pedirTabela();
    })));

    function filtrar(tipo) {
      consulta.filtro = tipo;
      consulta.pagina = 1;
      contadores.forEach((c) => c.setAttribute("aria-pressed", c.dataset.tipo === tipo ? "true" : "false"));
      return pedirTabela();
    }
    // Contador clicável: filtra pelo tipo; clicar de novo volta para todas.
    contadores.forEach((c) => c.addEventListener("click", ctx.proteger(() => filtrar(consulta.filtro === c.dataset.tipo ? "todas" : c.dataset.tipo))));
    selZona.addEventListener("change", ctx.proteger(() => { consulta.zona = selZona.value || null; consulta.pagina = 1; return pedirTabela(); }));
    selUso.addEventListener("change", ctx.proteger(() => { consulta.uso = selUso.value || null; consulta.pagina = 1; return pedirTabela(); }));
    chkVerTodas.addEventListener("change", ctx.proteger(() => { consulta.ver_todas = chkVerTodas.checked; consulta.pagina = 1; return pedirTabela(); }));
    btnPagAnt.addEventListener("click", ctx.proteger(() => { consulta.pagina -= 1; return pedirTabela(); }));
    btnPagProx.addEventListener("click", ctx.proteger(() => { consulta.pagina += 1; return pedirTabela(); }));

    // --- Modo de exibição ---
    async function definirModo(modo) {
      consulta.modo = modo;
      // "Todos os lotes" abre com "Ver todas" ligado (paginado); o analista pode voltar às 15 primeiras.
      consulta.ver_todas = modo === "todos";
      consulta.pagina = 1;
      botoesModo.forEach((b) => b.setAttribute("aria-pressed", b.dataset.modo === modo ? "true" : "false"));
      agendarTodos();
      await pedirTabela();
    }
    botoesModo.forEach((b) => b.addEventListener("click", ctx.proteger(() => definirModo(b.dataset.modo))));

    // Modo "Todos os lotes" no mapa: só os lotes do retângulo visível (o Python corta pela área).
    function agendarTodos() {
      if (timerTodos) clearTimeout(timerTodos);
      timerTodos = setTimeout(ctx.proteger(carregarTodos), 300);
    }

    async function carregarTodos() {
      const meu = ++contadorTodos;
      if (camadaTodos && (consulta.modo !== "todos" || !dados)) { mapa.map.removeLayer(camadaTodos); camadaTodos = null; }
      if (consulta.modo !== "todos" || !dados) { avisoTodos.classList.add("hidden"); return; }
      if (mapa.map.getZoom() < ZOOM_MIN_TODOS) {
        if (camadaTodos) { mapa.map.removeLayer(camadaTodos); camadaTodos = null; }
        avisoTodos.textContent = "Todos os lotes: aproxime o mapa para desenhar os " + fmt.inteiro.format(dados.area.n_lotes) + " lotes da área (a tabela já lista todos).";
        avisoTodos.classList.remove("hidden");
        return;
      }
      const b = mapa.map.getBounds();
      const res = await chamar("prospectar_mapa_lotes", [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()], mapa.map.getZoom());
      if (meu !== contadorTodos) return;
      if (!res.ok) { avisoTodos.textContent = res.erro; avisoTodos.classList.remove("hidden"); return; }
      if (camadaTodos) { mapa.map.removeLayer(camadaTodos); camadaTodos = null; }
      if (res.truncado) {
        avisoTodos.textContent = fmt.inteiro.format(res.n) + " lotes neste trecho (o mapa desenha até " + fmt.inteiro.format(res.limite) + "): aproxime mais.";
        avisoTodos.classList.remove("hidden");
        return;
      }
      avisoTodos.classList.add("hidden");
      camadaTodos = L.geoJSON(res.geojson, {
        pane: "camadas",
        style: estiloTodos,
        onEachFeature: (f, layer) => {
          const p = f.properties;
          layer.bindTooltip(p.sql + " · " + fmt.inteiro.format(p.area_m2) + " m² · " + fmt.moeda.format(p.vgv) + (p.escondido_por ? " · escondido: " + p.escondido_por : ""), { sticky: true });
          layer.on("click", ctx.proteger((e) => {
            L.DomEvent.stopPropagation(e);
            if (ferramenta !== "lote") return aoClicarMapa(e.latlng);
            return selecionar(p.chave, true);
          }));
        }
      }).addTo(mapa.map);
      if (camadaCandidatos) camadaCandidatos.bringToFront();
    }
    mapa.map.on("moveend", ctx.proteger(() => { if (consulta.modo === "todos") agendarTodos(); }));

    // --- Seleção e detalhe: escolher uma linha (ou um lote no mapa) põe o terreno em foco ---
    async function selecionar(chave, veioDoMapa, semFoco) {
      selecionado = chave;
      marcarLinhas();
      if (!semFoco && painelDetalhe.classList.contains("recolhido")) {
        definirPainelRecolhido(painelDetalhe, setaDetalhe, false, "▶", "◀");
      }
      const linha = corpoTabela.querySelector('tr[data-chave="' + chave + '"]');
      if (linha && veioDoMapa) linha.scrollIntoView({ block: "nearest" });
      const layer = camadasPorChave.get(chave);
      if (layer && !veioDoMapa) {
        const b = layer.getBounds();
        if (b.isValid()) mapa.map.fitBounds(b, { padding: [50, 50], maxZoom: 18 });
      }
      const meu = ++contadorDetalhe;
      detalheEl.replaceChildren(carregandoLinha("Abrindo o detalhe…"));
      const res = await chamar("prospectar_detalhe", chave);
      if (meu !== contadorDetalhe) return;
      if (!res.ok && semFoco) {
        // Seleção automática do lote em foco depois de um cálculo: fora da área, mostra o cartão do foco.
        selecionado = null;
        marcarLinhas();
        const f = focoComum.atual();
        if (f) mostrarCartaoFoco(f, "O terreno em foco não está entre os lotes da área.");
        return;
      }
      if (!res.ok) { detalheEl.replaceChildren(el("p", "msg erro", res.erro)); return; }
      detalheAtual = res.detalhe;
      const ids = res.detalhe.lotes.map((l) => l.cd_identificador);
      const f = focoComum.atual();
      if (!semFoco && !(f && focoComum.mesmosIds(f.ids, ids))) await focoComum.definir(ids, "prospectar");
      mostrarDetalhe(res.detalhe);
    }

    function dl(pares) {
      const lista = el("dl", "dl");
      for (const [rot, val, cls] of pares) {
        lista.appendChild(el("dt", null, rot));
        lista.appendChild(el("dd", cls || null, val));
      }
      return lista;
    }

    function botao(texto, cls, fn) {
      const b = el("button", "bt" + (cls ? " " + cls : ""), texto);
      b.type = "button";
      b.addEventListener("click", ctx.proteger(fn));
      return b;
    }

    // Garante o foco nestes ids e leva à aba pedida (Raio-X ou Simulador).
    async function focarEIr(ids, aba) {
      const f = focoComum.atual();
      if (!(f && focoComum.mesmosIds(f.ids, ids))) await focoComum.definir(ids, "prospectar");
      return window.RaioX.ativarAba(aba);
    }

    function acoesDoTerreno(ids) {
      const f = focoComum.atual();
      const emFoco = Boolean(f && focoComum.mesmosIds(f.ids, ids));
      const acoes = el("div", "acoes-v");
      if (emFoco) acoes.appendChild(el("p", "nota", "Este é o terreno em foco."));
      else acoes.appendChild(botao("Colocar em foco", "pri", () => focoComum.definir(ids, "prospectar")));
      acoes.appendChild(botao("Abrir no Raio-X", null, () => focarEIr(ids, "lote")));
      acoes.appendChild(botao("Simular", emFoco ? "pri" : null, () => focarEIr(ids, "simulador")));
      return acoes;
    }

    function mostrarDetalhe(d) {
      const frag = document.createDocumentFragment();
      const cat = d.escondido_por ? "escondido" : d.tipo;
      frag.appendChild(el("span", "tag tag-" + cat, (d.escondido_por ? "Escondido · " : "") + (ROTULO_TIPO[d.tipo] || d.tipo) + (d.lotes.length > 1 ? " de " + d.lotes.length + " lotes" : "")));
      frag.appendChild(el("h2", null, d.lotes.map((l) => l.endereco || "—").join(" + ")));
      const pares = [["SQL", d.lotes.map((l) => l.sql).join(" + ")], ["Área do terreno", fmt.inteiro.format(d.area_m2) + " m²"]];
      if (d.lotes.length === 1) {
        const l = d.lotes[0];
        pares.push(["Zona", l.zona], ["CA", fmt.ca.format(l.ca)]);
        if (l.estacao) pares.push(["Estação mais próxima", l.estacao + " · " + fmt.inteiro.format(l.dist_estacao_m) + " m", "texto"]);
        pares.push(["Uso", (l.uso || "—") + (l.pct_construido == null ? "" : " · " + fmt.inteiro.format(l.pct_construido) + "% construído"), "texto"]);
      }
      pares.push(["Área computável", fmt.inteiro.format(d.area_computavel_m2) + " m²"], ["VGV potencial", fmt.moeda.format(d.vgv)]);
      frag.appendChild(dl(pares));
      const conta = el("ol", "conta");
      for (const passo of d.conta) conta.appendChild(el("li", null, passo));
      frag.appendChild(conta);
      if (d.escondido_por) frag.appendChild(el("p", "msg aviso", "Escondido por: " + d.escondido_por));
      if (d.divisas.length) {
        frag.appendChild(el("div", "sub", "Divisa entre os lotes (mínimo pedido: " + fmt.inteiro.format(d.divisa_minima_m) + " m)"));
        for (const dv of d.divisas) frag.appendChild(el("p", "nota", dv.texto));
      }
      frag.appendChild(el("p", "nota", "Sinais: " + (d.sinais.length ? d.sinais.join(" · ") : "nenhum")));
      if (d.uso_porte.length) {
        frag.appendChild(el("div", "sub", "Uso e porte (motor antigo; fatos, confira na LPUOS)"));
        for (const f of d.uso_porte) frag.appendChild(el("p", f.startsWith("Bloqueia") ? "nota marca-uso" : "nota", f));
      }
      const ids = d.lotes.map((l) => l.cd_identificador);
      frag.appendChild(acoesDoTerreno(ids));
      if (d.lotes.length > 1) {
        frag.appendChild(el("div", "sub", "Lotes que compõem"));
        for (const l of d.lotes) {
          const c = el("div", "lote-cartao");
          c.appendChild(el("div", "titulo", l.endereco || "—"));
          c.appendChild(el("div", "nota", "SQL " + l.sql + " · " + fmt.inteiro.format(l.area_m2) + " m² · " + l.zona + " · CA " + fmt.ca.format(l.ca)));
          c.appendChild(el("div", "nota", "Computável " + fmt.inteiro.format(l.area_computavel_m2) + " m² · " + fmt.moeda.format(l.vgv) + (l.sinais.length ? " · " + l.sinais.join(" · ") : "")));
          if (l.escondido_por) c.appendChild(el("div", "nota marca-uso", "Escondido por: " + l.escondido_por));
          c.appendChild(botao("Ver este lote no Raio-X", null, async () => {
            const f = focoComum.atual();
            if (!(f && focoComum.mesmosIds(f.ids, ids))) await focoComum.definir(ids, "prospectar");
            return window.RaioX.pedir("lote", "mostrarLote", l.cd_identificador);
          }));
          frag.appendChild(c);
        }
      }
      detalheEl.replaceChildren(frag);
    }

    // Cartão do foco quando ele não é uma linha da área (clique fora da área, ou foco vindo de outra aba).
    function mostrarCartaoFoco(f, nota) {
      detalheAtual = null;
      const frag = document.createDocumentFragment();
      frag.appendChild(el("span", "tag tag-foco", "Em foco · " + (ROTULO_TIPO[f.tipo] || f.tipo)));
      frag.appendChild(el("h2", null, f.endereco));
      frag.appendChild(dl([["SQL", f.sql], ["Área do terreno", fmt.inteiro.format(f.area_m2) + " m²"], ["Zona", f.zona], ["CA", fmt.ca.format(f.ca)]]));
      frag.appendChild(el("p", "nota", nota));
      const acoes = el("div", "acoes-v");
      acoes.appendChild(botao("Calcular o círculo de " + inputRaio.value + " m em volta", "pri", calcularCirculoFoco));
      acoes.appendChild(botao("Abrir no Raio-X", null, () => window.RaioX.ativarAba("lote")));
      acoes.appendChild(botao("Simular", null, () => window.RaioX.ativarAba("simulador")));
      frag.appendChild(acoes);
      detalheEl.replaceChildren(frag);
    }

    // --- Exportações ---
    async function exportar(botaoEl, pedido, rotuloOk) {
      const original = botaoEl.textContent;
      botaoEl.textContent = "Exportando…";
      botaoEl.disabled = true;
      try {
        const res = await pedido();
        msgE(res.ok ? rotuloOk + ": " + res.caminho : res.erro, res.ok ? "ok" : "erro");
      } finally {
        botaoEl.textContent = original;
        atualizarBotoes();
      }
    }
    btnCsv.addEventListener("click", ctx.proteger(() => exportar(btnCsv,
      () => chamar("prospectar_exportar_csv", Object.assign({}, consulta)), "CSV gravado (as linhas da tabela)")));
    btnKmzEntorno.addEventListener("click", ctx.proteger(() => exportar(btnKmzEntorno,
      () => chamar("prospectar_exportar_kmz"), "KMZ do entorno gravado")));

    limparEntorno();
    escolherFerramenta("lote");

    return {
      async aoPonteProntas() {
        await mapa.montarListaVer();
        const op = await chamar("prospectar_opcoes");
        if (!op.ok) throw new Error(op.erro);
        montarTriagem(op.triagem);
        sincronizarMeta();
        await atualizarRegioes();
      },
      aoMudarPremissas(motivo) {
        const p = window.RaioX.premissas.atuais();
        sincronizarMeta();
        if (motivo === "carga") { escreverRaio(p.raio_entorno_m); return undefined; }
        if (motivo !== "alteracao" || !dados) return undefined;
        return executarArea("Recalculando com as premissas novas…", "prospectar_recalcular", [premissasOuErro()]);
      },
      aoAtivar() { mapa.invalidar(); },
      // Foco mudou (aqui ou noutra aba): contorno laranja no mapa e o estado do detalhe.
      aoMudarFoco(f, origem) {
        desenharFoco(f);
        atualizarBotoes();
        if (origem === "prospectar") { if (detalheAtual) mostrarDetalhe(detalheAtual); return; }
        selecionado = null;
        marcarLinhas();
        if (f) mostrarCartaoFoco(f, dados ? "Terreno escolhido noutra aba." : "Escolha a área de busca ou calcule o círculo em volta dele.");
        else detalheEl.replaceChildren(el("p", "vazio-painel", "Clique num lote no mapa (L) ou numa linha da tabela para ver o detalhe aqui."));
      },
      soltarArquivo: (arquivo) => carregarArquivo(arquivo),
      // Barra do foco: "Ver entorno" = círculo em volta do terreno em foco.
      async verEntornoDoFoco(raio) {
        if (raio != null) escreverRaio(raio);
        const f = focoComum.atual();
        if (f) enquadrarFoco(f);
        await calcularCirculoFoco();
      },
      // Ganchos do autoteste (comum.js): os mesmos caminhos dos botões, do teclado e do clique no mapa.
      teclar(tecla) { document.dispatchEvent(new KeyboardEvent("keydown", { key: tecla, bubbles: true })); },
      clicarMapaEm: (lat, lng) => aoClicarMapa(L.latLng(lat, lng)),
      usarFaixaMarechal: () => faixaMarechal(),
      definirModo: (modo) => definirModo(modo),
      filtrar: (tipo) => filtrar(tipo),
      async marcarPontoEm(lat, lng, raio) {
        escolherFerramenta("raio");
        escreverRaio(raio);
        marcarPonto(L.latLng(lat, lng));
        const previa = Boolean(circuloPrevia) && Math.round(circuloPrevia.getRadius()) === raio;
        await calcularPonto();
        return previa;
      },
      async desenharAreaEm(pontos, nome) {
        escolherFerramenta("desenho");
        for (const [lat, lng] of pontos) aoClicarMapa(L.latLng(lat, lng));
        aoClicarMapa(L.latLng(pontos[pontos.length - 1][0], pontos[pontos.length - 1][1]));  // duplo clique
        const n = vertices.length;
        inputDesenhoNome.value = nome || "";
        await fecharArea();
        return n;
      },
      async desenharTodosEm(lat, lng, zoom) {
        mapa.map.setView([lat, lng], zoom, { animate: false });
        if (timerTodos) clearTimeout(timerTodos);
        const t0 = performance.now();
        await carregarTodos();
        let n = 0;
        if (camadaTodos) camadaTodos.eachLayer(() => { n += 1; });
        return { lotes_desenhados: n, ms: Math.round(performance.now() - t0), aviso: avisoTodos.classList.contains("hidden") ? null : avisoTodos.textContent };
      },
      estadoTela: () => {
        const contagens = {};
        contadores.forEach((c) => { const b = c.querySelector("b"); contagens[b.dataset.n] = Number(b.textContent.replace(/\D/g, "")); });
        return {
          contagens,
          area: areaInfoEl.textContent,
          resumo_area: resArea.textContent,
          ferramenta,
          cursor: getComputedStyle(elMapa).cursor,
          linhas: corpoTabela.querySelectorAll("tr[data-chave]").length,
          total_filtrado: tabela ? tabela.total_filtrado : null,
          modo: consulta.modo,
          selecionado: detalheEl.textContent
        };
      },
      selecionarPrimeira: async (tipo) => {
        const tr = Array.from(corpoTabela.querySelectorAll("tr[data-chave]")).find((x) => !tipo || x.querySelector(".tipo-" + tipo));
        if (tr) await selecionar(tr.dataset.chave, false);
        return tr ? tr.dataset.chave : null;
      }
    };
  }

  window.RaioX.registrarAba("prospectar", "Prospectar", iniciar);
})();
