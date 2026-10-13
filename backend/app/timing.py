"""timing — zaman çizelgesi ve altyazı (SRT / VTT / JSON / LRC).

Motor her parçanın (chunk) süresini ve parçalar arasındaki duraklamaları bilir; bu modül bunlardan parça (cümle) ve
yaklaşık sözcük zamanlı bir zaman çizelgesi, oradan da YouTube/Instagram'a yüklenebilen altyazı dosyaları üretir.

Sözcük zamanları ses hizalaması değil, Türkçe hece sayısına dayalı bir tahmindir — "karaoke" tarzı vurgulama için
yeterli: parça süresi sözcüklerin hece ağırlığıyla orantılı paylaştırılır, sözcükler arasında boşluk bırakılmaz.

Zamanlar örnek (sample) ızgarasında toplanır; böylece çizelge prosody.join_natural'ın kurduğu sesle örtüşür
(duraklama = round(sr·ms/1000) örnek, parça = round(süre·sr) örnek). Doğru hizalama için `duration` yuvarlanmadan
(len(parça)/sr) verilmeli; nefes boşluğu uzattıysa aradaki fark `extra_before_ms` ile eklenmelidir.
"""
from __future__ import annotations

import copy
import json
import math
import re
from itertools import combinations

from .tr import count_syllables, words

__all__ = [
    "build_timeline", "to_srt", "to_vtt", "to_json", "to_lrc", "shift", "merge_timelines", "total_duration",
    "render", "tokenize", "token_weight", "SUBTITLE_FORMATS", "MIN_GAP_MS", "MIN_BLOCK_MS",
]

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

PUNCT_PAUSE_WEIGHT = 0.5        # duraklama noktalamasıyla biten sözcüğe eklenen pay (hece cinsinden)
PAUSE_PUNCT = ",.;:!?…—–"       # virgül/nokta ve aynı işi gören işaretler: duraklama payı alır
SENTENCE_END = ".!?…"           # blok burada biterse kırılma cezası yok
CLOSERS = "\"'“”‘’«»)]}"        # noktalama denetiminde sondan atlanan kapanış işaretleri
MIN_GAP_MS = 80                 # ardışık iki altyazı bloğu arasında en az boşluk
MIN_BLOCK_MS = 700              # en kısa blok süresi

SUBTITLE_FORMATS: dict[str, tuple[str, str]] = {   # biçim → (Content-Type, dosya uzantısı)
    "srt": ("application/x-subrip; charset=utf-8", ".srt"),
    "vtt": ("text/vtt; charset=utf-8", ".vtt"),
    "json": ("application/json; charset=utf-8", ".json"),
    "lrc": ("text/plain; charset=utf-8", ".lrc"),
}

_TAG_RE = re.compile(r"\[[^\[\]]*\]")              # [gülerek], [nefes]… seslendirilmez, altyazıya girmez
_DIGITS_RE = re.compile(r"\d+")
_CIRCUMFLEX = str.maketrans("âîûÂÎÛ", "aiuAİU")    # tr.count_syllables şapkalı ünlüyü saymaz: hâlâ → hala

# Blok bölme maliyetleri (dinamik programlama): önce blok sayısı, sonra kısa blok, sonra birleştirme ve görünüm.
_COST_BLOCK = 1000.0
_COST_SHORT = 500.0
_COST_MERGE = 50.0
_COST_BALANCE = 100.0
_COST_BREAK_CLAUSE = 5.0        # blok parçanın ortasında virgül/noktalı virgülde bitiyor
_COST_BREAK_WORD = 20.0         # blok parçanın ortasında noktalamasız bitiyor
_COST_PYRAMID = 30.0            # blokta alt satır üsttekinden uzun kalıyor
_COST_IMBALANCE = 0.5           # satır uzunluklarının eşitlikten sapması (karakter başına)
_MAX_LAYOUTS = 5000             # dengeli satır aramasında denenecek en çok bölme sayısı


# ---------------------------------------------------------------------------
# Küçük yardımcılar
# ---------------------------------------------------------------------------

