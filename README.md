# Raio-X de Terrenos SP

Programa para consultar um terreno em São Paulo: zoneamento, coeficiente de aproveitamento, restrições
(água, alta tensão, melhoramento viário e outras), área útil e simulação. Mostra fatos e contas à vista,
para apoiar a análise de quem decide. Usa dados públicos do GeoSampa (Prefeitura de São Paulo).

---

## Passo 1 · Testar se o seu computador serve (5 minutos)

Isso não instala nada e não lê os seus arquivos.

1. Nesta página, clique no botão verde **Code** e depois em **Download ZIP**.
2. Abra o arquivo baixado e **extraia** (botão direito > Extrair tudo).
3. Entre na pasta **teste-colega** e dê dois cliques em **TESTAR.bat**.
4. Espere até 2 minutos. No fim, aparece o arquivo **resultado-teste.txt** na mesma pasta.
5. Envie o **resultado-teste.txt** para quem pediu o teste.

Se o Windows avisar que o arquivo é desconhecido, clique em *Mais informações > Executar assim mesmo*.
Se o `.bat` for bloqueado, avise quem pediu o teste.

## Passo 2 · Baixar o programa

1. Abra a página de versões: <https://github.com/direcional-victorcunha/raiox-terrenos/releases/latest>
2. Em **Assets**, clique em **Raio-X-<versão>.zip** para baixar (cerca de 70 MB).
3. **Extraia** o zip numa pasta sua, por exemplo `Documentos\Raio-X`. Não precisa de administrador
   nem de Python. Evite pastas protegidas, como *Arquivos de Programas*.
4. Dê dois cliques em **Raio-X.exe**. Para facilitar, clique com o botão direito nele > *Enviar para* >
   *Área de trabalho (criar atalho)*.

Se o Windows mostrar *"O Windows protegeu seu computador"*, clique em **Mais informações** e em
**Executar assim mesmo**. Se o antivírus ou a TI bloquear o programa, avise quem pediu o teste.

## Passo 3 · Usar

Na primeira vez em cada região, o programa baixa os dados do GeoSampa (uns 30 a 60 segundos) e mostra uma
faixa de progresso. Depois disso a mesma região abre na hora, e funciona sem internet. O mapa de fundo
(satélite) precisa de internet.

A aba **Prospectar** é o ponto de partida:

1. **Marcar no mapa**: clique num ponto e escolha o raio (de 100 m a 5 km). O programa lista os lotes da
   área e destaca as oportunidades.
2. **Desenhar área**: marque os vértices no mapa e feche a figura.
3. **Soltar um KMZ**: arraste o arquivo do Google Earth para a janela.
4. Clique num lote para pô-lo em **foco** (faixa no topo). Daí:
   - **Raio-X do lote**: zoneamento, CA, restrições, área útil, estação mais próxima.
   - **Simulador**: outorga, resíduo e resultado, com os números à vista.

Ajuste as **premissas** (regime, preço por m², meta) na barra do topo; o que estiver aberto é recalculado.
Os arquivos gerados (Excel, KMZ, CSV) vão para a pasta **Downloads\RaioX**.

Neste programa **não existe busca por endereço**: localize o terreno pelo mapa, pelo desenho ou por um KMZ.
A busca por SQL só acha lotes de áreas que você já abriu.

## Atualizações

- **Dados:** a cada 30 dias o programa avisa que os dados baixados estão velhos e pergunta se você quer
  atualizar. Nada é atualizado sem você pedir.
- **Programa:** ao abrir, se houver versão nova, aparece uma faixa *"Há uma versão nova… Atualizar agora"*.
  Aceitando, ele baixa, fecha e abre de novo sozinho. Se a pasta for protegida, baixe a versão nova pela
  página de versões (Passo 2).

## Se algo der errado

- **A janela não abre:** confira se o *Microsoft Edge WebView2* está instalado (já vem no Windows 11).
- **"Não consegui baixar os dados":** confira a internet e tente de novo. Se continuar, o servidor da
  Prefeitura pode estar fora do ar; tente mais tarde.
- **Um aviso diz que uma camada não está disponível:** o cálculo continua sem ela; o aviso diz qual.
- **Diagnóstico:** abra o *Prompt de Comando* na pasta do programa e rode `Raio-X.exe --diagnostico`.
  Ele grava `%TEMP%\raiox_diagnostico.json`; envie esse arquivo a quem presta o suporte.
- **Onde ficam os dados baixados:** `%LOCALAPPDATA%\Raio-X\dados`. Pode apagar a pasta para forçar um
  novo download; o programa recria tudo.

Os dados são do GeoSampa (Prefeitura de São Paulo); consulte os termos de reutilização no portal deles.
Programa fornecido sem garantia: confira os números antes de decidir.
