# Instalação do APEX no Windows.
#
#   powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1
#
# Cria o ambiente virtual, instala dependências, baixa a voz e testa o áudio.

$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

function Passo($texto) {
    Write-Host ""
    Write-Host "──> $texto" -ForegroundColor Red
}

Write-Host ""
Write-Host "  APEX — instalação" -ForegroundColor Red
Write-Host "  ─────────────────" -ForegroundColor DarkGray

# --- Python -----------------------------------------------------------------

Passo "Conferindo o Python"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "Python não encontrado. Instale o 3.10 ou mais novo:" -ForegroundColor Yellow
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
    Write-Host "  .venv já existia"
}

$pip = ".\.venv\Scripts\pip.exe"
$py  = ".\.venv\Scripts\python.exe"

# --- Dependências -----------------------------------------------------------

Passo "Instalando dependências (demora alguns minutos)"
& $pip install --upgrade pip --quiet
& $pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "Alguma dependência falhou. Veja o erro acima." -ForegroundColor Yellow
    exit 1
}

# --- Config -----------------------------------------------------------------

Passo "Configuração"
if (-not (Test-Path "config.json")) {
    Copy-Item "config.example.json" "config.json"
    Write-Host "  config.json criado a partir do exemplo"
}

$config = Get-Content "config.json" -Raw | ConvertFrom-Json
if (-not $config.anthropic_api_key) {
    Write-Host ""
    Write-Host "  Preciso da sua chave da API da Anthropic." -ForegroundColor Yellow
    Write-Host "  Pegue em: https://console.anthropic.com/settings/keys"
    Write-Host "  (Enter pra pular e preencher o config.json na mão)"
    $chave = Read-Host "  Chave"
    if ($chave) {
        $config.anthropic_api_key = $chave
        $config | ConvertTo-Json -Depth 10 | Set-Content "config.json" -Encoding UTF8
        Write-Host "  Chave salva no config.json"
    }
}

# --- Voz --------------------------------------------------------------------

Passo "Baixando a voz do Piper (pt-BR, offline)"
& $py -m apex.audio.tts --baixar-voz
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Não consegui baixar. O APEX vai cair pro edge-tts (precisa de internet)." -ForegroundColor DarkYellow
}

# --- Modelo de transcrição --------------------------------------------------

Passo "Baixando o modelo de transcrição (roda offline depois)"
& $py -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8'); WhisperModel('tiny', device='cpu', compute_type='int8'); print('  modelos prontos')"

# --- Fim --------------------------------------------------------------------

Write-Host ""
Write-Host "  Pronto." -ForegroundColor Green
Write-Host ""
Write-Host "  Testar o microfone:  .\.venv\Scripts\python.exe -m apex --testar-audio"
Write-Host "  Testar sem voz:      .\.venv\Scripts\python.exe -m apex --texto"
Write-Host "  Rodar de verdade:    .\rodar.bat"
Write-Host ""
