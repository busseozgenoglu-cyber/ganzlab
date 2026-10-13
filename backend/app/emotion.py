"""Duygu sistemi (ElevenLabs v3 etiket mantığıyla).

Üç katman birlikte çalışır:
1. Referans katmanı — duyguyu asıl belirleyen şey referans klibin tonudur. Her sesin duygu başına
   kendi örneği olabilir (kullanıcı kaydeder). Yoksa nötr örnekten perde/tempo/dinamik ile türetilir.
2. Üretim katmanı — duyguya göre exaggeration / cfg / temperature.
3. Çıktı katmanı — duyguya göre tempo, kazanç, mikro perde kaydırma, fısıltı için nefesli ton, kızgın için sıkıştırma.

Metin tarafı:
- Duygu etiketi: "[heyecanlı] …" (sonraki etikete kadar) ya da kapsamlı "[heyecanlı: yalnızca bu kısım]".
- Yoğunluk: "[heyecanlı:1]" (0.7) / ":2" (1.0) / ":3" (1.4), "[biraz üzgün]" (0.65), "[çok kızgın]" (1.35),
  "[aşırı heyecanlı]" (1.6), "[heyecanlı %150]" (1.5; 50–160 arasına sıkıştırılır) → Segment.intensity.
- Karışım: "[üzgün+umutlu]" → birincil "üzgün", Segment.blend ["umutlu"] (en çok 2 ikincil).
- Kayış (arc): "[heyecanlı→sakin]" ya da "[sakinleşerek]" → bölüm boyunca hedef duyguya geçiş (Segment.arc_to).
- Satır içi kontroller (sürekli): "[hız:0.9]" (Segment.rate), "[perde:+1]" (Segment.pitch), "[ses:Ayşe]"
  (Segment.speaker); "[hız]" / "[hız:normal]" sıfırlar.
- Sözsüz etiketler ([gülme], [iç çekme], [hmm], [tüh]…) akan metne en yakın Türkçe ünlem olarak eklenir;
  keep_nonverbal=True iken kanonik adla (NONVERBAL_CANON) ayrı bir bölüm olur (gerçek tepki kaydı için).
- Duraklamalar: [nefes], [kısa duraklama], [uzun duraklama], [sessizlik] ve sayılı [1.5 sn] / [500 ms] / [2 saniye].
- Vurgu: "*sözcük*", "[vurgu] sözcük" ya da "[vurgu: kısa öbek]" → yıldızlar temizlenir, Segment.emphasis_words dolar;
  plan_emphasis() parçayı vurgulu sözcük sınırlarından böler.
- Cümle içeriğinden otomatik duygu çıkarımı (sözlük + olumsuzluk + noktalama + büyük harf oranı).

Profil tarafı: effective_profile() yoğunluk ve karışımı tek profile indirger, interpolate_profile() kayış için ara
profil üretir; ikisi de PROFILES'ı değiştirmeden yeni nesne döndürür.

Satır başı "Heyecanlı: …" biçimi bilerek DESTEKLENMEZ (tiyatro/diyalog metinleriyle karışır).
Tüm küçük harf dönüşümleri `tr_lower` ile yapılır ("İNANILMAZ" → "inanılmaz"; str.lower() İ/ı'yı bozar).
"""
from __future__ import annotations

import logging
import math
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import soundfile as sf

from .tr import tr_lower

log = logging.getLogger("sesklon.emotion")


@dataclass
class EmotionProfile:
    name: str
    label: str
    # üretim
    exaggeration: float | None = None
    cfg_weight: float | None = None
    temperature: float | None = None
    # referans türetme (nötr klipten): yarım ton ve tempo çarpanı
    ref_pitch: float = 0.0
    ref_tempo: float = 1.0
    ref_gain_db: float = 0.0
    ref_breathy: bool = False
    # çıktı işleme
    speed: float = 1.0
    out_pitch: float = 0.0
    out_gain_db: float = 0.0
    highpass_hz: int = 0
    compress: bool = False
    breathy: bool = False
    whisper_mix: float = 0.0     # 1 = tam fısıltı dönüşümü, 0.3 = hafif nefesli
    pause_mul: float = 1.0       # cümle arası duraklama çarpanı
    aliases: list[str] = field(default_factory=list)
    description: str = ""        # arayüzde gösterilen kısa Türkçe ipucu


PROFILES: dict[str, EmotionProfile] = {p.name: p for p in [
    EmotionProfile("normal", "Normal",
                   aliases=["nötr", "neutral", "doğal", "natural", "düz", "plain"],
                   description="Doğal, nötr okuma; ek duygu ayarı yapılmaz."),
    EmotionProfile("heyecanlı", "Heyecanlı", exaggeration=0.7, cfg_weight=0.35, temperature=0.9,
                   ref_pitch=+1.2, ref_tempo=1.07, ref_gain_db=+2, speed=1.04, out_pitch=+0.5, out_gain_db=+1.5,
                   pause_mul=0.8,
                   aliases=["heyecanli", "excited", "coşkulu", "enerjik", "energetic", "enthusiastic", "heyecan",
                            "coşku", "thrilled", "hyped", "canlı", "lively"],
                   description="Enerjik ve coşkulu; tanıtım, müjde ve sürprizler için."),
    EmotionProfile("mutlu", "Mutlu", exaggeration=0.7, cfg_weight=0.4, temperature=0.85,
                   ref_pitch=+0.8, ref_tempo=1.03, speed=1.02, out_pitch=+0.2, out_gain_db=+0.5,
                   pause_mul=0.9,
                   aliases=["happy", "neşeli", "cheerful", "sevinçli", "joyful", "glad", "keyifli", "sevinç", "neşe",
                            "pleased"],
                   description="Neşeli, gülümseyen bir ton; teşekkür ve iyi haberler için."),
    EmotionProfile("sakin", "Sakin", exaggeration=0.35, cfg_weight=0.55, temperature=0.7,
                   ref_pitch=-0.4, ref_tempo=0.95, speed=0.95, out_gain_db=-0.5,
                   pause_mul=1.25,
                   aliases=["calm", "huzurlu", "rahat", "relaxed", "soft", "dingin", "peaceful", "serene", "yumuşak",
                            "sükûnet", "sakince"],
                   description="Yavaş, yumuşak ve huzurlu; meditasyon ve rahatlatıcı anlatım için."),
    EmotionProfile("ciddi", "Ciddi", exaggeration=0.4, cfg_weight=0.55, temperature=0.7,
                   ref_pitch=-0.6, ref_tempo=0.97, speed=0.97, out_pitch=-0.2,
                   pause_mul=1.15,
                   aliases=["serious", "resmi", "formal", "kararlı", "determined", "ağırbaşlı", "solemn", "grave",
                            "ciddiyetle"],
                   description="Ağırbaşlı ve kararlı; uyarılar ve önemli duyurular için."),
    EmotionProfile("üzgün", "Üzgün", exaggeration=0.3, cfg_weight=0.5, temperature=0.7,
                   ref_pitch=-1.3, ref_tempo=0.9, ref_gain_db=-2, speed=0.9, out_pitch=-0.5, out_gain_db=-2.5,
                   pause_mul=1.5,
                   aliases=["uzgun", "sad", "hüzünlü", "kederli", "melancholic", "mutsuz", "hüzün", "keder", "upset",
                            "kırgın", "melankolik", "sorrowful"],
                   description="Hüzünlü, alçak ve yavaş; kötü haber ve veda anları için."),
    EmotionProfile("kızgın", "Kızgın", exaggeration=0.85, cfg_weight=0.3, temperature=0.9,
                   ref_pitch=+0.5, ref_tempo=1.06, ref_gain_db=+3, speed=1.03, out_gain_db=+2.5, compress=True,
                   pause_mul=0.8,
                   aliases=["kizgin", "angry", "öfkeli", "sinirli", "furious", "annoyed", "öfke", "sinir", "mad",
                            "hiddetli", "rage", "irritated"],
                   description="Sert ve yüksek enerjili; öfke ve tepki cümleleri için."),
    EmotionProfile("şaşkın", "Şaşkın", exaggeration=0.75, cfg_weight=0.35, temperature=0.9,
                   ref_pitch=+1.5, ref_tempo=1.0, speed=1.0, out_pitch=+0.6,
                   pause_mul=1.1,
                   aliases=["saskin", "surprised", "hayret", "shocked", "amazed", "şaşırmış", "şok", "astonished",
                            "hayretle", "şaşkınlık"],
                   description="Yüksek perdeli hayret; beklenmedik haberler ve sorular için."),
    EmotionProfile("korkmuş", "Korkmuş", exaggeration=0.65, cfg_weight=0.4, temperature=0.9,
                   ref_pitch=+1.0, ref_tempo=1.08, ref_breathy=True, speed=1.05, out_pitch=+0.4, whisper_mix=0.25,
                   pause_mul=0.9,
                   aliases=["korkmus", "scared", "endişeli", "nervous", "tedirgin", "anxious", "korku", "afraid",
                            "fearful", "ürkek", "panik", "frightened", "korkarak"],
                   description="Hızlı, nefesli ve tedirgin; gerilim ve tehlike anları için."),
    EmotionProfile("fısıltı", "Fısıltı", exaggeration=0.25, cfg_weight=0.6, temperature=0.65,
                   ref_pitch=-0.3, ref_tempo=0.95, ref_gain_db=-6, ref_breathy=True, speed=0.93, out_gain_db=-8,
                   whisper_mix=1.0, pause_mul=1.3,
                   aliases=["fisilti", "whisper", "whispers", "sessiz", "gizli", "fısıldar", "fısıldayarak",
                            "whispering", "fısılda", "kısık"],
                   description="Kısık, nefesli fısıltı; sır ve gizem anları için."),
    EmotionProfile("vurgulu", "Vurgulu", exaggeration=0.8, cfg_weight=0.45, temperature=0.8,
                   ref_tempo=0.97, speed=0.97, out_gain_db=+1.5, compress=True,
                   pause_mul=1.1,
                   aliases=["emphasis", "emphatic", "önemli", "dikkat", "kesin", "vurgulayarak", "altını çizerek"],
                   description="Sözcükleri bastırarak, net ve güçlü okuma; önemli noktalar için."),
    EmotionProfile("samimi", "Samimi", exaggeration=0.55, cfg_weight=0.45, temperature=0.8,
                   ref_pitch=-0.2, ref_tempo=0.98, speed=0.98,
                   pause_mul=1.05,
                   aliases=["warm", "sıcak", "friendly", "dostça", "içten", "sincere", "içtenlikle", "sevecen",
                            "cana yakın"],
                   description="Sıcak, dostça ve içten; sohbet ve kişisel mesajlar için."),
    EmotionProfile("sıkılmış", "Sıkılmış", exaggeration=0.25, cfg_weight=0.55, temperature=0.7,
                   ref_pitch=-0.8, ref_tempo=0.92, speed=0.92, out_pitch=-0.3, out_gain_db=-1.5,
                   pause_mul=1.3,
                   aliases=["sikilmis", "bored", "bıkkın", "isteksiz", "tired", "yorgun", "sıkkın", "bezgin", "bitkin",
                            "uninterested", "weary"],
                   description="İsteksiz, yorgun ve yavaş; bıkkınlık anları için."),
    EmotionProfile("alaycı", "Alaycı", exaggeration=0.75, cfg_weight=0.4, temperature=0.85,
                   ref_pitch=+0.4, ref_tempo=0.96, speed=0.96, out_pitch=+0.2,
                   pause_mul=1.15,
                   aliases=["alayci", "sarcastic", "ironik", "ironic", "dalga", "iğneleyici", "mocking", "sarkastik",
                            "alaylı", "dalgacı"],
                   description="İğneleyici, ironik bir ton; dalga geçme ve espri için."),
    EmotionProfile("nazik", "Nazik", exaggeration=0.45, cfg_weight=0.5, temperature=0.75, pause_mul=1.1,
                   aliases=["kibar", "polite", "hizmet", "courteous", "nazikçe", "kibarca", "müşteri hizmeti",
                            "customer service"],
                   description="Kibar ve yardımsever; müşteri hizmetleri ve karşılama mesajları için."),
    EmotionProfile("gururlu", "Gururlu", exaggeration=0.6, cfg_weight=0.45,
                   aliases=["proud", "proudly", "gurur", "gururla", "onurlu", "iftihar"],
                   description="Göğsü kabarmış, güçlü ve onurlu; başarı ve kutlama anları için."),
    EmotionProfile("umutlu", "Umutlu", exaggeration=0.55,
                   aliases=["hopeful", "iyimser", "optimistic", "umut", "umut dolu", "umutla"],
                   description="Aydınlık ve iyimser; gelecek, dilek ve cesaret sözleri için."),
    EmotionProfile("nostaljik", "Nostaljik", exaggeration=0.4, speed=0.95, pause_mul=1.3,
                   aliases=["nostalgic", "nostalji", "özlem", "özlemli", "hasret", "hatıra", "eski günler"],
                   description="Yavaş, hatıralara dalmış ve hafif buruk; geçmişi anlatırken."),
    EmotionProfile("gergin", "Gergin", exaggeration=0.6, cfg_weight=0.4, temperature=0.85, speed=1.03,
                   pause_mul=0.85,
                   aliases=["tense", "stresli", "stressed", "stres", "gerilim", "huzursuz", "uneasy",
                            "diken üstünde"],
                   description="Hızlı ve diken üstünde; geri sayım ve gerilim sahneleri için."),
    EmotionProfile("romantik", "Romantik", exaggeration=0.5, cfg_weight=0.5, temperature=0.8, speed=0.95,
                   pause_mul=1.25, whisper_mix=0.15,
                   aliases=["romantic", "aşık", "âşık", "aşk", "sevgi dolu", "loving", "tender", "şefkatli"],
                   description="Yumuşak, yavaş ve hafif nefesli; sevgi sözleri için."),
    EmotionProfile("çocuksu", "Çocuksu", exaggeration=0.7, ref_pitch=+1.5,
                   aliases=["childlike", "childish", "çocuk", "çocukça", "child", "kid", "sevimli", "cute"],
                   description="İnce ve oyunbaz; çocuk karakterleri ve masallar için."),
    EmotionProfile("otoriter", "Otoriter", exaggeration=0.55, cfg_weight=0.55, temperature=0.7, speed=0.97,
                   compress=True,
                   aliases=["authoritative", "authority", "otorite", "buyurgan", "commanding", "emredici", "komuta"],
                   description="Güçlü, kontrollü ve buyurgan; talimat ve liderlik konuşmaları için."),
    EmotionProfile("hızlı", "Hızlı", ref_tempo=1.1, speed=1.12, pause_mul=0.7,
                   aliases=["hizli", "fast", "acele", "quick", "rapid", "çabuk", "seri"],
                   description="Tempoyu artırır, duraklamaları kısaltır."),
    EmotionProfile("yavaş", "Yavaş", ref_tempo=0.92, speed=0.9, pause_mul=1.4,
                   aliases=["yavas", "slow", "ağır", "slowly", "ağır ağır", "yavaşça"],
                   description="Tempoyu düşürür, duraklamaları uzatır."),
]}

