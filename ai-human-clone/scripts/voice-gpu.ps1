# Switch the cloned voice between a free Google Colab GPU (fast) and this laptop (slow CPU).
#   powershell -ExecutionPolicy Bypass -File scripts\voice-gpu.ps1
# GPU mode: copies your recorded voices and the notebook to Desktop\AI-Clone-GPU, puts the
# service token on the clipboard (never printed), sets LOCAL_VOICE_CLONE_URL to the Colab link
# and keeps the laptop service as LOCAL_VOICE_CLONE_FALLBACK_URL: when Colab stops, the app
# speaks from the laptop again by itself. Laptop mode removes the Colab link.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $root ".env"
$out = Join-Path ([Environment]::GetFolderPath("Desktop")) "AI-Clone-GPU"
Set-Location $root

function Get-EnvValue($name) {
    $line = Get-Content $envFile | Where-Object { $_ -match "^$name=" } | Select-Object -First 1
    if ($line) { return $line.Substring($name.Length + 1).Trim() }
    return ""
}

function Set-EnvValue($name, $value) {
    $lines = [System.Collections.Generic.List[string]](Get-Content $envFile)
    $index = $lines.FindIndex([Predicate[string]] { param($l) $l -match "^$name=" })
    if ($index -ge 0) { $lines[$index] = "$name=$value" } else { $lines.Add("$name=$value") }
    [IO.File]::WriteAllLines($envFile, $lines)
}

function Restart-Backend {
    Write-Host "Backend restart ho raha hai..."
    docker compose up -d backend | Out-Null
}

Write-Host ""
Write-Host "Aap ki aawaz kahan bane?"
Write-Host "  1 = Google Colab GPU (tez, muft)"
Write-Host "  2 = Isi laptop par (dheemi, internet ki zaroorat nahi)"
$choice = Read-Host "1 ya 2"

if ($choice -eq "2") {
    Set-EnvValue "LOCAL_VOICE_CLONE_URL" "http://voice-clone:8100"
    Set-EnvValue "LOCAL_VOICE_CLONE_FALLBACK_URL" ""
    Write-Host "Laptop wali voice service chalu ho rahi hai (model load: ~1-2 minute)..."
    docker compose --profile voice-clone up -d voice-clone | Out-Null
    Restart-Backend
    Write-Host "Ho gaya: aawaz ab laptop par banegi."
    Write-Host "Note: Colab par record ki gayi nayi aawaz laptop par nahi hogi; laptop par dobara record karein."
    exit 0
}
if ($choice -ne "1") { Write-Host "Sirf 1 ya 2 likhein."; exit 1 }

$token = Get-EnvValue "VOICE_CLONE_SERVICE_TOKEN"
if ($token.Length -lt 16) { Write-Host "VOICE_CLONE_SERVICE_TOKEN .env mein nahi hai."; exit 1 }

# 1) Notebook and recorded voices -> Desktop\AI-Clone-GPU
New-Item -ItemType Directory -Force (Join-Path $out "voices") | Out-Null
Copy-Item (Join-Path $root "voice-clone\colab\voice_clone_gpu.ipynb") $out -Force
docker run --rm --entrypoint sh -v ai-human-clone_voice_clone_data:/data -v "${out}\voices:/out" ai-human-clone-voice-clone `
    -c "cp /data/voices/*.wav /out/ 2>/dev/null; ls /out" | Out-Null
$count = (Get-ChildItem (Join-Path $out "voices") -Filter *.wav -ErrorAction SilentlyContinue | Measure-Object).Count
Write-Host ""
Write-Host "Tayyar: $out  (notebook + $count aawaz file)"
Write-Host ""
Write-Host "Ab ye karein:"
Write-Host "  1. https://colab.research.google.com kholen > File > Upload notebook > $out\voice_clone_gpu.ipynb"
Write-Host "  2. Pehli baar: Google Drive mein 'ai-clone-voices' folder banayein aur $out\voices ki .wav files us mein upload karein"
Write-Host "  3. Colab: Runtime > Change runtime type > T4 GPU > Save, phir Runtime > Run all"
Write-Host "  4. Token maange to Ctrl+V + Enter (token clipboard par copy ho gaya hai)"
Write-Host "  5. Aakhir mein jo https://....trycloudflare.com link aaye, wo neeche paste karein"
Set-Clipboard -Value $token
Write-Host ""

# 2) Colab link -> .env, after checking it answers with the GPU model loaded
while ($true) {
    $url = (Read-Host "Colab ka link").Trim().TrimEnd("/")
    if ($url -notmatch '^https://[a-z0-9-]+\.trycloudflare\.com$') { Write-Host "Link aisa hona chahiye: https://kuch-naam.trycloudflare.com"; continue }
    try {
        $health = Invoke-RestMethod "$url/health" -TimeoutSec 30
    } catch {
        Write-Host "Link se jawab nahi aaya. Colab cell chal raha hai? Dobara paste karein."
        continue
    }
    if (-not $health.model_loaded) { Write-Host "Model abhi load ho raha hai, thodi der baad dobara paste karein."; continue }
    Write-Host "Colab tayyar: device=$($health.device)"
    break
}
Set-EnvValue "LOCAL_VOICE_CLONE_URL" $url
Set-EnvValue "LOCAL_VOICE_CLONE_FALLBACK_URL" "http://voice-clone:8100"
Write-Host "Laptop wali voice service backup ke liye chalu rehti hai..."
docker compose --profile voice-clone up -d voice-clone | Out-Null
Restart-Backend
Set-Clipboard -Value " "
Write-Host ""
Write-Host "Ho gaya: aap ki aawaz ab Colab GPU par banegi. Colab ka tab khula rakhein."
Write-Host "Colab band ho to app khud laptop wali (dheemi) aawaz istemal karegi."
Write-Host "Colab dobara chalayen to ye script phir chalayen aur naya link dein."
