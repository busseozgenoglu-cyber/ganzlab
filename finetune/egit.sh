#!/usr/bin/env bash
# SesKlon — Chatterbox T3 ince ayarı (LoRA): kurulum → eğitim → birleştirme.
#
# gokhaneraslan/chatterbox-finetuning deposunu finetune/chatterbox-finetuning/ altına klonlar, sanal ortamı kurar,
# depodaki src/config.py'yi SesKlon ayarlarıyla yamalar, train.py ile eğitir, LoRA ise merge_lora.py ile tek bir
# .safetensors dosyası üretir ve SesKlon'un o dosyayla nasıl başlatılacağını yazdırır.
# Ayrıntılar ve araştırma bulguları: finetune/README.md · sözleşme: docs/SOZLESME3.md §6.
#
# Kullanım (proje kökünden):
#   bash finetune/egit.sh                                   # hepsi: kur → egit → birlestir
#   ADIM=kur bash finetune/egit.sh                          # depo + sanal ortam + paketler + temel model indirme
#   ADIM=egit EPOCH=15 BATCH=2 GRAD_ACCUM=8 bash finetune/egit.sh
#   ADIM=birlestir bash finetune/egit.sh                    # LoRA bağdaştırıcısını T3'e göm, sonucu yazdır
#   ADIM=yamala bash finetune/egit.sh                       # yalnızca yamaları uygula ve etkin ayarları göster
#
# Ortam değişkenleri (parantez içinde varsayılan):
#   VERI           hazirla.py çıktısı: metadata.csv + wavs/ (finetune/MyTTSDataset)
#   EPOCH          eğitim turu (10)
#   BATCH          adım başına örnek (4) — bellek yetmezse yarıya indirin
#   GRAD_ACCUM     gradyan biriktirme (4) — etkin batch = BATCH × GRAD_ACCUM
#   LORA_R         LoRA rankı (64)
#   LORA_ALPHA     LoRA alfa (128)
#   OGRENME_HIZI   öğrenme hızı (boş = deponunki: LoRA 1e-4, tam ince ayar 1e-5)
#   CIHAZ          otomatik | cuda | mps | cpu (otomatik)
#   TAM_INCE_AYAR  1 = LoRA yerine tüm T3 ağırlıkları (çok bellek; > 10 saat veri) (0)
#   MTL_TABAN      1 = Multilingual T3 tabanı + MTLTokenizer (SesKlon'la uyumlu, deneysel yama) ·
#                  0 = deponun özgün yolu (İngilizce T3 tabanı; SesKlon'da tokenizer uyuşmazlığı) (1)
#   MTL_T3_SURUM   Multilingual T3 sürümü: v3 | v2 — SesKlon'un T3_MODEL'iyle aynı olmalı (v3)
#   DIL            dil kimliği, MTL tokenizer'ın başa eklediği [tr] etiketi (tr)
#   ON_ISLEME      otomatik | 1 | 0 — ses/metin belirteçlerinin yeniden çıkarılması (otomatik)
#   ISCI           veri yükleyici işçi sayısı (boş = deponunki)
#   DEPO_DIZIN     eğitim deposunun klasörü (finetune/chatterbox-finetuning)
#   DEPO_URL       (https://github.com/gokhaneraslan/chatterbox-finetuning.git) · DEPO_DALI (main) ·
#   DEPO_SURUM     belirli bir commit'e sabitlemek için (boş)
#   PYTHON         sanal ortamı kuracak yorumlayıcı (python3)
#   ADIM           kur | egit | birlestir | hepsi | yamala (hepsi)
set -euo pipefail

BETIK_DIZIN="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJE_DIZIN="$(dirname "$BETIK_DIZIN")"

VERI="${VERI:-$BETIK_DIZIN/MyTTSDataset}"
EPOCH="${EPOCH:-10}"
BATCH="${BATCH:-4}"
GRAD_ACCUM="${GRAD_ACCUM:-4}"
LORA_R="${LORA_R:-64}"
LORA_ALPHA="${LORA_ALPHA:-128}"
OGRENME_HIZI="${OGRENME_HIZI:-}"
CIHAZ="${CIHAZ:-otomatik}"
TAM_INCE_AYAR="${TAM_INCE_AYAR:-0}"
MTL_TABAN="${MTL_TABAN:-1}"
MTL_T3_SURUM="${MTL_T3_SURUM:-v3}"
DIL="${DIL:-tr}"
ON_ISLEME="${ON_ISLEME:-otomatik}"
ISCI="${ISCI:-}"
DEPO_DIZIN="${DEPO_DIZIN:-$BETIK_DIZIN/chatterbox-finetuning}"
DEPO_URL="${DEPO_URL:-https://github.com/gokhaneraslan/chatterbox-finetuning.git}"
DEPO_DALI="${DEPO_DALI:-main}"
DEPO_SURUM="${DEPO_SURUM:-}"
PYTHON="${PYTHON:-python3}"
ADIM="${ADIM:-hepsi}"

# ---------- günlük yardımcıları ----------

bilgi() { printf '[egit %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
uyari() { printf '[egit %s] UYARI: %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
hata() { printf '[egit %s] HATA: %s\n' "$(date +%H:%M:%S)" "$*" >&2; exit 1; }
baslik() { printf '\n==== %s ====\n' "$*"; }

sayi_mi() {      # sayi_mi AD DEĞER — pozitif tam sayı değilse Türkçe hatayla çık
    case "$2" in
        ''|*[!0-9]*) hata "$1 pozitif bir tam sayı olmalı (verilen: '$2')." ;;
    esac
    [ "$2" -gt 0 ] || hata "$1 sıfırdan büyük olmalı (verilen: '$2')."
}

ikili_mi() {     # ikili_mi AD DEĞER — 0 ya da 1
    case "$2" in
        0|1) ;;
        *) hata "$1 0 ya da 1 olmalı (verilen: '$2')." ;;
    esac
}

