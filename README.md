# Raio-X de Terrenos SP

Programa de consulta urbanística e de área útil para terrenos em São Paulo. Mostra fatos e contas
transparentes (zoneamento, coeficiente de aproveitamento, restrições, área útil, simulação) para apoiar
a análise de quem decide. Usa dados públicos do GeoSampa (Prefeitura de São Paulo), baixados na hora do
uso e guardados no próprio computador.

## Testar o computador antes de instalar
Baixe a pasta `teste-colega`, abra o `TESTAR.bat` e envie o `resultado-teste.txt` gerado.
O teste não instala nada e não lê seus arquivos.

## Instalar
O programa pronto (`Raio-X`) fica na área **Releases** deste repositório. Baixe, extraia e abra
`Raio-X.exe`. Não precisa de administrador nem de Python.

## Dados
- Lotes e camadas vêm do GeoSampa por quadrados de 3 km, só da área que você consulta.
- Ficam em `%LOCALAPPDATA%\Raio-X\dados`. O programa avisa quando passarem de 30 dias e pergunta se
  você quer atualizar.
- Arquivos gerados (Excel, KMZ) vão para `Downloads\RaioX`.

Os dados do GeoSampa são públicos; consulte os termos da Prefeitura para reutilização.