_FOLD_TABLE = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def fold_ascii(s: str) -> str:
    """Türkçe harfleri ASCII karşılığına indirger ("üzgün" → "uzgun"); Türkçe klavyesi olmayanlar için yedek eşleşme."""
    return s.translate(_FOLD_TABLE)


def _norm_key(s: str) -> str:
    """Tablo anahtarı: Türkçe küçük harf, tek boşluk, baş/son boşluksuz."""
    return re.sub(r"\s+", " ", tr_lower(s).replace("i̇", "i")).strip()


def _key_variants(raw: str) -> list[str]:
    """Bir ad/etiket için sırayla denenecek anahtarlar: Türkçe küçük harf ("HEYECANLI" → "heyecanlı") ve
    tire/alt çizgi → boşluk biçimi. İngilizce büyük harf ("EXCITED" → tr_lower "excıted") ASCII yedeğiyle
    (fold_ascii → "excited") eşleşir; str.lower() kullanılmaz."""
    k = _norm_key(str(raw))
    out = [k] if k else []
    v = re.sub(r"[_\-]+", " ", k).strip()
    if v and v not in out:
        out.append(v)
    return out


# ad/eş anlamlı → profil adı. Önce asıl adlar yazılır; bir eş anlamlı hiçbir zaman başka profilin adını ezemez.
ALIAS_TO_NAME: dict[str, str] = {}
for _p in PROFILES.values():
    ALIAS_TO_NAME[_norm_key(_p.name)] = _p.name
for _p in PROFILES.values():
    for _a in _p.aliases:
        ALIAS_TO_NAME.setdefault(_norm_key(_a), _p.name)
_ALIAS_FOLD: dict[str, str] = {}
for _k, _n in ALIAS_TO_NAME.items():
    _ALIAS_FOLD.setdefault(fold_ascii(_k), _n)


def resolve(name: str | None) -> EmotionProfile | None:
    """Ad ya da eş anlamlıdan profil bulur: "HEYECANLI", "Üzgün", "ŞAŞKIN", "excited", "uzgun"… Bulamazsa None."""
    if name is None or not str(name).strip():
        return None
    keys = _key_variants(str(name))
    for k in keys:
        if k in ALIAS_TO_NAME:
            return PROFILES[ALIAS_TO_NAME[k]]
    for k in keys:
        n = _ALIAS_FOLD.get(fold_ascii(k))
        if n:
            return PROFILES[n]
    return None


# ---------- sözsüz etiketler ve duraklamalar ----------

# Sözsüz etiketler → seslendirilecek metin. Model gerçek gülme/iç çekme üretemez; en yakın Türkçe ünlem okunur ve
# akan metnin içine konur (tek başına üretilince halüsinasyon yapıyor). Değeri "" olanlar ses üretmez; duraklama
# süreleri PAUSE_TAGS'ten gelir (geriye uyumluluk için burada da tutulur).
NONVERBAL: dict[str, str] = {
    # gülme
    "gülme": "Hahaha!", "güler": "Hahaha!", "gülüyor": "Hahaha!", "gülüş": "Hahaha!", "laughs": "Hahaha!",
    "laugh": "Hahaha!", "laughing": "Hahaha!", "haha": "Haha!", "hahaha": "Hahaha!",
    "kahkaha": "Hahahaha!", "kahkaha atar": "Hahahaha!", "kahkahalar": "Hahahaha!", "laughs hard": "Hahahaha!",
    "kıkırdama": "Hihihi!", "kıkırdar": "Hihihi!", "giggles": "Hihihi!", "giggle": "Hihihi!", "hihi": "Hihi!",
    "chuckles": "Heh heh.", "chuckle": "Heh heh.", "kıs kıs güler": "Heh heh.",
    # iç çekme, nefes verme, bıkkınlık
    "iç çekme": "Ahh...", "iç çeker": "Ahh...", "sighs": "Ahh...", "sigh": "Ahh...",
    "nefes verir": "Hoff...", "nefes verme": "Hoff...", "exhales": "Hoff...",
    "of": "Off...", "off": "Off...", "pff": "Pöf...", "pf": "Pöf...", "pöf": "Pöf...", "puflar": "Pöf...",
    # düşünme, dolgu, onay
    "hmm": "Hmm...", "hm": "Hmm...", "düşünür": "Hmm...", "thinks": "Hmm...",
    "ıı": "Iıı...", "ee": "Iıı...", "dolgu": "Iıı...", "um": "Iıı...", "uh": "Iıı...",
    "şey": "Şey...",
    "hı hı": "Hı hı.", "hıhı": "Hı hı.", "ıhı": "Hı hı.", "onay": "Hı hı.", "uh huh": "Hı hı.",
    "mmm": "Mmm...", "mm": "Mmm...", "lezzet": "Mmm...", "yum": "Mmm...",
    "hums": "Hmm hmm hmm.", "hum": "Hmm hmm hmm.", "mırıldanır": "Hmm hmm hmm.",
    "evet evet": "Evet, evet.", "cık": "Cık cık.", "cık cık": "Cık cık.",
    # ünlemler
    "şaşırır": "Vay canına!", "vay canına": "Vay canına!", "wow": "Vay!", "vay": "Vay!",
    "gasps": "Hah!", "gasp": "Hah!", "hah": "Hah!", "nefesi kesilir": "Hah!",
    "tüh": "Tüh!", "aman": "Aman!", "ay": "Ay!", "oh": "Oh...", "hıh": "Hıh.", "yok ya": "Yok ya!",
    "hişt": "Hişt!", "pişt": "Pişt!", "ıslık": "Fiiüüt!", "ıslık çalar": "Fiiüüt!", "whistles": "Fiiüüt!",
    "groans": "Ohh...", "groan": "Ohh...", "inler": "Ohh...", "inleme": "Ohh...",
    # ağlama, burun çekme, öksürme, esneme
    "ağlar": "Hıh hıh...", "ağlıyor": "Hıh hıh...", "ağlama": "Hıh hıh...", "cries": "Hıh hıh...",
    "sobs": "Hıh hıh...", "hıçkırır": "Hık!",
    "sniffs": "Sniff.", "sniff": "Sniff.", "burnunu çeker": "Sniff.",
    "öksürür": "Öhö öhö.", "öksürük": "Öhö öhö.", "coughs": "Öhö öhö.", "cough": "Öhö öhö.",
    "boğaz temizler": "Ehem.", "boğazını temizler": "Ehem.", "clears throat": "Ehem.", "ehem": "Ehem.",
    "esner": "Aaah...", "esneme": "Aaah...", "yawns": "Aaah...",
    # ses üretmeyenler (süre PAUSE_TAGS'te)
    "nefes": "", "nefes alır": "", "derin nefes": "", "breath": "", "takes a breath": "", "deep breath": "",
    "pause": "", "duraklama": "", "kısa duraklama": "", "uzun duraklama": "", "sessizlik": "", "...": "",
}

