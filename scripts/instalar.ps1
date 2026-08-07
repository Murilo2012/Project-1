# Instalacao do APEX no Windows.
#
#   powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1
#
# ATENCAO AO EDITAR ESTE ARQUIVO: use SOMENTE ASCII.
# O Windows PowerShell 5.1 le arquivos .ps1 como ANSI (Windows-1252), nao como
# UTF-8. Qualquer acento ou travessao vira lixo e quebra o parser inteiro, com
# erros que nao parecem ter nada a ver com a linha do acento.

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

function Passo($texto) {
    Write-Host ""
    Write-Host "--> $texto" -ForegroundColor Red
}

# Grava UTF-8 SEM BOM. O `Set-Content -Encoding UTF8` do PowerShell 5.1 escreve
# COM BOM, e os tres bytes invisiveis no comeco fazem o json do Python recusar.
function Write-Utf8NoBom($caminho, $texto) {
    $semBom = New-Object System.Text.UTF8Encoding $false
    $completo = [System.IO.Path]::GetFullPath((Join-Path $PWD $caminho))
    [System.IO.File]::WriteAllText($completo, $texto, $semBom)
}

Write-Host ""
Write-Host "  APEX - instalacao" -ForegroundColor Red
Write-Host "  -----------------" -ForegroundColor DarkGray

# --- Python -----------------------------------------------------------------

Passo "Conferindo o Python"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python nao encontrado. Instale o 3.10 ou mais novo:" -ForegroundColor Yellow
    Write-Host "  winget install Python.Python.3.12"
    exit 1
}
$versao = (python --version) -replace 'Python ', ''
Write-Host "  Python $versao"

$partes = $versao.Split('.')
if ([int]$partes[0] -lt 3 -or ([int]$partes[0] -eq 3 -and [int]$partes[1] -lt 10)) {
    Write-Host "Preciso do Python 3.10 ou mais novo." -ForegroundColor Yellow
    exit 1
}

# --- Ambiente virtual -------------------------------------------------------

Passo "Criando o ambiente virtual"
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    Write-Host "  .venv criado"
} else {
    Write-Host "  .venv ja existia"
}

$pip = ".\.venv\Scripts\pip.exe"
$py  = ".\.venv\Scripts\python.exe"

# --- Dependencias -----------------------------------------------------------

Passo "Instalando dependencias (demora alguns minutos)"
& $pip install --upgrade pip --quiet
& $pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "Alguma dependencia falhou. Veja o erro acima." -ForegroundColor Yellow
    exit 1
}

# --- Config -----------------------------------------------------------------

Passo "Configuracao"

if (-not (Test-Path "config.json")) {
    Copy-Item "config.example.json" "config.json"
    Write-Host "  config.json criado a partir do exemplo"
}

$config = Get-Content "config.json" -Raw | ConvertFrom-Json
if (-not $config.anthropic_api_key) {
    Write-Host ""
    Write-Host "  Preciso da sua chave da API da Anthropic." -ForegroundColor Yellow
    Write-Host "  Pegue em: https://console.anthropic.com/settings/keys"
    Write-Host "  (Enter pra pular. Da pra rodar local depois com: .\rodar.bat --local)"
    $chave = Read-Host "  Chave"
    if ($chave) {
        $config.anthropic_api_key = $chave.Trim()
        Write-Utf8NoBom "config.json" ($config | ConvertTo-Json -Depth 10)
        Write-Host "  Chave salva no config.json"
    }
}

# Confere agora: melhor descobrir aqui do que na primeira execucao.
& $py -c "import sys; sys.path.insert(0,'.'); import apex.config as c; c.load(); print('  config.json lido sem erro')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "  config.json esta ilegivel. Apague-o e rode a instalacao de novo." -ForegroundColor Yellow
    exit 1
}

# --- Voz --------------------------------------------------------------------

Passo "Baixando a voz do Piper (pt-BR, offline)"
& $py -m apex.audio.tts --baixar-voz
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Nao consegui baixar. O APEX vai cair pro edge-tts (precisa de internet)." -ForegroundColor DarkYellow
}

# --- Modelo de transcricao --------------------------------------------------

Passo "Baixando o modelo de transcricao (roda offline depois)"
& $py -c "from faster_whisper import WhisperModel as W; W('small', device='cpu', compute_type='int8'); W('tiny', device='cpu', compute_type='int8'); print('  modelos prontos')"

# --- Microfone --------------------------------------------------------------

Passo "Microfones encontrados"
& $py -m apex --listar-audio

# --- Fim --------------------------------------------------------------------

Write-Host ""
Write-Host "  Pronto." -ForegroundColor Green
Write-Host ""
Write-Host "  Testar o microfone:  .\rodar.bat --testar-audio"
Write-Host "  Escolher outro mic:  .\rodar.bat --testar-audio --dispositivo N"
Write-Host "  Testar sem voz:      .\rodar.bat --texto"
Write-Host "  Rodar de verdade:    .\rodar.bat"
Write-Host ""
