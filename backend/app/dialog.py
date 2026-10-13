"""Diyalog modu: çok konuşmacılı metni sıralara (Turn) ayırma ve sıra alma duraklamalarını planlama.

Sözleşme: docs/SOZLESME2.md bölüm 1. Desteklenen biçimler (aynı metinde karışık olabilir):

    Ayşe: Selam, naber?                   satır başı ad + ":" (ad 1–3 sözcük, Türkçe büyük harfle başlar)
    AYŞE — Selam. / Ayşe - Selam.         ad + uzun tire / iki yanı boşluklu kısa tire
    [ses:Mehmet] İyiyim. [ses:Ayşe] Ya?   satır içi bölümler; [konuşmacı: …] eş anlamlı, boşluklu yazım da olur
    Ayşe (gülerek): Selam.                parantezli yönerge → "[gülerek] Selam." (duygu/tepki olarak çözülemezse,
                                          ör. "(kapıyı açar)", atılır)

Kurallar:
- Konuşmacısız satır önceki konuşmacıyla sürer; metnin başındaysa anlatıcıdır (speaker=None).
- Her dolu satır en az bir AYRI Turn olur (aynı konuşmacının ardışık satırları birleştirilmez); boş satır atlanır.
- Sıra metninin başındaki "(…)" sahne yönergesidir (yukarıdaki kuralla); yalnızca parantezden oluşan satır da.
- Köşeli parantez etiketleri ([heyecanlı], [gülme], [1.5 sn]) Turn.text içinde olduğu gibi kalır; yalnızca
  [ses:…]/[konuşmacı:…] çıkarılır. Motor bunları sonra emotion.parse_tagged_text ile çözer.
- Ad eşleştirmesi tr_lower ile yapılır (Ayşe == AYŞE == ayşe); ilk görülen yazım korunur.
- Yanlış pozitif koruması: başlık sözcükleri ("Not:", "Örnek:", "Saat:" …), rakam içeren adlar ("Saat 14:30:"),
  40 karakterden uzun adlar ve ayraçtan sonra boşluk + metin gelmeyen satırlar ("https://…", "12:30") ad sayılmaz.
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass

from .emotion import NONVERBAL, PAUSE_TAGS, fold_ascii, resolve, timed_pause_ms
from .tr import tr_lower

__all__ = [
    "Turn", "parse_dialog", "is_dialog", "speakers_of", "plan_turn_pauses", "merge_turn_report",
    "strip_speaker_tags", "format_dialog", "resolve_directive",
    "HEADER_WORDS", "SPEAKER_TAG_KEYS", "TURN_PAUSE_MS",
]


@dataclass
class Turn:
    index: int
    speaker: str | None        # "Ayşe" / None = anlatıcı
    text: str                  # satırın metni (etiketler dahil; [ses:…] ve "Ad:" öneki ÇIKARILMIŞ)
    line_no: int               # kaynak metindeki satır numarası (1'den başlar)


# ---------- sabitler ----------

NAME_MAX_CHARS = 40            # ":" öncesindeki ad bundan uzunsa ad değildir
NAME_MAX_WORDS = 3
DIRECTIVE_MAX_CHARS = 60       # ad yanındaki / sıra başındaki yönerge parantezinin en uzun hali
STAGE_LINE_MAX_CHARS = 300     # yalnızca parantezden oluşan satır (sahne yönergesi) için üst sınır

# [ses:…] etiket anahtarları (tr_lower + fold_ascii sonrası biçim): ses, konuşmacı, speaker, voice
SPEAKER_TAG_KEYS = frozenset({"ses", "konusmaci", "speaker", "voice"})

# Sözleşmedeki 20 başlık sözcüğü (tr_lower biçimi): bunlar asla konuşmacı adı değildir
HEADER_WORDS = frozenset({
    "not", "örnek", "dikkat", "uyarı", "soru", "cevap", "özet", "başlık", "konu", "tarih",
    "saat", "adres", "telefon", "fiyat", "önemli", "sonuç", "kaynak", "açıklama", "ipucu", "adım",
})

# Ek koruma ("ad sözlük/ünlem değil"): söylem belirteçleri, belge/senaryo başlıkları, iletişim alanları, ünlemler
_NON_NAME_WORDS = frozenset("""
    yani mesela örneğin özetle kısacası ayrıca ancak fakat ama lakin çünkü bence evet hayır tamam peki şimdi
    sonra önce hatta üstelik oysa aslında elbette tabii neyse işte bakın dinleyin şöyle bu şu ve veya ya ki
    sorun mesele durum amaç hedef öneri tavsiye bilgi duyuru haber dakika flaş güncelleme hatırlatma
    bölüm kısım ünite ders sayfa madde giriş ek tablo şekil liste malzemeler yapılışı hazırlanışı ipuçları
    talimat görev ödev gün hafta yıl sene oda kat sınıf aşama sahne perde mekan mekân zaman yer dekor müzik
    efekt ses tel gsm faks fax e-posta eposta mail e-mail email web site url www http https ftp link bağlantı
    ah oh of eyvah hey vay ey aman hadi haydi bravo