# Sözsüz etiketlerin kanonik Türkçe adları (kanonik ad → eş adları). Gerçek tepki kayıtları (nonverbal.py) bu
# adlarla saklanır. Kaydedilebilir 15 anahtar ("gülme", "kahkaha", "kıkırdama", "iç çekme", "hmm", "of",
# "nefes verir", "öksürür", "boğaz temizler", "esner", "ağlar", "şaşırır", "hıh", "mmm", "cık") en yakın eş adları
# toplar ("chuckles" → "kıkırdama", "vay" → "şaşırır"); karşılığı olmayanlar ("tüh", "aman", "şey"…) kendi adıyla
# kalır. Her kanonik ad NONVERBAL'da bir anahtardır; okunuşu nonverbal_fallback() ile alınır.
_NONVERBAL_GROUPS: dict[str, tuple[str, ...]] = {
    "gülme": ("güler", "gülüyor", "gülüş", "laughs", "laugh", "laughing", "haha", "hahaha"),
    "kahkaha": ("kahkaha atar", "kahkahalar", "laughs hard"),
    "kıkırdama": ("kıkırdar", "giggles", "giggle", "hihi", "chuckles", "chuckle", "kıs kıs güler"),
    "iç çekme": ("iç çeker", "sighs", "sigh"),
    "nefes verir": ("nefes verme", "exhales"),
    "of": ("off", "pff", "pf", "pöf", "puflar"),
    "hmm": ("hm", "düşünür", "thinks"),
    "mmm": ("mm", "lezzet", "yum"),
    "hıh": ("hı hı", "hıhı", "ıhı", "onay", "uh huh"),
    "cık": ("cık cık",),
    "şaşırır": ("vay canına", "wow", "vay", "gasps", "gasp", "hah", "nefesi kesilir"),
    "ağlar": ("ağlıyor", "ağlama", "cries", "sobs"),
    "öksürür": ("öksürük", "coughs", "cough"),
    "boğaz temizler": ("boğazını temizler", "clears throat", "ehem"),
    "esner": ("esneme", "yawns"),
    # kaydedilebilir karşılığı olmayanlar
    "ıı": ("ee", "dolgu", "um", "uh"),
    "şey": (),
    "mırıldanır": ("hums", "hum"),
    "evet evet": (),
    "tüh": (), "aman": (), "ay": (), "oh": (), "yok ya": (), "hişt": (), "pişt": (), "hıçkırır": (),
    "ıslık": ("ıslık çalar", "whistles"),
    "inler": ("groans", "groan", "inleme"),
    "burnunu çeker": ("sniffs", "sniff"),
}
# eş ad → kanonik ad ("laughs" → "gülme", "kahkaha atar" → "kahkaha", "hıhı" → "hıh"); kanonik ad kendine eşlenir
NONVERBAL_CANON: dict[str, str] = {
    alias: canon for canon, aliases in _NONVERBAL_GROUPS.items() for alias in (canon, *aliases)
}

# Duraklama etiketleri → milisaniye
PAUSE_TAGS: dict[str, int] = {
    "kısa duraklama": 350, "kısa ara": 350, "short pause": 350,
    "nefes": 500, "nefes alır": 500, "breath": 500, "takes a breath": 500,
    "derin nefes": 700, "deep breath": 700,
    "duraklama": 800, "pause": 800, "...": 800,
    "uzun duraklama": 1500, "long pause": 1500,
    "sessizlik": 2000, "silence": 2000,
}

MAX_TIMED_PAUSE_MS = 10_000
# "[1.5 sn]", "[1,5 sn]", "[500 ms]", "[2 saniye]", "[duraklama: 1 sn]", "[pause 2s]"
_TIMED_PAUSE_RE = re.compile(
    r"^(?:(?:duraklama|pause|sessizlik|silence|bekle|wait)\s*:?\s*)?"
    r"(\d{1,5}(?:[.,]\d{1,3})?)\s*"
    r"(ms|msn|milisaniye|milliseconds?|sn|s|saniye|sec|secs|seconds?)\.?$"
)
_MS_UNITS = ("ms", "msn", "milisaniye", "millisecond", "milliseconds")


def timed_pause_ms(tag: str) -> int | None:
    """Sayılı duraklama etiketini milisaniyeye çevirir ("1.5 sn" → 1500, "500 ms" → 500, "2 saniye" → 2000).
    En çok MAX_TIMED_PAUSE_MS. Etiket bu biçimde değilse None."""
    for key in _key_variants(tag):
        m = _TIMED_PAUSE_RE.match(fold_ascii(key))      # birimler ASCII: "2 SECONDS" → "2 seconds"
        if not m:
            continue
        value = float(m.group(1).replace(",", "."))
        ms = value if m.group(2) in _MS_UNITS else value * 1000.0
        return int(round(min(max(ms, 0.0), MAX_TIMED_PAUSE_MS)))
    return None


# "[vurgu] sözcük" / "[vurgu: öbek]" — "vurgulu" duygu profilinden ayrı: yalnızca sözcüğü işaretler
EMPHASIS_TAGS = frozenset({"vurgu", "vurgula", "emphasize"})

_NONVERBAL_FOLD: dict[str, str] = {}
for _k in NONVERBAL:
    _NONVERBAL_FOLD.setdefault(fold_ascii(_k), _k)
_PAUSE_FOLD: dict[str, str] = {}
for _k in PAUSE_TAGS:
    _PAUSE_FOLD.setdefault(fold_ascii(_k), _k)


# ---------- otomatik duygu çıkarımı ----------

# Kalıp kuralları (hepsi küçük harf):
#  - Kalıp sözcük başından eşleşir ve ek alabilir (kök): "üzül" → "üzüldüm", "kaybet" → "kaybettik".
#  - Son sözcüğü 3 harf ya da daha kısa olan kalıp tam sözcük eşleşir: "vay", "gerçekten mi" ("mimar" değil).
#  - "=" ile başlayan kalıp tam sözcüktür: "=asla" ("aslan" değil), "=süper" ("süpermarket" değil).
#  - Noktalama içeren kalıp ("ne?", "yeter!") olduğu gibi aranır.
#  - Tek sözcük 2, çok sözcüklü kalıp 3 puan. Çakışan eşleşmelerde en uzun kalıp kazanır
#    ("endişelenme" → sakin; içindeki "endişe" → korkmuş sayılmaz). Liste sırası eşitlikte önceliktir.
AUTO_LEXICON: list[tuple[str, tuple[str, ...]]] = [
    ("heyecanlı", (
        "harika", "müthiş", "inanılmaz", "muhteşem", "=süper", "süpersin", "efsane", "hadi", "başlıyoruz",
        "kaçırma", "mükemmel", "bomba", "wow", "vay", "heyecan", "yaşasın", "kazandı", "sürpriz", "yeni geldi",
        "şahane", "fantastik", "olağanüstü", "muazzam", "eşsiz", "kusursuz", "bayıl", "acayip", "müjde",
        "şampiyon", "zafer kazan", "zaferimiz", "gol", "rekor", "son şans", "çılgın", "coşku")),
    ("mutlu", (
        "mutlu", "sevin", "teşekkür", "güzel", "tebrik", "seviyorum", "keyif", "neşe", "gülümse", "harikasın",
        "kutla", "kutlu", "iyi ki", "şükür", "şanslıyım", "eğlen", "oley", "hayırlı olsun", "afiyet", "sevimli",
        "minnettar", "iyi haber", "sağ ol", "sağ olun", "hoş geldin", "hoşuma", "kahkaha", "gülüyor", "güldük",
        "bayram")),
    ("üzgün", (
        "maalesef", "üzgün", "ne yazık", "üzül", "kaybet", "özledim", "hüzün", "ağla", "=veda", "vedalaş",
        "keşke", "yalnızım", "yalnızlık", "kırgın", "pişman", "başımız sağ olsun", "elveda", "acı haber",
        "acı verici", "vefat", "rahmet", "büyük kayıp", "taziye", "gözyaşı", "kalbim kırık", "kırıldım", "üzücü",
        "yazık", "mutsuz", "hayal kırıklığı", "keder", "çaresiz", "umutsuz", "yıkıldım", "kahrol", "artık yok",
        "yas", "matem", "buruk")),
    ("kızgın", (
        "sinir", "öfke", "yeter artık", "yeter be", "yeter!", "rezalet", "rezil", "saçma", "dayanamıyorum",
        "bıktım", "usandım", "kabul edilemez", "ciddi misin", "=asla", "nasıl olur", "utanma", "terbiyesiz",
        "saygısız", "küstah", "aptal", "salak", "lanet", "kahretsin", "defol", "kes sesini", "sus artık",
        "çıldır", "delirt", "nefret", "berbat", "skandal", "haddini", "ayıp", "sabrım", "kaç kere",
        "ne cüretle", "hiddet")),
    ("şaşkın", (
        "şaşır", "şaşkın", "inanama", "gerçekten mi", "ciddi mi", "cidden mi", "nasıl ya", "nasıl yani",
        "olamaz", "ne?", "yok artık", "hayret", "vay be", "vay canına", "aa", "aaa", "hiç beklemiyordum",
        "beklenmedik", "inanılır gibi değil", "şok", "şoke", "afalla", "dona kaldım", "ne diyorsun",
        "emin misin", "sahi mi", "hakikaten mi", "bu da ne", "neler oluyor", "imkansız", "imkânsız",
        "harbi mi", "oha", "hadi ya")),
    ("korkmuş", (
        "kork", "endişe", "tehlike", "dikkat et", "ürper", "tedirgin", "panik", "imdat", "yardım edin", "eyvah",
        "aman tanrım", "kaçın!", "kaçalım", "biri var", "titre", "dehşet", "kabus", "kâbus", "öleceğ",
        "kurtarın", "tehdit", "ürkü", "kalbim duracak", "saklan", "felaket", "karanlıkta", "ses duydum",
        "takip ediyor", "nefesim kesildi")),
    ("ciddi", (
        "önemli", "önemle", "unutma", "dikkat", "uyarı", "mutlaka", "kesinlikle", "kesin olarak", "şart",
        "zorunlu", "kural", "yasak", "sorumlu", "ihlal", "yükümlü", "acil", "talimat", "prosedür", "güvenlik",
        "güvenliğ", "ihtar", "hiçbir koşulda", "ciddiye", "gerekli", "tedbir", "önlem", "denetim",
        "yönetmelik", "son tarih", "ciddi")),
    ("sakin", (
        "rahatla", "sakin", "huzur", "derin nefes", "yavaşça", "dinlen", "sessiz", "usulca", "nefes alın",
        "nefes verin", "gevşe", "=korkma", "korkmayın", "endişelenme", "merak etme", "sorun yok",
        "her şey yolunda", "her şey geçecek", "yavaş yavaş", "sükunet", "sükûnet", "dingin", "rahat ol",
        "rahat olun", "meditasyon", "gözlerini kapat", "telaşlanma", "acele etme", "keyfine bak", "kafa dinle",
        "usul usul")),
    ("gergin", (
        "gergin", "geril", "stres", "zaman daralıyor", "vakit yok", "acele", "çabuk", "hemen şimdi",
        "geç kaldık", "yetişeme", "diken üstünde", "kalbim küt küt", "ter bastı", "sıkıştık", "baskı altında",
        "kritik", "riskli", "geri sayım", "son saniye", "ya olmazsa", "ya başaramazsak", "huzursuz", "bekleyiş",
        "nefesler tutuldu", "son dakika", "tetikte")),
    ("umutlu", (
        "umarım", "umuyorum", "umut ediyorum", "umutlu", "umudum", "inşallah", "belki bir gün",
        "bir gün mutlaka", "yarınlar", "daha iyi olacak", "her şey düzelecek", "düzelecek", "başarabiliriz",
        "başaracağız", "hayallerimiz", "dilerim", "dua", "tünelin ucunda", "yeni bir başlangıç", "vazgeçme",
        "pes etme", "güçlüyüz", "güneşli günler", "iyileşecek", "umut var", "inanıyorum")),
    ("gururlu", (
        "gurur", "onur duy", "onurlu", "onurla", "iftihar", "başardı", "alnımızın akıyla", "göğsümüzü kabart",
        "kahraman", "tarih yazdı", "layık", "hak etti", "emeğimiz", "emeklerimiz", "ödül", "madalya", "zirve",
        "takdir", "övün", "şeref", "başarımız", "eserimiz", "dünya birincisi", "rekor kır",
        "başarıyla tamamla")),
    ("nostaljik", (
        "eski günler", "o günler", "o zamanlar", "bir zamanlar", "çocukluğum", "çocukken", "hatırlı", "anılar",
        "hatıra", "nostalji", "eskiden", "yıllar önce", "yıllar geçti", "özlem", "oynardık", "giderdik",
        "eski fotoğraf", "gençliğim", "kaset", "=plak", "siyah beyaz", "geçmişte", "geçmişe", "hasret",
        "memleket", "köyümüz", "anneannem", "babaannem", "dedem", "ninem", "o eski")),
    ("romantik", (
        "seni seviyorum", "aşk", "aşkım", "aşkla", "aşık", "âşık", "sevgilim", "gözlerin", "kalbim seninle",
        "yanımda ol", "sonsuza dek", "sonsuza kadar", "öpücük", "sarıl", "romantik", "ay ışığı", "dans edelim",
        "evlenir misin", "hayatımın aşkı", "tatlım", "bir tanem", "gülüşün", "seni özledim", "sevdiğim",
        "kalbimin", "sevgiyle", "canımın içi", "biricik")),
    ("nazik", (
        "lütfen", "rica eder", "rica etsem", "memnuniyetle", "yardımcı olabilir", "yardımcı olmaktan",
        "nasıl yardımcı", "buyurun", "efendim", "teşekkür ederiz", "değerli müşteri", "anlayışınız", "sabrınız",
        "özür dile", "kusura bakmayın", "iyi günler", "hayırlı günler", "hoş geldiniz", "rahatsızlık için",
        "size nasıl", "talebiniz", "bilginize", "zahmet olmazsa", "saygılar", "tercih ettiğiniz",
        "hizmetinizde", "nazik", "kibar", "iyi akşamlar", "iyi dileklerimizle")),
]