def _num(x, default: float = 0.0) -> float:
    """Sayıya çevirir; geçersiz ya da sonsuz değer → default."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _ms(seconds) -> int:
    """Saniye → tam milisaniye."""
    return int(round(_num(seconds) * 1000.0))


def _rate(sr) -> int:
    """Örnekleme hızı; geçersizse milisaniye ızgarası (1000) kullanılır."""
    r = int(_num(sr))
    return r if r > 0 else 1000


def _samples_ms(ms, rate: int) -> int:
    """Milisaniye → örnek sayısı (join_natural ile aynı yuvarlama); eksik/negatif → 0."""
    v = _num(ms)
    return int(round(rate * v / 1000.0)) if v > 0 else 0


def _samples_s(seconds, rate: int) -> int:
    """Saniye → örnek sayısı; eksik/negatif → 0."""
    v = _num(seconds)
    return int(round(v * rate)) if v > 0 else 0


def _by_start(timeline) -> list[dict]:
    """Geçerli parçalar, başlangıç sırasıyla (eşitlikte özgün sıra korunur)."""
    return sorted((c for c in (timeline or []) if isinstance(c, dict)), key=lambda c: _num(c.get("start")))


# ---------------------------------------------------------------------------
# Sözcükler ve ağırlıklar
# ---------------------------------------------------------------------------

def tokenize(text: str) -> list[str]:
    """Metni boşlukla ayrılmış sözcüklere (token) böler; noktalama sözcüğe yapışık kalır ("önemli," tek token).

    Yalnızca noktalamadan oluşan token'lar ("—", "…", "?") önceki sözcüğe eklenir (metnin başındaysa sonrakine);
    böylece satır ya da blok hiçbir zaman tek başına bir noktalama işaretiyle başlamaz. [etiket]'ler atılır.
    """
    out: list[str] = []
    lead = ""
    for tok in _TAG_RE.sub(" ", str(text or "")).split():
        if any(ch.isalnum() for ch in tok):
            if lead:
                tok, lead = f"{lead} {tok}", ""
            out.append(tok)
        elif out:
            out[-1] = f"{out[-1]} {tok}"
        else:
            lead = f"{lead} {tok}".strip()
    if lead:                       # metin yalnızca noktalamadan oluşuyor
        out.append(lead)
    return out


def _number_syllables(token: str) -> int:
    """Token'daki rakamların okunuşundaki hece sayısı ("2024" → "iki bin yirmi dört" → 6)."""
    total = 0
    for run in _DIGITS_RE.findall(token):
        try:
            from .textnorm import read_number_tr   # tembel içe aktarma: normalize metinde rakam nadirdir
            total += count_syllables(read_number_tr(run))
        except Exception:  # noqa: BLE001 — okunamazsa kaba tahmin: hane başına bir hece
            total += len(run)
    return total


def _ends_with_pause(token: str) -> bool:
    """Token (kapanış tırnağı/parantezi atlanarak) duraklama noktalamasıyla mı bitiyor?"""
    t = token.rstrip(CLOSERS)
    return bool(t) and t[-1] in PAUSE_PUNCT


def token_weight(token: str) -> float:
    """Sözcüğün süre ağırlığı: max(1, hece) + (virgül/nokta vb. ile bitiyorsa) 0.5 duraklama payı.

    Hece = tr.words ile bulunan sözcüklerin tr.count_syllables toplamı (şapkalı ünlüler düz sayılır) + rakamların
    okunuşundaki hece. Duraklama payı sözcüğün SONUNA eklenir: sözcüğün bitişi gecikir, sonraki sözcük ondan sonra
    başlar.
    """
    tok = str(token or "").translate(_CIRCUMFLEX)
    syllables = sum(count_syllables(w) for w in words(tok)) + _number_syllables(tok)
    weight = float(max(1, syllables))
    if _ends_with_pause(tok):
        weight += PUNCT_PAUSE_WEIGHT
    return weight


