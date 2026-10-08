# Creates the TTS server environment: tts_server\.venv with PyTorch (CUDA 12.8) + OmniVoice.
# Run once:  .\tts_server\setup.ps1
# The model (~3 GB) and Whisper (~1.6 GB) download on first use into the Hugging Face cache.
# Native tools write progress to stderr; failures are caught via exit codes in Check.
$ErrorActionPreference = "Continue"
$here = $PSScriptRoot

function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what falhou (codigo $LASTEXITCODE)" } }

$venv = Join-Path $here ".venv"
$py = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "==> criando ambiente em $venv" -ForegroundColor Cyan
    py -3.13 -m venv $venv; Check "criar venv"
}
& $py -m pip install -q --upgrade pip; Check "pip upgrade"

Write-Host "==> PyTorch 2.8 (CUDA 12.8)" -ForegroundColor Cyan
& $py -m pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --extra-index-url https://download.pytorch.org/whl/cu128
Check "instalar PyTorch"

Write-Host "==> OmniVoice e dependencias do servidor" -ForegroundColor Cyan
& $py -m pip install -r (Join-Path $here "requirements.txt"); Check "instalar OmniVoice"

Write-Host "==> verificando a GPU" -ForegroundColor Cyan
& $py -c "import torch; ok = torch.cuda.is_available(); print('CUDA:', ok, torch.cuda.get_device_name(0) if ok else '(sem GPU NVIDIA: o modelo vai rodar na CPU, bem mais lento)')"
Check "verificar GPU"
Write-Host "Pronto. Abra o app (ou reinicie o servidor de voz na aba Voz)." -ForegroundColor Green