# Olumsuzlanınca (ör. "harika değil") üzgün/kızgın lehine çevrilen olumlu duygular
_POSITIVE_EMOTIONS = frozenset({"heyecanlı", "mutlu", "sakin", "umutlu", "gururlu", "romantik", "nazik"})
NEGATION_WINDOW = 3                       # kökten sonra en çok kaç sözcükte olumsuzluk aranır
CAPS_MIN_LETTERS = 8                      # büyük harf kuralı için en az harf
CAPS_RATIO = 0.6                          # büyük harf oranı bunu aşarsa "bağırma" sayılır
_NEGATION_RE = re.compile(r"^(?:değil\w*|yok(?:tu|muş|tur)?|asla|hiç(?:bir)?)$")
_QUESTION_PARTICLE_RE = re.compile(r"^m[ıiuü](?:[sydnz]\w*)?$")    # mi, mı, misin, miydi… ("değil mi?")
_CLAUSE_BREAK_RE = re.compile(r"[.!?;:,…]")
_WORD_TOKEN_RE = re.compile(r"\w+")


def _compile_entry(entry: str) -> tuple[re.Pattern[str], int]:
    exact = entry.startswith("=")
    parts = (entry[1:] if exact else entry).split()
    last = parts[-1]
    last_is_word = re.fullmatch(r"\w+", last) is not None
    if last_is_word and len(last) <= 3:
        exact = True
    body = r"\s+".join(re.escape(p) for p in parts)
    tail = r"(?!\w)" if exact and last_is_word else ""
    return re.compile(r"(?<!\w)" + body + tail), (3 if len(parts) > 1 else 2)


_LEX_PATTERNS: list[tuple[str, re.Pattern[str], int]] = [
    (emo, *_compile_entry(entry)) for emo, entries in AUTO_LEXICON for entry in entries
]
_PRIORITY: dict[str, int] = {emo: i for i, (emo, _) in enumerate(AUTO_LEXICON)}


def _find_negator(s: str, tokens: list[re.Match[str]], end: int) -> tuple[int, int] | None:
    """Eşleşmeden sonraki en çok NEGATION_WINDOW sözcükte (virgül/cümle sınırı aşılmadan) olumsuzluk sözcüğü
    (değil, yok, asla, hiç) varsa onun konumunu döndürür. "değil mi?" onay sorusu ve "yok artık" / "yok ya"
    ünlemi olumsuzluk sayılmaz."""
    after = [t for t in tokens if t.start() >= end]
    for i, tok in enumerate(after[:NEGATION_WINDOW]):
        if _CLAUSE_BREAK_RE.search(s, end, tok.start()):
            return None
        word = tok.group()
        if not _NEGATION_RE.match(word):
            continue
        nxt = after[i + 1].group() if i + 1 < len(after) else ""
        if word.startswith("değil") and _QUESTION_PARTICLE_RE.match(nxt):
            continue
        if word == "yok" and nxt in ("artık", "ya"):
            continue
        return tok.span()
    return None


def _score(sentence: str) -> tuple[dict[str, int], dict[str, int]]:
    """Döndürür: (toplam puanlar, yalnızca sözlükten gelen puanlar). Eşitlikte sözlük kanıtı öne geçer."""
    if not sentence or not sentence.strip():
        return {}, {}
    s = tr_lower(sentence)
    tokens = list(_WORD_TOKEN_RE.finditer(s))
    found = [(m.start(), m.end(), emo, w) for emo, pat, w in _LEX_PATTERNS for m in pat.finditer(s)]
    found.sort(key=lambda f: (f[0] - f[1], f[0], _PRIORITY[f[2]]))      # en uzun eşleşme önce
    accepted: list[tuple[int, int, str, int]] = []
    for f in found:
        if not any(f[0] < e and b < f[1] for b, e, _, _ in accepted):
            accepted.append(f)
    negators = {(b, e): _find_negator(s, tokens, e) for b, e, _, _ in accepted}
    used_negators = {span for span in negators.values() if span}
    exclaim = "!" in s
    lex: dict[str, int] = {}
    for b, e, emo, weight in accepted:
        if (b, e) in used_negators:        # başka bir sözcüğü olumsuzlayan "asla" kendi başına puan almaz
            continue
        if negators[(b, e)]:
            if emo in _POSITIVE_EMOTIONS:  # "hiç güzel değil" → üzgün, "harika değil!" → kızgın
                target = "kızgın" if exclaim else "üzgün"
                lex[target] = lex.get(target, 0) + 1
            continue
        lex[emo] = lex.get(emo, 0) + weight
    scores = dict(lex)
    letters = [ch for ch in sentence if ch.isalpha()]
    if len(letters) >= CAPS_MIN_LETTERS and sum(ch.isupper() for ch in letters) / len(letters) > CAPS_RATIO:
        for emo in ("kızgın", "heyecanlı"):
            scores[emo] = scores.get(emo, 0) + 2
    if exclaim:
        for emo in ("heyecanlı", "kızgın", "şaşkın", "mutlu"):
            if emo in scores:
                scores[emo] += 1
        if not scores:
            scores["heyecanlı"] = 1
    if "?!" in s or "!?" in s:
        scores["şaşkın"] = scores.get("şaşkın", 0) + 2
    if "?" in s and "şaşkın" in scores:
        scores["şaşkın"] += 1
    if "..." in s or "…" in s:
        for emo in ("üzgün", "sakin"):
            if emo in scores:
                scores[emo] += 1
    return scores, lex


def _rank_key(scores: dict[str, int], lex: dict[str, int]):
    return lambda emo: (scores[emo], lex.get(emo, 0), -_PRIORITY.get(emo, len(_PRIORITY)))


def infer_emotion_scores(sentence: str) -> dict[str, int]:
    """Her aday duygunun puanı (büyükten küçüğe; ilk anahtar = infer_emotion sonucu). Aday yoksa {}."""
    scores, lex = _score(sentence)
    key = _rank_key(scores, lex)
    return {emo: scores[emo] for emo in sorted(scores, key=key, reverse=True)}


def infer_emotion(sentence: str) -> str | None:
    """Cümle içeriğinden ve noktalamadan basit duygu tahmini. Emin değilse None."""
    scores, lex = _score(sentence)
    if not scores:
        return None
    return max(scores, key=_rank_key(scores, lex))


# ---------- ses işleme (ffmpeg) ----------

FFMPEG_TIMEOUT_S = 300


def _has_rubberband() -> bool:
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, timeout=10).stdout
        return " rubberband " in out
    except Exception:  # noqa: BLE001
        return False


_RB: bool | None = None


def _rb() -> bool:
    global _RB
    if _RB is None:
        _RB = shutil.which("ffmpeg") is not None and _has_rubberband()
    return _RB


def _ffmpeg_filter(wav: np.ndarray, sr: int, afilter: str) -> np.ndarray:
    """ffmpeg ses filtresi uygular. ffmpeg yoksa, filtre boşsa ya da ffmpeg hata verirse (check=True, zaman aşımı,
    okunamayan çıktı) uyarı yazar ve girdiyi değiştirmeden döndürür: duygu işleme üretimi hiçbir zaman düşürmemeli."""
    if not afilter or not shutil.which("ffmpeg"):
        return wav
    try:
        with tempfile.TemporaryDirectory() as td:
            src, dst = Path(td) / "in.wav", Path(td) / "out.wav"
            sf.write(str(src), np.asarray(wav, dtype=np.float32), sr)
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-filter:a", afilter, "-ar", str(sr), str(dst)],
                check=True, capture_output=True, timeout=FFMPEG_TIMEOUT_S,
            )
            out, _ = sf.read(str(dst), dtype="float32", always_2d=False)
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or b"").decode("utf-8", "replace").strip()[:300] or f"çıkış kodu {e.returncode}"
        log.warning("ffmpeg filtresi başarısız (%s): %s — işlenmemiş ses kullanılıyor", afilter[:120], detail)
        return wav
    except Exception as e:  # noqa: BLE001 — zaman aşımı, dosya/soundfile hataları
        log.warning("ffmpeg filtresi uygulanamadı (%s): %s — işlenmemiş ses kullanılıyor", afilter[:120], e)
        return wav
    return np.asarray(out, dtype=np.float32).squeeze()


def pitch_tempo_filter(sr: int, semitones: float = 0.0, tempo: float = 1.0) -> str:
    """Perde (yarım ton) ve tempoyu bağımsız değiştiren ffmpeg filtre dizesi."""
    parts = []
    if _rb() and (abs(semitones) > 0.01 or abs(tempo - 1) > 0.005):
        parts.append(f"rubberband=pitch={2 ** (semitones / 12):.5f}:tempo={tempo:.4f}:pitchq=quality")
    else:
        if abs(semitones) > 0.01:
            ratio = 2 ** (semitones / 12)
            parts.append(f"asetrate={int(sr * ratio)},aresample={sr},atempo={1 / ratio:.5f}")
        if abs(tempo - 1) > 0.005:
            parts.append(f"atempo={tempo:.4f}")
    return ",".join(parts)


def breathy_filter(level_db: float = -24.0) -> str:
    """Nefesli/fısıltı tınısı: alçakları kes, 2–6 kHz'i hafif yükselt."""
    return "highpass=f=160,equalizer=f=3500:t=q:w=1.2:g=4,treble=g=3:f=5000"