def _word_times(text: str, start: float, end: float) -> list[dict]:
    """Parça süresini sözcüklere hece ağırlığıyla orantılı dağıtır; ilk sözcük start'ta başlar, son sözcük end'de
    biter, sözcükler arasında boşluk yoktur. Boş metin → []."""
    toks = tokenize(text)
    if not toks:
        return []
    end = max(end, start)
    weights = [token_weight(t) for t in toks]
    total = sum(weights)
    span = end - start
    out: list[dict] = []
    acc, t0, last = 0.0, start, len(toks) - 1
    for k, (tok, w) in enumerate(zip(toks, weights)):
        acc += w
        t1 = end if k == last else start + span * acc / total
        out.append({"word": tok, "start": round(t0, 3), "end": round(t1, 3)})
        t0 = t1
    return out


# ---------------------------------------------------------------------------
# Zaman çizelgesi
# ---------------------------------------------------------------------------

def build_timeline(chunks: list[dict], pauses_ms: list[int], sr: int, *, lead_in_ms: int = 0,
                   extra_before_ms: list[int] | None = None) -> list[dict]:
    """Parça süreleri ve duraklamalardan zaman çizelgesi kurar.

    chunks[i] = {"text", "duration" (sn), "emotion", "speaker"?}. En başta lead_in_ms; i. parçadan ÖNCE
    extra_before_ms[i] (nefes gibi), SONRA pauses_ms[i] eklenir. Eksik/negatif değerler 0 sayılır.
    Dönüş: [{"index","start","end","text","emotion","speaker","words":[{"word","start","end"}]}] — saniye, 3 ondalık.
    """
    rate = _rate(sr)
    pauses = list(pauses_ms or [])
    extras = list(extra_before_ms or [])
    pos = _samples_ms(lead_in_ms, rate)            # örnek cinsinden konum: birikimli yuvarlama hatası yok
    timeline: list[dict] = []
    for i, ch in enumerate(chunks or []):
        ch = ch if isinstance(ch, dict) else {}
        pos += _samples_ms(extras[i] if i < len(extras) else 0, rate)
        length = _samples_s(ch.get("duration"), rate)
        start, end = pos / rate, (pos + length) / rate
        text = str(ch.get("text") or "").strip()
        timeline.append({
            "index": i,
            "start": round(start, 3),
            "end": round(end, 3),
            "text": text,
            "emotion": ch.get("emotion"),
            "speaker": ch.get("speaker"),
            "words": _word_times(text, start, end),
        })
        pos += length + _samples_ms(pauses[i] if i < len(pauses) else 0, rate)
    return timeline


def total_duration(timeline: list[dict]) -> float:
    """Çizelgenin toplam süresi (sn): en geç biten parçanın sonu; boş çizelge → 0.0."""
    return round(max((_num(c.get("end")) for c in _by_start(timeline)), default=0.0), 3)


def _moved(t, d: float) -> float:
    return round(max(0.0, _num(t) + d), 3)


def shift(timeline: list[dict], seconds: float) -> list[dict]:
    """Tüm zamanları (parça ve sözcük) `seconds` kadar kaydırır; yeni liste döner, girdi değişmez.
    Negatif kaydırmada 0'ın altına inen zaman 0 olur."""
    d = _num(seconds)
    out: list[dict] = []
    for ch in timeline or []:
        c = copy.deepcopy(ch)
        for key in ("start", "end"):
            if key in c:
                c[key] = _moved(c[key], d)
        for w in c.get("words") or []:
            if isinstance(w, dict):
                for key in ("start", "end"):
                    if key in w:
                        w[key] = _moved(w[key], d)
        out.append(c)
    return out


def merge_timelines(parts: list[list[dict]], gaps_s: list[float]) -> list[dict]:
    """Ayrı ayrı üretilmiş çizelgeleri sırayla birleştirir (diyalogda sıra sıra).

    k. çizelge, öncekilerin süreleri (total_duration) + aradaki boşluklar kadar kaydırılır; gaps_s[k], k. ile (k+1).
    çizelge arasındaki boşluktur (sn; eksik/negatif → 0). index'ler 0'dan yeniden numaralanır; girdiler değişmez.
    """
    gaps = list(gaps_s or [])
    out: list[dict] = []
    offset_ms = 0
    for k, part in enumerate(parts or []):
        part = list(part or [])
        for ch in shift(part, offset_ms / 1000.0):
            ch["index"] = len(out)
            out.append(ch)
        offset_ms += _ms(total_duration(part)) + max(0, _ms(gaps[k] if k < len(gaps) else 0))
    return out


