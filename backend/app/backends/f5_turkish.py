"""F5-TTS Türkçe arka ucu (marduk-ra/F5-TTS-Turkish) — akış eşleme (flow matching) tabanlı A/B karşılaştırma modeli.

**Lisans:** ağırlıklar CC-BY-NC 4.0 (Mozilla Common Voice 17.0 ile eğitildi) → yalnızca ticari olmayan kullanım
(``commercial=False``). F5-TTS kodu MIT; SWivid'in temel ağırlıkları da CC-BY-NC (Emilia verisi).

Gerçek API (``SWivid/F5-TTS``, ``src/f5_tts/api.py`` — WebFetch ile doğrulandı, 2026-10)::

    from f5_tts.api import F5TTS
    F5TTS(model="F5TTS_v1_Base", ckpt_file="", vocab_file="", ode_method="euler", use_ema=True,
          vocoder_local_path=None, device=None, hf_cache_dir=None)
    wav, sr, spec = f5.infer(ref_file, ref_text, gen_text, show_info=print, progress=tqdm, target_rms=0.1,
                             cross_fade_duration=0.15, sway_sampling_coef=-1, cfg_strength=2, nfe_step=32,
                             speed=1.0, fix_duration=None, remove_silence=False, file_wave=None, file_spec=None,
                             seed=None)
    f5.transcribe(ref_audio, language=None)       # Whisper (openai/whisper-large-v3-turbo) ile transkript

* ``model`` yapılandırma adıdır (``configs/{model}.yaml``); ``ckpt_file`` boşsa SWivid'in temel ağırlıkları
  Hugging Face'ten indirilir — bu yüzden burada ``ckpt_file`` ve ``vocab_file`` ZORUNLUDUR. ``device=None`` ise
  F5 kendisi cuda → xpu → mps → cpu seçer; biz motorun seçtiği cihazı geçiririz.
* ``.safetensors`` ağırlıklar EMA anahtarları olarak yüklenir (``use_ema=True`` varsayılanı uygun).
* ``infer`` dönüşü ``(wav: np.ndarray, sr: int, spec)``; ``sr`` yapılandırmadaki ``target_sample_rate``
  (her iki temel yapılandırmada 24000, vocos vokoder). Metin parçası yoksa ``wav`` ``None`` olabilir.
* ``seed=None`` verilirse F5 her çağrıda rastgele tohum seçer (``seed_everything``); tekrarlanabilirlik için
  motorun tohumunu (``seed()`` ile saklanan) her ``infer``'e geçiririz.
* ``ref_text`` boşsa F5, referansı Whisper large-v3-turbo ile yazıya döker (dili otomatik sezer; ilk çağrıda
  ~1,6 GB model indirir, ek GPU belleği; CPU/mps'te saniyeler sürer). Biz önce ``transcribe(ref, language="tr")``
  ile Türkçe zorlayarak transkripti kendimiz çıkarır ve (yol, değişiklik zamanı) anahtarıyla önbelleğe alırız;
  bu başarısız olursa boş metni F5'e bırakırız (o da kendi ASR'sini çalıştırır). Hız ve doğruluk için
  ``ref_text`` vermek (kıyaslama betiği verebilir) her zaman daha iyidir.
* F5 (``utils_infer.preprocess_ref_audio_text``) referansı ≤ 12 sn'ye kırpar: önce
  ``split_on_silence(min_silence_len=1000, silence_thresh=-50, keep_silence=1000, seek_step=10)`` parçalarını
  toplam 6 sn'yi geçtikten sonra 12 sn'yi aşacak parçaya kadar biriktirir; hâlâ > 12 sn ise aynısını
  ``min_silence_len=100, silence_thresh=-40`` ile dener; yine uzunsa ilk 12 sn'yi keser; sonra kenar
  sessizliklerini (−42 dBFS) atıp 50 ms sessizlik ekler. **Verilen ``ref_text`` ise olduğu gibi kullanılır** —
  14 sn'lik bir kaydın tam transkripti, kırpılmış 12 sn'lik sesle eşleşmez (hizalama ve süre tahmini bozulur).
  Bu yüzden referans 12 sn'den uzunsa onu kendimiz AYNI mantıkla kırpar (``clip_reference``; pydub varsa birebir
  aynı çağrılar, yoksa numpy yaklaşımı), geçici WAV'ı (yol + değişiklik zamanı ile) önbelleğe alır, transkripti
  bu kırpılmış sesten çıkarır ve ``infer``'e de bu dosyayı veririz. F5'in kendi ön işlemi ≤ 12 sn'lik dosyada
  yalnızca uzun sessizlikleri kısaltır; metin sesle eşleşmeye devam eder. 5–10 sn temiz referans idealdir.
* Tohum tek kullanımlıktır: ``seed()`` ile verilen tohum yalnızca bir sonraki ``generate``'te kullanılır, sonra
  silinir. Motor tohumsuz isteklerde ``seed()`` çağırmaz; tohum kalıcı olsaydı önceki isteğin tohumu sonraki
  tohumsuz isteklere (ve QC'nin "tohum" yeniden denemesine) sızar, hep aynı ses üretilirdi. Tohum yoksa ``infer``'e
  ``seed`` hiç gönderilmez (F5 her çağrıda rastgele seçer).

Model kartı (huggingface.co/marduk-ra/F5-TTS-Turkish): dosyalar ``f5_tts_turkish_1000000.safetensors`` (ayrıca
``…_400000`` ve ``…_650000`` ara adımları, her biri ~1,35 GB) ve ``vocab.txt``; temel model ``SWivid/F5-TTS``;
"nfe adımını 64 yapmak daha kaliteli ses verir" notu (``F5_TR_NFE=64``). Kart yapılandırma adını belirtmez.
**Dikkat:** ağırlıklar 2024-11-15/16'da yüklendi, ``F5TTS_v1_Base`` ise 2025-03'te yayımlandı; yani ağırlıklar
büyük olasılıkla eski ``F5TTS_Base`` yapılandırmasıyla (``text_mask_padding=False``, ``pe_attn_head=1``) eğitildi.
Katman boyutları iki yapılandırmada aynı olduğundan v1 yapılandırması da hatasız yüklenir ama çıktı bozulabilir.
Yapılandırma adı ``F5_TR_MODEL`` ortam değişkeniyle seçilir; varsayılan sözleşmedeki ``F5TTS_v1_Base``'dir —
çıktı bozuksa ``F5_TR_MODEL=F5TTS_Base`` deneyin.

Motorla konuşulan yüz (``docs/SOZLESME3.md`` §2): ``sr``, ``generate(...)`` (açık parametreler; ``exaggeration`` /
``cfg_weight`` / ``temperature`` / ``emotion`` TANIMLANMAZ — motor bunları süzer), ``seed``.
"""
from __future__ import annotations

