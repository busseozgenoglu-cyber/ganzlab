#!/usr/bin/env bash
# SesKlon — Docker'sız yerel çalıştırma (Linux/macOS). Windows için: run.ps1
#
#   ./run.sh          gerekirse kurar, arayüzü derler ve http://localhost:8000 adresinde başlatır
#   ./run.sh --dev    geliştirme: API (uvicorn --reload, :8000) + arayüz (vite, :5173) birlikte, canlı yenileme
#
# Gereksinimler: Python 3.10+ (önerilen 3.11), Node.js 18+ (önerilen 20), ffmpeg, git.
# Ayarlar: proje kökündeki .env okunur (bkz. .env.example); zaten tanımlı ortam değişkenleri ezilmez.
# Kurulum seçenekleri (yalnızca bu betik için):
#   TORCH_INDEX=https://download.pytorch.org/whl/cpu ./run.sh   GPU'suz Linux'ta CUDA'sız PyTorch (birkaç GB daha az)
#   TORCH_VERSION=2.6.0                                           TORCH_INDEX ile kurulacak sürüm (Chatterbox'ın sabitlediği)
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

if [ -t 1 ]; then
  KALIN=$'\033[1m'; SARI=$'\033[33m'; KIRMIZI=$'\033[31m'; YESIL=$'\033[32m'; SIFIRLA=$'\033[0m'
else
  KALIN=""; SARI=""; KIRMIZI=""; YESIL=""; SIFIRLA=""
fi
bilgi() { printf '%s\n' "$*"; }
uyari() { printf '%sUyarı:%s %s\n' "$SARI" "$SIFIRLA" "$*" >&2; }
hata() { printf '%sHata:%s %s\n' "$KIRMIZI" "$SIFIRLA" "$*" >&2; exit 1; }

kullanim() {
  cat <<'EOF'
Kullanım: ./run.sh [--dev]

  (seçeneksiz)  Sanal ortamı ve paketleri gerekirse kurar, arayüzü derler, http://localhost:8000 adresinde başlatır.
  --dev         Geliştirme modu: API (uvicorn --reload, :8000) ve arayüz (vite, :5173) birlikte çalışır.
                Arayüzü http://localhost:5173 adresinden açın; kod değişiklikleri anında yansır.
  -h, --help    Bu yardımı gösterir.
EOF
}

DEV=0
for arg in "$@"; do
  case "$arg" in
    --dev|-d) DEV=1 ;;
    -h|--help) kullanim; exit 0 ;;
    *) kullanim >&2; hata "Bilinmeyen seçenek: $arg" ;;
  esac
done

case "$(uname -s)" in
  Darwin) OS=mac ;;
  Linux) OS=linux ;;
  *) OS=diger ;;
esac

kur_ipucu() {
  case "$OS:$1" in
    mac:python) echo "brew install python@3.11  (ya da https://www.python.org/downloads/)" ;;
    mac:node) echo "brew install node@20  (ya da https://nodejs.org)" ;;
    mac:ffmpeg) echo "brew install ffmpeg" ;;
    mac:git) echo "xcode-select --install  (ya da: brew install git)" ;;
    linux:python) echo "Ubuntu/Debian: sudo apt install python3.11 python3.11-venv  •  Fedora: sudo dnf install python3.11" ;;
    linux:node) echo "https://nodejs.org adresinden LTS sürümü ya da nvm ile: nvm install 20" ;;
    linux:ffmpeg) echo "Ubuntu/Debian: sudo apt install ffmpeg  •  Fedora: sudo dnf install ffmpeg  •  Arch: sudo pacman -S ffmpeg" ;;
    linux:git) echo "Ubuntu/Debian: sudo apt install git  •  Fedora: sudo dnf install git" ;;
    *) echo "işletim sisteminizin paket yöneticisiyle kurun" ;;
  esac
}