def derive_reference(src: Path, dst: Path, profile: EmotionProfile, sr: int) -> Path:
    """Nötr referanstan duyguya özgü referans üretir (perde/tempo/kazanç/nefes).
    ffmpeg başarısız olursa uyarı yazılır ve işlenmemiş (yalnızca tepe sınırlı) kopya kullanılır."""
    wav, file_sr = sf.read(str(src), dtype="float32", always_2d=False)
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    filters = []
    pt = pitch_tempo_filter(file_sr, profile.ref_pitch, profile.ref_tempo)
    if pt:
        filters.append(pt)
    if profile.ref_breathy:
        filters.append(breathy_filter())
    if abs(profile.ref_gain_db) > 0.1:
        filters.append(f"volume={profile.ref_gain_db:+.1f}dB")
    out = _ffmpeg_filter(wav, file_sr, ",".join(filters)) if filters else wav
    if filters and out is wav and shutil.which("ffmpeg"):
        log.warning("Duygu referansı türetilemedi (%s); nötr kayıt kopyalanıyor", profile.name)
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 0.98:
        out = out * (0.98 / peak)
    dst.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(dst), out, file_sr)
    return dst


def whisperize(wav: np.ndarray, sr: int, mix: float = 1.0, order: int = 24, frame_ms: int = 25, hop_ms: int = 10) -> np.ndarray:
    """Konuşmayı fısıltıya çevirir: her karede LPC ile ses yolu zarfı çıkarılır, periyodik uyarım yerine
    gürültü ile yeniden sentezlenir (ses telleri titreşmiyormuş gibi). mix=1 tam fısıltı, 0.5 yarı nefesli."""
    import librosa
    from scipy.signal import lfilter

    x = np.asarray(wav, dtype=np.float64)
    if x.size < sr // 10:
        return wav
    frame = int(sr * frame_ms / 1000)
    hop = int(sr * hop_ms / 1000)
    pre = np.append(x[0], x[1:] - 0.97 * x[:-1])          # pre-emphasis
    win = np.hanning(frame)
    out = np.zeros(len(x) + frame)
    norm = np.zeros(len(x) + frame)
    rng = np.random.default_rng(7)
    for start in range(0, len(x) - frame, hop):
        seg = pre[start:start + frame] * win
        energy = np.sqrt(np.mean(seg ** 2)) + 1e-9
        if energy < 1e-4:
            continue
        try:
            a = librosa.lpc(seg, order=order)
        except Exception:  # noqa: BLE001
            continue
        noise = rng.standard_normal(frame)
        synth = lfilter([1.0], a, noise)
        if not np.all(np.isfinite(synth)):
            continue
        synth *= energy / (np.sqrt(np.mean(synth ** 2)) + 1e-9)
        out[start:start + frame] += synth * win
        norm[start:start + frame] += win ** 2
    norm[norm < 1e-6] = 1.0
    y = out[: len(x)] / norm[: len(x)]
    y = lfilter([1.0], [1.0, -0.97], y)                    # de-emphasis
    # Fısıltıda alçak frekans yoktur; tipik fısıltı spektrumu için yüksek geçiren + hafif tiz
    y = _ffmpeg_filter(y.astype(np.float32), sr, "highpass=f=250,treble=g=2:f=4000,lowpass=f=9000")
    y = y[: len(x)] if len(y) >= len(x) else np.pad(y, (0, len(x) - len(y)))
    # Orijinalin RMS zarfını koru (hece vurgusu kaybolmasın)
    env_x = _envelope(x, sr)
    env_y = _envelope(y, sr) + 1e-6
    y = y * np.clip(env_x / env_y, 0, 10)
    hp_orig = _ffmpeg_filter(np.asarray(wav, dtype=np.float32), sr, "highpass=f=1200")
    hp_orig = hp_orig[: len(x)] if len(hp_orig) >= len(x) else np.pad(hp_orig, (0, len(x) - len(hp_orig)))
    res = mix * y + (1 - mix) * np.asarray(wav, dtype=np.float64) + 0.15 * hp_orig  # biraz tıslama ayrıntısı
    peak = np.max(np.abs(res)) + 1e-9
    target = np.max(np.abs(x)) + 1e-9
    return (res * (target / peak)).astype(np.float32)


def _envelope(x: np.ndarray, sr: int, ms: int = 20) -> np.ndarray:
    n = max(1, int(sr * ms / 1000))
    kernel = np.ones(n) / n
    return np.sqrt(np.convolve(np.asarray(x, dtype=np.float64) ** 2, kernel, mode="same") + 1e-12)


FX_LEVELS = ("off", "light", "full")


def post_process(wav: np.ndarray, sr: int, profile: EmotionProfile | None, fx: str = "off") -> np.ndarray:
    """Üretilen parçaya duyguya göre çıktı işleme uygular (hız hariç; o ayrı uygulanır).

    fx="off"  : işleme yok (en doğal; fısıltı yalnızca kısılır ve alçaklar kesilir)
    fx="light": kazanç + fısıltı/kızgın için hafif tını
    fx="full" : perde kaydırma, sıkıştırma, nefesli tını, LPC fısıltı dönüşümü (deneysel)
    ffmpeg hatasında uyarı yazılır ve parça işlenmeden döner.
    """
    if profile is None:
        return wav
    if fx == "off":
        if profile.name == "fısıltı":
            try:
                return _ffmpeg_filter(wav, sr, "highpass=f=150,volume=-7dB")
            except Exception as e:  # noqa: BLE001
                log.warning("Fısıltı işleme atlandı: %s", e)
                return wav
        return wav
    if fx == "light":
        filters = []
        if abs(profile.out_gain_db) > 0.1:
            filters.append(f"volume={profile.out_gain_db:+.1f}dB")
        if profile.name == "fısıltı":
            filters.append("highpass=f=180,treble=g=2:f=4000")
        if not filters:
            return wav
        try:
            return _ffmpeg_filter(wav, sr, ",".join(filters))
        except Exception as e:  # noqa: BLE001
            log.warning("Duygu çıktı işleme (light) atlandı: %s", e)
            return wav
    if profile.whisper_mix > 0:
        try:
            wav = whisperize(wav, sr, mix=profile.whisper_mix)
        except Exception as e:  # noqa: BLE001
            log.warning("Fısıltı dönüşümü atlandı: %s", e)
    filters = []
    if abs(profile.out_pitch) > 0.01:
        filters.append(pitch_tempo_filter(sr, profile.out_pitch, 1.0))
    if profile.highpass_hz:
        filters.append(f"highpass=f={profile.highpass_hz}")
    if profile.breathy:
        filters.append(breathy_filter())
    if profile.compress:
        filters.append("acompressor=threshold=-18dB:ratio=3:attack=10:release=120:makeup=2")
    if abs(profile.out_gain_db) > 0.1:
        filters.append(f"volume={profile.out_gain_db:+.1f}dB")
    filters = [f for f in filters if f]
    if not filters:
        return wav
    try:
        return _ffmpeg_filter(wav, sr, ",".join(filters))
    except Exception as e:  # noqa: BLE001
        log.warning("Duygu çıktı işleme atlandı: %s", e)
        return wav


# ---------- etiket ayrıştırma ----------

_TAG_RE = re.compile(r"\[([^\[\]]{1,600})\]")
SIMPLE_TAG_MAX = 40            # iki noktasız etiketin en uzun hali; daha uzun köşeli parantez metin olarak kalır
_SCOPE_LABEL_MAX = 30          # "[etiket: metin]" biçiminde etiket kısmının en uzun hali
_REPEAT3_RE = re.compile(r"(.)\1{2,}")      # "hmmm" → "hmm", "offf" → "off"
_REPEAT2_RE = re.compile(r"(.)\1+")         # "tühh" → "tüh"
_LAUGH_RE = re.compile(r"^(?:ha){2,}h?$")   # "hahahaha"
_GIGGLE_RE = re.compile(r"^(?:hi){2,}h?$")  # "hihihi"
# *sözcük* / **kısa öbek** — "2*3*4" ya da "* madde" gibi kullanımlar eşleşmez
_EMPH_RE = re.compile(r"(?<![\w*])(\*{1,2})(?=[^\s*])([^*\n]{1,60}?)(?<=[^\s*])\1(?![\w*])")
_FIRST_WORD_RE = re.compile(r"^[\s\"'«“‘(]*([^\s.,!?;:…\"'«»“”‘’()\[\]]+)")


@dataclass
class Segment:
    text: str
    emotion: str | None          # profil adı
    pause_before_ms: int = 0     # bölüm başındaki ek duraklama
    pause_after_ms: int = 0
    emphasis_words: list[str] = field(default_factory=list)   # vurgulanan sözcük/öbekler (metindeki biçimiyle)
    # keep_nonverbal=True iken sözsüz bölümün kanonik anahtarı ("gülme"); o zaman text "" olur
    nonverbal: str | None = None
    intensity: float = 1.0       # duygu yoğunluğu (0.5–1.6); effective_profile'a verilir
    blend: list[str] = field(default_factory=list)            # ikincil duygular ("[üzgün+umutlu]" → ["umutlu"])
    rate: float | None = None    # "[hız:0.9]" (0.7–1.3); None = değişiklik yok
    pitch: float | None = None   # "[perde:+1]" yarım ton (−4…+4); None = değişiklik yok
    speaker: str | None = None   # "[ses:Ayşe]" — yalnızca ayrıştırılır, ses eşlemesi motorda
    # "[sakinleşerek]" / "[heyecanlı→sakin]": bölüm boyunca bu duyguya kayış ("normal" da olabilir). Önerilen
    # kullanım: başlangıç effective_profile(emotion, intensity, blend), bitiş effective_profile(arc_to, intensity),
    # aradaki cümleler interpolate_profile(başlangıç, bitiş, i / (n - 1)).
    arc_to: str | None = None
    nonverbal_reads: str = ""          # keep_nonverbal=True iken ham etiketin kendi okunuşu ("[hı hı]" → "Hı hı.")


# ---------- yoğunluk, karışım, kayış ve satır içi kontroller ----------