import inspect
import logging
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from .. import config
from ..tr import tr_lower
from . import BackendUnavailable, BaseBackend

log = logging.getLogger("sesklon.backends.f5")

INDIRME_IPUCU = ("Ağırlıkları huggingface.co/marduk-ra/F5-TTS-Turkish adresinden indirin "
                 "(f5_tts_turkish_1000000.safetensors ve vocab.txt) ve yollarını F5_TR_CKPT / F5_TR_VOCAB "
                 "ortam değişkenlerine yazın.")
VARSAYILAN_MODEL = "F5TTS_v1_Base"
VARSAYILAN_NFE = 32
# F5'in referans kırpma mantığı (utils_infer.preprocess_ref_audio_text) — milisaniye / dBFS
F5_REF_MAX_MS = 12000
F5_REF_MIN_MS = 6000
# (min_silence_len, silence_thresh): önce uzun ve derin sessizlikler, olmazsa kısa ve sığ sessizlikler
F5_SPLIT_ADIMLARI = ((1000, -50), (100, -40))
F5_KEEP_SILENCE_MS = 1000
F5_KENAR_ESIK_DB = -42
F5_SON_SESSIZLIK_MS = 50
_ADIM_MS = 10          # pydub seek_step ile aynı çözünürlük


def _biriktir(parcalar: list, uzunluk, bos, birlestir=lambda a, b: a + b):
    """F5'in döngüsü: 6 sn'yi geçtikten sonra 12 sn'yi aşacak ilk parçada durur (uzunluklar ms)."""
    dalga = bos
    for parca in parcalar:
        if uzunluk(dalga) > F5_REF_MIN_MS and uzunluk(dalga) + uzunluk(parca) > F5_REF_MAX_MS:
            break
        dalga = birlestir(dalga, parca)
    return dalga