# ---------- .env (varsa) ----------
# KEY=değer satırları okunur; yorum ve boş satırlar atlanır, tırnaklar soyulur, boş değerler (KEY=) varsayılan
# demektir, ortamda zaten tanımlı olanlar ezilmez.
env_yukle() {
  [ -f .env ] || return 0
  local satir anahtar deger
  while IFS= read -r satir || [ -n "$satir" ]; do
    satir="${satir%$'\r'}"
    satir="${satir#"${satir%%[![:space:]]*}"}"           # baştaki boşluklar
    case "$satir" in ''|'#'*) continue ;; esac
    case "$satir" in *=*) ;; *) continue ;; esac
    anahtar="${satir%%=*}"
    anahtar="${anahtar#export }"
    anahtar="$(printf '%s' "$anahtar" | tr -d '[:space:]')"
    case "$anahtar" in ''|[0-9]*|*[!A-Za-z0-9_]*) continue ;; esac
    deger="${satir#*=}"
    deger="${deger#"${deger%%[![:space:]]*}"}"          # baştaki boşluklar
    case "$deger" in
      \"*\") deger="${deger#\"}"; deger="${deger%\"}" ;;
      \'*\') deger="${deger#\'}"; deger="${deger%\'}" ;;
      *) deger="${deger%%[[:space:]]\#*}"                  # tırnaksız değerde satır sonu yorumu
         deger="${deger%"${deger##*[![:space:]]}"}" ;;    # sondaki boşluklar
    esac
    [ -n "$deger" ] || continue                            # boş değer = varsayılanı kullan (Compose ile aynı)
    if ! printenv "$anahtar" >/dev/null 2>&1; then
      export "$anahtar=$deger"
    fi
  done < .env
}
env_yukle

# ---------- ön kontroller ----------
command -v ffmpeg >/dev/null 2>&1 || hata "ffmpeg bulunamadı. SesKlon ses dönüştürme (mikrofon kayıtları dahil), MP3,
  tempo ve mastering için ffmpeg kullanır. Kurulum: $(kur_ipucu ffmpeg)
  Kurduktan sonra yeni bir terminal açıp ./run.sh komutunu tekrar çalıştırın."

python_bul() {
  local aday surum
  for aday in python3.11 python3.12 python3.10 python3.13 python3 python; do
    command -v "$aday" >/dev/null 2>&1 || continue
    surum="$("$aday" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" || continue
    case "$surum" in
      3.1[0-9]) printf '%s %s\n' "$aday" "$surum"; return 0 ;;
    esac
  done
  return 1
}

node_kontrol() {
  command -v node >/dev/null 2>&1 || hata "Node.js bulunamadı (arayüzü derlemek için gerekli). Kurulum: $(kur_ipucu node)"
  command -v npm >/dev/null 2>&1 || hata "npm bulunamadı (Node.js ile birlikte gelir). Kurulum: $(kur_ipucu node)"
  local ana
  ana="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
  [ "$ana" -ge 18 ] 2>/dev/null || hata "Node.js $(node -v 2>/dev/null || echo '?') çok eski; en az 18 gerekli (önerilen 20). Kurulum: $(kur_ipucu node)"
}

arayuz_bagimliliklari() {
  if [ ! -d frontend/node_modules ] || [ frontend/package-lock.json -nt frontend/node_modules/.package-lock.json ]; then
    bilgi "Arayüz bağımlılıkları kuruluyor (npm)…"
    if [ -f frontend/package-lock.json ]; then
      (cd frontend && npm ci --no-audit --no-fund) || hata "Arayüz bağımlılıkları kurulamadı (npm ci)."
    else
      (cd frontend && npm install --no-audit --no-fund) || hata "Arayüz bağımlılıkları kurulamadı (npm install)."
    fi
  fi
}

arayuz_guncel_mi() {
  [ -f frontend/dist/index.html ] || return 1
  [ -z "$(find frontend -path frontend/node_modules -prune -o -path frontend/dist -prune -o \
          -type f -newer frontend/dist/index.html -print 2>/dev/null | head -n 1)" ]
}

# ---------- Python sanal ortamı ----------
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
if [ ! -x "$PY" ]; then
  if [ -d "$VENV" ]; then
    uyari "Yarım kalmış .venv klasörü bulundu; yeniden oluşturuluyor."
    rm -rf "$VENV"
  fi
  PYBILGI="$(python_bul)" || hata "Python 3.10 veya üstü bulunamadı (önerilen 3.11). Kurulum: $(kur_ipucu python)"
  PYEXE="${PYBILGI% *}"; PYSURUM="${PYBILGI#* }"
  [ "$PYSURUM" = "3.11" ] || uyari "Python $PYSURUM kullanılacak; en çok test edilen sürüm 3.11."
  bilgi "Sanal ortam oluşturuluyor (.venv, Python $PYSURUM)…"
  if ! "$PYEXE" -m venv "$VENV"; then
    rm -rf "$VENV"
    hata "Sanal ortam oluşturulamadı. Ubuntu/Debian'da venv ayrı pakettir: sudo apt install python${PYSURUM}-venv"
  fi
fi