""".split())

# Addan sonra küçük harfle yazılabilen hitaplar: "Ali bey:", "Fatma teyze:", "Hasan usta:"
_HONORIFICS = frozenset("""
    bey beyefendi hanım hanımefendi abla abi ağabey amca teyze dayı hala yenge enişte efendi paşa ağa hoca
    hocam usta bacı kardeş dede nine nene
""".split())

# Kurallarla türetilemeyen yaygın sahne yönergeleri → emotion'ın tanıdığı anahtar
_EXTRA_DIRECTIVES = {
    "bağırarak": "kızgın", "bağırır": "kızgın", "haykırarak": "kızgın", "sinirlenerek": "kızgın",
    "öfkelenerek": "kızgın", "gülümseyerek": "mutlu", "gülümser": "mutlu", "sevinerek": "mutlu",
    "titreyerek": "korkmuş", "ürkerek": "korkmuş", "ağlamaklı": "üzgün", "hıçkırarak": "ağlar",
    "duraksayarak": "duraklama", "düşünerek": "hmm", "tereddütle": "hmm",
}
# Sözleşme 3. bölümdeki geçiş (arc) etiketleri → hedef duygu
_ARC_DIRECTIVES = {
    "sakinleşerek": "sakin", "heyecanlanarak": "heyecanlı", "yumuşayarak": "samimi",
    "sertleşerek": "kızgın", "hüzünlenerek": "üzgün",
}
_INTENSIFIERS = ("çok ", "biraz ", "hafif ", "hafifçe ", "aşırı ", "son derece ", "oldukça ", "gayet ")
_MANNER_SUFFIXES = (" bir ses tonuyla", " ses tonuyla", " bir sesle", " sesle", " bir tonla", " bir şekilde",
                    " şekilde", " bir edayla", " bir ifadeyle", " ifadeyle", " bir tavırla", " tavırla")

_NV_FOLD: dict[str, str] = {}
for _k in NONVERBAL:
    _NV_FOLD.setdefault(fold_ascii(_k), _k)
_PAUSE_FOLD: dict[str, str] = {}
for _k in PAUSE_TAGS:
    _PAUSE_FOLD.setdefault(fold_ascii(_k), _k)

# ---------- düzenli ifadeler ----------

_LINE_SPLIT_RE = re.compile(r"\r\n|\r|\n")
_GROUP = r"\([^()\[\]\n]{1,60}\)|\[[^()\[\]\n]{1,60}\]"
_GROUP_RE = re.compile(r"\(([^()\[\]\n]{1,60})\)|(\[[^()\[\]\n]{1,60}\])")
# ad adayı (asıl denetim _valid_name'de) + en çok 3 yönerge + ayraç (":" | "—" | "–" | " - ") + boşluk + metin
_PREFIX_RE = re.compile(
    r"(?P<name>[^\W\d_][^:()\[\]\n]{0,59}?)"
    rf"(?P<dirs>(?:\s*(?:{_GROUP})){{0,3}})"
    r"(?:\s*:|\s*[—–]|\s+--?)"
    r"\s+(?P<text>\S.*)"
)
_NAME_TOKEN_RE = re.compile(r"[^\W\d_](?:[^\W\d_]|[.'’\-])*")
# "[anahtar: değer]" — yalnızca anahtarı SPEAKER_TAG_KEYS'te olanlar konuşmacı etiketidir
_KV_TAG_RE = re.compile(r"\[\s*(?P<key>[^\[\]:\n]{1,20}?)\s*:\s*(?P<val>[^\[\]\n]{0,60}?)\s*\]")
_LEAD_TAG_RE = re.compile(r"\[[^\[\]\n]{0,600}\]\s*")
_LEAD_PAREN_RE = re.compile(r"\(([^()\n]{1,%d})\)\s*" % STAGE_LINE_MAX_CHARS)
_DIRECTIVE_SPLIT_RE = re.compile(r"\s*[,;/]\s*|\s+ve\s+")
_EDGE_PUNCT = " \t.,;:!?…\"'“”‘’«»-—–"


# ---------- küçük yardımcılar ----------

def _speaker_key(name: str) -> str:
    """Konuşmacı eşleştirme anahtarı: Türkçe küçük harf, tek boşluk ("AYŞE" == "Ayşe" == "ayşe")."""
    return re.sub(r"\s+", " ", tr_lower(name.replace("’", "'"))).strip()


def _skey(name: str | None) -> str | None:
    return None if name is None else _speaker_key(name)


def _word_key(tok: str) -> str:
    return tr_lower(tok).strip(".'’-")


def _is_blocked_word(w: str) -> bool:
    if w in HEADER_WORDS or w in _NON_NAME_WORDS:
        return True
    return len(w) > 3 and w[-3:] in ("lar", "ler") and w[:-3] in HEADER_WORDS     # "Notlar", "Adımlar"


def _valid_name(name: str, known=()) -> bool:
    """Satır başı ad adayı gerçekten bir konuşmacı adı mı (yanlış pozitif korumaları burada). Daha önce görülmüş
    bir konuşmacı (known: _speaker_key kümesi) küçük harfle yazılsa da kabul edilir ("ayşe:" → Ayşe)."""
    name = name.strip()
    if not name or len(name) > NAME_MAX_CHARS:
        return False
    toks = name.split()
    if not 1 <= len(toks) <= NAME_MAX_WORDS or not all(_NAME_TOKEN_RE.fullmatch(t) for t in toks):
        return False
    if _speaker_key(name) not in known:
        if not toks[0][0].isupper():
            return False
        if not all(t[0].isupper() or _word_key(t) in _HONORIFICS for t in toks[1:]):
            return False
    return not any(_is_blocked_word(_word_key(t)) for t in toks)


def _is_speaker_tag(m: re.Match[str]) -> bool:
    return fold_ascii(tr_lower(m.group("key").strip())) in SPEAKER_TAG_KEYS


def _speaker_tags(line: str) -> list[re.Match[str]]:
    return [m for m in _KV_TAG_RE.finditer(line) if _is_speaker_tag(m)]


# ---------- sahne yönergeleri ----------

def _norm_directive(s: str) -> str:
    return re.sub(r"\s+", " ", tr_lower(s)).strip(_EDGE_PUNCT)


def _direct_tag(c: str) -> str | None:
    """Yönerge doğrudan emotion'ın tanıdığı bir etiket mi: sözsüz tepki, duraklama, sayılı duraklama, duygu."""
    if not c:
        return None
    if c in _EXTRA_DIRECTIVES:
        return _EXTRA_DIRECTIVES[c]
    if c in _ARC_DIRECTIVES:
        return _ARC_DIRECTIVES[c]
    f = fold_ascii(c)
    for table, folded in ((NONVERBAL, _NV_FOLD), (PAUSE_TAGS, _PAUSE_FOLD)):
        if c in table:
            return c
        if f in folded:
            return folded[f]
    if timed_pause_ms(c) is not None:
        return c
    prof = resolve(c)
    return prof.name if prof is not None else None


