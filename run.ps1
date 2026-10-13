# SesKlon — Docker'sız yerel çalıştırma (Windows PowerShell 5.1 ve PowerShell 7). Linux/macOS için: run.sh
#
#   .\run.ps1          gerekirse kurar, arayüzü derler ve http://localhost:8000 adresinde başlatır
#   .\run.ps1 -Dev     geliştirme: API (uvicorn --reload, :8000) + arayüz (vite, :5173) birlikte ("--dev" de olur)
#
# Yürütme ilkesi betiği engelliyorsa:  powershell -ExecutionPolicy Bypass -File .\run.ps1
# Gereksinimler: Python 3.10+ (önerilen 3.11), Node.js 18+ (önerilen 20), ffmpeg, git (hepsi PATH'te).
# Ayarlar: proje kökündeki .env okunur (bkz. .env.example); zaten tanımlı ortam değişkenleri ezilmez.
# Kurulum seçenekleri (yalnızca bu betik için):
#   $env:TORCH_INDEX   PyTorch'un kurulacağı dizin. Boşsa: NVIDIA GPU (nvidia-smi) varsa CUDA 12.4 dizini
#                      (https://download.pytorch.org/whl/cu124), yoksa PyPI (Windows'ta PyPI sürümü yalnız CPU'dur).
#   $env:TORCH_VERSION Kurulacak PyTorch sürümü (varsayılan 2.6.0 — Chatterbox'ın sabitlediği sürüm).
# Not: Bu dosya UTF-8 (BOM'lu) kaydedilmelidir; yoksa Windows PowerShell 5.1 Türkçe karakterleri bozar.

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$Root = $PSScriptRoot
$env:PYTHONUTF8 = '1'   # Python Windows'ta da UTF-8 kullansın (Türkçe metin, JSON, günlükler)

function Bilgi([string]$Mesaj) { Write-Host $Mesaj }
function Uyari([string]$Mesaj) { Write-Host "Uyarı: $Mesaj" -ForegroundColor Yellow }
function Hata([string]$Mesaj) { Write-Host "Hata: $Mesaj" -ForegroundColor Red; exit 1 }

function Kullanim {
    Write-Host @'
Kullanım: .\run.ps1 [-Dev]

  (seçeneksiz)  Sanal ortamı ve paketleri gerekirse kurar, arayüzü derler, http://localhost:8000 adresinde başlatır.
  -Dev, --dev   Geliştirme modu: API (uvicorn --reload, :8000) ve arayüz (vite, :5173) birlikte çalışır.
                Arayüzü http://localhost:5173 adresinden açın; kod değişiklikleri anında yansır.
  -h, --help    Bu yardımı gösterir.
'@
}

$Dev = $false
foreach ($a in $args) {
    if ($a -in @('-Dev', '--dev', '-d', '/dev')) { $Dev = $true }
    elseif ($a -in @('-h', '--help', '-help', '/?')) { Kullanim; exit 0 }
    else { Kullanim; Hata "Bilinmeyen seçenek: $a" }
}