# ---------- ayar denetimi ----------

sayi_mi EPOCH "$EPOCH"
sayi_mi BATCH "$BATCH"
sayi_mi GRAD_ACCUM "$GRAD_ACCUM"
sayi_mi LORA_R "$LORA_R"
sayi_mi LORA_ALPHA "$LORA_ALPHA"
ikili_mi TAM_INCE_AYAR "$TAM_INCE_AYAR"
ikili_mi MTL_TABAN "$MTL_TABAN"
[ -z "$ISCI" ] || case "$ISCI" in *[!0-9]*) hata "ISCI tam sayı olmalı (verilen: '$ISCI')." ;; esac
case "$CIHAZ" in otomatik|cuda|mps|cpu) ;; *) hata "CIHAZ otomatik | cuda | mps | cpu olmalı (verilen: '$CIHAZ')." ;; esac
case "$MTL_T3_SURUM" in v2|v3) ;; *) hata "MTL_T3_SURUM v2 ya da v3 olmalı (verilen: '$MTL_T3_SURUM')." ;; esac
case "$ON_ISLEME" in otomatik|0|1) ;; *) hata "ON_ISLEME otomatik | 0 | 1 olmalı (verilen: '$ON_ISLEME')." ;; esac
case "$ADIM" in kur|egit|birlestir|hepsi|yamala) ;; *) hata "ADIM kur | egit | birlestir | hepsi | yamala olmalı (verilen: '$ADIM')." ;; esac
if [ -n "$OGRENME_HIZI" ]; then
    "$PYTHON" -c 'import sys; float(sys.argv[1])' "$OGRENME_HIZI" 2>/dev/null \
        || hata "OGRENME_HIZI bir sayı olmalı (örn. 1e-4; verilen: '$OGRENME_HIZI')."
fi