INTENSITY_MIN, INTENSITY_MAX = 0.5, 1.6
INTENSITY_LEVELS: dict[int, float] = {1: 0.7, 2: 1.0, 3: 1.4}          # "[heyecanlı:1]" … "[heyecanlı:3]"
# "[biraz üzgün]", "[çok kızgın]"… (önek sözcükler; ASCII yazım da tanınır: "cok", "asiri")
INTENSITY_WORDS: dict[str, float] = {
    "biraz": 0.65, "hafif": 0.65, "az": 0.65, "birazcık": 0.65, "azıcık": 0.65, "hafifçe": 0.65,
    "slightly": 0.65, "a bit": 0.65,
    "çok": 1.35, "epey": 1.35, "oldukça": 1.35, "very": 1.35,
    "aşırı": 1.6, "çok çok": 1.6, "son derece": 1.6, "extremely": 1.6,
}
_QUALIFIERS = sorted(INTENSITY_WORDS.items(), key=lambda kv: -len(kv[0]))    # en uzun önce ("çok çok" > "çok")
MAX_BLEND = 2                     # "[üzgün+umutlu+sakin]" → en çok 2 ikincil
BLEND_SECONDARY_WEIGHT = 0.3      # ikincillerin toplam payı (birincil %70)
# Tek sözcüklük kayış etiketleri → hedef duygu (kaynak: o anki duygu)
ARC_WORDS: dict[str, str] = {
    "sakinleşerek": "sakin", "heyecanlanarak": "heyecanlı", "yumuşayarak": "samimi", "sertleşerek": "kızgın",
    "hüzünlenerek": "üzgün", "neşelenerek": "mutlu", "ciddileşerek": "ciddi",
}
_ARC_FOLD: dict[str, str] = {fold_ascii(k): v for k, v in ARC_WORDS.items()}
RATE_MIN, RATE_MAX = 0.7, 1.3     # "[hız:0.9]"; aralık dışı değer yok sayılır
PITCH_MIN, PITCH_MAX = -4.0, 4.0  # "[perde:+1]" yarım ton; aralık dışı değer yok sayılır
SPEAKER_NAME_MAX = 40
# kontrol etiketi adı → Segment alanı (ASCII yazımla eşleşir: "hiz", "konusmaci")
_CONTROL_LABELS: dict[str, str] = {
    "hız": "rate", "tempo": "rate", "perde": "pitch", "pitch": "pitch", "ses": "speaker", "konuşmacı": "speaker",
}
_CONTROL_FOLD: dict[str, str] = {fold_ascii(k): v for k, v in _CONTROL_LABELS.items()}
_RESET_WORDS = frozenset({"normal", "varsayilan", "default", "sifirla"})        # ASCII karşılıklarıyla
_NUM = r"(\d+(?:[.,]\d+)?|[.,]\d+)"
_RATE_RE = re.compile(r"^[x×]?\s*" + _NUM + r"\s*[x×]?$", re.IGNORECASE)    # "0.9", "0,9", "1.1x"
_RATE_PCT_RE = re.compile(r"^(?:%\s*" + _NUM + r"|" + _NUM + r"\s*%)$")       # "%90", "90%"
_PITCH_RE = re.compile(r"^([+\-−–]?)\s*" + _NUM + r"$")                         # "+1", "-2", "−1,5"
_SPEAKER_RE = re.compile(r"^[\w .'’\-]+$")
_LEVEL_RE = re.compile(r"^(?P<body>[^:]+?)\s*:\s*(?P<level>[1-3])$")
_PCT_TAIL_RE = re.compile(r"^(?P<body>[^%:]+?)\s*:?\s*(?:%\s*(?P<a>\d{1,3})|(?P<b>\d{1,3})\s*%)$")
_PCT_HEAD_RE = re.compile(r"^(?:%\s*(?P<a>\d{1,3})|(?P<b>\d{1,3})\s*%)\s*(?P<body>[^%:]+)$")
_ARROW_RE = re.compile(r"\s*(?:->|=>|→|⟶|>)\s*")
_PLUS_RE = re.compile(r"\s*\+\s*")


@dataclass
class _EmotionExpr:
    """Ayrıştırılmış duygu ifadesi: "[çok üzgün+umutlu]", "[heyecanlı→sakin]", "[sakinleşerek]"…"""
    emotion: str | None = None         # profil adı ("normal" dahil); keep_current iken kullanılmaz
    intensity: float | None = None     # None: yazılmadı (yeni duyguda 1.0, kayışta o anki yoğunluk)
    blend: list[str] = field(default_factory=list)
    arc_to: str | None = None
    nonverbal_reads: str = ""          # keep_nonverbal=True iken ham etiketin kendi okunuşu ("[hı hı]" → "Hı hı.")
    keep_current: bool = False         # kaynak duygu o anki duygudur ("[sakinleşerek]", "[→sakin]")


@dataclass
class _State:
    """Ayrıştırıcının sürekli ("sticky") durumu: etiketler bir sonraki değişikliğe kadar geçerlidir."""
    emotion: str | None = None
    intensity: float = 1.0
    blend: list[str] = field(default_factory=list)
    arc_to: str | None = None
    nonverbal_reads: str = ""          # keep_nonverbal=True iken ham etiketin kendi okunuşu ("[hı hı]" → "Hı hı.")          # bekleyen kayış: bir sonraki metin bölümüne uygulanır
    rate: float | None = None
    pitch: float | None = None
    speaker: str | None = None

    def segment(self, text: str, pause_before_ms: int, words, nonverbal: str | None = None) -> Segment:
        return Segment(text, self.emotion, pause_before_ms, 0, list(words), nonverbal, self.intensity,
                       list(self.blend), self.rate, self.pitch, self.speaker, None if nonverbal else self.arc_to)

    def with_emotion(self, name: str) -> "_State":
        """Düz duygu etiketi: yoğunluk, karışım ve bekleyen kayış sıfırlanır."""
        return replace(self, emotion=None if name == "normal" else name, intensity=1.0, blend=[], arc_to=None)

    def with_expr(self, e: _EmotionExpr) -> "_State":
        if e.keep_current:
            st = replace(self, blend=list(self.blend), arc_to=e.arc_to,
                         intensity=self.intensity if e.intensity is None else e.intensity)
        else:
            st = replace(self, emotion=None if e.emotion == "normal" else e.emotion, blend=list(e.blend),
                         intensity=1.0 if e.intensity is None else e.intensity, arc_to=e.arc_to)
        if st.arc_to is not None and st.arc_to == (st.emotion or "normal") and not st.blend:
            st.arc_to = None                       # aynı duyguya kayış etkisizdir
        return st

    def settle(self) -> None:
        """Kayışlı bölüm yazıldıktan sonra ses hedef duyguda kalır (yoğunluk korunur, karışım biter)."""
        if self.arc_to is not None:
            self.emotion = None if self.arc_to == "normal" else self.arc_to
            self.blend = []
            self.arc_to = None


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _match_nonverbal(raw: str) -> str | None:
    """Sözsüz etiketin NONVERBAL'daki anahtarı; _classify_simple ile aynı sırayla arar (birebir, harf tekrarı
    sadeleştirilmiş, en son ASCII): "HMMM" → "hmm", "gulme" → "gülme", "hahahaha" → "gülme"."""
    variants = _tag_variants(raw)
    for k in variants:
        if k in NONVERBAL:
            return k
        if _LAUGH_RE.match(k):
            return "gülme"
        if _GIGGLE_RE.match(k):
            return "kıkırdama"
    for k in variants:
        f = fold_ascii(k)
        if f in _NONVERBAL_FOLD:
            return _NONVERBAL_FOLD[f]
        if _LAUGH_RE.match(f):
            return "gülme"
        if _GIGGLE_RE.match(f):
            return "kıkırdama"
    return None


def nonverbal_key(tag: str | None) -> str | None:
    """Sözsüz etiketi ya da eş adını kanonik Türkçe ada çevirir: "laughs" → "gülme", "Kahkaha atar" → "kahkaha",
    "hıhı" → "hıh", "SIGHS" → "iç çekme". Ses üretmeyen ([nefes]) ya da sözsüz olmayan etiket → None."""
    if tag is None or not str(tag).strip():
        return None
    k = _match_nonverbal(str(tag).strip())
    return NONVERBAL_CANON.get(k) if k else None


def nonverbal_fallback(key: str) -> str:
    """Kanonik adın (ya da herhangi bir eş adın) yedek okunuşu — gerçek tepki kaydı yoksa seslendirilecek metin:
    "gülme" → "Hahaha!", "iç çekme" → "Ahh...". Tanınmayan anahtar → ""."""
    canon = nonverbal_key(key)
    return NONVERBAL.get(canon, "") if canon else ""


def _arc_target(raw: str) -> str | None:
    """Tek sözcüklük kayış etiketi ("sakinleşerek", "SAKİNLEŞEREK", "sakinleserek") → hedef duygu."""
    for k in _key_variants(raw):
        if k in ARC_WORDS:
            return ARC_WORDS[k]
        f = fold_ascii(k)
        if f in _ARC_FOLD:
            return _ARC_FOLD[f]
    return None


def _strip_qualifier(s: str) -> tuple[float | None, str]:
    """Baştaki yoğunluk sözcüğünü ayırır: "çok üzgün" → (1.35, "üzgün"); yoksa (None, s)."""
    folded = fold_ascii(s)                 # fold_ascii harf sayısını değiştirmez; dilimleme güvenli
    for word, value in _QUALIFIERS:
        prefix = fold_ascii(word) + " "
        if folded.startswith(prefix):
            return value, s[len(prefix):].strip()
    return None, s


def _resolve_part(part: str) -> str | None:
    """Karışım/kayış parçası → profil adı; parçadaki yoğunluk sözcüğü yok sayılır ("biraz umutlu" → "umutlu")."""
    p = part.strip()
    if not p:
        return None
    prof = resolve(p)
    if prof is None:
        q, rest = _strip_qualifier(p)
        if q is not None:
            prof = resolve(rest)
    return prof.name if prof is not None else None


def _parse_blend(s: str) -> tuple[str, list[str]] | None:
    """"üzgün+umutlu" → ("üzgün", ["umutlu"]). Bilinmeyen ve yinelenen parçalar atılır; en çok MAX_BLEND ikincil."""
    names: list[str] = []
    for part in _PLUS_RE.split(s):
        n = _resolve_part(part)
        if n is not None and n not in names:
            names.append(n)
    if not names:
        return None
    return names[0], names[1:1 + MAX_BLEND]


def _parse_emotion_expr(raw: str) -> _EmotionExpr | None:
    """Yoğunluk / karışım / kayış içeren duygu ifadesi; ifade değilse None.

    "heyecanlı:3", "heyecanlı %150", "%120 heyecanlı", "çok üzgün", "üzgün + umutlu", "heyecanlı→sakin",
    "heyecanlı -> sakin", "→sakin", "sakinleşerek". Yoğunluk sözcüğü ile sayı birlikte yazılırsa çarpılır.
    Kayışın bilinmeyen tarafı atılır: kaynak bilinmiyorsa o anki duygudan, hedef bilinmiyorsa kayışsız.
    "İki nokta" yalnızca seviye son ekinde geçebilir; "[duygu: metin]" kapsamlı etiketiyle karışmaz."""
    s = _norm_key(raw)
    if not s:
        return None
    level: float | None = None
    m = _LEVEL_RE.match(s)
    if m:
        s, level = m["body"].strip(), INTENSITY_LEVELS[int(m["level"])]
    else:
        m = _PCT_TAIL_RE.match(s) or _PCT_HEAD_RE.match(s)
        if m:
            pct = int(m["a"] or m["b"])
            s, level = m["body"].strip(), _clamp(pct / 100.0, INTENSITY_MIN, INTENSITY_MAX)
    if not s or ":" in s or "%" in s:
        return None
    q, s = _strip_qualifier(s)
    intensity = level
    if q is not None:
        intensity = q if level is None else round(_clamp(q * level, INTENSITY_MIN, INTENSITY_MAX), 4)
    if not s:
        return None
    parts = _ARROW_RE.split(s)
    if len(parts) > 1:
        src = _parse_blend(parts[0]) if parts[0].strip() else None
        dst = _resolve_part(parts[-1])
        if src is None and dst is None:
            return None
        if src is None:
            return _EmotionExpr(intensity=intensity, arc_to=dst, keep_current=True)
        return _EmotionExpr(src[0], intensity, src[1], dst)
    arc = _arc_target(s)
    if arc is not None:
        return _EmotionExpr(intensity=intensity, arc_to=arc, keep_current=True)
    src = _parse_blend(s)
    if src is None:
        return None
    return _EmotionExpr(src[0], intensity, src[1])