# ---------- .env (varsa) ----------
# KEY=değer satırları okunur; yorum ve boş satırlar atlanır, tırnaklar soyulur, boş değerler (KEY=) varsayılan
# demektir, ortamda zaten tanımlı olanlar ezilmez.
function EnvYukle {
    $dosya = Join-Path $Root '.env'
    if (-not (Test-Path -LiteralPath $dosya)) { return }
    foreach ($satir in [System.IO.File]::ReadAllLines($dosya)) {
        $s = $satir.Trim()
        if ($s -eq '' -or $s.StartsWith('#')) { continue }
        if ($s.StartsWith('export ')) { $s = $s.Substring(7).Trim() }
        $i = $s.IndexOf('=')
        if ($i -lt 1) { continue }
        $k = $s.Substring(0, $i).Trim()
        if ($k -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { continue }
        $v = $s.Substring($i + 1).Trim()
        if ($v.Length -ge 2 -and (($v.StartsWith('"') -and $v.EndsWith('"')) -or ($v.StartsWith("'") -and $v.EndsWith("'")))) {
            $v = $v.Substring(1, $v.Length - 2)
        } else {
            $v = ($v -replace '\s+#.*$', '').Trim()
        }
        if ($v -eq '') { continue }
        if ($null -eq [Environment]::GetEnvironmentVariable($k)) {
            [Environment]::SetEnvironmentVariable($k, $v, 'Process')
        }
    }
}
EnvYukle

function KomutVar([string]$Komut) { return [bool](Get-Command $Komut -ErrorAction SilentlyContinue) }

# ---------- ön kontroller ----------
if (-not (KomutVar 'ffmpeg')) {
    Hata ("ffmpeg bulunamadı. SesKlon ses dönüştürme (mikrofon kayıtları dahil), MP3, tempo ve mastering için ffmpeg kullanır.`n" +
        "  Kurulum: winget install Gyan.FFmpeg   (ya da https://www.gyan.dev/ffmpeg/builds/ — bin klasörünü PATH'e ekleyin)`n" +
        "  Kurduktan sonra YENİ bir PowerShell penceresi açıp .\run.ps1 komutunu tekrar çalıştırın.")
}

function PythonBul {
    $ErrorActionPreference = 'SilentlyContinue'
    $adaylar = @()
    if (KomutVar 'py') { foreach ($s in '3.11', '3.12', '3.10', '3.13') { $adaylar += , @('py', "-$s") } }
    foreach ($ad in 'python', 'python3') { if (KomutVar $ad) { $adaylar += , @($ad) } }
    foreach ($aday in $adaylar) {
        $exe = $aday[0]
        $ek = @($aday | Select-Object -Skip 1)
        $surum = $null
        $global:LASTEXITCODE = 1
        try { $surum = @(& $exe @ek -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null)[0] } catch { $surum = $null }
        # Microsoft Store'un sahte python.exe'si 9009 ile döner; sürüm satırı da vermez.
        if ($LASTEXITCODE -eq 0 -and "$surum".Trim() -match '^3\.1\d$') {
            return @{ Exe = $exe; Ek = $ek; Surum = "$surum".Trim() }
        }
    }
    return $null
}

function NodeKontrol {
    if (-not (KomutVar 'node')) { Hata "Node.js bulunamadı (arayüzü derlemek için gerekli). Kurulum: winget install OpenJS.NodeJS.LTS" }
    if (-not (KomutVar 'npm')) { Hata "npm bulunamadı (Node.js ile birlikte gelir). Kurulum: winget install OpenJS.NodeJS.LTS" }
    $ana = 0
    try { $ana = [int](& node -p "process.versions.node.split('.')[0]") } catch { $ana = 0 }
    if ($ana -lt 18) { Hata "Node.js $(& node -v) çok eski; en az 18 gerekli (önerilen 20). Kurulum: winget install OpenJS.NodeJS.LTS" }
}

function ArayuzBagimliliklari {
    $fe = Join-Path $Root 'frontend'
    $nm = Join-Path $fe 'node_modules'
    $kilit = Join-Path $fe 'package-lock.json'
    $kurulu = Join-Path $nm '.package-lock.json'
    $gerekli = -not (Test-Path -LiteralPath $nm)
    if (-not $gerekli -and (Test-Path -LiteralPath $kilit) -and (Test-Path -LiteralPath $kurulu)) {
        $gerekli = (Get-Item -LiteralPath $kilit).LastWriteTimeUtc -gt (Get-Item -LiteralPath $kurulu).LastWriteTimeUtc
    }
    if (-not $gerekli) { return }
    Bilgi 'Arayüz bağımlılıkları kuruluyor (npm)…'
    Push-Location -LiteralPath $fe
    try {
        if (Test-Path -LiteralPath $kilit) { & npm ci --no-audit --no-fund } else { & npm install --no-audit --no-fund }
        if ($LASTEXITCODE -ne 0) { Hata 'Arayüz bağımlılıkları kurulamadı (npm).' }
    } finally { Pop-Location }
}

function ArayuzGuncelMi {
    $index = Join-Path $Root 'frontend\dist\index.html'
    if (-not (Test-Path -LiteralPath $index)) { return $false }
    $t = (Get-Item -LiteralPath $index).LastWriteTimeUtc
    $yeni = Get-ChildItem -LiteralPath (Join-Path $Root 'frontend') -Force |
        Where-Object { $_.Name -notin @('node_modules', 'dist') } |
        ForEach-Object { if ($_.PSIsContainer) { Get-ChildItem -LiteralPath $_.FullName -Recurse -File -Force -ErrorAction SilentlyContinue } else { $_ } } |
        Where-Object { $_.LastWriteTimeUtc -gt $t } |
        Select-Object -First 1
    return ($null -eq $yeni)
}

# ---------- Python sanal ortamı ----------
$Venv = Join-Path $Root '.venv'
$Py = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Py)) {
    if (Test-Path -LiteralPath $Venv) {
        Uyari 'Yarım kalmış .venv klasörü bulundu; yeniden oluşturuluyor.'
        Remove-Item -LiteralPath $Venv -Recurse -Force
    }
    $p = PythonBul
    if ($null -eq $p) {
        Hata ("Python 3.10 veya üstü bulunamadı (önerilen 3.11).`n" +
            "  Kurulum: winget install Python.Python.3.11   (python.org kurulumunda 'Add python.exe to PATH' seçin)")
    }
    if ($p.Surum -ne '3.11') { Uyari "Python $($p.Surum) kullanılacak; en çok test edilen sürüm 3.11." }
    Bilgi "Sanal ortam oluşturuluyor (.venv, Python $($p.Surum))…"
    $ek = $p.Ek
    & $p.Exe @ek -m venv $Venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Py)) {
        if (Test-Path -LiteralPath $Venv) { Remove-Item -LiteralPath $Venv -Recurse -Force }
        Hata 'Sanal ortam oluşturulamadı. Python kurulumunuzu kontrol edin.'
    }
}