def _kirp_pydub(kaynak: str, hedef: Path) -> float:
    """``preprocess_ref_audio_text``'in birebir aynısı (pydub ile); dönüş: kırpılmış süre (sn)."""
    from pydub import AudioSegment, silence

    aseg = AudioSegment.from_file(kaynak)
    dalga = aseg
    for min_sessizlik, esik in F5_SPLIT_ADIMLARI:
        parcalar = silence.split_on_silence(aseg, min_silence_len=min_sessizlik, silence_thresh=esik,
                                            keep_silence=F5_KEEP_SILENCE_MS, seek_step=_ADIM_MS)
        dalga = _biriktir(parcalar, len, AudioSegment.silent(duration=0))
        if len(dalga) <= F5_REF_MAX_MS:
            break
    if len(dalga) > F5_REF_MAX_MS:
        dalga = dalga[:F5_REF_MAX_MS]
    bas = silence.detect_leading_silence(dalga, silence_threshold=F5_KENAR_ESIK_DB)
    dalga = dalga[bas:]
    son = silence.detect_leading_silence(dalga.reverse(), silence_threshold=F5_KENAR_ESIK_DB)
    if son > 0:
        dalga = dalga[: len(dalga) - son]
    dalga = dalga + AudioSegment.silent(duration=F5_SON_SESSIZLIK_MS, frame_rate=dalga.frame_rate)
    dalga.export(str(hedef), format="wav")
    return len(dalga) / 1000.0