def _verb_forms(stem: str):
    """Zarf-fiil gövdesinden ("gül", "ağla", "iç çek") etiket adayları: geniş zaman, -me/-ma, gövde."""
    if stem[-1] in "aeıioöuü":
        yield stem + "r"                                   # ağla → ağlar, esne → esner
    else:
        for v in "aeıiuü":
            yield stem + v + "r"                           # gül → güler, öksür → öksürür, iç çek → iç çeker
    yield stem + "me"                                      # gül → gülme, esne → esneme
    yield stem + "ma"                                      # ağla → ağlama
    yield stem


def _candidates(k: str):
    bases = [k] + [k[len(p):] for p in _INTENSIFIERS if k.startswith(p)]
    bases += [b[: -len(s)] for b in list(bases) for s in _MANNER_SUFFIXES if b.endswith(s) and len(b) > len(s)]
    for b in bases:
        yield b
    for b in bases:
        for suf in ("yarak", "yerek", "arak", "erek"):     # -arak/-erek: gülerek, ağlayarak, iç çekerek
            if b.endswith(suf) and len(b) > len(suf) + 1:
                yield from _verb_forms(b[: -len(suf)])
                break
        for suf in ("yla", "yle", "la", "le"):             # -la/-le: heyecanla, öfkeyle, hızla
            if b.endswith(suf) and len(b) > len(suf) + 2:
                stem = b[: -len(suf)]
                yield stem
                yield from (stem + x for x in ("lı", "li", "lu", "lü"))
                break
        for suf in ("ca", "ce", "ça", "çe"):               # -ca/-ce: sessizce
            if b.endswith(suf) and len(b) > len(suf) + 2:
                yield b[: -len(suf)]
                break