# Paketler yalnızca ilk kurulumda ya da requirements.txt / TORCH_INDEX değişince kurulur (sonraki açılışlar hızlı,
# internetsiz de çalışır).
$TorchIndex = "$env:TORCH_INDEX"
$TorchVersion = if ($env:TORCH_VERSION) { $env:TORCH_VERSION } else { '2.6.0' }
$otoCuda = $false
if (-not $TorchIndex -and (KomutVar 'nvidia-smi')) {
    $TorchIndex = 'https://download.pytorch.org/whl/cu124'
    $otoCuda = $true
}
$ozet = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $Root 'backend\requirements.txt')).Hash
$istenen = "$ozet $TorchIndex".Trim()
$damga = Join-Path $Venv '.sesklon-kurulum'
$mevcut = ''
if (Test-Path -LiteralPath $damga) { $mevcut = ([System.IO.File]::ReadAllText($damga)).Trim() }
if ($istenen -ne $mevcut) {
    if (-not (KomutVar 'git')) { Hata 'git bulunamadı (Chatterbox V3 GitHub kaynağından kurulur). Kurulum: winget install Git.Git' }
    if ($mevcut -eq '') {
        Bilgi 'İlk kurulum: Python paketleri iniyor (PyTorch dahil birkaç GB; bağlantıya göre 5–15 dk sürebilir).'
    } else {
        Bilgi 'requirements.txt ya da TORCH_INDEX değişmiş; Python paketleri güncelleniyor…'
    }
    & $Py -m pip install -q --upgrade pip
    if ($LASTEXITCODE -ne 0) { Hata 'pip güncellenemedi. İnternet bağlantınızı kontrol edin.' }
    if ($TorchIndex) {
        if ($otoCuda) {
            Bilgi 'NVIDIA GPU bulundu: PyTorch CUDA 12.4 sürümüyle kurulacak (~2,5 GB).'
            Bilgi "  CPU sürümü isterseniz: `$env:TORCH_INDEX='https://download.pytorch.org/whl/cpu'; .\run.ps1"
        }
        # Yerel sürüm etiketi (+cu124, +cpu) verilir; böylece önceden kurulmuş farklı bir yapı da değiştirilir.
        $etiket = ($TorchIndex.TrimEnd('/') -split '/')[-1]
        $spec = $TorchVersion
        if ($etiket -match '^(cpu|cu\d+|rocm[\d.]+)$') { $spec = "$TorchVersion+$etiket" }
        Bilgi "PyTorch $spec şu kaynaktan kuruluyor: $TorchIndex"
        & $Py -m pip install "torch==$spec" "torchaudio==$spec" --index-url $TorchIndex
        if ($LASTEXITCODE -ne 0) { Hata "PyTorch kurulamadı (TORCH_INDEX=$TorchIndex, sürüm $spec)." }
    }
    & $Py -m pip install -r (Join-Path $Root 'backend\requirements.txt')
    if ($LASTEXITCODE -ne 0) { Hata 'Python paketleri kurulamadı. Yukarıdaki pip çıktısını ve internet bağlantınızı kontrol edin.' }
    [System.IO.File]::WriteAllText($damga, $istenen)
    Write-Host 'Python paketleri hazır.' -ForegroundColor Green
}