def _kare_db(x: np.ndarray, sr: int, pencere_ms: int) -> np.ndarray:
    """Her ``_ADIM_MS`` adımda başlayan ``pencere_ms``'lik pencerenin dBFS değeri (pydub'ın yaklaşığı)."""
    adim = max(1, sr * _ADIM_MS // 1000)
    pencere = max(1, sr * pencere_ms // 1000)
    if len(x) < pencere:
        return np.zeros(0)
    kare = np.concatenate([[0.0], np.cumsum(x.astype(np.float64) ** 2)])
    basl = np.arange(0, len(x) - pencere + 1, adim)
    rms = np.sqrt((kare[basl + pencere] - kare[basl]) / pencere)
    return 20 * np.log10(np.maximum(rms, 1e-10))


def _sessiz_olmayan_parcalar(x: np.ndarray, sr: int, min_sessizlik: int, esik: float) -> list[np.ndarray]:
    """``pydub.silence.split_on_silence`` yaklaşığı (keep_silence dahil; komşu parçalar sessizliği paylaşır)."""
    db = _kare_db(x, sr, min_sessizlik)
    ms = lambda i: i * sr // 1000  # noqa: E731 - ms → örnek
    sessiz: list[list[int]] = []                       # [başlangıç_ms, bitiş_ms]
    for i in np.flatnonzero(db < esik):
        bas = int(i) * _ADIM_MS
        if sessiz and bas <= sessiz[-1][1]:
            sessiz[-1][1] = bas + min_sessizlik
        else:
            sessiz.append([bas, bas + min_sessizlik])
    toplam_ms = len(x) * 1000 // sr
    araliklar, onceki = [], 0
    for bas, bit in sessiz:
        if bas > onceki:
            araliklar.append([onceki, bas])
        onceki = bit
    if onceki < toplam_ms:
        araliklar.append([onceki, toplam_ms])
    if not araliklar:
        return []
    genis = [[max(0, b - F5_KEEP_SILENCE_MS), min(toplam_ms, e + F5_KEEP_SILENCE_MS)] for b, e in araliklar]
    for a, b in zip(genis, genis[1:]):                 # örtüşen tutulan sessizlik ortadan bölünür
        if a[1] > b[0]:
            orta = (a[1] + b[0]) // 2
            a[1], b[0] = orta, orta
    return [x[ms(b):ms(e)] for b, e in genis]


def _kirp_numpy(kaynak: str, hedef: Path) -> float:
    """pydub yoksa aynı mantığın numpy yaklaşığı (soundfile ile okur/yazar)."""
    import soundfile as sf

    x, sr = sf.read(kaynak, dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    uzunluk = lambda d: len(d) * 1000 // sr  # noqa: E731
    dalga = x
    for min_sessizlik, esik in F5_SPLIT_ADIMLARI:
        parcalar = _sessiz_olmayan_parcalar(x, sr, min_sessizlik, esik)
        dalga = _biriktir(parcalar, uzunluk, np.zeros(0, dtype=np.float32),
                          lambda a, b: np.concatenate([a, b]))
        if uzunluk(dalga) <= F5_REF_MAX_MS:
            break
    if uzunluk(dalga) > F5_REF_MAX_MS:
        dalga = dalga[: F5_REF_MAX_MS * sr // 1000]
    db = _kare_db(dalga, sr, _ADIM_MS)
    sesli = np.flatnonzero(db >= F5_KENAR_ESIK_DB)
    if sesli.size:
        adim = sr * _ADIM_MS // 1000
        dalga = dalga[int(sesli[0]) * adim: (int(sesli[-1]) + 1) * adim]
    dalga = np.concatenate([dalga, np.zeros(F5_SON_SESSIZLIK_MS * sr // 1000, dtype=np.float32)])
    sf.write(str(hedef), dalga, sr, subtype="PCM_16")
    return len(dalga) / sr


def ses_suresi(yol: str) -> float | None:
    """Ses dosyasının süresi (sn); okunamazsa ``None``."""
    try:
        import soundfile as sf

        return float(sf.info(yol).duration)
    except Exception:  # noqa: BLE001 - biçim soundfile ile okunamıyorsa pydub denenir
        pass
    try:
        from pydub import AudioSegment

        return len(AudioSegment.from_file(yol)) / 1000.0
    except Exception:  # noqa: BLE001
        return None


def _filter_kwargs(fn: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """``fn`` imzasında tanımlı anahtarları bırakır (``**kwargs`` kabul ediyorsa hepsini geçirir)."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return dict(kwargs)
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(kwargs)
    return {k: v for k, v in kwargs.items() if k in params}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        log.warning("%s tamsayı olmalı; varsayılan %d kullanılıyor", name, default)
        return default


def _f5_bilgi(msg: Any) -> None:
    """F5'in ``show_info`` çıktısını (normalde print) log'a yönlendirir."""
    log.debug("F5: %s", msg)


class F5TurkishBackend(BaseBackend):
    """F5-TTS Türkçe ince ayarı (marduk-ra) — referans kaydı + (isteğe bağlı) transkriptiyle sıfır atışlı klon."""

    name = "f5-tr"
    label = "F5-TTS Türkçe (akış eşleme, A/B için)"
    license = "CC-BY-NC 4.0 — yalnızca ticari olmayan kullanım (Common Voice ile eğitildi)"
    model_id = "f5-tts-turkish"
    sr = 24000
    commercial = False
    supports_emotion_controls = False
    needs_torch = True
    required_modules = ("torch", "f5_tts")
    install_hint = ("pip install f5-tts  (ağırlıklar: huggingface.co/marduk-ra/F5-TTS-Turkish → "
                    "F5_TR_CKPT, F5_TR_VOCAB)")

    def __init__(self, device: str = "cpu") -> None:
        super().__init__(device)
        if not config.F5_TR_CKPT:
            raise BackendUnavailable(f"F5_TR_CKPT ortam değişkeni boş: F5-TTS Türkçe ağırlık dosyası "
                                     f"(.safetensors) gerekli. {INDIRME_IPUCU}")
        if not config.F5_TR_VOCAB:
            raise BackendUnavailable(f"F5_TR_VOCAB ortam değişkeni boş: F5-TTS Türkçe sözlük dosyası (vocab.txt) "
                                     f"gerekli. {INDIRME_IPUCU}")
        ckpt = Path(config.F5_TR_CKPT).expanduser()
        vocab = Path(config.F5_TR_VOCAB).expanduser()
        if not ckpt.is_file():
            raise FileNotFoundError(f"F5-TTS Türkçe ağırlık dosyası bulunamadı: {ckpt} (F5_TR_CKPT). {INDIRME_IPUCU}")
        if not vocab.is_file():
            raise FileNotFoundError(f"F5-TTS Türkçe sözlük dosyası bulunamadı: {vocab} (F5_TR_VOCAB). {INDIRME_IPUCU}")

        from f5_tts.api import F5TTS

        self.ckpt = str(ckpt)
        self.vocab = str(vocab)
        self.config_name = os.getenv("F5_TR_MODEL", "").strip() or VARSAYILAN_MODEL
        self.nfe_step = _env_int("F5_TR_NFE", VARSAYILAN_NFE)
        self._seed: int | None = None
        self._ref_text_cache: dict[tuple[str, float], str] = {}
        self._clip_cache: dict[tuple[str, float], str] = {}
        self.clip_dir = Path(tempfile.gettempdir()) / "sesklon-f5-ref"     # kırpılmış referansların önbelleği
        self.model_id = f"f5-tts-turkish:{ckpt.name}"

        log.info("F5-TTS Türkçe yükleniyor: %s (yapılandırma=%s, cihaz=%s)", ckpt, self.config_name, device)
        kwargs = _filter_kwargs(F5TTS, {"model": self.config_name, "ckpt_file": self.ckpt,
                                        "vocab_file": self.vocab, "device": device})
        self._model = F5TTS(**kwargs)
        self.sr = int(getattr(self._model, "target_sample_rate", None) or 24000)
        log.info("F5-TTS Türkçe hazır: %s (sr=%d, nfe=%d)", self.model_id, self.sr, self.nfe_step)

    # --- motorun kullandığı yüz ---
    def seed(self, seed: int) -> None:
        """Tohumu bir sonraki ``generate`` için saklar (tek kullanımlık) ve varsa PyTorch tohumunu da verir."""
        self._seed = int(seed)
        try:
            import torch
        except ImportError:
            return
        manual_seed = getattr(torch, "manual_seed", None)
        if callable(manual_seed):
            manual_seed(self._seed)

    def clip_reference(self, ref_path: str) -> str:
        """Referans F5'in 12 sn sınırından uzunsa F5'in mantığıyla kırpılmış geçici WAV'ın yolunu döndürür.

        Kısa (≤ 12 sn) ya da süresi okunamayan referans olduğu gibi döner. Kırpılmış dosya yol + değişiklik zamanı
        ile önbelleğe alınır (aynı dosya için tekrar kırpılmaz, transkript önbelleği de korunur).
        """
        try:
            mtime = Path(ref_path).stat().st_mtime
        except OSError:
            return ref_path
        key = (ref_path, mtime)
        onceki = self._clip_cache.get(key)
        if onceki and Path(onceki).is_file():
            return onceki
        sure = ses_suresi(ref_path)
        if sure is None or sure * 1000 <= F5_REF_MAX_MS:
            return ref_path
        self.clip_dir.mkdir(parents=True, exist_ok=True)
        ozet = hashlib.sha1(f"{ref_path}|{mtime}".encode("utf-8")).hexdigest()[:12]
        hedef = self.clip_dir / f"{Path(ref_path).stem}_{ozet}_12sn.wav"
        try:
            try:
                yeni_sure = _kirp_pydub(ref_path, hedef)
            except ImportError:
                yeni_sure = _kirp_numpy(ref_path, hedef)
        except Exception as e:  # noqa: BLE001 - kırpılamazsa F5 kendisi kırpar (transkript uyumsuz kalabilir)
            log.warning("Referans 12 sn'ye kırpılamadı (%s): %s — F5 kendisi kırpacak", ref_path, e)
            return ref_path
        log.info("Referans %.1f sn > 12 sn: F5 mantığıyla %.1f sn'ye kırpıldı → %s", sure, yeni_sure, hedef)
        self._clip_cache[key] = str(hedef)
        return str(hedef)

    def transcript_for(self, ref_path: str) -> str:
        """Referansın Türkçe transkripti (Whisper; yavaş). Yol + değişiklik zamanı ile önbellekte tutulur.

        Çıkarılamazsa boş metin döner; ``infer`` o zaman F5'in kendi ASR'sini (dil otomatik) çalıştırır.
        """
        try:
            key = (ref_path, Path(ref_path).stat().st_mtime)
        except OSError:
            key = (ref_path, 0.0)
        if key in self._ref_text_cache:
            return self._ref_text_cache[key]
        transcribe = getattr(self._model, "transcribe", None)
        if not callable(transcribe):
            return ""
        log.info("Referans transkripti yok; Whisper ile çıkarılıyor (yavaş): %s", ref_path)
        try:
            metin = transcribe(ref_path, **_filter_kwargs(transcribe, {"language": "tr"}))
        except Exception as e:  # noqa: BLE001 - F5 kendi ASR'siyle yine dener
            log.warning("Referans yazıya dökülemedi (%s); F5 kendi ASR'sini çalıştıracak", e)
            return ""
        metin = str(metin or "").strip()
        if metin:
            self._ref_text_cache[key] = metin
        return metin

    def generate(self, text: str, language_id: str = "tr", audio_prompt_path: str | None = None,
                 ref_text: str = "", speed: float = 1.0) -> np.ndarray:
        """Referans kaydın sesiyle ``text``'i üretir.

        ``audio_prompt_path`` zorunludur (F5'in varsayılan sesi yoktur). ``ref_text`` referansın transkriptidir;
        boşsa Whisper ile çıkarılır (yavaş, ilk çağrıda ASR modeli indirilir) — kıyaslama betiği hazır metni
        geçirebilir. ``language_id`` "tr" değilse uyarılır ama yine üretilir (model yalnızca Türkçe eğitildi).

        Referans 12 sn'den uzunsa F5'in mantığıyla kırpılır ve hem transkript hem ``infer`` kırpılmış dosyayı
        kullanır; bu durumda verilen ``ref_text`` tam kayda ait olduğundan yok sayılır (uyarı loglanır).
        ``seed()`` ile verilen tohum yalnızca bu çağrıda kullanılır ve silinir; tohum yoksa F5 rastgele seçer.
        """
        if not audio_prompt_path:
            raise ValueError("F5-TTS referans kaydı olmadan üretemez: audio_prompt_path (bir ses klonu) gerekli.")
        if not str(text or "").strip():
            raise ValueError("F5-TTS için üretilecek metin boş.")
        dil = tr_lower(str(language_id or "tr")).strip()
        if dil != "tr":
            log.warning("F5-TTS Türkçe modeli yalnızca Türkçe ile eğitildi; '%s' dili için çıktı kötü olabilir", dil)
        tohum, self._seed = self._seed, None          # tek kullanımlık: sonraki tohumsuz isteklere sızmasın
        tam = str(audio_prompt_path)
        ref = self.clip_reference(tam)
        ref_text = str(ref_text or "").strip()
        if ref_text and ref != tam:
            log.warning("Referans 12 sn'den uzun ve kırpıldı; verilen ref_text tam kayda ait olduğu için yok "
                        "sayılıyor, transkript kırpılmış sesten çıkarılacak")
            ref_text = ""
        ref_text = ref_text or self.transcript_for(ref)
        istek: dict[str, Any] = {
            "ref_file": ref, "ref_text": ref_text, "gen_text": text, "show_info": _f5_bilgi,
            "nfe_step": int(self.nfe_step), "speed": float(speed), "remove_silence": False,
        }
        if tohum is not None:
            istek["seed"] = tohum
        kwargs = _filter_kwargs(self._model.infer, istek)
        sonuc = self._model.infer(**kwargs)
        wav, sr = sonuc[0], sonuc[1]
        if wav is None:
            raise RuntimeError(f"F5-TTS ses üretmedi (metin parçalanamadı): {text[:60]!r}")
        if sr:
            self.sr = int(sr)
        return self.to_numpy(wav)

    def info(self) -> dict[str, Any]:
        d = super().info()
        d.update({"ckpt": self.ckpt, "vocab": self.vocab, "ref_text_required": True,
                  "config": self.config_name, "nfe_step": self.nfe_step})
        return d


__all__ = ["F5TurkishBackend", "ses_suresi"]