# ---------------------------------------------------------------------------
# Altyazı blokları
# ---------------------------------------------------------------------------

def _chunk_words(ch: dict) -> list[tuple[str, int, int]]:
    """Parçanın sözcükleri (token, başlangıç_ms, bitiş_ms); "words" yoksa metinden hesaplanır."""
    items: list[tuple[str, int, int]] = []
    for w in ch.get("words") or []:
        if not isinstance(w, dict):
            continue
        tok = " ".join(str(w.get("word") or "").split())      # satır sonu / CR asla altyazıya sızmaz
        if tok:
            items.append((tok, _ms(w.get("start")), _ms(w.get("end"))))
    if not items:
        s, e = _num(ch.get("start")), _num(ch.get("end"))
        items = [(w["word"], _ms(w["start"]), _ms(w["end"])) for w in _word_times(str(ch.get("text") or ""), s, e)]
    return items


def _greedy_cuts(sizes: list[int], max_chars: int) -> tuple[int, ...]:
    """Soldan doldurma ile satır başı olan sözcük sıraları (sığmayan uzun sözcük kendi satırında kalır)."""
    cuts: list[int] = []
    cur = -1
    for k, size in enumerate(sizes):
        if cur < 0:
            cur = size
        elif cur + 1 + size <= max_chars:
            cur += 1 + size
        else:
            cuts.append(k)
            cur = size
    return tuple(cuts)


def _layout_key(lens: list[int]) -> tuple:
    """Satır düzeni anahtarı (küçük olan iyi): (piramit sayısı, eşitlikten sapma, eşitlikte üst satır uzun).
    "Piramit": alttaki satır üsttekinden uzun."""
    mean = sum(lens) / len(lens)
    return (sum(b > a for a, b in zip(lens, lens[1:])),
            sum(abs(x - mean) for x in lens),
            tuple(-x for x in lens))


def _layout(sizes: list[int], max_chars: int, max_lines: int) -> tuple[tuple, tuple[int, ...]] | None:
    """Token uzunluklarından en iyi satır bölmesi: (anahtar, kesimler); max_lines satıra sığmıyorsa None.

    En az satır kullanılır; bu satır sayısındaki bölmeler arasında piramit olmayan, sonra en eşit olan seçilir.
    Tek sözcük max_chars'tan uzun olsa da tek satırda kabul edilir (bölünemez).
    """
    n = len(sizes)
    pre = [0]
    for s in sizes:
        pre.append(pre[-1] + s)

    def width(a: int, b: int) -> int:              # sizes[a:b] boşluklarla birlikte
        return pre[b] - pre[a] + (b - a - 1)

    if n < 2 or width(0, n) <= max_chars:
        return _layout_key([width(0, n)]), ()
    greedy = _greedy_cuts(sizes, max_chars)
    count = len(greedy) + 1                          # en az satır sayısı
    if count > max_lines or max(sizes) > max_chars:
        return None
    candidates = (combinations(range(1, n), count - 1) if math.comb(n - 1, count - 1) <= _MAX_LAYOUTS
                  else [greedy])
    best = None
    for cut in candidates:
        edges = (0, *cut, n)
        lens = [width(a, b) for a, b in zip(edges, edges[1:])]
        if max(lens) > max_chars:
            continue
        key = _layout_key(lens)
        if best is None or key < best[0]:
            best = (key, tuple(cut))
    return best


def _balanced_lines(tokens: list[str], max_chars: int, max_lines: int) -> list[str]:
    """Sözcükleri en az satıra, hiçbir satır max_chars'ı aşmadan ve dengeli dağıtır (bkz. _layout)."""
    sizes = [len(t) for t in tokens]
    lay = _layout(sizes, max_chars, max_lines)
    cuts = lay[1] if lay is not None else _greedy_cuts(sizes, max_chars)
    edges = (0, *cuts, len(tokens))
    return [" ".join(tokens[a:b]) for a, b in zip(edges, edges[1:])]


