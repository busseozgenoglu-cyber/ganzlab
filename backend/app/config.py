import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
VOICES_DIR = DATA_DIR / "voices"
OUTPUT_DIR = DATA_DIR / "outputs"
UPLOAD_TMP_DIR = DATA_DIR / "tmp"
DB_PATH = DATA_DIR / "sesklon.db"
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", BASE_DIR.parent / "frontend" / "dist"))

API_KEY = os.getenv("API_KEY", "").strip()          # boşsa kimlik doğrulama yok
DEVICE = os.getenv("DEVICE", "").strip() or None    # cuda | mps | cpu (boş = otomatik)
T3_MODEL = os.getenv("T3_MODEL", "v3")              # Chatterbox Multilingual v3 / v2

# Sentez arka ucu (app/backends): chatterbox (PyTorch, varsayılan) | chatterbox-mlx (Apple Silicon) | f5-tr | xtts | fake
TTS_BACKEND = os.getenv("TTS_BACKEND", "chatterbox").strip() or "chatterbox"
T3_FINETUNED = os.getenv("T3_FINETUNED", "").strip() or None          # ince ayarlı T3 ağırlıkları (.safetensors / .pt)
T3_EMOTION_TAGS = os.getenv("T3_EMOTION_TAGS", "0") == "1"           # ince ayar verisindeki "[mutlu] " öneki metne eklensin mi
T3_EMOTION_SET = os.getenv("T3_EMOTION_SET", "").strip()  # etiket alacak duygular (virgüllü; boş = ince ayar bankasındaki 19 duygu)
CHATTERBOX_LOCAL_DIR = os.getenv("CHATTERBOX_LOCAL_DIR", "").strip() or None   # tüm ağırlıklar yerel klasörden
MLX_MODEL = os.getenv("MLX_MODEL", "mlx-community/chatterbox-multilingual-v3").strip()
F5_TR_CKPT = os.getenv("F5_TR_CKPT", "").strip() or None              # F5-TTS Türkçe ağırlık dosyası (.safetensors)
F5_TR_VOCAB = os.getenv("F5_TR_VOCAB", "").strip() or None            # F5-TTS Türkçe vocab.txt
XTTS_MODEL = os.getenv("XTTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2").strip()
MAX_REF_SECONDS = float(os.getenv("MAX_REF_SECONDS", "15"))
MAX_TEXT_CHARS = int(os.getenv("MAX_TEXT_CHARS", "5000"))
CHUNK_CHARS = int(os.getenv("CHUNK_CHARS", "170"))
PRELOAD = os.getenv("PRELOAD", "1") == "1"          # 1 = modeli açılışta arka planda yükle
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "60"))
MAX_OUTPUTS = int(os.getenv("MAX_OUTPUTS", "500"))     # geçmişte tutulacak en fazla çıktı (0 = sınırsız)

SUPPORTED_LANGUAGES = {
    "tr": "Türkçe", "en": "English", "de": "Deutsch", "fr": "Français", "es": "Español",
    "it": "Italiano", "pt": "Português", "nl": "Nederlands", "pl": "Polski", "ru": "Русский",
    "ar": "العربية", "he": "עברית", "hi": "हिन्दी", "ja": "日本語", "ko": "한국어", "zh": "中文",
    "el": "Ελληνικά", "da": "Dansk", "fi": "Suomi", "sv": "Svenska", "no": "Norsk",
    "ms": "Bahasa Melayu", "sw": "Kiswahili",
}

for d in (VOICES_DIR, OUTPUT_DIR, UPLOAD_TMP_DIR):
    d.mkdir(parents=True, exist_ok=True)