def _parse_rate(value: str) -> float | None:
    m = _RATE_RE.match(value)
    if m:
        r = float(m.group(1).replace(",", "."))
    else:
        m = _RATE_PCT_RE.match(value)
        if not m:
            return None
        r = float((m.group(1) or m.group(2)).replace(",", ".")) / 100.0
    return round(r, 4) if RATE_MIN <= r <= RATE_MAX else None


def _parse_pitch(value: str) -> float | None:
    m = _PITCH_RE.match(value)
    if not m:
        return None
    p = float(m.group(2).replace(",", "."))
    if m.group(1) and m.group(1) != "+":
        p = -p
    return round(p, 4) + 0.0 if PITCH_MIN <= p <= PITCH_MAX else None     # +0.0: "-0" → 0.0


def _parse_control(stripped: str) -> tuple[str, object] | None:
    """"hız:0.9" → ("rate", 0.9), "perde:+1" → ("pitch", 1.0), "ses: Ayşe" → ("speaker", "Ayşe");
    "hız", "hız:normal", "ses" → (alan, None) yani sıfırla. Ad kontrol etiketi değilse ya da değer geçersiz /
    aralık dışıysa None (etiket eski kurallarla sınıflanır, sonuçta yok sayılır)."""
    label, _, value = stripped.partition(":")
    kind = _CONTROL_FOLD.get(fold_ascii(_norm_key(label)))
    if kind is None:
        return None
    value = value.strip()
    if kind == "speaker":
        if not value:
            return "speaker", None
        name = re.sub(r"\s+", " ", value)
        if len(name) <= SPEAKER_NAME_MAX and _SPEAKER_RE.match(name):
            return "speaker", name                 # ad yazıldığı gibi (büyük/küçük harf korunur)
        return None
    if not value or fold_ascii(_norm_key(value)) in _RESET_WORDS:
        return kind, None
    num = _parse_rate(value) if kind == "rate" else _parse_pitch(value)
    return (kind, num) if num is not None else None


def _extract_emphasis(text: str) -> tuple[str, list[str]]:
    """"Bu *çok* önemli" → ("Bu çok önemli", ["çok"]). Yıldızlar silinir, sözcük olduğu gibi kalır: büyük harfe
    çevirmek modelin harf harf okumasına yol açabilir; vurguyu motor emphasis_words ile uygular."""
    found: list[str] = []

    def repl(m: re.Match[str]) -> str:
        phrase = m.group(2).strip()
        found.append(phrase)
        return phrase

    return _EMPH_RE.sub(repl, text), found


def _tag_variants(raw: str) -> list[str]:
    out: list[str] = []
    for k in _key_variants(raw):
        for v in (k, _REPEAT3_RE.sub(r"\1\1", k), _REPEAT2_RE.sub(r"\1", k)):
            if v and v not in out:
                out.append(v)
    return out


def _classify_simple(raw: str) -> tuple[str, object] | None:
    """İki noktasız etiket: duraklama / sayılı duraklama / sözsüz / vurgu / duygu. Önce birebir anahtar, sonra
    harf tekrarı sadeleştirilmiş ("hmmm"), en son ASCII karşılığı ("gulme") denenir."""
    variants = _tag_variants(raw)
    for k in variants:
        if k in PAUSE_TAGS:
            return "pause", PAUSE_TAGS[k]
        ms = timed_pause_ms(k)
        if ms is not None:
            return "pause", ms
        if k in NONVERBAL:
            return "nonverbal", NONVERBAL[k]
        if _LAUGH_RE.match(k):
            return "nonverbal", "Hahaha!"
        if _GIGGLE_RE.match(k):
            return "nonverbal", "Hihihi!"
        if k in EMPHASIS_TAGS:
            return "emphasis", None
        if k in ALIAS_TO_NAME:
            return "emotion", ALIAS_TO_NAME[k]
    for k in variants:
        f = fold_ascii(k)
        if f in _PAUSE_FOLD:
            return "pause", PAUSE_TAGS[_PAUSE_FOLD[f]]
        if f in _NONVERBAL_FOLD:
            return "nonverbal", NONVERBAL[_NONVERBAL_FOLD[f]]
        if _LAUGH_RE.match(f):
            return "nonverbal", "Hahaha!"
        if _GIGGLE_RE.match(f):
            return "nonverbal", "Hihihi!"
        if f in _ALIAS_FOLD:
            return "emotion", _ALIAS_FOLD[f]
    return None


def _classify_tag(inner: str) -> tuple[str, object]:
    """Döndürür: (tür, değer). Türler: pause, nonverbal (değer: okunuş), emphasis, emotion, scoped_emotion,
    scoped_emphasis, expr (_EmotionExpr: yoğunluk / karışım / kayış), scoped_expr ((_EmotionExpr, metin)),
    rate / pitch / speaker (değer None = sıfırla), unknown (yok sayılır), text (etiket değil; uzun köşeli parantez
    metni olduğu gibi kalır). Eski etiketlerin sınıfı değişmez; istisnalar sözleşme gereği: "[fısıldayarak]" artık
    kayıştır (kapsamlı "[fısıldayarak: …]" eskisi gibi fısıltı) ve "[duygu:1]"…"[duygu:3]" artık yoğunluktur
    (eskiden "1" metni okunurdu)."""
    stripped = inner.strip()
    if not stripped:
        return "unknown", None
    control = _parse_control(stripped)
    if control is not None:
        return control
    if len(stripped) <= SIMPLE_TAG_MAX:
        arc = _arc_target(stripped)
        if arc is not None:
            return "expr", _EmotionExpr(arc_to=arc, keep_current=True)
        hit = _classify_simple(stripped)
        if hit is not None:
            return hit
        expr = _parse_emotion_expr(stripped)
        if expr is not None:
            return "expr", expr
    label, sep, body = stripped.partition(":")
    if sep and body.strip() and 0 < len(label.strip()) <= _SCOPE_LABEL_MAX:
        if any(k in EMPHASIS_TAGS for k in _key_variants(label)):
            return "scoped_emphasis", body.strip()
        prof = resolve(label)
        if prof is not None:            # "[fısıldayarak: …]" eskisi gibi kapsamlı fısıltıdır
            return "scoped_emotion", (prof.name, body.strip())
        expr = _parse_emotion_expr(label)
        if expr is not None:
            return "scoped_expr", (expr, body.strip())
    return ("unknown", None) if len(stripped) <= SIMPLE_TAG_MAX else ("text", None)


def parse_tagged_text(text: str, keep_nonverbal: bool = False) -> list[Segment]:
    """Metni [duygu]/[duraklama]/[kontrol] sınırlarından bölümlere ayırır.

    - "[heyecanlı] …" sonraki duygu etiketine kadar geçerlidir; "[heyecanlı: …]" yalnızca parantez içine uygulanır.
      Yoğunluk ("[heyecanlı:3]", "[çok üzgün]", "[kızgın %120]"), karışım ("[üzgün+umutlu]") ve kayış
      ("[heyecanlı→sakin]", "[sakinleşerek]") hem sürekli hem kapsamlı ("[çok heyecanlı: …]") yazılabilir.
    - Kayış, etiketten sonraki ilk metin bölümüne uygulanır (Segment.arc_to); bölüm bitince ses hedef duyguda kalır
      (sonraki bölümler emotion=hedef). Tek sözcüklü biçimlerde ve "[→sakin]"de kaynak o anki duygudur.
    - "[hız:0.9]", "[perde:+1]", "[ses:Ayşe]" yeni bölüm başlatır ve duygudan bağımsız olarak süreklidir;
      "[hız]" / "[hız:normal]" (perde ve ses için de) sıfırlar. Aralık dışı değer yok sayılır.
    - Sözsüz etiketler ([gülme] → "Hahaha!") varsayılan olarak akan metne satır içi eklenir ki model onları cümle
      bağlamında üretsin (tek başına halüsinasyon yapıyor). keep_nonverbal=True iken metne gömülmez: önceki metin
      kapatılır ve Segment(text="", nonverbal=<kanonik ad>, o anki duygu/konuşmacı…) ayrı bölüm olarak eklenir;
      motor varsa sesin gerçek tepki kaydını, yoksa nonverbal_fallback(ad) okunuşunu kullanır.
    - Duraklamalar ([nefes], [1.5 sn]…) sonraki bölümün pause_before_ms'ine, metin sonundaysa son bölümün
      pause_after_ms'ine eklenir.
    - "*sözcük*", "[vurgu] sözcük", "[vurgu: öbek]" → yıldızlar silinir, Segment.emphasis_words dolar.
    - Tanınmayan kısa etiket sessizce yok sayılır (ElevenLabs de bilinmeyenleri yok sayar).
    """
    segments: list[Segment] = []
    st = _State()
    pending_pause = 0
    buf: list[str] = []
    emph: list[str] = []
    emph_next = False
    pos = 0

    def add_text(chunk: str) -> None:
        nonlocal emph_next
        if not chunk:
            return
        clean, found = _extract_emphasis(chunk)
        if emph_next:
            m = _FIRST_WORD_RE.match(clean)
            if m:
                found.insert(0, m.group(1))
                emph_next = False
        buf.append(clean)
        emph.extend(found)

    def flush(state: _State) -> None:
        """Biriken metni state ile bölüm yapar; bekleyen kayış bu bölüme uygulanıp hedef duyguda sabitlenir."""
        nonlocal pending_pause
        t = " ".join(x.strip() for x in buf if x.strip()).strip()
        buf.clear()
        if t:
            segments.append(state.segment(t, pending_pause, dict.fromkeys(w for w in emph if w)))
            pending_pause = 0
            state.settle()
        emph.clear()

    for m in _TAG_RE.finditer(text):
        add_text(text[pos:m.start()])
        pos = m.end()
        kind, value = _classify_tag(m.group(1))
        if kind == "pause":
            flush(st)
            pending_pause += int(value)  # type: ignore[arg-type]
        elif kind == "nonverbal":
            key = nonverbal_key(m.group(1)) if keep_nonverbal else None
            if key:
                flush(st)
                seg = st.segment("", pending_pause, (), nonverbal=key)
                seg.nonverbal_reads = str(value or "")          # eş adın kendi okunuşu (kayıt yoksa bu seslendirilir)
                segments.append(seg)
                pending_pause = 0
            elif value:
                buf.append(str(value))
        elif kind == "emphasis":
            emph_next = True
        elif kind == "emotion":
            flush(st)
            st = st.with_emotion(str(value))
        elif kind == "expr":
            flush(st)
            st = st.with_expr(value)  # type: ignore[arg-type]
        elif kind == "scoped_emotion":
            name, body = value  # type: ignore[misc]
            flush(st)
            add_text(body)
            flush(st.with_emotion(name))
        elif kind == "scoped_expr":
            expr, body = value  # type: ignore[misc]
            flush(st)
            add_text(body)
            flush(st.with_expr(expr))
        elif kind in ("rate", "pitch", "speaker"):
            flush(st)
            setattr(st, kind, value)
        elif kind == "scoped_emphasis":
            clean, found = _extract_emphasis(str(value))
            buf.append(clean)
            emph.append(clean.strip())
            emph.extend(found)
        elif kind == "text":
            buf.append(m.group(0))
    add_text(text[pos:])
    flush(st)
    if segments and pending_pause:
        segments[-1].pause_after_ms += pending_pause
    return segments


