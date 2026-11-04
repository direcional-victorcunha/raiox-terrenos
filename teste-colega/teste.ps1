# Teste de compatibilidade do PC para o Raio-X (nao instala nada, nao le seus arquivos).
# Verifica: rede ate o GeoSampa e o GitHub, WebView2 (janela do programa) e se o PC deixa rodar um .exe novo.
# Escreve o resultado em resultado-teste.txt, na mesma pasta. Texto sem acentos de proposito.

$ErrorActionPreference = "Continue"
$pasta = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$saida = Join-Path $pasta "resultado-teste.txt"
$linhas = New-Object System.Collections.Generic.List[string]
function Reg($t) { $linhas.Add($t); Write-Host $t }

Reg "=== Teste Raio-X em $(Get-Date -Format 'yyyy-MM-dd HH:mm') ==="
Reg ""

# 1. Sistema
$os = (Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue)
Reg "[1] Windows: $($os.Caption) versao $($os.Version)"
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Reg "    Executando como administrador: $admin"
Reg "    Modo da linguagem PowerShell: $($ExecutionContext.SessionState.LanguageMode)  (ConstrainedLanguage = PC bem travado)"

# 2. WebView2 (a janela do programa depende dele)
$wv = $null
foreach ($k in @("HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
                 "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
                 "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}")) {
    $v = (Get-ItemProperty $k -ErrorAction SilentlyContinue).pv
    if ($v) { $wv = $v; break }
}
Reg "[2] WebView2 Runtime: $(if ($wv) { 'INSTALADO, versao ' + $wv } else { 'NAO ENCONTRADO' })"

# 3. Rede
function Testar($nome, $url) {
    $t = Get-Date
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 40
        $ms = [int]((Get-Date) - $t).TotalMilliseconds
        Reg "    OK   $nome  (HTTP $($r.StatusCode), $ms ms, $($r.RawContentLength) bytes)"
    } catch {
        $msg = $_.Exception.Message
        Reg "    FALHOU $nome  -> $msg"
    }
}
Reg "[3] Rede"
$wfs = "http://wfs.geosampa.prefeitura.sp.gov.br/geoserver/wfs?service=WFS&version=2.0.0&request=GetFeature&typeNames=geoportal:lote_cidadao&outputFormat=application/json&srsName=EPSG:4326&count=5&bbox=354000,7397000,354300,7397300,EPSG:31983"
Testar "GeoSampa WFS (lotes, http)" $wfs
Testar "GitHub (atualizacao do programa, https)" "https://github.com"
Testar "GitHub raw (https)" "https://raw.githubusercontent.com/github/gitignore/main/README.md"
Testar "Imagem de satelite do mapa (Esri, https)" "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/14/6200/4000"
$proxy = (Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" -ErrorAction SilentlyContinue)
Reg "    Proxy ligado: $($proxy.ProxyEnable)   servidor: $($proxy.ProxyServer)   script automatico: $($proxy.AutoConfigURL)"

# 4. Executavel novo em pasta do usuario (o ponto mais incerto: AppLocker / antivirus)
Reg "[4] Executar .exe a partir da pasta do usuario"
$dest = Join-Path $env:LOCALAPPDATA "Raio-X-teste"
New-Item -ItemType Directory -Force -Path $dest | Out-Null

# 4a. um .exe assinado da Microsoft copiado para la (testa a regra de CAMINHO)
$copia = Join-Path $dest "whoami-copia.exe"
try {
    Copy-Item "$env:SystemRoot\System32\whoami.exe" $copia -Force
    $saidaExe = & $copia 2>&1
    Reg "    4a. copia de exe assinado (Microsoft): RODOU"
} catch {
    Reg "    4a. copia de exe assinado (Microsoft): BLOQUEADO -> $($_.Exception.Message)"
}

# 4b. um .exe novo, sem assinatura, compilado agora (testa o caso real: programa nosso, nao assinado)
$csc = Join-Path $env:SystemRoot "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$fonte = Join-Path $dest "ola.cs"
$exeNovo = Join-Path $dest "ola.exe"
if (Test-Path $csc) {
    'class P { static void Main() { System.Console.WriteLine("ola"); } }' | Set-Content -Path $fonte -Encoding ASCII
    try {
        & $csc /nologo /out:$exeNovo $fonte 2>&1 | Out-Null
        if (Test-Path $exeNovo) {
            try { $o = & $exeNovo 2>&1; Reg "    4b. exe novo sem assinatura: RODOU (saida: $o)" }
            catch { Reg "    4b. exe novo sem assinatura: BLOQUEADO ao executar -> $($_.Exception.Message)" }
        } else { Reg "    4b. nao consegui criar o exe de teste (antivirus pode ter apagado)" }
    } catch { Reg "    4b. compilador bloqueado -> $($_.Exception.Message)" }
} else {
    Reg "    4b. compilador do .NET nao encontrado; teste pulado"
}

# 5. Escrita em Arquivos de Programas (esperado: negado sem administrador)
Reg "[5] Gravar em Arquivos de Programas"
try {
    $t = Join-Path $env:ProgramFiles "teste-raiox.tmp"
    "x" | Set-Content $t -ErrorAction Stop
    Remove-Item $t -Force
    Reg "    PERMITIDO (tem administrador)"
} catch { Reg "    NEGADO (esperado sem administrador)" }

# 6. Python instalado? (so informativo)
$py = (Get-Command python -ErrorAction SilentlyContinue)
Reg "[6] Python no PC: $(if ($py) { $py.Source } else { 'nao' })"

# Limpeza
Remove-Item $dest -Recurse -Force -ErrorAction SilentlyContinue

Reg ""
Reg "Fim. Mande o arquivo resultado-teste.txt de volta."
$linhas | Set-Content -Path $saida -Encoding UTF8
Write-Host ""
Write-Host "Resultado salvo em: $saida"