def _dash(group: list[str]) -> str:
    """Farklı konuşmacıların aynı bloktaki sözü: "- Naber?" biçiminde kendi satırında."""
    return "- " + " ".join(group)


def _blocks(timeline: list[dict], *, max_chars: int = 42, max_lines: int = 2,
            max_duration_s: float = 7.0) -> list[tuple[int, int, list[str]]]:
    """Zaman çizelgesini altyazı bloklarına çevirir: [(başlangıç_ms, bitiş_ms, [satır, …]), …].

    Kurallar: her parça bir ya da daha çok blok olur; blok max_lines satıra (her satır ≤ max_chars) sığmalı ve
    max_duration_s'yi aşmamalı — aşan parça sözcük sınırından bölünür (blok süresi sözcük zamanlarından; tek
    sözcük bölünemediği için istisnadır). Bölme yeri dinamik programlamayla seçilir: en az blok, kısa blok yok,
    mümkünse cümle/virgül sonunda, dengeli. Tek başına 700 ms gösterilemeyecek kısa parça sonraki parçayla aynı
    bloğa girer (süre ve satır sınırı içinde; farklı konuşmacıysa "- " satırlarıyla). Sonra bloklar arası en az
    80 ms boşluk (önceki bloğun sonu kırpılır) ve hâlâ kısa kalan bloğun sonu, yer varsa 700 ms'ye uzatılır.
    """
    max_chars = max(1, int(max_chars))
    max_lines = max(1, int(max_lines))
    max_ms = max(1, int(round(_num(max_duration_s, 7.0) * 1000)))
    min_ms = min(MIN_BLOCK_MS, max_ms)
    cap = max_chars * max_lines

    # 1) Tüm parçaların sözcükleri tek dizide; her sözcük hangi parçadan geldiğini bilir.
    toks: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    cid: list[int] = []        # sözcüğün parça sırası
    first: list[int] = []      # parçanın ilk sözcüğünün sırası
    spk: list = []             # parçanın konuşmacısı
    for ch in _by_start(timeline):
        items = _chunk_words(ch)
        if not items:
            continue
        c = len(first)
        first.append(len(toks))
        prev = None
        for tok, s, e in items:
            s = s if prev is None else max(s, prev)            # sözcük başlangıçları azalmaz
            toks.append(tok)
            starts.append(s)
            ends.append(max(e, s))
            cid.append(c)
            prev = s
        spk.append(ch.get("speaker"))
    n = len(toks)
    if n == 0:
        return []
    nch = len(first)
    # Sonraki parçaya 80 ms kalana dek uzatılsa bile 700 ms gösterilemeyen parça "kısa"dır: sonrakiyle birleşir.
    # Son parça serbestçe uzatılabildiği için kısa sayılmaz.
    short = [c + 1 < nch and starts[first[c + 1]] - MIN_GAP_MS - starts[first[c]] < min_ms for c in range(nch)]

    def runs(j: int, i: int) -> list[list[str]]:
        """Bloğun sözcüklerini konuşmacı değişimlerinden gruplar (tek konuşmacı → tek grup)."""
        out = [[toks[j]]]
        for k in range(j + 1, i):
            if spk[cid[k]] != spk[cid[k - 1]]:
                out.append([toks[k]])
            else:
                out[-1].append(toks[k])
        return out

    def shape_cost(j: int, i: int) -> float | None:
        """Blok satırlara sığıyorsa satır düzeninin maliyeti (piramit, dengesizlik); sığmıyorsa None."""
        groups = runs(j, i)
        if len(groups) > 1:       # her konuşmacı "- " ile kendi satırında
            ok = len(groups) <= max_lines and all(len(_dash(g)) <= max_chars for g in groups)
            return 0.0 if ok else None
        lay = _layout([len(t) for t in toks[j:i]], max_chars, max_lines)
        if lay is None:
            return None
        pyramids, imbalance, _ = lay[0]
        return _COST_PYRAMID * pyramids + _COST_IMBALANCE * imbalance

    def merge_cost(j: int, i: int) -> float | None:
        """Blok parça sınırını aşıyorsa maliyeti; None → böyle blok kurulamaz.

        Yalnızca baştan (tamamı) alınmış kısa parça(lar) sonraki parçayla birleşir; sonraki parçanın yalnızca başı
        da alınabilir (kalanı sonraki blokta sürer). Konuşmacı değişiyorsa satır kuralı shape_cost'ta: her
        konuşmacı "- " ile tek satır.
        """
        cj, ci = cid[j], cid[i - 1]
        if cj == ci:
            return 0.0
        if j != first[cj] or not all(short[c] for c in range(cj, ci)):
            return None
        return _COST_MERGE * (ci - cj)

    def block_cost(j: int, i: int, chars: int) -> float:
        s, e = starts[j], ends[i - 1]
        cost = _COST_BLOCK + _COST_BALANCE * ((chars / cap) ** 2 + ((e - s) / max_ms) ** 2)
        if i < n:
            if starts[i] - MIN_GAP_MS - s < min_ms:       # uzatılsa bile 700 ms'ye ulaşamaz
                cost += _COST_SHORT
            if cid[i] == cid[i - 1]:                       # blok parçanın ortasında bitiyor
                last = toks[i - 1].rstrip(CLOSERS)
                if not last or last[-1] not in SENTENCE_END:
                    cost += _COST_BREAK_CLAUSE if last and last[-1] in PAUSE_PUNCT else _COST_BREAK_WORD
        return cost

    # 2) Dinamik programlama: best[i] = ilk i sözcüğün en ucuz bloklanışı, back[i] = son bloğun başı.
    best = [0.0] + [math.inf] * n
    back = [0] * (n + 1)
    for i in range(1, n + 1):
        chars = -1
        for j in range(i - 1, -1, -1):
            chars += len(toks[j]) + 1
            single = j == i - 1   # tek sözcük her zaman kabul: sığmasa da bölünemez
            if not single and (chars > cap or ends[i - 1] - starts[j] > max_ms):
                break             # sözcük eklendikçe uzunluk ve süre yalnızca artar
            extra = merge_cost(j, i)
            if extra is None:
                continue
            shape = 0.0 if single else shape_cost(j, i)
            if shape is None:
                continue
            cost = best[j] + extra + shape + block_cost(j, i, chars)
            if cost < best[i]:
                best[i], back[i] = cost, j

    # 3) Blokları geri kur, satırlara dök.
    blocks: list[list] = []
    i = n
    while i > 0:
        j = back[i]
        groups = runs(j, i)
        lines = [_dash(g) for g in groups] if len(groups) > 1 else _balanced_lines(groups[0], max_chars, max_lines)
        blocks.append([starts[j], ends[i - 1], lines])
        i = j
    blocks.reverse()

    # 4) Ardışık bloklar arasında en az 80 ms: gerekirse önceki bloğun sonu kırpılır.
    for a, b in zip(blocks, blocks[1:]):
        if b[0] - a[1] < MIN_GAP_MS:
            a[1] = max(a[0] + 1, b[0] - MIN_GAP_MS)
    # 5) Birleştirilemediği için kısa kalan blok, sonraki bloğa 80 ms kalana dek uzatılır (son blok serbestçe).
    for k, blk in enumerate(blocks):
        if blk[1] - blk[0] < min_ms:
            limit = blocks[k + 1][0] - MIN_GAP_MS if k + 1 < len(blocks) else math.inf
            blk[1] = max(blk[1], min(blk[0] + min_ms, limit))
    return [(int(s), int(e), lines) for s, e, lines in blocks]