def resolve_directive(text: str) -> str | None:
    """Sahne yönergesini ("gülerek", "Fısıldayarak", "alaycı bir sesle", "iç çekerek") emotion'ın tanıdığı
    anahtara (profil adı, NONVERBAL ya da duraklama anahtarı) çevirir; çözülemezse None ("kapıyı açar")."""
    k = _norm_directive(text or "")
    if not k or len(k) > DIRECTIVE_MAX_CHARS:
        return None
    for c in _candidates(k):
        hit = _direct_tag(c)
        if hit:
            return hit
    return None


def _directive_tags(inner: str) -> list[str]:
    """Parantez içinden Turn.text'e eklenecek etiket metinleri: bütünü çözülürse o, değilse virgül/"ve" ile
    ayrılmış çözülebilen parçalar ("gülerek, kapıyı açar" → ["gülerek"]). Hiçbiri çözülmezse []."""
    whole = _norm_directive(inner)
    if not whole:
        return []

    def _as_tag(k: str) -> str | None:
        """Yönerge emotion'ın doğrudan tanıdığı bir etiketse olduğu gibi kalır ("biraz üzgün" → yoğunluk korunur);
        değilse ("gülerek", "bağırarak") kanonik anahtara çözülür."""
        if _tag_recognized(k):
            return k
        return resolve_directive(k)

    r = _as_tag(whole)
    if r:
        return [r]
    out = []
    for x in _DIRECTIVE_SPLIT_RE.split(whole):
        k = _norm_directive(x)
        r = _as_tag(k) if k else None
        if r:
            out.append(r)
    return out


def _tag_recognized(k: str) -> bool:
    """emotion.parse_tagged_text bu etiketi (duygu, yoğunluk, karışım, kayış, tepki, duraklama) tanıyor mu?"""
    try:
        from .emotion import parse_tagged_text

        segs = parse_tagged_text(f"[{k}] x", keep_nonverbal=True)
    except Exception:  # noqa: BLE001
        return False
    if not segs:
        return False
    s0 = segs[0]
    return bool(s0.emotion or s0.nonverbal or s0.arc_to or s0.pause_before_ms or s0.pause_after_ms
                or getattr(s0, "rate", None) or getattr(s0, "pitch", None))


# ---------- ayrıştırma ----------

def _match_prefix(line: str, known=()) -> tuple[str, list[str], str] | None:
    """Satır başı konuşmacı öneki: (ad, ad yanındaki yönergelerden etiketler, kalan metin) ya da None."""
    m = _PREFIX_RE.fullmatch(line)
    if m is None or not _valid_name(m.group("name"), known):
        return None
    lead: list[str] = []
    for paren, bracket in _GROUP_RE.findall(m.group("dirs")):
        if bracket:
            lead.append(bracket)                               # "[gülerek]" zaten etiket: olduğu gibi
        else:
            lead.extend(f"[{t}]" for t in _directive_tags(paren))
    return m.group("name").strip(), lead, m.group("text")


def _turn_text(lead: list[str], chunk: str) -> str:
    """Sıra metni: ad yanındaki etiketler + baştaki sahne yönergeleri işlenmiş metin. Baştaki köşeli parantez
    etiketleri atlanarak "(…)" aranır; kısa parantez (≤ 60) ya da bölümün tamamı olan parantez yönergedir."""
    s = chunk.strip()
    parts: list[str] = []
    pos, touched = 0, False
    while pos < len(s):
        m = _LEAD_TAG_RE.match(s, pos)
        if m:
            parts.append(m.group(0).strip())
            pos = m.end()
            continue
        m = _LEAD_PAREN_RE.match(s, pos)
        if m and (len(m.group(1)) <= DIRECTIVE_MAX_CHARS or m.end() == len(s)):
            parts.extend(f"[{t}]" for t in _directive_tags(m.group(1)))
            pos, touched = m.end(), True
            continue
        break
    body = " ".join(parts + ([s[pos:].strip()] if s[pos:].strip() else [])) if touched else s
    return " ".join(lead + ([body] if body else []))


