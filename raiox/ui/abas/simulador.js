// Aba "Simulador": o terreno vem do FOCO (lote, dupla ou trinca escolhido em qualquer aba) ou da
// busca própria (que põe o achado em foco). Parâmetros à esquerda, em grupos (os do simulador
// antigo, view "gleba"); resultado à direita: resíduo, outorga, limites de CA, DRE com % e alertas.
// O estado desta aba é só dela; a conta é do Python (simulador_simular_terreno).
(function () {
  "use strict";
  const { el, fmt, parsearNumeroDigitado, mostrarMsg, esconderMsg, chamar, carregandoLinha, listaOpcoes } = window.RaioX;
  const focoComum = window.RaioX.foco;

  const fmtCampo = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 4 });
  const fmtPct = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const REGIMES = [["R2V_LIVRE", "R2V livre"], ["EHMP", "EHMP"], ["EHIS", "EHIS"]];

  // Campos do formulário (nomes = EntradaSimulador). `erro`: trecho das mensagens do motor/Python
  // que aponta para o campo, para marcar o campo certo além da mensagem da aba.
  const GRUPOS = [
    ["Terreno", [
      { nome: "area_liquida_m2", rotulo: "Área líquida do lote (m²)", erro: /Área líquida/ },
      { nome: "area_construida_existente_m2", rotulo: "Área construída existente (m²)", ajuda: "entra na demolição", erro: /construída existente/ }
    ]],
    ["Projeto", [
      { nome: "regime", rotulo: "Regime", tipo: "regime", erro: /Regime/ },
      { nome: "alvo", tipo: "alvo" },
      { nome: "ca_alvo", rotulo: "CA alvo", opcional: true, erro: /CA alvo/ },
      { nome: "area_computavel_alvo_m2", rotulo: "Área computável alvo (m²)", opcional: true, erro: /computável alvo|area_computavel_alvo/ },
      { nome: "area_privativa_media_m2", rotulo: "Área privativa média (m²/UH)", erro: /privativa média/ },
      { nome: "n_unidades", rotulo: "Nº de unidades", opcional: true, inteiro: true, placeholder: "automático: computável ÷ área privativa", erro: /unidades/ },
      { nome: "via_acesso_largura_m", rotulo: "Largura da via de acesso (m)", erro: /via de acesso/ },
      { nome: "preco_m2", rotulo: "Preço por m² (R$)", erro: /Preço por m²/ }
    ]],
    ["Alavancas", [
      { nome: "opcao_sem_vaga", rotulo: "Opção sem vaga (art. 62)", tipo: "bool" },
      { nome: "doacao_calcada_m2", rotulo: "Doação de calçada (m²)", ajuda: "só gera desconto em zona de eixo", erro: /calçada/ },
      { nome: "fruicao_publica_m2", rotulo: "Fruição pública (m²)", erro: /[Ff]ruição/ },
      { nome: "cota_solidariedade", rotulo: "Cota de solidariedade", tipo: "bool" }
    ]],
    ["Outorga", [
      { nome: "v_reais", rotulo: "Valor do m² (V), Quadro 14 (R$)", erro: /\(V\)/ },
      { nome: "fp", rotulo: "Fator de planejamento (Fp)", erro: /\(Fp\)/ },
      { nome: "fs", rotulo: "Fator social (Fs)", opcional: true, erro: /\(Fs\)/ }
    ]],
    ["Custos e margem", [
      { nome: "custo_obra_m2", rotulo: "Custo de obra (R$/m²)", erro: /[Cc]usto de obra/ },
      { nome: "custo_demolicao_m2", rotulo: "Custo de demolição (R$/m²)", erro: /[Cc]usto de demolição/ },
      { nome: "margem_lucro_desejada", rotulo: "Margem de lucro desejada (%)", pct: true, erro: /[Mm]argem/ },
      { nome: "custo_terreno", rotulo: "Custo do terreno (R$)", opcional: true, placeholder: "opcional: dá o lucro projetado", erro: /[Cc]usto do terreno/ }
    ]]
  ];
  const CAMPOS = GRUPOS.flatMap((g) => g[1]).filter((c) => c.tipo !== "alvo");

  function iniciar(ctx) {
    const $ = ctx.$;
    const inputBusca = $("sm-busca");
    const btnBuscar = $("sm-btn-buscar");
    const msg = $("sm-mensagem");
    const candidatosEl = $("sm-candidatos");
    const terrenoEl = $("sm-terreno");
    const form = $("sm-form");
    const formAcoes = $("sm-form-acoes");
    const btnSimular = $("sm-btn-simular");
    const btnIniciais = $("sm-btn-iniciais");
    const resultadoEl = $("sm-resultado");
    const btnResumo = $("sm-btn-resumo");
    const btnExcel = $("sm-btn-excel");
    const btnPasta = $("sm-btn-pasta");
    const acoesMsg = $("sm-acoes-msg");
    const reservaClip = $("sm-clipboard-reserva");
    const textareaResumo = $("sm-textarea-resumo");

    let terreno = null;        // descrição do terreno vinda do Python
    let simulado = false;      // há resultado válido para os parâmetros na tela
    let pendente = true;       // o foco mudou e a aba ainda não carregou
    let carga = null;          // promessa da última carga (o autoteste espera por ela)
    let contadorReq = 0;
    const entradas = {};       // nome -> { input, erro, campo, origem }
    let radioCa = null, radioArea = null, notaFs = null, notaRegime = null;

    const mensagem = (t, tipo) => mostrarMsg(msg, t, tipo);
    const limparMensagem = () => esconderMsg(msg);
    const acoes = (t, tipo) => mostrarMsg(acoesMsg, t, tipo);
    function limparAcoes() { esconderMsg(acoesMsg); reservaClip.classList.add("hidden"); }

    function premissasOuErro() {
      const p = window.RaioX.premissas.atuais();
      if (!p) throw new Error("as premissas ainda não foram lidas; aguarde a ponte com o Python");
      return p;
    }

    // --- Formulário ---
    function montarFormulario() {
      form.replaceChildren();
      for (const [titulo, campos] of GRUPOS) {
        const bloco = el("fieldset", "sm-grupo");
        bloco.appendChild(el("legend", null, titulo));
        for (const c of campos) {
          if (c.tipo === "alvo") { bloco.appendChild(montarAlvo()); continue; }
          const linha = el("div", "sm-campo");
          let input;
          if (c.tipo === "bool") {
            const rot = el("label", "chk");
            input = el("input");
            input.type = "checkbox";
            rot.appendChild(input);
            rot.appendChild(el("span", null, c.rotulo));
            linha.appendChild(rot);
          } else {
            const rot = el("label", null, c.rotulo);
            rot.htmlFor = "sm-c-" + c.nome;
            linha.appendChild(rot);
            if (c.tipo === "regime") {
              input = el("select");
              for (const [v, t] of REGIMES) { const o = el("option", null, t); o.value = v; input.appendChild(o); }
            } else {
              input = el("input");
              input.type = "text";
              input.inputMode = "decimal";
              if (c.placeholder) input.placeholder = c.placeholder;
            }
            linha.appendChild(input);
          }
          input.id = "sm-c-" + c.nome;
          const origem = el("div", "nota");
          if (c.ajuda) origem.textContent = c.ajuda;
          linha.appendChild(origem);
          if (c.nome === "fs") {
            notaFs = origem;
            const chips = el("div", "atalhos-chips");
            for (const [val, txt] of [["1", "Fs 1,0 (Quadro 5)"], ["0,85", "Fs 0,85 (até 50 m²)"], ["0,4", "Fs 0,4 (HIS/HMP)"]]) {
              const b = el("button", "chip-atalho", txt);
              b.type = "button";
              b.addEventListener("click", ctx.proteger(() => {
                if (input.disabled) return;
                input.value = val;
                aoEditar();
              }));
              chips.appendChild(b);
            }
            linha.appendChild(chips);
          }
          if (c.nome === "regime") { notaRegime = el("div", "nota"); linha.appendChild(notaRegime); }
          const erro = el("div", "campo-erro hidden");
          linha.appendChild(erro);
          bloco.appendChild(linha);
          entradas[c.nome] = { input, erro, campo: c, origem };
          input.addEventListener(c.tipo === "bool" || c.tipo === "regime" ? "change" : "input", ctx.proteger(aoEditar));
          if (c.tipo !== "bool" && c.tipo !== "regime") {
            input.addEventListener("keydown", ctx.proteger((e) => {
              if (e.key !== "Enter") return undefined;
              e.preventDefault();
              return simular();
            }));
          }
        }
        form.appendChild(bloco);
      }
      entradas.regime.input.addEventListener("change", ctx.proteger(ajustarFs));
    }

    function montarAlvo() {
      const linha = el("div", "sm-campo");
      linha.appendChild(el("span", "nota", "Definir o projeto por"));
      const opcoes = el("div", "sm-alvo");
      function radio(valor, texto) {
        const rot = el("label", "chk");
        const r = el("input");
        r.type = "radio";
        r.name = "sm_alvo";
        r.value = valor;
        r.addEventListener("change", ctx.proteger(() => { ajustarAlvo(); aoEditar(); }));
        rot.appendChild(r);
        rot.appendChild(el("span", null, texto));
        opcoes.appendChild(rot);
        return r;
      }
      radioCa = radio("ca", "CA alvo");
      radioArea = radio("area", "área computável alvo");
      linha.appendChild(opcoes);
      return linha;
    }

    function ajustarAlvo() {
      const porCa = radioCa.checked;
      entradas.ca_alvo.input.disabled = !porCa;
      entradas.area_computavel_alvo_m2.input.disabled = porCa;
    }

    // Fs: R2V livre sem padrão (obrigatório); EHIS 0; EHMP automático pela área privativa.
    function ajustarFs() {
      const regime = entradas.regime.input.value;
      const fs = entradas.fs.input;
      if (regime === "EHIS") {
        fs.value = "0";
        fs.disabled = true;
        fs.placeholder = "";
        notaFs.textContent = "EHIS: Fs = 0 (isento, Dec. 63.728).";
      } else if (regime === "EHMP") {
        if (fs.disabled) fs.value = "";
        fs.disabled = false;
        fs.placeholder = "automático pela área privativa";
        notaFs.textContent = "EHMP: vazio = Fs do Dec. 63.728 arts. 19-20 (0,4 até 50 m²; 0,6 de 50 a 70 m²).";
      } else {
        if (fs.disabled) fs.value = "";
        fs.disabled = false;
        fs.placeholder = "obrigatório: Quadro 5 do PDE";
        if (fs.value === "") fs.value = "1";
        notaFs.textContent = "R2V livre: informe o Fs oficial (Quadro 5 do PDE; sugestão inicial 1,0).";
      }
      // O motor do simulador confere o CA alvo contra o teto do ca_engine, que multiplica EHIS/EHMP.
      const p = window.RaioX.premissas.atuais();
      notaRegime.textContent = regime !== "R2V_LIVRE" && p && !p.multiplicador_ehis_ehmp
        ? "O teto de CA do simulador é o do motor (com ×1,5/×1,25 em EHIS/EHMP); o CA alvo inicial vem do Raio-X, sem o multiplicador (premissa desligada)."
        : "";
    }

    function escreverNumero(c, v) {
      if (v == null) return "";
      return fmtCampo.format(c.pct ? v * 100 : v);
    }

    function preencher(valores, origens) {
      for (const c of CAMPOS) {
        const { input, origem } = entradas[c.nome];
        const v = valores[c.nome];
        if (c.tipo === "bool") input.checked = Boolean(v);
        else if (c.tipo === "regime") input.value = v;
        else input.value = escreverNumero(c, v);
        if (c.nome !== "fs") {
          const o = origens[c.nome] || (c.ajuda ? null : origens.demais);
          origem.textContent = [c.ajuda, o ? "valor inicial: " + o : null].filter(Boolean).join(" · ");
        }
      }
      const porCa = valores.area_computavel_alvo_m2 == null;
      radioCa.checked = porCa;
      radioArea.checked = !porCa;
      ajustarAlvo();
      ajustarFs();
      limparErrosCampos();
    }

    function limparErrosCampos() {
      for (const { input, erro } of Object.values(entradas)) {
        input.classList.remove("campo-com-erro");
        erro.textContent = "";
        erro.classList.add("hidden");
      }
    }

    function marcarCampo(nome, texto) {
      const { input, erro } = entradas[nome];
      input.classList.add("campo-com-erro");
      erro.textContent = texto;
      erro.classList.remove("hidden");
    }

    // Lê o formulário: devolve os parâmetros (todo campo presente; vazio = null) ou null se algum é inválido.
    function lerFormulario() {
      limparErrosCampos();
      const saida = {};
      let ok = true;
      for (const c of CAMPOS) {
        const { input } = entradas[c.nome];
        if (c.tipo === "bool") { saida[c.nome] = input.checked; continue; }
        if (c.tipo === "regime") { saida[c.nome] = input.value; continue; }
        if (input.disabled) { saida[c.nome] = null; continue; }
        const v = parsearNumeroDigitado(input.value);
        if (Number.isNaN(v)) { marcarCampo(c.nome, "Use só números (ex.: 1.500 ou 0,75)."); ok = false; continue; }
        if (v !== null && c.inteiro && !Number.isInteger(v)) { marcarCampo(c.nome, "Use um número inteiro."); ok = false; continue; }
        saida[c.nome] = v === null ? null : (c.pct ? v / 100 : v);
      }
      // EHIS: o Fs é 0 por lei; o motor ignora o campo.
      if (saida.regime === "EHIS") saida.fs = null;
      return ok ? saida : null;
    }

    function aoEditar() {
      if (!simulado) return;
      simulado = false;
      habilitarSaidas(false);
      const aviso = resultadoEl.querySelector(".sm-desatualizado");
      if (aviso) aviso.classList.remove("hidden");
    }

    function habilitarSaidas(sim) {
      btnResumo.disabled = !sim;
      btnExcel.disabled = !sim;
    }

    // --- Terreno ---
    function renderizarTerreno(t) {
      const caixa = el("div", "bloco");
      const tipo = { lote: "Lote", dupla: "Dupla", trinca: "Trinca" }[t.tipo] || t.tipo;
      caixa.appendChild(el("span", "tag tag-" + t.tipo, tipo));
      caixa.appendChild(el("div", "titulo-lote", t.enderecos.join(" + ")));
      const lista = el("dl", "dl");
      for (const [rot, val] of [
        ["SQL", t.sql],
        ["Área líquida", fmt.inteiro.format(t.area_liquida_m2) + " m²"],
        ["Área do cadastro", fmt.inteiro.format(t.area_bruta_m2) + " m²"],
        ["Zona", t.zona_base + (t.zonas.length > 1 ? " (lotes: " + t.zonas.join(", ") + ")" : "")],
        ["CA do Raio-X", fmt.ca.format(t.ca_lote)]
      ]) {
        lista.appendChild(el("dt", null, rot));
        lista.appendChild(el("dd", null, val));
      }
      caixa.appendChild(lista);
      if (t.retiradas.length) {
        caixa.appendChild(el("p", "nota", "Retiradas: " + t.retiradas.map((r) =>
          r.rotulo + " – " + fmt.inteiro.format(r.area_m2) + " m²" + (t.ids.length > 1 ? " (" + r.sql + ")" : "")).join(" · ")));
      }
      if (t.avisos.length) {
        const ul = el("ul", "lista-avisos");
        for (const a of t.avisos) ul.appendChild(el("li", null, a));
        caixa.appendChild(ul);
      }
      terrenoEl.replaceChildren(caixa);
    }

    function mostrarParametros(sim) {
      form.classList.toggle("hidden", !sim);
      formAcoes.classList.toggle("hidden", !sim);
    }

    function semTerreno(texto) {
      terreno = null;
      simulado = false;
      habilitarSaidas(false);
      mostrarParametros(false);
      terrenoEl.replaceChildren(el("p", "vazio-painel", texto));
      resultadoEl.replaceChildren(el("p", "vazio-painel", "Escolha um terreno; os parâmetros aparecem à esquerda. Confira e clique em “Simular”."));
    }

    // Abre o terreno (busca ou ids); `aoAbrir(t)` roda quando abriu (a busca põe o achado em foco).
    function executarTerreno(metodo, args, aoAbrir) {
      const meu = ++contadorReq;
      carga = (async () => {
        limparMensagem();
        limparAcoes();
        candidatosEl.replaceChildren();
        terrenoEl.replaceChildren(carregandoLinha("Abrindo o terreno…"));
        const res = await chamar(metodo, ...args);
        if (meu !== contadorReq) return res;
        if (!res.ok) {
          semTerreno("Nenhum terreno aberto.");
          mensagem(res.erro, "erro");
          return res;
        }
        if (res.tipo === "Terreno") {
          terreno = res.terreno;
          simulado = false;
          habilitarSaidas(false);
          renderizarTerreno(terreno);
          preencher(terreno.valores_iniciais, terreno.origem_iniciais);
          mostrarParametros(true);
          resultadoEl.replaceChildren(el("p", "vazio-painel", "Confira os parâmetros à esquerda e clique em “Simular”."));
          if (aoAbrir) await aoAbrir(terreno);
        } else if (res.tipo === "Candidatos") {
          semTerreno("Escolha uma das opções abaixo.");
          candidatosEl.replaceChildren(listaOpcoes(ctx, fmt.inteiro.format(res.resultado.opcoes.length) + " opções para “" + (res.resultado.texto || "") + "”. Escolha uma:",
            res.resultado.opcoes, (op) => abrirTerreno([op.cd_identificador], porEmFoco)));
          for (const a of res.resultado.avisos || []) candidatosEl.appendChild(el("p", "nota", a));
        } else if (res.tipo === "NaoEncontrado") {
          semTerreno("Não encontrado na base para “" + (res.resultado.texto || "") + "”. " + (res.resultado.motivo || "") +
            " Isso não prova que o lote não exista: confira a grafia ou tente pelo SQL.");
        } else {
          throw new Error("tipo de resposta desconhecido: " + res.tipo);
        }
        return res;
      })();
      return carga;
    }

    // O terreno achado pela busca desta aba vai para o foco (as outras abas reagem quando abertas).
    const porEmFoco = (t) => focoComum.definir(t.ids, "simulador");

    function buscar(texto) {
      return executarTerreno("simulador_buscar", [texto, premissasOuErro()], porEmFoco);
    }

    function abrirTerreno(ids, aoAbrir) {
      return executarTerreno("simulador_abrir", [ids, premissasOuErro()], aoAbrir);
    }

    function carregarFoco() {
      pendente = false;
      const f = focoComum.atual();
      if (!f) {
        semTerreno("Nenhum terreno em foco. Escolha um no Prospectar ou no Raio-X; ele aparece aqui já preenchido. Ou busque:");
        return Promise.resolve();
      }
      if (terreno && focoComum.mesmosIds(terreno.ids, f.ids)) return carga || Promise.resolve();
      return abrirTerreno(f.ids, null);
    }

    // --- Resultado ---
    const m2 = (v) => fmt.inteiro.format(v) + " m²";
    const reais = (v) => fmt.moeda.format(v);

    function blocoDl(titulo, pares) {
      const b = el("div", "bloco");
      b.appendChild(el("h3", null, titulo));
      const lista = el("dl", "dl");
      for (const [rot, val, dica] of pares) {
        const dt = el("dt", null, rot);
        if (dica) dt.title = dica;
        lista.appendChild(dt);
        lista.appendChild(el("dd", null, val));
      }
      b.appendChild(lista);
      return b;
    }

    function renderizarResultado(res) {
      const r = res.resultado;
      const frag = document.createDocumentFragment();
      frag.appendChild(el("p", "msg aviso sm-desatualizado hidden", "Os parâmetros mudaram: clique em “Simular” para refazer a conta."));
      if (r.bloqueado) {
        frag.appendChild(el("p", "faixa-bloqueio", "Resultado com bloqueio legal: confira antes de usar os números. Os números abaixo seguem a conta do motor."));
      }
      frag.appendChild(el("p", "nota", "Zona base " + r.zona_base + " · zona efetiva " + (r.zona_efetiva || "nenhuma (bloqueado)") +
        " · Fs usado " + (res.fs_usado == null ? "—" : fmt.decimal.format(res.fs_usado))));

      const residuo = el("div", "bloco");
      residuo.appendChild(el("h3", null, "Resíduo do terreno"));
      residuo.appendChild(el("div", r.residuo_terreno >= 0 ? "grande" : "grande neg", reais(r.residuo_terreno)));
      residuo.appendChild(el("p", "nota", (r.residuo_terreno >= 0 ? "Teto que dá para pagar pelo terreno" : "Resíduo negativo") +
        " mantendo a margem de " + fmtPct.format(res.entrada.margem_lucro_desejada * 100) +
        "% (VGV − obra − outorga líquida − demolição − lucro desejado). Se o resíduo cai ao subir o CA, a alavanca não compensa."));
      frag.appendChild(residuo);

      const grade = el("div", "sm-grade-res");
      grade.appendChild(blocoDl("Outorga onerosa", [
        ["Outorga bruta", reais(r.outorga_bruta)],
        ["Desconto calçada", reais(r.desconto_calcada)],
        ["Desconto fruição", reais(r.desconto_fruicao)],
        ["Descontos (total)", reais(r.descontos_total)],
        ["Outorga líquida", reais(r.outorga_liquida)]
      ]));
      grade.appendChild(blocoDl("Limites de CA", [
        ["CA básico", fmt.ca.format(r.ca_basico)],
        ["CA máx. da zona", fmt.ca.format(r.ca_max_zona)],
        ["CA do produto", fmt.ca.format(r.ca_max_produto)],
        ["CA teto", fmt.ca.format(r.ca_teto)],
        ["CA alvo", fmt.ca.format(r.ca_alvo)]
      ]));
      grade.appendChild(blocoDl("Área construída", [
        ["Computável", m2(r.area_computavel_m2)],
        ["Não computável (estim.)", m2(r.area_nc_m2), res.entrada.opcao_sem_vaga ? "10% da computável (opção sem vaga)" : "garagem estimada pelo motor"],
        ["Total construída", m2(r.area_total_construida_m2)],
        ["Unidades", fmt.inteiro.format(r.n_unidades)]
      ]));
      frag.appendChild(grade);

      const dre = el("div", "bloco");
      dre.appendChild(el("h3", null, "DRE simplificada"));
      const caixaTabela = el("div", "sm-dre-container");
      const tabela = el("table", "sm-dre");
      const cab = el("tr");
      for (const [t, cls] of [["Rubrica", null], ["Valor", "n"], ["% do VGV", "n"], ["Detalhe", null]]) cab.appendChild(el("th", cls, t));
      const thead = el("thead");
      thead.appendChild(cab);
      tabela.appendChild(thead);
      const corpo = el("tbody");
      r.dre.forEach((l, i) => {
        const tr = el("tr", i === r.dre.length - 1 ? "tot" : null);
        tr.appendChild(el("td", null, l.rubrica));
        tr.appendChild(el("td", "n", reais(l.valor)));
        tr.appendChild(el("td", "n", l.percentual_vgv == null ? "—" : fmtPct.format(l.percentual_vgv) + "%"));
        tr.appendChild(el("td", "detalhe-dre", l.detalhe));
        corpo.appendChild(tr);
      });
      tabela.appendChild(corpo);
      caixaTabela.appendChild(tabela);
      dre.appendChild(caixaTabela);
      frag.appendChild(dre);

      const al = el("div", "bloco");
      al.appendChild(el("h3", null, "Alertas do motor"));
      if (r.alertas.length) {
        const ul = el("ul", "lista-avisos");
        for (const a of r.alertas) ul.appendChild(el("li", a.startsWith("[BLOQUEIO]") ? "alerta-bloqueio" : null, a));
        al.appendChild(ul);
      } else {
        al.appendChild(el("p", "nota", "(nenhum)"));
      }
      frag.appendChild(al);
      resultadoEl.replaceChildren(frag);
    }

    // Marca o campo citado pela mensagem do motor (a mensagem também aparece na aba).
    function marcarPeloErro(texto) {
      for (const c of CAMPOS) {
        if (c.erro && c.erro.test(texto) && !entradas[c.nome].input.disabled) { marcarCampo(c.nome, texto); return c.nome; }
      }
      return null;
    }

    // Simula o terreno aberto pelos ids (o ponto único do Python): o Python reabre o terreno e roda o motor.
    async function simular() {
      if (!terreno) { mensagem("Escolha um terreno antes de simular.", "erro"); return { ok: false }; }
      limparMensagem();
      limparAcoes();
      const parametros = lerFormulario();
      if (!parametros) { mensagem("Corrija os campos marcados em vermelho.", "erro"); return { ok: false }; }
      btnSimular.disabled = true;
      resultadoEl.replaceChildren(carregandoLinha("Simulando…"));
      try {
        const res = await chamar("simulador_simular_terreno", terreno.ids, parametros, premissasOuErro());
        if (!res.ok) {
          simulado = false;
          habilitarSaidas(false);
          const campo = marcarPeloErro(res.erro);
          mensagem(res.erro, "erro");
          resultadoEl.replaceChildren(el("p", "vazio-painel", "Sem resultado: corrija " + (campo ? "o campo marcado" : "os parâmetros") + " e simule de novo."));
          return res;
        }
        terreno = res.terreno;
        renderizarResultado(res);
        simulado = true;
        habilitarSaidas(true);
        return res;
      } finally {
        btnSimular.disabled = false;
      }
    }

    // --- Saídas ---
    async function comBotao(btn, texto, fn) {
      const original = btn.textContent;
      btn.textContent = texto;
      btn.disabled = true;
      limparAcoes();
      try {
        await fn();
      } finally {
        btn.textContent = original;
        btn.disabled = btn === btnPasta ? false : !simulado;
      }
    }

    btnResumo.addEventListener("click", ctx.proteger(() => comBotao(btnResumo, "Gerando…", async () => {
      const res = await chamar("simulador_copiar_resumo");
      if (!res.ok) { acoes(res.erro, "erro"); return; }
      try {
        await navigator.clipboard.writeText(res.texto);
        acoes("Resumo da simulação copiado.", "ok");
      } catch (eNavegador) {
        const clip = await chamar("copiar_texto", res.texto);
        if (clip.ok) { acoes("Resumo da simulação copiado.", "ok"); return; }
        textareaResumo.value = res.texto;
        reservaClip.classList.remove("hidden");
        textareaResumo.focus();
        textareaResumo.select();
        acoes("Não consegui copiar sozinha: selecione e use Ctrl+C.", "erro");
      }
    })));

    btnExcel.addEventListener("click", ctx.proteger(() => comBotao(btnExcel, "Gerando…", async () => {
      const res = await chamar("simulador_exportar_excel");
      acoes(res.ok ? "Excel salvo em " + res.caminho : res.erro, res.ok ? "ok" : "erro");
    })));

    btnPasta.addEventListener("click", ctx.proteger(() => comBotao(btnPasta, "Abrindo…", async () => {
      const res = await chamar("abrir_pasta_saida");
      if (!res.ok) acoes(res.erro, "erro");
    })));

    // --- Busca e botões ---
    function aoBuscar() {
      const texto = inputBusca.value.trim();
      if (!texto) { mensagem("Digite um SQL, endereço ou identificador.", "erro"); return undefined; }
      return buscar(texto);
    }
    inputBusca.addEventListener("keydown", ctx.proteger((e) => {
      if (e.key !== "Enter") return undefined;
      e.preventDefault();
      return aoBuscar();
    }));
    btnBuscar.addEventListener("click", ctx.proteger(aoBuscar));
    btnSimular.addEventListener("click", ctx.proteger(simular));
    btnIniciais.addEventListener("click", ctx.proteger(() => {
      if (!terreno) return;
      preencher(terreno.valores_iniciais, terreno.origem_iniciais);
      aoEditar();
    }));

    montarFormulario();
    habilitarSaidas(false);

    return {
      aoMudarFoco(f, origem) {
        if (origem === "simulador") return undefined;
        pendente = true;
        return ctx.ativa() ? carregarFoco() : undefined;
      },
      aoAtivar() {
        if (pendente) return carregarFoco();
        return carga || Promise.resolve();
      },
      // Autoteste: busca pela caixa da aba, troca um campo e simula pela tela.
      buscar: (texto) => { inputBusca.value = texto; return buscar(texto); },
      definirCampo(nome, valor) {
        const { input, campo } = entradas[nome];
        if (campo.tipo === "bool") input.checked = Boolean(valor);
        else input.value = valor;
        input.dispatchEvent(new Event(campo.tipo === "bool" || campo.tipo === "regime" ? "change" : "input"));
      },
      simular: () => simular(),
      estadoTela() {
        const erros = Object.entries(entradas).filter(([, x]) => !x.erro.classList.contains("hidden")).map(([n]) => n);
        return {
          terreno: terreno ? { ids: terreno.ids, tipo: terreno.tipo, sql: terreno.sql, area_liquida_m2: terreno.area_liquida_m2, zona: terreno.zona_base } : null,
          cabecalho: terrenoEl.textContent,
          mensagem: msg.classList.contains("hidden") ? "" : msg.textContent,
          campos_com_erro: erros,
          resultado: resultadoEl.textContent,
          linhas_dre: resultadoEl.querySelectorAll(".sm-dre tbody tr").length,
          exportar_habilitado: !btnExcel.disabled
        };
      }
    };
  }

  window.RaioX.registrarAba("simulador", "Simulador", iniciar);
})();