# Göreli yolları mutlak yap (eğitim betikleri depo klasöründen çalışır)
case "$VERI" in /*) ;; *) VERI="$(pwd)/$VERI" ;; esac
case "$DEPO_DIZIN" in /*) ;; *) DEPO_DIZIN="$(pwd)/$DEPO_DIZIN" ;; esac
VERI="${VERI%/}"
DEPO_DIZIN="${DEPO_DIZIN%/}"

VENV="$DEPO_DIZIN/.venv"
PY="$VENV/bin/python"
MODEL_DIZIN="$DEPO_DIZIN/pretrained_models"
CIKTI_DIZIN="$DEPO_DIZIN/chatterbox_output"
GUNLUK_DIZIN="$DEPO_DIZIN/gunlukler"
ON_ISLEME_DIZIN="$VERI/preprocess"
ON_ISLEME_ISARET="$ON_ISLEME_DIZIN/.sesklon_taban"     # "TABAN_KIMLIK metadata.csv-sha256": ön işleme neyle yapıldı
TABAN_KAYDI="$CIKTI_DIZIN/sesklon_taban.txt"           # eğitimin tabanı; birlestir bununla karşılaştırır
if [ "$MTL_TABAN" = "1" ]; then TABAN_KIMLIK="mtl-$MTL_T3_SURUM-$DIL"; else TABAN_KIMLIK="en-t3_cfg"; fi
ETIKETLI=0

# Yamalama yalnızca standart kütüphaneyle çalışır; sanal ortam yoksa sistem Python'u yeter
yama_python() { if [ -x "$PY" ]; then printf '%s' "$PY"; else printf '%s' "$PYTHON"; fi; }

# ---------- cihaz ----------

cihaz_bul() {
    local bulunan="$CIHAZ"
    if [ "$bulunan" = "otomatik" ]; then
        bulunan="$("$(yama_python)" -c 'import torch
if torch.cuda.is_available():
    print("cuda")
elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
    print("mps")
else:
    print("cpu")' 2>/dev/null || echo cpu)"
    fi
    case "$bulunan" in
        cuda)
            bilgi "Cihaz: cuda (NVIDIA GPU)." ;;
        mps)
            export PYTORCH_ENABLE_MPS_FALLBACK=1
            uyari "Cihaz: mps (Apple Silicon). Eğitim burada ÖNERİLMEZ: depo cuda ya da cpu için yazılmış, bf16 ve bazı" \
                  "işlemler mps'te desteklenmeyebilir (PYTORCH_ENABLE_MPS_FALLBACK=1 ayarlandı). Bulut GPU kullanın." ;;
        cpu)
            [ "$CIHAZ" = "cpu" ] && export CUDA_VISIBLE_DEVICES=""
            uyari "Cihaz: cpu. Eğitim çok yavaş olur (3 saat veriyle günler sürebilir); 24 GB'lık bir GPU önerilir." ;;
    esac
    BULUNAN_CIHAZ="$bulunan"
}

# ---------- yamalar ----------

yamala() {   # yamala ON_ISLEME(0|1)
    local on_isleme="$1"
    [ -f "$DEPO_DIZIN/src/config.py" ] || hata "Eğitim deposu bulunamadı: $DEPO_DIZIN — önce: ADIM=kur bash finetune/egit.sh"
    if [ -d "$DEPO_DIZIN/.git" ] && command -v git >/dev/null 2>&1; then
        # Önceki yamaları geri al: her çalıştırma temiz dosyalara aynı yamaları uygular (ayar değişince eski yama kalmaz)
        git -C "$DEPO_DIZIN" checkout -- . 2>/dev/null \
            || uyari "Depo dosyaları geri alınamadı; yamalar mevcut dosyalara uygulanacak."
    fi
    bilgi "src/config.py ve eğitim betikleri yamalanıyor (MTL_TABAN=$MTL_TABAN, LoRA=$([ "$TAM_INCE_AYAR" = 1 ] && echo hayır || echo evet))…"
    SK_DEPO="$DEPO_DIZIN" SK_VERI="$VERI" SK_CIKTI="$CIKTI_DIZIN" SK_MODEL="$MODEL_DIZIN" SK_ON_ISLEME="$on_isleme" \
    SK_TAM="$TAM_INCE_AYAR" SK_MTL="$MTL_TABAN" SK_SURUM="$MTL_T3_SURUM" SK_DIL="$DIL" SK_EPOCH="$EPOCH" \
    SK_BATCH="$BATCH" SK_ACCUM="$GRAD_ACCUM" SK_R="$LORA_R" SK_ALPHA="$LORA_ALPHA" SK_LR="$OGRENME_HIZI" \
    SK_ISCI="$ISCI" "$(yama_python)" - <<'PYEOF' || hata "Yamalama başarısız (ayrıntı yukarıda)."
"""egit.sh yamacısı: src/config.py anahtarlarını ve (MTL_TABAN=1) eğitim betiklerini SesKlon için düzenler."""
import os
import re
import sys
from pathlib import Path

depo = Path(os.environ["SK_DEPO"])
veri = Path(os.environ["SK_VERI"])
mtl = os.environ["SK_MTL"] == "1"
surum = os.environ["SK_SURUM"]
dil = os.environ["SK_DIL"]
lora = os.environ["SK_TAM"] != "1"
ISARET = "# SesKlon egit.sh yaması"
eksik_zorunlu = []


def uyari(m):
    print(f"[yama] UYARI: {m}", file=sys.stderr)


def bilgi(m):
    print(f"[yama] {m}")


# --- 1) src/config.py ---
degerler = {
    "is_turbo": False,
    "is_lora": lora,
    "ljspeech": True,
    "json_format": False,
    "preprocess": os.environ["SK_ON_ISLEME"] == "1",
    "is_inference": False,
    "model_dir": os.environ["SK_MODEL"],
    "csv_path": str(veri / "metadata.csv"),
    "wav_dir": str(veri / "wavs"),
    "preprocessed_dir": str(veri / "preprocess"),
    "output_dir": os.environ["SK_CIKTI"],
    "new_vocab_size": 2454,
    "lora_r": int(os.environ["SK_R"]),
    "lora_alpha": int(os.environ["SK_ALPHA"]),
    "num_epochs": int(os.environ["SK_EPOCH"]),
    "batch_size": int(os.environ["SK_BATCH"]),
    "grad_accum": int(os.environ["SK_ACCUM"]),
}
if os.environ.get("SK_LR"):
    degerler["learning_rate"] = float(os.environ["SK_LR"])
KALICI = re.compile(r"\bdataloader_persistent_workers=True,")
if os.environ.get("SK_ISCI"):
    isci = int(os.environ["SK_ISCI"])
    egitim_yol = depo / "train.py"
    if isci == 0 and not (egitim_yol.is_file() and KALICI.search(egitim_yol.read_text(encoding="utf-8"))):
        # persistent_workers=True işçisiz (0) yükleyiciyle hata verir; yamalanamıyorsa en az 1 işçi
        uyari("ISCI=0 ama train.py'deki 'dataloader_persistent_workers=True,' yamalanamıyor — ISCI=1 kullanılıyor.")
        isci = 1
    degerler["dataloader_num_workers"] = isci

cfg_yol = depo / "src" / "config.py"
metin = cfg_yol.read_text(encoding="utf-8")
for anahtar, deger in degerler.items():
    desen = re.compile(rf"^(?P<girinti>[ \t]+){re.escape(anahtar)}(?P<tip>[ \t]*:[^=\n]*)?[ \t]*=(?!=)[^\n]*$", re.M)
    m = desen.search(metin)
    if not m:
        uyari(f"src/config.py içinde '{anahtar}' anahtarı bulunamadı — atlandı (depo değişmiş olabilir).")
        continue
    tip = (m.group("tip") or "").rstrip()
    yeni = f"{m.group('girinti')}{anahtar}{tip} = {deger!r}  {ISARET}"
    metin = metin[: m.start()] + yeni + metin[m.end():]
try:
    compile(metin, str(cfg_yol), "exec")
except SyntaxError as e:
    print(f"[yama] HATA: yamalanan src/config.py sözdizimi bozuk: {e}", file=sys.stderr)
    sys.exit(2)
cfg_yol.write_text(metin, encoding="utf-8")

# Etkin değerleri göster (config.py yalnızca dataclasses/typing kullanır; torch gerekmez)
ad_alani = {"__name__": "sesklon_config_denetimi"}
try:
    exec(compile(metin, str(cfg_yol), "exec"), ad_alani)
    c = ad_alani["TrainConfig"]()
    ozet = ", ".join(f"{k}={getattr(c, k, '?')!r}" for k in (
        "is_turbo", "is_lora", "new_vocab_size", "lora_r", "lora_alpha", "num_epochs", "batch_size", "grad_accum",
        "learning_rate", "preprocess"))
    bilgi(f"etkin ayarlar: {ozet}")
    bilgi(f"veri: {getattr(c, 'csv_path', '?')} · çıktı: {getattr(c, 'output_dir', '?')}")
except Exception as e:  # noqa: BLE001 - yalnızca bilgi amaçlı
    uyari(f"etkin ayarlar okunamadı: {e}")


# --- 2) eğitim betikleri ---
def yamali_yaz(yol, yeni_metin):
    if not yeni_metin.startswith(ISARET):
        yeni_metin = f"{ISARET} (MTL_TABAN={int(mtl)})\n" + yeni_metin
    yol.write_text(yeni_metin, encoding="utf-8")


# Yalnızca eğitim yolundaki betikler: inference.py / inference_callback.py dokunulmaz (is_inference=False; çıkarımı
# SesKlon yapar). Multilingual generate() language_id ister; o betikler yamalanırsa bozulurdu.
betikler = [depo / "train.py", depo / "merge_lora.py"] + sorted((depo / "src").glob("preprocess_*.py"))
ICE_AKTAR = re.compile(r"^from src\.chatterbox_\.tts import (?P<adlar>[^\n(]+)$", re.M)
BELIRTEC = re.compile(r"\.text_to_tokens\((?P<arg>[A-Za-z_][A-Za-z0-9_]*)\)")
DENETIM = re.compile(r"(?<!def )\bcheck_pretrained_models\([^()]*\)")
BF16 = re.compile(r"\bbf16=True,")

for yol in betikler:
    if not yol.is_file():
        continue
    eski = yol.read_text(encoding="utf-8")
    if eski.startswith(ISARET):
        bilgi(f"{yol.relative_to(depo)} zaten yamalı (git yok) — atlandı.")
        continue
    yeni = eski
    sayac = {"ice_aktar": 0, "belirtec": 0, "denetim": 0, "bf16": 0, "kalici_isci": 0}

    # bf16 yalnızca Ampere+ GPU'da var; T4/V100/cpu'da Trainer hata verir → donanım destekliyorsa aç
    if yol.name == "train.py":
        yeni, sayac["bf16"] = BF16.subn(
            "bf16=bool(torch.cuda.is_available() and torch.cuda.is_bf16_supported()),", yeni)
        if not sayac["bf16"]:
            uyari("train.py'de 'bf16=True,' bulunamadı — bf16 ayarı olduğu gibi bırakıldı.")
        # persistent_workers yalnız işçi varken geçerli (ISCI=0 → torch "persistent_workers requires num_workers > 0")
        yeni, sayac["kalici_isci"] = KALICI.subn(
            "dataloader_persistent_workers=bool(cfg.dataloader_num_workers > 0),", yeni)

    if mtl:
        def ice_aktar(m):
            adlar = [a.strip() for a in m.group("adlar").split(",") if a.strip()]
            if "ChatterboxTTS" not in adlar:
                return m.group(0)
            sayac["ice_aktar"] += 1
            # punc_norm da Multilingual sürümünden gelir (çıkarımda ChatterboxMultilingualTTS.generate onu kullanır)
            mtl_adlar = ["ChatterboxMultilingualTTS as ChatterboxTTS"] + [a for a in adlar if a == "punc_norm"]
            kalan = [a for a in adlar if a not in ("ChatterboxTTS", "punc_norm")]
            satirlar = [f"from src.chatterbox_.tts import {', '.join(kalan)}"] if kalan else []
            satirlar.append(f"from src.chatterbox_.mtl_tts import {', '.join(mtl_adlar)}  # SesKlon: Multilingual taban")
            return "\n".join(satirlar)

        yeni = ICE_AKTAR.sub(ice_aktar, yeni)
        yeni, sayac["belirtec"] = BELIRTEC.subn(rf'.text_to_tokens(\g<arg>, language_id="{dil}")', yeni)
        if yol.name == "train.py":      # dosya denetimi İngilizce dosya adlarını arar (t3_cfg.safetensors …)
            yeni, sayac["denetim"] = DENETIM.subn("True", yeni)

    try:
        compile(yeni, str(yol), "exec")
    except SyntaxError as e:
        print(f"[yama] HATA: {yol.relative_to(depo)} yamadan sonra sözdizimi bozuk: {e}", file=sys.stderr)
        sys.exit(2)
    if yeni != eski:
        yamali_yaz(yol, yeni)
        degisen = ", ".join(f"{k}×{v}" for k, v in sayac.items() if v)
        bilgi(f"{yol.relative_to(depo)} yamalandı ({degisen}).")
    if mtl and yol.name in ("train.py", "merge_lora.py") and not sayac["ice_aktar"]:
        eksik_zorunlu.append(f"{yol.name}: ChatterboxTTS içe aktarımı bulunamadı")
    if mtl and yol.name == "preprocess_ljspeech.py" and not (sayac["ice_aktar"] and sayac["belirtec"]):
        eksik_zorunlu.append("src/preprocess_ljspeech.py: ChatterboxTTS içe aktarımı ya da text_to_tokens çağrısı "
                             "bulunamadı")

# --- 3) vendored Multilingual yükleyici: T3 sürümü ve CPU'ya güvenli yükleme ---
if mtl:
    mtl_yol = depo / "src" / "chatterbox_" / "mtl_tts.py"
    if not mtl_yol.is_file():
        eksik_zorunlu.append("src/chatterbox_/mtl_tts.py yok (depoda Multilingual sınıfı bulunamadı)")
    elif not mtl_yol.read_text(encoding="utf-8").startswith(ISARET):
        eski = mtl_yol.read_text(encoding="utf-8")
        yeni, n_surum = eski, 0
        if surum != "v2":
            yeni, n_surum = re.subn(r"t3_mtl23ls_v2\.safetensors", f"t3_mtl23ls_{surum}.safetensors", yeni)
            if not n_surum:
                uyari(f"mtl_tts.py'de 't3_mtl23ls_v2.safetensors' bulunamadı — T3 sürümü {surum} uygulanamadı.")
        yeni, n_cpu = re.subn(r'torch\.load\((ckpt_dir / "(?:ve|s3gen)\.pt"), weights_only=True\)',
                              r'torch.load(\1, weights_only=True, map_location="cpu")', yeni)
        if yeni != eski:
            compile(yeni, str(mtl_yol), "exec")
            yamali_yaz(mtl_yol, yeni)
            bilgi(f"src/chatterbox_/mtl_tts.py yamalandı (T3 sürümü×{n_surum}, cpu yükleme×{n_cpu}).")

if eksik_zorunlu:
    print("[yama] HATA: Multilingual taban yaması uygulanamadı:", file=sys.stderr)
    for e in eksik_zorunlu:
        print(f"[yama]   - {e}", file=sys.stderr)
    print("[yama] Depo değişmiş olabilir: finetune/README.md 'Multilingual taban' bölümündeki elle yama talimatını "
          "izleyin ya da MTL_TABAN=0 ile deponun özgün yolunu kullanın (SesKlon'da tokenizer uyuşmazlığı uyarısıyla).",
          file=sys.stderr)
    sys.exit(3)
bilgi("yamalar tamam.")
PYEOF
    if [ "$MTL_TABAN" = "0" ]; then
        uyari "MTL_TABAN=0: depo İngilizce Chatterbox T3'ünden (t3_cfg, 704 belirteç) başlar ve metni [tr] etiketi," \
              "küçük harf ve NFKD olmadan belirteçler. SesKlon (ChatterboxMultilingualTTS) çıkarımda [tr] + küçük harf +" \
              "NFKD uygular: dosya yüklenir ama sonuç güvenilmez. Ayrıntı: finetune/README.md → Multilingual taban."
    fi
}

# ---------- ADIM: kur ----------

adim_kur() {
    baslik "1/3 Kurulum: depo, sanal ortam, paketler, temel model"
    command -v git >/dev/null 2>&1 || hata "git bulunamadı. Kurun: macOS 'xcode-select --install', Ubuntu 'sudo apt install git'."
    command -v "$PYTHON" >/dev/null 2>&1 || hata "$PYTHON bulunamadı (PYTHON değişkeniyle başka bir yorumlayıcı verin)."
    command -v ffmpeg >/dev/null 2>&1 || uyari "ffmpeg bulunamadı; deponun ses işleme adımları için gerekli olabilir."

    if [ -d "$DEPO_DIZIN/.git" ]; then
        bilgi "Eğitim deposu güncelleniyor: $DEPO_DIZIN"
        git -C "$DEPO_DIZIN" checkout -- . 2>/dev/null || true      # önceki yamaları geri al; aşağıda yeniden uygulanır
        if [ -n "$DEPO_SURUM" ]; then
            git -C "$DEPO_DIZIN" fetch --quiet origin || uyari "git fetch başarısız; yereldeki sürümle devam."
        else
            git -C "$DEPO_DIZIN" pull --ff-only --quiet || uyari "Depo güncellenemedi; yereldeki sürümle devam."
        fi
    else
        [ -e "$DEPO_DIZIN" ] && hata "$DEPO_DIZIN var ama bir git deposu değil; silin ya da DEPO_DIZIN ile başka bir yer verin."
        bilgi "Eğitim deposu klonlanıyor: $DEPO_URL → $DEPO_DIZIN"
        mkdir -p "$(dirname "$DEPO_DIZIN")"
        git clone --quiet --branch "$DEPO_DALI" "$DEPO_URL" "$DEPO_DIZIN"
    fi
    if [ -n "$DEPO_SURUM" ]; then
        bilgi "Depo şu sürüme sabitleniyor: $DEPO_SURUM"
        git -C "$DEPO_DIZIN" checkout --quiet "$DEPO_SURUM"
    fi
    bilgi "Depo sürümü: $(git -C "$DEPO_DIZIN" rev-parse --short HEAD 2>/dev/null || echo bilinmiyor)"

    if [ ! -x "$PY" ]; then
        bilgi "Sanal ortam oluşturuluyor: $VENV"
        "$PYTHON" -m venv "$VENV"
    fi
    local ozet isaret="$VENV/.sesklon_paketler"
    ozet="$("$PY" -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' \
        "$DEPO_DIZIN/requirements.txt")"
    if [ ! -f "$isaret" ] || [ "$(cat "$isaret")" != "$ozet" ]; then
        bilgi "Python paketleri kuruluyor (torch dahil birkaç GB; 5–20 dk)…"
        "$PY" -m pip install --quiet --upgrade pip
        "$PY" -m pip install -r "$DEPO_DIZIN/requirements.txt"
        printf '%s' "$ozet" > "$isaret"
    else
        bilgi "Python paketleri güncel (requirements.txt değişmemiş)."
    fi

    yamala 0
    if [ "$MTL_TABAN" = "1" ]; then
        bilgi "Multilingual temel model indiriliyor (ResembleAI/chatterbox, T3 $MTL_T3_SURUM) → $MODEL_DIZIN"
        SK_MODEL="$MODEL_DIZIN" SK_SURUM="$MTL_T3_SURUM" "$PY" - <<'PYEOF' || hata "Model indirilemedi (internet / Hugging Face erişimi?)."
import os
from huggingface_hub import snapshot_download

surum = os.environ["SK_SURUM"]
desenler = ["ve.pt", f"t3_mtl23ls_{surum}.safetensors", "s3gen.pt", "grapheme_mtl_merged_expanded_v1.json",
            "conds.pt", "Cangjie5_TC.json"]
yol = snapshot_download(repo_id="ResembleAI/chatterbox", repo_type="model", allow_patterns=desenler,
                        local_dir=os.environ["SK_MODEL"], token=os.getenv("HF_TOKEN"))
eksik = [d for d in desenler[:5] if not os.path.exists(os.path.join(yol, d))]
if eksik:
    raise SystemExit(f"[indir] HATA: şu dosyalar inmedi: {', '.join(eksik)}")
print(f"[indir] tamam: {yol}")
PYEOF
    else
        bilgi "Temel model deponun setup.py'siyle indiriliyor (İngilizce ChatterboxTTS, standart kip)…"
        (cd "$DEPO_DIZIN" && "$PY" setup.py)
    fi
    bilgi "Kurulum tamam."
}

# ---------- ADIM: egit ----------

veri_denetle() {
    [ -f "$VERI/metadata.csv" ] && [ -d "$VERI/wavs" ] || hata "Eğitim verisi bulunamadı: $VERI (metadata.csv + wavs/ gerekli). Önce:" \
        "python finetune/hazirla.py --kayitlar kayitlar/ --manifest senaryo/manifest.csv --cikti finetune/MyTTSDataset --etiket --dogrulama 0.05"
    local satir wav
    satir="$(grep -c . "$VERI/metadata.csv" || true)"
    wav="$(find "$VERI/wavs" -maxdepth 1 -name '*.wav' | wc -l | tr -d ' ')"
    [ "${satir:-0}" -gt 0 ] || hata "$VERI/metadata.csv boş."
    bilgi "Veri: $VERI — $satir satır, $wav WAV."
    [ "$wav" -ge "$satir" ] || uyari "WAV sayısı ($wav) metadata satırından ($satir) az; eksik dosyalar ön işlemede atlanır."
    # Boş metin: depo metadata.csv'yi pandas ile okur, boş alan NaN → "nan" metniyle eğitilirdi
    local bos
    bos="$(awk -F'|' '/^[[:space:]]*$/ { next }
        { r = $2; n = $3; gsub(/^[ \t\r]+|[ \t\r]+$/, "", r); gsub(/^[ \t\r]+|[ \t\r]+$/, "", n)
          if (NF < 3 || r == "" || n == "") { c++; if (c <= 3) ids = ids (ids ? ", " : "") $1 } }
        END { if (c) print c " satır (ilk: " ids ")" }' "$VERI/metadata.csv")"
    [ -z "$bos" ] || hata "metadata.csv'de metni boş satırlar var: $bos. Eğitim deposu bunları 'nan' metniyle" \
        "eğitirdi. Önce ASR ile doldurun (Whisper; finetune/README.md → Transkriptsiz bölme) ya da bu satırları çıkarın."
    # Yalnız rakamdan oluşan adlar: pandas '0001'i sayı okur → '1.wav' aranır, kayıt bulunamaz
    local sayisal
    sayisal="$(awk -F'|' '/^[[:space:]]*$/ { next } { t++ } $1 ~ /^[0-9]+$/ { c++; if (c <= 3) ids = ids (ids ? ", " : "") $1 }
        END { if (c) print (c == t ? "hepsi " : "bazı ") c "/" t " (ilk: " ids ")" }' "$VERI/metadata.csv")"
    if [ -n "$sayisal" ]; then
        case "$sayisal" in
            hepsi*) hata "Tüm kayıt adları yalnız rakam: $sayisal. Eğitim deposu metadata.csv'yi pandas ile okur;" \
                "'0001' sayıya çevrilip '1.wav' aranır ve kayıtlar bulunamaz. Adlara ön ek verin (örn. normal_0001) ve" \
                "hazirla.py'yi yeniden çalıştırın." ;;
            *) uyari "Yalnız rakamdan oluşan kayıt adları var: $sayisal (karışık sütunda pandas metin okur, sorun" \
                "beklenmez; yine de ön ekli ad önerilir)." ;;
        esac
    fi
    if grep -q '|\[' "$VERI/metadata.csv"; then
        ETIKETLI=1
        bilgi "Metinlerde duygu etiketi var ([mutlu] …): SesKlon'u T3_EMOTION_TAGS=1 ile çalıştırın."
    fi
    if [ -f "$VERI/rapor.json" ]; then
        bilgi "Veri raporu: $VERI/rapor.json (duygu başına dakika ve tonlama aralığı)."
    fi
}

veri_ozeti() {   # metadata.csv'nin sha256 özeti (veri değişti mi?)
    "$(yama_python)" -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' \
        "$VERI/metadata.csv"
}

on_isleme_karari() {   # on_isleme_karari BEKLENEN_ISARET → 1 (yeniden ön işle) | 0 (atla)
    local beklenen="$1" guncel=1
    if ls "$ON_ISLEME_DIZIN"/*.pt >/dev/null 2>&1 && [ -f "$ON_ISLEME_ISARET" ] \
        && [ "$(cat "$ON_ISLEME_ISARET")" = "$beklenen" ]; then
        guncel=0
    fi
    case "$ON_ISLEME" in
        1) echo 1 ;;
        0)
            [ "$guncel" = 0 ] || uyari "ON_ISLEME=0 ama ön işleme dosyaları bu veri/taban ($TABAN_KIMLIK) için değil;" \
                "eski belirteçlerle eğitilecek. Emin değilseniz ON_ISLEME=1."
            echo 0 ;;
        *) echo "$guncel" ;;
    esac
}

on_isleme_temizle() {   # depo ChatterboxDataset'ı klasördeki TÜM .pt'leri okur: eskiler (reddedilen, doğrulama,
                        # önceki taban) eğitime sızmasın diye ön işlemeden önce silinir
    rm -f "$ON_ISLEME_ISARET"
    [ -d "$ON_ISLEME_DIZIN" ] || return 0
    local n
    n="$(find "$ON_ISLEME_DIZIN" -maxdepth 1 -type f -name '*.pt' | wc -l | tr -d ' ')"
    if [ "$n" -gt 0 ]; then
        bilgi "Eski ön işleme dosyaları siliniyor: $n .pt ($ON_ISLEME_DIZIN)."
        find "$ON_ISLEME_DIZIN" -maxdepth 1 -type f -name '*.pt' -delete
    fi
}

taban_kaydet() {
    mkdir -p "$CIKTI_DIZIN"
    printf 'MTL_TABAN=%s\nMTL_T3_SURUM=%s\nDIL=%s\nTAM_INCE_AYAR=%s\nTABAN_KIMLIK=%s\n' \
        "$MTL_TABAN" "$MTL_T3_SURUM" "$DIL" "$TAM_INCE_AYAR" "$TABAN_KIMLIK" > "$TABAN_KAYDI"
}

taban_dogrula() {   # birlestir: eğitimdeki taban ortamdakiyle aynı mı?
    if [ ! -f "$TABAN_KAYDI" ]; then
        uyari "Eğitim tabanı kaydı yok ($TABAN_KAYDI): eğitim elle ya da egit.sh'ın eski sürümüyle yapılmış;" \
              "ortamdaki ayarlar kullanılıyor (MTL_TABAN=$MTL_TABAN MTL_T3_SURUM=$MTL_T3_SURUM TAM_INCE_AYAR=$TAM_INCE_AYAR)."
        return 0
    fi
    local k v fark=""
    while IFS='=' read -r k v; do
        case "$k" in
            MTL_TABAN) [ "$v" = "$MTL_TABAN" ] || fark="$fark MTL_TABAN=$v" ;;
            MTL_T3_SURUM) [ "$v" = "$MTL_T3_SURUM" ] || fark="$fark MTL_T3_SURUM=$v" ;;
            TAM_INCE_AYAR) [ "$v" = "$TAM_INCE_AYAR" ] || fark="$fark TAM_INCE_AYAR=$v" ;;
        esac
    done < "$TABAN_KAYDI"
    [ -z "$fark" ] || hata "Eğitim farklı bir tabanla yapılmış ($TABAN_KAYDI:$fark); şimdiki ortam MTL_TABAN=$MTL_TABAN" \
        "MTL_T3_SURUM=$MTL_T3_SURUM TAM_INCE_AYAR=$TAM_INCE_AYAR. Birleştirme eğitimdeki tabanla yapılmalı:" \
        "ADIM=birlestir$fark bash finetune/egit.sh"
    bilgi "Eğitim tabanı doğrulandı: $TABAN_KIMLIK (MTL_T3_SURUM=$MTL_T3_SURUM)."
}

oom_onerisi() {
    local yari=$(( BATCH / 2 )) iki_kat=$(( GRAD_ACCUM * 2 ))
    [ "$yari" -ge 1 ] || yari=1
    uyari "Bellek yetmedi (out of memory). Etkin batch'i koruyarak BATCH'i yarıya indirin:"
    uyari "  ADIM=egit BATCH=$yari GRAD_ACCUM=$iki_kat ON_ISLEME=0 bash finetune/egit.sh"
    [ "$TAM_INCE_AYAR" = "1" ] && uyari "  Tam ince ayar çok bellek ister; TAM_INCE_AYAR=0 (LoRA) deneyin."
    [ "$LORA_R" -gt 32 ] && uyari "  Yine yetmezse LORA_R=32 LORA_ALPHA=64 deneyin."
    return 0
}

adim_egit() {
    baslik "2/3 Eğitim: ön işleme + train.py"
    [ -x "$PY" ] || hata "Sanal ortam yok: $VENV — önce: ADIM=kur bash finetune/egit.sh"
    veri_denetle
    local on_isleme beklenen
    beklenen="$TABAN_KIMLIK $(veri_ozeti)"
    on_isleme="$(on_isleme_karari "$beklenen")"
    if [ "$on_isleme" = "1" ]; then
        bilgi "Ön işleme açık: konuşmacı gömmesi, ses ve metin belirteçleri yeniden çıkarılacak ($TABAN_KIMLIK)."
        on_isleme_temizle
    else
        bilgi "Ön işleme atlanıyor: $ON_ISLEME_DIZIN güncel ($TABAN_KIMLIK, metadata.csv değişmemiş). Zorlamak için ON_ISLEME=1."
    fi
    yamala "$on_isleme"
    rm -f "$TABAN_KAYDI"          # yarıda kalan eğitimin bağdaştırıcısı eski kayıtla birleştirilmesin
    cihaz_bul
    mkdir -p "$GUNLUK_DIZIN"
    local gunluk durum
    gunluk="$GUNLUK_DIZIN/egitim_$(date +%Y%m%d_%H%M%S).log"
    bilgi "Eğitim başlıyor: EPOCH=$EPOCH BATCH=$BATCH GRAD_ACCUM=$GRAD_ACCUM LORA_R=$LORA_R LORA_ALPHA=$LORA_ALPHA" \
          "öğrenme hızı=${OGRENME_HIZI:-deponunki} cihaz=$BULUNAN_CIHAZ"
    bilgi "Günlük: $gunluk  ·  ilerleme: tensorboard --logdir $CIKTI_DIZIN"
    set +e
    (cd "$DEPO_DIZIN" && "$PY" train.py) 2>&1 | tee "$gunluk"
    durum="${PIPESTATUS[0]}"
    set -e
    if [ "$on_isleme" = "1" ] && grep -q "Preprocessing completed" "$gunluk" 2>/dev/null; then
        mkdir -p "$ON_ISLEME_DIZIN"
        printf '%s' "$beklenen" > "$ON_ISLEME_ISARET"
        grep "Preprocessing completed" "$gunluk" | tail -n 1 | sed 's/^/[egit] ön işleme: /'
    fi
    if [ "$durum" -ne 0 ]; then
        if grep -qiE "out of memory|OutOfMemoryError" "$gunluk"; then
            oom_onerisi
        fi
        hata "train.py başarısız oldu (çıkış kodu $durum). Günlük: $gunluk"
    fi
    taban_kaydet
    bilgi "Eğitim tamam. Taban kaydı: $TABAN_KAYDI ($TABAN_KIMLIK)."
}

# ---------- ADIM: birlestir ----------

sonuc_bul() {
    local aday
    if [ "$TAM_INCE_AYAR" = "1" ]; then aday="$CIKTI_DIZIN/t3_finetuned.safetensors"
    else aday="$CIKTI_DIZIN/t3_finetuned_merged.safetensors"; fi
    if [ -f "$aday" ]; then printf '%s' "$aday"; return 0; fi
    # Yedek: çıktı klasöründeki en yeni .safetensors (depo dosya adını değiştirmişse)
    aday="$(ls -t "$CIKTI_DIZIN"/*.safetensors 2>/dev/null | head -n 1 || true)"
    [ -n "$aday" ] && printf '%s' "$aday"
    return 0
}

adim_birlestir() {
    baslik "3/3 Birleştirme ve sonuç"
    [ -x "$PY" ] || hata "Sanal ortam yok: $VENV — önce: ADIM=kur bash finetune/egit.sh"
    [ -f "$VERI/metadata.csv" ] && grep -q '|\[' "$VERI/metadata.csv" && ETIKETLI=1
    taban_dogrula
    if [ "$TAM_INCE_AYAR" = "1" ]; then
        bilgi "Tam ince ayar: birleştirme gerekmez."
    else
        [ -d "$CIKTI_DIZIN/new_lang_adapter" ] || hata "LoRA bağdaştırıcısı yok: $CIKTI_DIZIN/new_lang_adapter — önce: ADIM=egit"
        yamala 0
        mkdir -p "$GUNLUK_DIZIN"
        local gunluk durum
        gunluk="$GUNLUK_DIZIN/birlestir_$(date +%Y%m%d_%H%M%S).log"
        bilgi "LoRA ağırlıkları T3'e gömülüyor (merge_lora.py, cpu)…"
        set +e
        (cd "$DEPO_DIZIN" && "$PY" merge_lora.py) 2>&1 | tee "$gunluk"
        durum="${PIPESTATUS[0]}"
        set -e
        [ "$durum" -eq 0 ] || hata "merge_lora.py başarısız (çıkış kodu $durum). Günlük: $gunluk"
    fi
    local sonuc
    sonuc="$(sonuc_bul)"
    [ -n "$sonuc" ] && [ -f "$sonuc" ] || hata "İnce ayarlı .safetensors bulunamadı: $CIKTI_DIZIN (merge_lora.py günlüğüne bakın)."
    sonuc_yazdir "$sonuc"
}

sonuc_yazdir() {
    local sonuc="$1" boyut etiket_env="" etiket_arg=""
    boyut="$(du -h "$sonuc" 2>/dev/null | cut -f1 || echo '?')"
    if [ "$ETIKETLI" = "1" ]; then etiket_env=" T3_EMOTION_TAGS=1"; etiket_arg=" --etiketli"; fi
    cat <<EOF

==== Bitti ====
İnce ayarlı T3 ağırlıkları: $sonuc ($boyut)
Taban: $TABAN_KIMLIK

1) Önce ölçün (temel ↔ ince ayar, kabul ölçütü: aralık medyanı ≥ 17 yarım ton, QC bozulmadan, hece/sn 3,5–6,5):
   python finetune/degerlendir.py --ref <konusmaci.wav> --ince "$sonuc"$etiket_arg --cikti finetune/rapor.json

2) KABUL çıkarsa SesKlon'u ince ayarlı modelle başlatın:
   cd "$PROJE_DIZIN/backend" && T3_FINETUNED="$sonuc"$etiket_env T3_MODEL=$MTL_T3_SURUM uvicorn app.main:app --host 0.0.0.0 --port 8000
   Kalıcı kullanım: proje kökündeki .env dosyasına şu satırları ekleyip ./run.sh ile başlatın:
     T3_FINETUNED=$sonuc
     T3_MODEL=$MTL_T3_SURUM$([ "$ETIKETLI" = 1 ] && printf '\n     T3_EMOTION_TAGS=1')
EOF
    if [ "$ETIKETLI" != "1" ]; then
        echo "   Not: veri duygu etiketsiz hazırlanmış; T3_EMOTION_TAGS=1 KULLANMAYIN (etiket metin olarak okunur)."
    fi
    if [ "$MTL_TABAN" = "0" ]; then
        uyari "Bu dosya İngilizce T3 tabanından eğitildi (MTL_TABAN=0); SesKlon'da tokenizer uyuşmazlığı beklenir."
    fi
}

# ---------- akış ----------

bilgi "SesKlon ince ayar — ADIM=$ADIM · depo: $DEPO_DIZIN · veri: $VERI"
case "$ADIM" in
    kur) adim_kur ;;
    egit) adim_egit ;;
    birlestir) adim_birlestir ;;
    yamala) yamala 0 ;;
    hepsi) adim_kur; adim_egit; adim_birlestir ;;
esac
