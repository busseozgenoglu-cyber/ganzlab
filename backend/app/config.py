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