# ---------- etkin profil: yoğunluk, karışım, kayış ----------

EX_RANGE = (0.25, 0.95)           # yoğunlukla ölçeklenen exaggeration sınırları
CFG_RANGE = (0.3, 0.7)            # yoğunlukla ölçeklenen cfg_weight sınırları
# Karışımda ve kayışta değeri None olan (istekteki/stildeki değeri kullanan) taraf bu nötr değerle katılır
_NEUTRAL: dict[str, float] = {"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8}
_BLEND_FIELDS = ("exaggeration", "cfg_weight", "temperature", "speed", "pause_mul", "out_gain_db", "ref_pitch",
                 "ref_tempo", "whisper_mix")
_INTERP_FIELDS = ("exaggeration", "cfg_weight", "temperature", "ref_pitch", "ref_tempo", "ref_gain_db", "speed",
                  "out_pitch", "out_gain_db", "whisper_mix", "pause_mul")


def _r(x: float | None) -> float | None:
    """Kayan nokta gürültüsünü temizler (0.7799999999 → 0.78); -0.0 → 0.0."""
    return None if x is None else round(float(x), 4) + 0.0


def _mix(field_name: str, weighted: list[tuple[EmotionProfile, float]]) -> float | None:
    """Ağırlıklı ortalama. Ağırlığı sıfır olan taraf hesaba girmez; değeri None olan taraf _NEUTRAL değeriyle
    katılır; ağırlıklı tarafların hepsi None ise sonuç None (motor istekteki/stildeki değeri kullanır)."""
    vals = [(getattr(p, field_name), w) for p, w in weighted if w > 0]
    if not vals or all(v is None for v, _ in vals):
        return None
    total = sum(w for _, w in vals)
    return sum((_NEUTRAL[field_name] if v is None else float(v)) * w for v, w in vals) / total


def _norm_intensity(intensity) -> float:
    try:
        k = float(intensity)
    except (TypeError, ValueError):
        return 1.0
    return _clamp(k, INTENSITY_MIN, INTENSITY_MAX) if math.isfinite(k) else 1.0


def effective_profile(name: str | None, intensity: float = 1.0,
                      blend: list[str] | None = None) -> EmotionProfile | None:
    """Duygu + yoğunluk + karışımı tek profile indirger. "normal" / None / bilinmeyen ad → None (yoğunluk 1'den
    farklı ya da karışım verilmiş olsa da). Döndürülen profil YENİ nesnedir (PROFILES değişmez), aliases boştur.

    Karışım (önce): birincil %70, ikinciller (en çok 2) kalan %30'u eşit paylaşır; exaggeration, cfg_weight,
    temperature, speed, pause_mul, out_gain_db, ref_pitch, ref_tempo, whisper_mix ağırlıklı ortalanır (None değer
    nötr: ex 0.5, cfg 0.5, temp 0.8), diğer alanlar ve bool alanlar birincilden; name birincilin, label
    "Üzgün + Umutlu". Bilinmeyen / yinelenen ikinciller atılır.
    Yoğunluk (sonra; k = intensity, 0.5–1.6'ya sıkıştırılır): ex = 0.5 + (ex − 0.5)·k (0.25–0.95),
    cfg = 0.5 + (cfg − 0.5)·k (0.3–0.7), speed = 1 + (speed − 1)·k, pause_mul = 1 + (pause_mul − 1)·k,
    out_gain_db·k. temperature yoğunlukla değişmez (sözleşme: "temp aynı"); None alanlar None kalır.
    Örnek: heyecanlı (ex 0.7) yoğunluk 1.4 → ex 0.78."""
    base = resolve(name)
    if base is None or base.name == "normal":
        return None
    k = _norm_intensity(intensity)
    secondaries: list[EmotionProfile] = []
    for b in ([blend] if isinstance(blend, str) else (blend or [])):
        p = resolve(b)
        if p is None or p.name == base.name or any(p.name == s.name for s in secondaries):
            continue
        secondaries.append(p)
        if len(secondaries) == MAX_BLEND:
            break
    if secondaries:
        share = BLEND_SECONDARY_WEIGHT / len(secondaries)
        weighted = [(base, 1.0 - BLEND_SECONDARY_WEIGHT)] + [(p, share) for p in secondaries]
        vals = {f: _mix(f, weighted) for f in _BLEND_FIELDS}
        label = " + ".join(p.label for p in (base, *secondaries))
    else:
        vals = {f: getattr(base, f) for f in _BLEND_FIELDS}
        label = base.label
    if vals["exaggeration"] is not None:
        vals["exaggeration"] = _clamp(0.5 + (vals["exaggeration"] - 0.5) * k, *EX_RANGE)
    if vals["cfg_weight"] is not None:
        vals["cfg_weight"] = _clamp(0.5 + (vals["cfg_weight"] - 0.5) * k, *CFG_RANGE)
    vals["speed"] = 1.0 + (vals["speed"] - 1.0) * k
    vals["pause_mul"] = 1.0 + (vals["pause_mul"] - 1.0) * k
    vals["out_gain_db"] = vals["out_gain_db"] * k
    return replace(base, label=label, aliases=[], **{f: _r(v) for f, v in vals.items()})


def interpolate_profile(a: EmotionProfile | None, b: EmotionProfile | None, t: float) -> EmotionProfile:
    """Kayış (arc) için ara profil: t=0 → a, t=1 → b (t 0–1'e sıkıştırılır). None taraf "normal" profildir.
    Sayısal alanlar doğrusal (None değer nötr değerle katılır; t uçlarında tarafın kendi değeri, None dahil);
    highpass_hz tam sayıya yuvarlanır. name, description ve bool alanlar t < 0.5 iken a'nın, aksi halde b'nin;
    label "Heyecanlı→Sakin". Her zaman YENİ nesne döner; aliases boştur."""
    pa = a if a is not None else PROFILES["normal"]
    pb = b if b is not None else PROFILES["normal"]
    try:
        tt = float(t)
    except (TypeError, ValueError):
        tt = 0.0
    tt = _clamp(tt, 0.0, 1.0) if math.isfinite(tt) else 0.0
    weighted = [(pa, 1.0 - tt), (pb, tt)]
    vals: dict[str, object] = {f: _r(_mix(f, weighted)) for f in _INTERP_FIELDS}
    vals["highpass_hz"] = int(round(_mix("highpass_hz", weighted) or 0))
    side = pa if tt < 0.5 else pb
    return replace(side, label=f"{pa.label}→{pb.label}", aliases=[], **vals)


# ---------- vurgu planı ----------

_EMPH_STRIP = "\"'“”‘’«»‹›()[]{}<>.,;:!?…*_~-–—/\\"


def _emph_norm(token: str) -> str:
    """Eşleşme anahtarı: Türkçe küçük harf, kesme işaretleri tekleştirilmiş, baş/son noktalama atılmış."""
    t = tr_lower(token).replace("i̇", "i").replace("’", "'").replace("‘", "'")
    return t.strip(_EMPH_STRIP)


def _emph_match(token: str, word: str) -> bool:
    """"önemli." ~ "önemli", "İSTANBUL" ~ "istanbul", "Ankara'ya" / "Ankara’ya" ~ "ankara" (kesmeden sonraki ek)."""
    if not token:
        return False
    if token == word:
        return True
    return "'" in token and "'" not in word and token.split("'", 1)[0] == word


def plan_emphasis(text: str, words: list[str]) -> list[tuple[str, bool]]:
    """Metni vurgulu sözcük sınırlarından parçalar: ("Bu çok önemli.", ["çok"]) →
    [("Bu", False), ("çok", True), ("önemli.", False)].

    - Eşleşme sözcük düzeyindedir (tr_lower; baştaki/sondaki noktalama ve kesmeden sonraki ek yok sayılır);
      noktalama parçada kalır. Çok sözcüklü öbekler ("hemen şimdi") ardışık sözcüklerle eşleşir.
    - Ardışık vurgulu sözcükler tek parçadır ("çok önemli"); sözcüğün metindeki her geçişi vurgulanır.
    - Boş liste ya da hiç eşleşme yoksa [(text, False)] (metin olduğu gibi).
    - " ".join(parçalar) metni yeniden verir (parça sınırlarındaki boşluk dizileri tek boşluk sayılır; parça
      içindeki boşluklar ve satır sonları korunur; baştaki/sondaki boşluk atılır)."""
    phrases: list[list[str]] = []
    for w in ([words] if isinstance(words, str) else (words or [])):
        toks = [t for t in (_emph_norm(x) for x in str(w).split()) if t]
        if toks and toks not in phrases:
            phrases.append(toks)
    if not phrases or not text or not text.strip():
        return [(text, False)]
    parts = re.split(r"(\s+)", text.strip())
    tokens, seps = parts[0::2], parts[1::2]
    norm = [_emph_norm(t) for t in tokens]
    flags = [False] * len(tokens)
    for ph in phrases:
        n = len(ph)
        for i in range(len(tokens) - n + 1):
            if all(_emph_match(norm[i + j], ph[j]) for j in range(n)):
                flags[i:i + n] = [True] * n
    if not any(flags):
        return [(text, False)]
    out: list[tuple[str, bool]] = []
    cur = tokens[0]
    for i in range(1, len(tokens)):
        if flags[i] == flags[i - 1]:
            cur += seps[i - 1] + tokens[i]
        else:
            out.append((cur, flags[i - 1]))
            cur = tokens[i]
    out.append((cur, flags[-1]))
    return out


def tag_catalog() -> dict:
    """Arayüz için etiket kataloğu. Eski alanlar ("emotions", "nonverbal": list[str], "pauses": list[str]) aynı
    biçimde korunur; ayrıntılar "nonverbal_detail" ve "pause_detail" alanlarındadır. v4 ekleri: "intensity"
    ([{suffix, label}]; "biraz " / "çok " önek olarak yazılır), "arcs" ([{tag, to}]), "controls" ([{tag, label}])."""
    voiced = sorted(k for k, v in NONVERBAL.items() if v)
    return {
        "emotions": [{"name": p.name, "label": p.label, "aliases": list(p.aliases), "description": p.description}
                     for p in PROFILES.values()],
        "nonverbal": voiced,
        "nonverbal_detail": [{"tag": k, "reads": NONVERBAL[k]} for k in voiced],
        "pauses": sorted(PAUSE_TAGS.keys()),
        "pause_detail": [{"tag": k, "ms": v} for k, v in sorted(PAUSE_TAGS.items(), key=lambda kv: (kv[1], kv[0]))],
        "timed_pause_examples": ["[500 ms]", "[1 sn]", "[1.5 sn]", "[2 saniye]"],
        "emphasis_examples": ["*çok* önemli", "[vurgu] yarın", "[vurgu: hemen şimdi]"],
        "scoped_example": "[heyecanlı: Yalnızca bu cümle heyecanlı.]",
        "intensity": [{"suffix": ":1", "label": "hafif"}, {"suffix": ":2", "label": "normal"},
                      {"suffix": ":3", "label": "güçlü"}, {"suffix": "biraz ", "label": "biraz"},
                      {"suffix": "çok ", "label": "çok"}],
        "arcs": [{"tag": tag, "to": to} for tag, to in ARC_WORDS.items()],
        "controls": [{"tag": "hız:0.9", "label": "Hız"}, {"tag": "perde:+1", "label": "Perde"},
                     {"tag": "ses:Ad", "label": "Konuşmacı"}],
    }