# ---------------------------------------------------------------------------
# Dışa aktarma: SRT / VTT / JSON / LRC
# ---------------------------------------------------------------------------

def _stamp(ms: int, sep: str) -> str:
    """Milisaniye → "00:00:01,250" (SRT) ya da "00:00:01.250" (VTT)."""
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, frac = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{frac:03d}"


def _vtt_escape(line: str) -> str:
    """WebVTT'de "&", "<", ">" etiket/varlık başlatır; düz metin olarak kaçışlanır."""
    return line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render(timeline: list[dict], sep: str, escape=None, *, max_chars: int = 42, max_lines: int = 2,
            max_duration_s: float = 7.0) -> str:
    out: list[str] = []
    blocks = _blocks(timeline, max_chars=max_chars, max_lines=max_lines, max_duration_s=max_duration_s)
    for no, (s, e, lines) in enumerate(blocks, 1):
        body = "\n".join(escape(x) if escape else x for x in lines)
        out.append(f"{no}\n{_stamp(s, sep)} --> {_stamp(e, sep)}\n{body}\n\n")
    return "".join(out)


def to_srt(timeline: list[dict], *, max_chars: int = 42, max_lines: int = 2, max_duration_s: float = 7.0) -> str:
    """SubRip altyazı: numaralı bloklar, "00:00:01,250 --> 00:00:03,900", satır sonu LF, dosya boş satırla biter.

    Uzun parça sözcük sınırından bloklara, blok dengeli satırlara bölünür; bloklar arası en az 80 ms, blok en az
    700 ms (bkz. _blocks). Türkçe karakterler olduğu gibi kalır. Boş çizelge → "".
    """
    return _render(timeline, ",", max_chars=max_chars, max_lines=max_lines, max_duration_s=max_duration_s)


