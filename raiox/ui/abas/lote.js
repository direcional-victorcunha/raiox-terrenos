// Aba "Raio-X do lote": o terreno em foco no SEU QUARTEIRÃO (lotes da mesma quadra, mapa enquadrado
// e travado nela), com retiradas e restrições desenhadas, e os cartões à direita: VGV potencial
// com a conta, zona e área (cadastro × desenho), farol, uso e porte, retiradas e saídas.
// Sem foco, a busca por SQL/endereço/KMZ continua aqui (e põe o lote achado em foco).
(function () {
  "use strict";
  const { el, fmt, COR, formatarSQL, mostrarMsg, esconderMsg, chamar, carregandoLinha, listaOpcoes } = window.RaioX;
  const focoComum = window.RaioX.foco;

  function iniciar(ctx) {
    const $ = ctx.$;
    const inputBusca = $("lt-busca");
    const rotuloBusca = $("lt-busca-rotulo");
    const inputArquivo = $("lt-arquivo-kmz");
    const btnAbrirKmz = $("lt-btn-kmz");
    const composicaoEl = $("lt-composicao");
    const msg = $("lt-mensagem");
    const resultadoEl = $("lt-resultado");
    const listaRetirar = $("lt-camadas-retirar");
    const mapaVazio = $("lt-mapa-vazio");
    const carregandoEl = $("lt-carregando");
    const dicaEl = $("lt-dica");
    const btnResumo = $("lt-btn-resumo");
    const btnExcel = $("lt-btn-excel");
    const btnKmz = $("lt-btn-exportar-kmz");
    const btnCroqui = $("lt-btn-croqui");
    const btnSimular = $("lt-btn-simular");
    const btnPasta = $("lt-btn-pasta");
    const acoesMsg = $("lt-acoes-msg");
    const reservaClip = $("lt-clipboard-reserva");
    const textareaResumo = $("lt-textarea-resumo");
    const modalCroqui = $("modal-croqui");
    const modalCorpo = $("modal-croqui-corpo");

    const mapa = window.RaioX.criarMapa(ctx, "lt", []);

    let foco = null;            // descrição do terreno em foco (do comum)
    let sub = 0;                // qual lote da composição está aberto
    let aberto = null;          // resposta RaioX na tela (o Python guarda o lote para recalcular)
    let pendente = true;        // o foco mudou e a aba ainda não carregou
    let carga = null;           // promessa da última carga (o autoteste espera por ela)
    let contadorReq = 0;
    let camadaQuadra = null, camadaLiquida = null, camadaRetiradas = null;
    let limitesQuadra = null;
    let travado = false;

    const mensagem = (t, tipo) => mostrarMsg(msg, t, tipo);
    const limparMensagem = () => esconderMsg(msg);
    const acoes = (t, tipo) => mostrarMsg(acoesMsg, t, tipo);
    function limparAcoes() { esconderMsg(acoesMsg); reservaClip.classList.add("hidden"); }

    function premissasOuErro() {
      const p = window.RaioX.premissas.atuais();
      if (!p) throw new Error("as premissas ainda não foram lidas; aguarde a ponte com o Python");
      return p;
    }

    // --- Mapa: só o quarteirão, enquadrado e travado ---
    function limparDesenhos() {
      for (const c of [camadaQuadra, camadaLiquida, camadaRetiradas]) if (c) mapa.map.removeLayer(c);
      camadaQuadra = camadaLiquida = camadaRetiradas = null;
      limitesQuadra = null;
      travado = false;
      mapa.map.setMaxBounds(null);
      mapa.map.setMinZoom(0);
    }

    function travarNaQuadra() {
      if (!limitesQuadra || !ctx.ativa()) return;
      const m = mapa.map;
      m.setMaxBounds(null);
      m.setMinZoom(0);
      m.fitBounds(limitesQuadra, { padding: [36, 36], maxZoom: 19, animate: false });
      m.setMinZoom(m.getZoom());
      m.setMaxBounds(limitesQuadra.pad(0.6));
      travado = true;
    }
    mapa.aoRedimensionar(travarNaQuadra);

    function estiloQuadra(feature) {
      const p = feature.properties;
      if (p.aberto) return { color: COR.foco, weight: 3.5, opacity: 1, fillColor: COR.foco, fillOpacity: 0.22 };
      if (foco && foco.ids.includes(p.cd_identificador)) return { color: COR.foco, weight: 2, dashArray: "5 4", opacity: 1, fillColor: COR.foco, fillOpacity: 0.1 };
      return { color: "#ffffff", weight: 1.2, opacity: 0.95, fillColor: "#f7f8f4", fillOpacity: 0.28 };
    }

    function desenhar(res) {
      limparDesenhos();
      camadaQuadra = L.geoJSON(res.quarteirao_geojson, {
        pane: "destaque", renderer: mapa.rendDestaque,
        style: estiloQuadra,
        onEachFeature: (f, layer) => {
          const p = f.properties;
          layer.bindTooltip(p.sql + " · " + p.endereco + " · " + fmt.inteiro.format(p.area_m2) + " m²" + (p.aberto ? " (aberto)" : " · clique para pôr em foco"), { sticky: true });
          if (!p.aberto) layer.on("click", ctx.proteger(() => escolher(p.cd_identificador)));
        }
      }).addTo(mapa.map);
      if (res.retiradas_geojson) {
        camadaRetiradas = L.geoJSON(res.retiradas_geojson, {
          pane: "foco", renderer: mapa.rendFoco,
          style: { color: "#b42318", weight: 1.5, opacity: 0.95, fillColor: "#ef4444", fillOpacity: 0.45 },
          onEachFeature: (f, layer) => layer.bindTooltip((f.properties.rotulo || f.properties.camada) + ": " + fmt.inteiro.format(f.properties.area_m2 || 0) + " m² retirados", { sticky: true })
        }).addTo(mapa.map);
      }
      if (res.liquida_geojson) {
        camadaLiquida = L.geoJSON(res.liquida_geojson, {
          pane: "foco", renderer: mapa.rendFoco, interactive: false,
          style: { color: "#7a2c06", weight: 2.5, opacity: 1, dashArray: "2 3", fill: false }
        }).addTo(mapa.map);
      }
      limitesQuadra = camadaQuadra.getBounds();
      travarNaQuadra();
      const lote = res.resultado.lote;
      const n = res.quarteirao_geojson.features.length;
      dicaEl.textContent = "Quadra " + lote.setor + "." + lote.quadra + ": " + fmt.inteiro.format(n) + (n === 1 ? " lote" : " lotes") +
        ". Só o quarteirão do terreno em foco; clique num vizinho para pô-lo em foco. Para o entorno, use “Ver entorno” na barra do foco.";
      // Restrições presentes no lote: liga as camadas delas no mapa.
      const ids = (res.resultado.sinais || []).filter((s) => s.presente).map((s) => mapa.idDaCamadaPeloRotulo(s.rotulo)).filter(Boolean);
      return mapa.ligarSomente(ids);
    }

    // --- Cartões ---
    function bloco(titulo) {
      const b = el("div", "bloco");
      if (titulo) b.appendChild(el("h3", null, titulo));
      return b;
    }

    function dl(pares) {
      const lista = el("dl", "dl");
      for (const [rot, val, cls] of pares) {
        lista.appendChild(el("dt", null, rot));
        lista.appendChild(el("dd", cls || null, val));
      }
      return lista;
    }

    function passo(passos, sufixo) {
      return (passos || []).find((p) => typeof p === "string" && p.trim().endsWith(sufixo)) || "";
    }

    function opcaoBase(valor, texto, atual) {
      const rotulo = el("label", "chk");
      const radio = el("input");
      radio.type = "radio";
      radio.name = "lt_base_vgv";
      radio.value = valor;
      radio.checked = atual === valor;
      radio.addEventListener("change", ctx.proteger(() => (radio.checked ? window.RaioX.premissas.alterar({ base_vgv: valor }, true) : undefined)));
      rotulo.appendChild(radio);
      rotulo.appendChild(el("span", null, texto));
      return rotulo;
    }

    function renderizarRaioX(res) {
      const r = res.resultado;
      const lote = r.lote, au = r.area_util, area = r.area;
      const p = premissasOuErro();
      const frag = document.createDocumentFragment();

      const cab = bloco(formatarSQL(lote.setor, lote.quadra, lote.lote, lote.digito, lote.sql));
      cab.appendChild(el("div", "titulo-lote", (lote.logradouro || "") + (lote.numero_porta ? ", " + lote.numero_porta : "")));
      let construida = "área construída não informada";
      if (lote.area_construida_m2 != null) {
        construida = fmt.inteiro.format(lote.area_construida_m2) + " m² construídos" + (r.pct_construido != null ? " (" + fmt.inteiro.format(r.pct_construido) + "% do terreno)" : "");
      }
      cab.appendChild(el("p", "nota", (lote.uso || "uso não informado") + " · " + construida));
      frag.appendChild(cab);

      // VGV potencial = área × CA × preço/m² (sem fator), o mesmo da tabela do Prospectar
      const vgv = bloco("VGV potencial");
      vgv.appendChild(el("div", "grande", au.vgv != null ? fmt.moeda.format(au.vgv) : "—"));
      const conta = el("ol", "conta");
      for (const passoTexto of au.passos) conta.appendChild(el("li", null, passoTexto));
      vgv.appendChild(conta);
      if (au.vgv != null) {
        vgv.appendChild(el("p", "nota", fmt.inteiro.format(au.unidades) + " unidades estimadas · meta " + fmt.moeda.format(res.meta_vgv) +
          (res.meta_vgv > 0 ? " · " + fmt.pct.format((au.vgv / res.meta_vgv) * 100) + "% da meta" : "")));
      } else {
        vgv.appendChild(el("p", "msg aviso", "Informe o preço por m² (ou o ticket da unidade) em ⚙ Premissas para ver o VGV potencial."));
      }
      if (au.unidades_min_cota_parte != null) {
        const cota = el("p", "nota", "Mínimo pela cota-parte: " + fmt.inteiro.format(au.unidades_min_cota_parte) + " unidades");
        cota.title = passo(au.passos, "pela cota-parte");
        vgv.appendChild(cota);
      }
      if (au.a_util != null) {
        vgv.appendChild(el("p", "nota", "Informativo, com fator privativo " + fmt.decimal.format(p.fator_privativo) + ": área útil privativa " +
          fmt.inteiro.format(au.a_util) + " m². Não muda o VGV, as unidades nem a meta."));
      }
      frag.appendChild(vgv);

      // Zona e área: a conta parte do cadastro; o desenho fica ao lado, com aviso acima do limite.
      const zonaArea = bloco("Zona e área");
      const zonas = (r.zonas || []).length ? r.zonas.map((z) => z[0] + " " + Math.round(Number(z[1]) || 0) + "%").join(" · ") : "sem zona na base";
      const div = res.divergencia_area_pct;
      const acima = div != null && div > res.limite_divergencia_area_pct;
      const pares = [
        ["Zona", zonas, "texto"],
        ["CA máximo", fmt.ca.format(au.ca_teto)],
        ["Área do cadastro", fmt.inteiro.format(area.bruta_m2) + " m²"],
        ["Área do desenho", fmt.inteiro.format(area.geometrica_m2) + " m²"],
        ["Diferença", div == null ? "—" : fmt.pct1.format(div) + "%", acima ? "destaque-alerta" : null],
        ["Área líquida (após retiradas)", fmt.inteiro.format(area.liquida_m2) + " m²"]
      ];
      zonaArea.appendChild(dl(pares));
      if (acima) zonaArea.appendChild(el("p", "msg aviso", "Cadastro × desenho divergem " + fmt.pct1.format(div) + "%; confira. A conta usa o cadastro (limite do aviso: " + fmt.decimal.format(res.limite_divergencia_area_pct) + "%, em ⚙ Premissas)."));
      else zonaArea.appendChild(el("p", "nota", "A conta parte da área do cadastro; o desenho só é comparado."));
      if (res.multiplicador) zonaArea.appendChild(el("p", "msg aviso", res.multiplicador));
      if ((area.retiradas || []).length) {
        const lista = el("ul", "lista-avisos");
        for (const x of area.retiradas) lista.appendChild(el("li", null, (x.rotulo || x.camada) + ": " + (x.area_m2 > 0 ? "– " + fmt.inteiro.format(x.area_m2) + " m²" : "0 m²")));
        zonaArea.appendChild(lista);
      }
      const base = el("div", "chave-vgv");
      base.appendChild(el("span", "sub", "Base do VGV"));
      base.appendChild(opcaoBase("referencia_ca", "área do cadastro (referência do CA)", p.base_vgv));
      base.appendChild(opcaoBase("liquida", "área líquida (após retiradas)", p.base_vgv));
      base.appendChild(el("p", "nota", "Pela pesquisa (PDE art. 81), o melhoramento viário não reduz o CA; confira no Diário Oficial."));
      zonaArea.appendChild(base);
      frag.appendChild(zonaArea);

      const farol = bloco("Farol de restrições");
      const lista = el("div", "farol");
      const sinais = r.sinais || [];
      for (const s of [...sinais.filter((x) => x.presente), ...sinais.filter((x) => !x.presente)]) {
        const item = el("div", "farol-item");
        item.appendChild(el("span", s.presente ? "sem presente" : "sem"));
        const corpo = el("div");
        corpo.appendChild(el("div", null, (s.rotulo || "") + (s.medida ? " · " + s.medida : "")));
        if (s.fonte) corpo.appendChild(el("div", "farol-fonte", s.fonte));
        item.appendChild(corpo);
        lista.appendChild(item);
      }
      farol.appendChild(lista);
      farol.appendChild(el("p", "nota", "“Não encontrado” quer dizer que não consta na base baixada, não que não exista. As restrições presentes aparecem no mapa."));
      frag.appendChild(farol);

      if ((r.uso_porte || []).length) {
        const uso = bloco("Uso e porte");
        for (const frase of r.uso_porte) uso.appendChild(el("p", frase.startsWith("Bloqueia") ? "nota marca-uso" : "nota", frase));
        frag.appendChild(uso);
      }

      const est = bloco("Estação mais próxima");
      const e = r.estacao;
      est.appendChild(el("p", "nota", Array.isArray(e) && e[0]
        ? e[0] + " · " + fmt.inteiro.format(Number(e[1]) || 0) + " m (até a borda do lote)"
        : "Nenhuma estação na base em até 5 km."));
      frag.appendChild(est);

      if ((r.avisos || []).length) {
        const av = bloco("Avisos");
        const ul = el("ul", "lista-avisos");
        for (const a of r.avisos) ul.appendChild(el("li", null, a));
        av.appendChild(ul);
        frag.appendChild(av);
      }
      resultadoEl.replaceChildren(frag);
    }

    function renderizarComposicao() {
      composicaoEl.replaceChildren();
      const busca = window.RaioX.instalado ? "SQL ou KMZ" : "SQL, endereço ou KMZ";
      rotuloBusca.textContent = foco ? "Buscar outro terreno (" + busca + ")" : busca + " do terreno";
      if (!foco || foco.ids.length < 2) return;
      const b = bloco((foco.tipo === "dupla" ? "Dupla" : "Trinca") + " em foco: o Raio-X é de um lote por vez");
      const linha = el("div", "composicao");
      foco.ids.forEach((cd, i) => {
        const bt = el("button", "bt", foco.sql.split(" + ")[i] || cd);
        bt.type = "button";
        bt.setAttribute("aria-pressed", i === sub ? "true" : "false");
        bt.addEventListener("click", ctx.proteger(() => mostrarLote(cd)));
        linha.appendChild(bt);
      });
      b.appendChild(linha);
      composicaoEl.appendChild(b);
    }

    function habilitarSaidas(sim) {
      for (const b of [btnResumo, btnExcel, btnKmz, btnCroqui, btnSimular]) b.disabled = !sim;
    }

    function semLote(texto) {
      aberto = null;
      limparDesenhos();
      habilitarSaidas(false);
      mapaVazio.classList.remove("hidden");
      resultadoEl.replaceChildren(el("p", "vazio-painel", texto));
    }

    // Chamada que troca o Raio-X da aba; `aoAbrir(res)` roda quando abriu um lote.
    function executar(textoCarregando, metodo, args, aoAbrir) {
      const meu = ++contadorReq;
      carga = (async () => {
        limparMensagem();
        limparAcoes();
        habilitarSaidas(false);
        carregandoEl.classList.remove("hidden");
        resultadoEl.replaceChildren(carregandoLinha(textoCarregando));
        let res;
        try {
          res = await chamar(metodo, ...args);
        } finally {
          if (meu === contadorReq) carregandoEl.classList.add("hidden");
        }
        if (meu !== contadorReq) return;
        await processar(res, aoAbrir);
      })();
      return carga;
    }

    async function processar(res, aoAbrir) {
      if (!res.ok) {
        semLote("Sem Raio-X: veja a mensagem acima.");
        mensagem(res.erro, "erro");
        return;
      }
      if (res.tipo === "RaioX") {
        aberto = res;
        mapaVazio.classList.add("hidden");
        renderizarRaioX(res);
        habilitarSaidas(true);
        await desenhar(res);
        if (aoAbrir) await aoAbrir(res);
      } else if (res.tipo === "Candidatos") {
        semLote("Escolha uma das opções acima.");
        resultadoEl.replaceChildren(listaOpcoes(ctx, fmt.inteiro.format(res.resultado.opcoes.length) + " opções para “" + (res.resultado.texto || "") + "”. Escolha uma:",
          res.resultado.opcoes, (op) => escolher(op.cd_identificador)));
        for (const a of res.resultado.avisos || []) resultadoEl.appendChild(el("p", "nota", a));
      } else if (res.tipo === "NaoEncontrado") {
        semLote("Não encontrado na base para “" + (res.resultado.texto || "") + "”. " + (res.resultado.motivo || "") +
          " Isso não prova que o lote não exista: confira a grafia ou tente pelo SQL.");
      } else if (res.tipo !== "Vazio") {
        throw new Error("tipo de resposta desconhecido: " + res.tipo);
      }
    }

    // O lote achado pela busca desta aba vai para o foco (as outras abas reagem quando abertas).
    const porEmFoco = (res) => focoComum.definir([res.resultado.lote.cd_identificador], "lote");

    function consultar(texto) {
      return executar("Consultando…", "lote_consultar", [texto, premissasOuErro()], porEmFoco);
    }

    function escolher(cd) {
      sub = 0;
      return executar("Consultando…", "lote_escolher", [cd, premissasOuErro()], porEmFoco);
    }

    function carregarFoco() {
      pendente = false;
      foco = focoComum.atual();
      renderizarComposicao();
      if (!foco) {
        semLote("Nenhum terreno em foco. Escolha um lote no Prospectar (clique no mapa ou numa linha da tabela) ou busque acima.");
        return Promise.resolve();
      }
      if (sub >= foco.ids.length) sub = 0;
      const cd = foco.ids[sub];
      if (aberto && aberto.resultado.lote.cd_identificador === cd) return carga || Promise.resolve();
      return executar("Abrindo o Raio-X de " + (foco.sql.split(" + ")[sub] || cd) + "…", "lote_escolher", [cd, premissasOuErro()], null);
    }

    function mostrarLote(cd) {
      foco = focoComum.atual();
      if (!foco) return Promise.resolve();
      const i = foco.ids.indexOf(cd);
      sub = i >= 0 ? i : 0;
      return carregarFoco();
    }

    async function carregarArquivo(arquivo) {
      if (!arquivo || !/\.(kmz|kml)$/i.test(arquivo.name)) {
        mensagem("Solte um arquivo .kmz ou .kml válido.", "erro");
        return;
      }
      const b64 = await window.RaioX.lerArquivoBase64(arquivo);
      sub = 0;
      await executar("Carregando " + arquivo.name + "…", "lote_carregar_kmz", [arquivo.name, b64, premissasOuErro()], porEmFoco);
    }

    // --- Retiradas (premissa comum, escolhida aqui) ---
    async function montarRetiradas() {
      const lista = await mapa.montarListaVer();
      listaRetirar.replaceChildren();
      const p = window.RaioX.premissas.atuais();
      const atalhos = el("div", "atalhos-chips");
      const btnTodas = el("button", "chip-atalho", "Marcar todas (viário, água, energia, duto)");
      btnTodas.type = "button";
      btnTodas.addEventListener("click", ctx.proteger(() => window.RaioX.premissas.alterar({ retiradas: ["melhoramento", "alta_tensao", "duto"] }, true)));
      const btnLimpar = el("button", "chip-atalho", "Desmarcar todas");
      btnLimpar.type = "button";
      btnLimpar.addEventListener("click", ctx.proteger(() => window.RaioX.premissas.alterar({ retiradas: [] }, true)));
      atalhos.appendChild(btnTodas);
      atalhos.appendChild(btnLimpar);
      listaRetirar.appendChild(atalhos);
      for (const c of lista) {
        if (!(c.usos || []).includes("retirar")) continue;
        const label = el("label", "chk");
        const chk = el("input");
        chk.type = "checkbox";
        chk.dataset.retirarId = c.id;
        chk.checked = Boolean(p && p.retiradas.includes(c.id));
        let rot = c.rotulo || c.id;
        if (c.faixa_m != null && c.id !== "alta_tensao") rot += " (faixa de " + fmt.inteiro.format(c.faixa_m) + " m)";
        chk.addEventListener("change", ctx.proteger(() => {
          const marcadas = Array.from(listaRetirar.querySelectorAll("input[data-retirar-id]")).filter((i) => i.checked).map((i) => i.dataset.retirarId);
          return window.RaioX.premissas.alterar({ retiradas: marcadas }, true);
        }));
        label.appendChild(chk);
        label.appendChild(el("span", null, rot));
        listaRetirar.appendChild(label);
        if (c.id === "alta_tensao") {
          const lf = el("label", "faixa-at");
          lf.appendChild(el("span", null, "faixa da linha aérea (m):"));
          const inp = el("input");
          inp.type = "text";
          inp.inputMode = "decimal";
          inp.dataset.faixaAltaTensao = "1";
          inp.value = p ? fmt.decimal.format(p.faixa_alta_tensao_m) : "";
          inp.addEventListener("change", ctx.proteger(() => {
            const v = window.RaioX.parsearNumeroDigitado(inp.value);
            if (v === null || Number.isNaN(v) || v <= 0) {
              mensagem("A faixa da linha aérea deve ser um número maior que zero.", "erro");
              return undefined;
            }
            return window.RaioX.premissas.alterar({ faixa_alta_tensao_m: v }, true);
          }));
          lf.appendChild(inp);
          listaRetirar.appendChild(lf);
          listaRetirar.appendChild(el("p", "nota", "A largura depende da tensão; confirme com a concessionária."));
        }
      }
    }

    function sincronizarRetiradas() {
      const p = window.RaioX.premissas.atuais();
      if (!p) return;
      listaRetirar.querySelectorAll("input[data-retirar-id]").forEach((i) => { i.checked = p.retiradas.includes(i.dataset.retirarId); });
      const faixa = listaRetirar.querySelector("input[data-faixa-alta-tensao]");
      if (faixa) faixa.value = fmt.decimal.format(p.faixa_alta_tensao_m);
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
        btn.disabled = btn === btnPasta ? false : !aberto;
      }
    }

    btnResumo.addEventListener("click", ctx.proteger(() => comBotao(btnResumo, "Gerando…", async () => {
      const res = await chamar("lote_copiar_resumo");
      if (!res.ok) { acoes(res.erro, "erro"); return; }
      try {
        await navigator.clipboard.writeText(res.texto);
        acoes("Resumo copiado.", "ok");
      } catch (eNavegador) {
        const clip = await chamar("copiar_texto", res.texto);
        if (clip.ok) { acoes("Resumo copiado.", "ok"); return; }
        textareaResumo.value = res.texto;
        reservaClip.classList.remove("hidden");
        textareaResumo.focus();
        textareaResumo.select();
        acoes("Não consegui copiar sozinha: selecione e use Ctrl+C.", "erro");
      }
    })));

    btnExcel.addEventListener("click", ctx.proteger(() => comBotao(btnExcel, "Gerando…", async () => {
      const res = await chamar("lote_exportar_excel");
      acoes(res.ok ? "Excel salvo em " + res.caminho : res.erro, res.ok ? "ok" : "erro");
    })));

    btnKmz.addEventListener("click", ctx.proteger(() => comBotao(btnKmz, "Gerando…", async () => {
      const res = await chamar("lote_exportar_kmz");
      acoes(res.ok ? "KMZ salvo em " + res.caminho : res.erro, res.ok ? "ok" : "erro");
    })));

    function fecharCroqui() { modalCroqui.classList.add("hidden"); modalCorpo.replaceChildren(); }
    btnCroqui.addEventListener("click", ctx.proteger(() => comBotao(btnCroqui, "Gerando…", async () => {
      const res = await chamar("lote_croqui");
      if (!res.ok) { acoes(res.erro, "erro"); return; }
      modalCorpo.innerHTML = res.svg;
      modalCroqui.classList.remove("hidden");
      $("btn-fechar-croqui").focus();
    })));
    $("btn-fechar-croqui").addEventListener("click", fecharCroqui);
    modalCroqui.addEventListener("click", (e) => { if (e.target === modalCroqui) fecharCroqui(); });
    window.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modalCroqui.classList.contains("hidden")) fecharCroqui(); });

    btnPasta.addEventListener("click", ctx.proteger(() => comBotao(btnPasta, "Abrindo…", async () => {
      const res = await chamar("abrir_pasta_saida");
      if (!res.ok) acoes(res.erro, "erro");
    })));

    // --- Busca, KMZ e Simular ---
    inputBusca.addEventListener("keydown", ctx.proteger((e) => {
      if (e.key !== "Enter") return undefined;
      e.preventDefault();
      const texto = inputBusca.value.trim();
      return texto ? consultar(texto) : undefined;
    }));
    btnAbrirKmz.addEventListener("click", () => inputArquivo.click());
    inputArquivo.addEventListener("change", ctx.proteger(async (e) => {
      const arq = e.target.files && e.target.files[0];
      inputArquivo.value = "";
      if (arq) await carregarArquivo(arq);
    }));
    btnSimular.addEventListener("click", ctx.proteger(() => window.RaioX.ativarAba("simulador")));

    habilitarSaidas(false);

    return {
      aoPonteProntas: () => montarRetiradas(),
      aoMudarPremissas(motivo) {
        sincronizarRetiradas();
        if (motivo !== "alteracao" || !aberto) return undefined;
        return executar("Recalculando com as premissas novas…", "lote_recalcular", [premissasOuErro()], null);
      },
      aoMudarFoco(f, origem) {
        foco = f;
        if (origem === "lote") { renderizarComposicao(); return undefined; }
        sub = 0;
        pendente = true;
        return ctx.ativa() ? carregarFoco() : undefined;
      },
      aoAtivar() {
        mapa.invalidar();
        travarNaQuadra();
        if (pendente) return carregarFoco();
        return carga || Promise.resolve();
      },
      soltarArquivo: (arquivo) => carregarArquivo(arquivo),
      // Detalhe do Prospectar: "Ver este lote no Raio-X" (um lote da composição em foco).
      mostrarLote: (cd) => mostrarLote(cd),
      estadoTela() {
        const feats = aberto ? aberto.quarteirao_geojson.features : [];
        const lote = aberto ? aberto.resultado.lote : null;
        const prefixo = lote ? lote.setor + "." + lote.quadra + "." : "";
        let destacado = false;
        if (camadaQuadra) camadaQuadra.eachLayer((l) => { if (l.feature.properties.aberto && l.options.color === COR.foco) destacado = true; });
        return {
          aberto: lote ? lote.cd_identificador : null,
          composicao: foco ? foco.ids.length : 0,
          quarteirao: { n: feats.length, todos_da_quadra: feats.length > 0 && feats.every((f) => f.properties.sql.startsWith(prefixo)), aberto_destacado: destacado },
          travado,
          texto: resultadoEl.textContent
        };
      }
    };
  }

  window.RaioX.registrarAba("lote", "Raio-X do lote", iniciar);
})();