#: Bu adlar konuşmacı değil anlatıcıdır (arayüzdeki "Anlatıcı" satırıyla aynı sese bağlanır).
NARRATOR_NAMES = frozenset({"anlatıcı", "anlatici", "anlatan", "dış ses", "dis ses", "narrator", "voice over"})


def parse_dialog(text: str) -> list[Turn]:
    """Metni konuşmacı sıralarına ayırır (biçimler ve kurallar modül belgesinde)."""
    turns: list[Turn] = []
    if not text:
        return turns
    names: dict[str, str] = {}

    def canon(raw: str) -> str | None:
        clean = re.sub(r"\s+", " ", raw).strip()
        if _speaker_key(clean) in NARRATOR_NAMES:                # "Anlatıcı:" / "Dış ses:" → anlatıcı (None)
            return None
        return names.setdefault(_speaker_key(clean), clean)      # ilk yazım korunur

    current: str | None = None
    for line_no, raw in enumerate(_LINE_SPLIT_RE.split(text.lstrip("﻿")), start=1):
        line = raw.strip()
        if not line:
            continue
        lead: list[str] = []
        prefix = _match_prefix(line, names)
        if prefix is not None:
            name, lead, line = prefix
            current = canon(name)
        pieces: list[tuple[str | None, str, list[str]]] = []
        speaker, pos = current, 0
        for tag in _speaker_tags(line):
            pieces.append((speaker, line[pos:tag.start()], lead))
            lead = []
            if tag.group("val").strip():                         # boş "[ses:]" yok sayılır
                speaker = canon(tag.group("val"))
            pos = tag.end()
        pieces.append((speaker, line[pos:], lead))
        current = speaker                                        # etiketsiz sonraki satır son konuşmacıyla sürer
        for spk, chunk, tags in pieces:
            body = _turn_text(tags, chunk)
            if body:
                turns.append(Turn(len(turns), spk, body, line_no))
    return turns


def speakers_of(turns: list[Turn]) -> list[str]:
    """Konuşmacılar ilk görülme sırasıyla, tekil (tr_lower ile); anlatıcı (None) dahil edilmez."""
    seen: dict[str, str] = {}
    for t in turns:
        if t.speaker is not None:
            seen.setdefault(_speaker_key(t.speaker), t.speaker)
    return list(seen.values())


def is_dialog(text: str) -> bool:
    """Metinde en az 2 farklı konuşmacı var mı (anlatıcı sayılmaz)."""
    return len(speakers_of(parse_dialog(text))) >= 2


# ---------- sıra alma duraklamaları ----------

TURN_PAUSE_MS = {
    "same": 450,         # aynı konuşmacı devam ediyor (paragraf gibi)
    "change": 260,       # konuşmacı değişimi
    "question": 200,     # "?" ile biten sıradan sonra hızlı cevap
    "exclaim": 230,      # "!" ile biten sıradan sonra
    "ellipsis": 520,     # "..." / "…" ile yarım kalan sıradan sonra
}
LONG_TURN_S = 6.0        # bundan uzun önceki sıra (konuşmacı değişiminde) …
LONG_TURN_BONUS_MS = 80  # … bu kadar ek düşünme payı alır
JITTER = 0.15            # ± oran (seed ile belirlenimci)
MIN_PAUSE_MS = 120
MAX_PAUSE_MS = 1500


def _ending(text: str) -> str:
    """Sıranın son noktalaması: "..." | "?" | "!" | "" (sondaki etiketler, tırnak ve parantezler atlanır)."""
    s = (text or "").rstrip()
    while True:
        t = re.sub(r"\[[^\[\]\n]*\]$", "", s).rstrip().rstrip("\"'”’»)").rstrip()
        if t == s:
            break
        s = t
    if s.endswith(("..", "…")):
        return "..."
    if s.endswith("?"):
        return "?"
    if s.endswith("!"):
        return "!"
    return ""


def _duration(durations_s, i: int) -> float:
    try:
        d = float(durations_s[i])
    except (IndexError, TypeError, ValueError):
        return 0.0
    return d if math.isfinite(d) else 0.0