# ---------- model notu ----------
if ($env:HF_HUB_CACHE) { $hfHub = $env:HF_HUB_CACHE }
elseif ($env:HF_HOME) { $hfHub = Join-Path $env:HF_HOME 'hub' }
else { $hfHub = Join-Path $env:USERPROFILE '.cache\huggingface\hub' }
$modelVar = Get-ChildItem -LiteralPath $hfHub -Directory -Filter 'models--ResembleAI--*' -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $modelVar) {
    Bilgi "Not: Model (~2 GB) ilk açılışta Hugging Face'ten inecek ve $hfHub altında saklanacak."
    Bilgi "     İnerken arayüz 'model yükleniyor' gösterir; sonraki açılışlarda yeniden inmez."
}

# ---------- geliştirme modu ----------
if ($Dev) {
    NodeKontrol
    ArayuzBagimliliklari
    $node = (Get-Command node -CommandType Application | Select-Object -First 1).Path
    $vite = Start-Process -FilePath $node -ArgumentList 'node_modules/vite/bin/vite.js' `
        -WorkingDirectory (Join-Path $Root 'frontend') -NoNewWindow -PassThru
    Bilgi ''
    Write-Host 'Geliştirme modu: arayüz http://localhost:5173 (canlı yenileme) • API http://localhost:8000/api/docs' -ForegroundColor Green
    Bilgi 'Durdurmak için Ctrl+C.'
    try {
        Set-Location -LiteralPath (Join-Path $Root 'backend')
        & $Py -m uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000
    } finally {
        Set-Location -LiteralPath $Root
        if ($vite -and -not $vite.HasExited) {
            $ErrorActionPreference = 'SilentlyContinue'
            & taskkill.exe /PID $vite.Id /T /F 2>&1 | Out-Null
        }
    }
    exit 0
}

# ---------- normal mod ----------
if (-not (ArayuzGuncelMi)) {
    if ((Test-Path -LiteralPath (Join-Path $Root 'frontend\dist\index.html')) -and -not (KomutVar 'node')) {
        Uyari 'Arayüz kaynakları derlenmiş sürümden yeni ama Node.js bulunamadı; mevcut (eski) arayüzle devam ediliyor.'
    } else {
        NodeKontrol
        ArayuzBagimliliklari
        Bilgi 'Arayüz derleniyor…'
        Push-Location -LiteralPath (Join-Path $Root 'frontend')
        try {
            & npm run build
            if ($LASTEXITCODE -ne 0) { Hata 'Arayüz derlenemedi (npm run build). Yukarıdaki çıktıya bakın.' }
        } finally { Pop-Location }
    }
}

$env:FRONTEND_DIST = Join-Path $Root 'frontend\dist'
if (-not $env:API_KEY) {
    Bilgi 'Not: API_KEY boş; aynı ağdaki herkes bu bilgisayarın 8000 numaralı portuna erişebilir. İnternete açacaksanız'
    Bilgi '     .env dosyasında API_KEY tanımlayın. (Windows Güvenlik Duvarı sorarsa "Özel ağlar" yeterlidir.)'
}
Write-Host 'SesKlon başlıyor → http://localhost:8000   (durdurmak için Ctrl+C)' -ForegroundColor Green
Set-Location -LiteralPath (Join-Path $Root 'backend')
& $Py -m uvicorn app.main:app --host 0.0.0.0 --port 8000
exit $LASTEXITCODE