# Paketler yalnızca ilk kurulumda ya da requirements.txt / TORCH_INDEX değişince kurulur (sonraki açılışlar hızlı,
# internetsiz de çalışır).
TORCH_VERSION="${TORCH_VERSION:-2.6.0}"
DAMGA="$VENV/.sesklon-kurulum"
istenen="$(cksum < backend/requirements.txt | awk '{print $1 "-" $2}') ${TORCH_INDEX:-}"
mevcut="$(cat "$DAMGA" 2>/dev/null || true)"
if [ "$istenen" != "$mevcut" ]; then
  command -v git >/dev/null 2>&1 || hata "git bulunamadı (Chatterbox V3 GitHub kaynağından kurulur). Kurulum: $(kur_ipucu git)"
  if [ -z "$mevcut" ]; then
    bilgi "${KALIN}İlk kurulum:${SIFIRLA} Python paketleri iniyor (PyTorch dahil birkaç GB; bağlantıya göre 5–15 dk sürebilir)."
  else
    bilgi "requirements.txt ya da TORCH_INDEX değişmiş; Python paketleri güncelleniyor…"
  fi
  "$PY" -m pip install -q --upgrade pip || hata "pip güncellenemedi. İnternet bağlantınızı kontrol edin."
  if [ -n "${TORCH_INDEX:-}" ]; then
    bilgi "PyTorch $TORCH_VERSION şu kaynaktan kuruluyor: $TORCH_INDEX"
    "$PY" -m pip install "torch==$TORCH_VERSION" "torchaudio==$TORCH_VERSION" --index-url "$TORCH_INDEX" \
      || hata "PyTorch kurulamadı (TORCH_INDEX=$TORCH_INDEX, TORCH_VERSION=$TORCH_VERSION)."
  fi
  "$PY" -m pip install -r backend/requirements.txt \
    || hata "Python paketleri kurulamadı. Yukarıdaki pip çıktısını ve internet bağlantınızı kontrol edin."
  printf '%s' "$istenen" > "$DAMGA"
  bilgi "${YESIL}Python paketleri hazır.${SIFIRLA}"
fi

# ---------- model notu ----------
HF_HUB="${HF_HUB_CACHE:-${HF_HOME:-${XDG_CACHE_HOME:-$HOME/.cache}/huggingface}/hub}"
if ! ls -d "$HF_HUB"/models--ResembleAI--* >/dev/null 2>&1; then
  bilgi "${KALIN}Not:${SIFIRLA} Model (~2 GB) ilk açılışta Hugging Face'ten inecek ve $HF_HUB altında saklanacak."
  bilgi "     İnerken arayüz 'model yükleniyor' gösterir; sonraki açılışlarda yeniden inmez."
fi

# ---------- geliştirme modu ----------
if [ "$DEV" = 1 ]; then
  node_kontrol
  arayuz_bagimliliklari
  API_PID=""; WEB_PID=""
  # shellcheck disable=SC2329  # trap ile çağrılır
  temizle() {
    trap - INT TERM EXIT
    if [ -n "$WEB_PID" ]; then kill "$WEB_PID" 2>/dev/null || true; fi
    if [ -n "$API_PID" ]; then kill "$API_PID" 2>/dev/null || true; fi
    wait 2>/dev/null || true
  }
  trap 'temizle; exit 130' INT TERM
  trap temizle EXIT
  (cd backend && exec "$PY" -m uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000) &
  API_PID=$!
  (cd frontend && exec node node_modules/vite/bin/vite.js) &
  WEB_PID=$!
  bilgi ""
  bilgi "${YESIL}Geliştirme modu:${SIFIRLA} arayüz http://localhost:5173 (canlı yenileme) • API http://localhost:8000/api/docs"
  bilgi "Durdurmak için Ctrl+C."
  while kill -0 "$API_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do sleep 1; done
  uyari "API ya da arayüz süreci kapandı; diğeri de durduruluyor."
  exit 1
fi

# ---------- normal mod ----------
if ! arayuz_guncel_mi; then
  if [ -f frontend/dist/index.html ] && ! command -v node >/dev/null 2>&1; then
    uyari "Arayüz kaynakları derlenmiş sürümden yeni ama Node.js bulunamadı; mevcut (eski) arayüzle devam ediliyor."
  else
    node_kontrol
    arayuz_bagimliliklari
    bilgi "Arayüz derleniyor…"
    (cd frontend && npm run build) || hata "Arayüz derlenemedi (npm run build). Yukarıdaki çıktıya bakın."
  fi
fi

export FRONTEND_DIST="$ROOT/frontend/dist"
if [ -z "${API_KEY:-}" ]; then
  bilgi "Not: API_KEY boş; aynı ağdaki herkes bu bilgisayarın 8000 numaralı portuna erişebilir. İnternete açacaksanız"
  bilgi "     .env dosyasında API_KEY tanımlayın."
fi
bilgi "${YESIL}SesKlon başlıyor →${SIFIRLA} http://localhost:8000   (durdurmak için Ctrl+C)"
cd backend
exec "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