def plan_turn_pauses(turns: list[Turn], durations_s: list[float], seed: int | None = None) -> list[int]:
    """Her sıradan SONRAKİ duraklama (ms). Aynı konuşmacı → 450; değişim → 260 ("?" → 200, "!" → 230,
    "..." → 520; önceki sıra > 6 sn ise +80); ±%15 titreşim (seed verilirse belirlenimci); 120–1500'e
    sıkıştırılır; son sıra 0. Eksik ya da geçersiz süre 0 sn sayılır."""
    n = len(turns)
    if n == 0:
        return []
    rng = random.Random(seed)
    jitter = [rng.uniform(-JITTER, JITTER) for _ in range(n)]     # aynı tohum + aynı sıra sayısı → aynı dizi
    out: list[int] = []
    for i in range(n - 1):
        prev, nxt = turns[i], turns[i + 1]
        if _skey(prev.speaker) == _skey(nxt.speaker):
            base = TURN_PAUSE_MS["same"]
        else:
            kind = {"?": "question", "!": "exclaim", "...": "ellipsis"}.get(_ending(prev.text), "change")
            base = TURN_PAUSE_MS[kind]
            if _duration(durations_s, i) > LONG_TURN_S:
                base += LONG_TURN_BONUS_MS
        ms = base * (1.0 + jitter[i])
        out.append(int(round(min(MAX_PAUSE_MS, max(MIN_PAUSE_MS, ms)))))
    out.append(0)
    return out


# ---------- rapor ve yardımcılar ----------

def _voice_name(speaker: str | None, voice_names: dict, normalized: dict) -> str | None:
    if speaker in voice_names:
        return voice_names[speaker]
    if speaker is not None:
        return normalized.get(_speaker_key(speaker))
    for key in ("", "anlatıcı", "narrator"):                     # anlatıcı için olası anahtarlar
        if key in normalized:
            return normalized[key]
    return None


def _time(values, i: int) -> float | None:
    try:
        v = float(values[i])
    except (IndexError, TypeError, ValueError):
        return None
    return round(v, 3) if math.isfinite(v) else None


def merge_turn_report(turns: list[Turn], starts_s: list[float], ends_s: list[float],
                      voice_names: dict[str, str]) -> list[dict]:
    """[{index, speaker, voice_name, text, start, end}] — sıra başına bir kayıt. Ses adı konuşmacı adıyla
    (tr_lower eşleşmesiyle) bulunur; anlatıcı için None/""/"anlatıcı"/"narrator" anahtarı. Eksik zaman → None."""
    voice_names = dict(voice_names or {})
    normalized: dict[str, str] = {}
    for k, v in voice_names.items():
        if isinstance(k, str):
            normalized.setdefault(_speaker_key(k), v)
    return [{
        "index": t.index,
        "speaker": t.speaker,
        "voice_name": _voice_name(t.speaker, voice_names, normalized),
        "text": t.text,
        "start": _time(starts_s, i),
        "end": _time(ends_s, i),
    } for i, t in enumerate(turns)]


def strip_speaker_tags(text: str) -> str:
    """Metin diyalog değilse [ses:…]/[konuşmacı:…] etiketlerini temizler (tek sesle okunacak metin); yalnızca
    etiketten oluşan satır silinir, diğer satırlara ve "Ad:" öneklerine dokunulmaz. Diyalogsa metin aynen döner."""
    if not text or is_dialog(text):
        return text or ""
    out: list[str] = []
    for line in text.split("\n"):
        tags = _speaker_tags(line)
        if not tags:
            out.append(line)
            continue
        pieces, pos = [], 0
        for m in tags:
            pieces.append(line[pos:m.start()])
            pos = m.end()
        pieces.append(line[pos:])
        joined = ""
        for p in (p.strip() for p in pieces):
            if p:
                joined += (" " if joined and p[0] not in ".,!?;:…)" else "") + p
        if joined:
            out.append(joined)
    return "\n".join(out)


def format_dialog(turns: list[Turn]) -> str:
    """Sıraları metne geri yazar (test/önizleme için): geçerli adlar "Ad: metin", diğerleri "[ses:Ad] metin",
    anlatıcı düz satır. parse_dialog çıktısı için geri ayrıştırma aynı (konuşmacı, metin) dizisini verir;
    elle kurulmuş, bir konuşmacıdan SONRA gelen anlatıcı satırı ise önceki konuşmacının devamı sayılır."""
    lines: list[str] = []
    for t in turns:
        body = (t.text or "").strip()
        if t.speaker is None:
            lines.append(body)
        elif _valid_name(t.speaker):
            lines.append(f"{t.speaker}: {body}")
        else:
            lines.append(f"[ses:{t.speaker}] {body}")
    return "\n".join(lines)