def to_vtt(timeline: list[dict], **kw) -> str:
    """WebVTT altyazı: "WEBVTT" başlığı + SRT ile aynı bloklar, zaman ondalığı noktalı ("00:00:01.250").
    kw: to_srt ile aynı (max_chars, max_lines, max_duration_s). Boş çizelge → "WEBVTT\\n\\n"."""
    return "WEBVTT\n\n" + _render(timeline, ".", _vtt_escape, **kw)


def to_json(timeline: list[dict]) -> str:
    """Zaman çizelgesinin JSON'u (Türkçe karakterler kaçışsız, 2 boşluk girinti)."""
    return json.dumps(list(timeline or []), ensure_ascii=False, indent=2)


def _lrc_stamp(seconds: float) -> str:
    cs = max(0, int(round(_num(seconds) * 100)))
    m, rem = divmod(cs, 6000)
    s, c = divmod(rem, 100)
    return f"[{m:02d}:{s:02d}.{c:02d}]"


def to_lrc(timeline: list[dict]) -> str:
    """Müzik uygulamaları için satır (parça) zamanlı LRC: "[mm:ss.xx]metin". Sonda, son parçanın bitişinde ekranı
    temizleyen boş zaman damgası bulunur. Boş çizelge → ""."""
    lines: list[str] = []
    last_end = 0
    for ch in _by_start(timeline):
        items = _chunk_words(ch)
        if not items:
            continue
        lines.append(_lrc_stamp(items[0][1] / 1000.0) + " ".join(t for t, _, _ in items))
        last_end = max(last_end, items[-1][2], _ms(ch.get("end")))
    if not lines:
        return ""
    lines.append(_lrc_stamp(last_end / 1000.0))
    return "\n".join(lines) + "\n"


def render(timeline: list[dict], fmt: str = "srt", **kw) -> str:
    """Biçim adına göre altyazı metni (API uç noktası için): "srt" | "vtt" | "json" | "lrc".
    kw yalnızca srt/vtt'ye geçer; Content-Type ve uzantı için SUBTITLE_FORMATS."""
    f = str(fmt or "srt").strip().lower().lstrip(".")
    if f == "srt":
        return to_srt(timeline, **kw)
    if f == "vtt":
        return to_vtt(timeline, **kw)
    if f == "json":
        return to_json(timeline)
    if f == "lrc":
        return to_lrc(timeline)
    raise ValueError(f"Bilinmeyen altyazı biçimi: {fmt!r} (srt, vtt, json ya da lrc olmalı)")
