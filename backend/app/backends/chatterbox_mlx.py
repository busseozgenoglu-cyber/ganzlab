"""Chatterbox Multilingual (MLX, Apple Silicon) arka ucu — PyTorch/mps hızını (≈ 4,6× gerçek zaman) düşürmek için.

mlx-audio API'si (doğrulama: ``Blaizzy/mlx-audio`` ``main`` dalı, ``mlx_audio/version.py`` → ``0.5.8``; 2026-10):

* Yükleme — ``mlx_audio/tts/utils.py``: ``load_model(model_path, lazy=False, strict=True, **kwargs) -> nn.Module``.
  Hugging Face kimliği ya da yerel yol alır (``mlx-community/chatterbox-multilingual-v3``; v2 için
  ``mlx-community/chatterbox-fp16``). Model sınıfı ``config.json``'daki ``model_type``'tan seçilir; yüklemeden sonra
  ``Model.post_load_hook`` klasördeki ``conds.safetensors``'u varsayılan (klonsuz) ses koşulu olarak ``_conds``'a koyar.
* Model — ``mlx_audio/tts/models/chatterbox/chatterbox.py`` (``class Model(nn.Module)``):
  ``self.sr = S3GEN_SR`` (24000) ve ``sample_rate`` özelliği (24000).
* Üretim imzası (aynı dosya)::

      generate(self, text, audio_prompt=None, audio_prompt_sr=None, conds=None, exaggeration=0.1, cfg_weight=0.5,
               temperature=0.8, repetition_penalty=1.2, min_p=0.05, top_p=1.0, max_new_tokens=1000,
               ref_audio=None, voice=None, speed=1.0, lang_code="en", max_tokens=None, verbose=True,
               stream=False, streaming_interval=2.0, **kwargs) -> Generator[GenerationResult, None, None]

  - Referans: ``ref_audio`` (dosya yolu ya da dizi; yol ise ``load_audio`` ile 24 kHz okunur). ``audio_prompt``
    KULLANILMAZ: yalnızca dizi + ``audio_prompt_sr`` ile çalışır, ``sr`` verilmezse referansı sessizce yok sayar.
  - Dil: ``lang_code`` (varsayılan ``"en"``!). İmzada ``**kwargs`` olduğundan ``language_id`` gibi yanlış bir ad hata
    vermeden YUTULUR ve model İngilizce okur — bu yüzden ad eşlemesi açık parametrelerden yapılır.
  - ``verbose=True`` varsayılanı her çağrıda konsola döküm basar; burada ``verbose=False`` geçilir.
  - Referanslı çağrı koşulları her seferinde yeniden hesaplar ve modelin varsayılan ``_conds``'unu EZMEZ; bu yüzden
    PyTorch'taki gibi ``conds`` geri yükleme gerekmez (MLX modelinde genel ``conds`` özniteliği de yok).
* Sonuç — ``mlx_audio/tts/models/base.py``: ``GenerationResult(audio: mx.array, samples, sample_rate, segment_idx,
  token_count, audio_duration, real_time_factor, prompt, audio_samples, processing_time_seconds, peak_memory_usage,
  is_streaming_chunk=False, is_final_chunk=False)``. Chatterbox tek parça üretir ama üreteç döndürür; burada tüm
  parçaların ``.audio``'su birleştirilir.

İmza sürümden sürüme değişebileceği için parametre adları çalışma zamanında ``inspect.signature`` ile seçilir:
referans için ``ref_audio`` → ``audio_prompt_path`` → ``speaker_wav``, dil için ``lang_code`` → ``language`` →
``language_id``; ilk bulunan açık parametre kullanılır. Hiçbiri açık değilse ve imza ``**kwargs`` alıyorsa mlx-audio'nun
standart adları (``ref_audio``, ``lang_code``) gönderilir. İmzada olmayan ad asla gönderilmez.

Sınırlar: ``T3_FINETUNED`` (PyTorch ince ayar ağırlıkları) bu arka uca uygulanmaz — uyarı loglanır. ``T3_EMOTION_TAGS``
açıkken ``[duygu] `` öneki PyTorch arka ucuyla aynı kuralla eklenir.

Sözleşme: ``docs/SOZLESME3.md`` §2.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any

import numpy as np

from .. import config
from ..tr import tr_lower
from . import BackendUnavailable, BaseBackend

log = logging.getLogger("sesklon.backends.chatterbox_mlx")

VARSAYILAN_SR = 24000
# İç ``generate``'in sürüme göre değişebilen parametre adları (öncelik sırasıyla; ilki mlx-audio'nun gerçek adı)
REF_ADAYLARI = ("ref_audio", "audio_prompt_path", "speaker_wav")
DIL_ADAYLARI = ("lang_code", "language", "language_id")


def _imza(fn: Any) -> tuple[set[str], bool]:
    """(açık parametre adları, ``**kwargs`` alıyor mu). İmza okunamazsa (boş küme, True) — standart adlar gider."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return set(), True
    acik = {ad for ad, p in params.items()
            if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)}
    return acik, any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())


def _ad_sec(adaylar: tuple[str, ...], acik: set[str], var_kw: bool) -> str | None:
    """Adaylardan imzada açıkça bulunan ilkini; yoksa ``**kwargs`` varsa standart adı (ilk aday); yoksa ``None``."""
    for ad in adaylar:
        if ad in acik:
            return ad
    return adaylar[0] if var_kw else None


def _parcalar(cikti: Any) -> list[Any]:
    """İç ``generate`` dönüşünü parça listesine çevirir: üreteç/liste → parçalar, tek sonuç ya da dizi → [o]."""
    if cikti is None:
        return []
    if hasattr(cikti, "audio"):                       # tek GenerationResult
        return [cikti]
    if isinstance(cikti, (list, tuple)) and cikti and all(hasattr(p, "audio") for p in cikti):
        return list(cikti)
    if inspect.isgenerator(cikti) or (hasattr(cikti, "__next__") and hasattr(cikti, "__iter__")):
        return list(cikti)
    return [cikti]                                    # doğrudan dalga biçimi (mx.array / ndarray / liste)


def _yeniden_ornekle(x: np.ndarray, kaynak_sr: int, hedef_sr: int) -> np.ndarray:
    """Basit doğrusal yeniden örnekleme (yalnızca beklenmedik örnekleme hızı uyuşmazlığında)."""
    if kaynak_sr == hedef_sr or x.size == 0:
        return x
    n = max(1, int(round(len(x) * hedef_sr / kaynak_sr)))
    eski = np.linspace(0.0, 1.0, num=len(x), endpoint=False)
    yeni = np.linspace(0.0, 1.0, num=n, endpoint=False)
    return np.interp(yeni, eski, x).astype(np.float32)


class ChatterboxMlxBackend(BaseBackend):
    """Chatterbox Multilingual V3 — mlx-audio (MIT) üzerinden Apple Silicon'da (Metal) yerel çalışır; torch gerekmez."""

    name = "chatterbox-mlx"
    label = "Chatterbox Multilingual (MLX, Apple Silicon)"
    license = "MIT — ticari kullanım serbest"
    model_id = ""
    sr = VARSAYILAN_SR
    commercial = True
    supports_emotion_controls = True
    needs_torch = False
    required_modules = ("mlx", "mlx_audio")
    install_hint = "pip install mlx-audio"

    def __init__(self, device: str = "mlx") -> None:
        super().__init__("mlx")                       # MLX cihaz seçmez: birleşik bellek + Metal
        if device not in (None, "", "mlx", "cpu", "mps"):
            log.info("MLX arka ucu cihaz seçimini yok sayar (istenen: %s); Metal kullanılır.", device)
        try:
            from mlx_audio.tts.utils import load_model
        except ImportError as e:
            raise BackendUnavailable(f"mlx-audio içe aktarılamadı ({e}). Kurulum: {self.install_hint} "
                                     f"(yalnızca Apple Silicon / macOS).") from e

        self.mlx_model: str = config.MLX_MODEL
        self.model_id = self.mlx_model
        if config.T3_FINETUNED:
            log.warning("T3_FINETUNED (%s) MLX arka ucuna uygulanmaz; ince ayarlı model için 'chatterbox' (PyTorch) "
                        "arka ucunu kullanın ya da ağırlıkları MLX'e dönüştürüp MLX_MODEL ile gösterin.",
                        config.T3_FINETUNED)
        log.info("Chatterbox Multilingual (MLX) yükleniyor: %s", self.mlx_model)
        try:
            self._model = load_model(self.mlx_model)
        except Exception as e:  # noqa: BLE001 - ağ / eksik dosya / desteklenmeyen model: Türkçe mesajla yeniden fırlat
            raise RuntimeError(f"MLX modeli yüklenemedi ({self.mlx_model}): {e}. MLX_MODEL bir mlx-community "
                               f"kimliği (örn. mlx-community/chatterbox-multilingual-v3) ya da yerel klasör olmalı.") from e
        sr = getattr(self._model, "sample_rate", None) or getattr(self._model, "sr", None) or VARSAYILAN_SR
        try:
            self.sr = int(sr)
        except (TypeError, ValueError):
            self.sr = VARSAYILAN_SR
        log.info("Chatterbox MLX hazır: %s (sr=%d)", self.model_id, self.sr)

    # --- isteğe bağlı ``conds``: yalnızca iç modelde varsa görünür (motor ``hasattr`` ile bakar) ---
    def __getattr__(self, ad: str) -> Any:
        # yalnızca normal arama başarısız olunca çağrılır
        if ad == "conds":
            ic = self.__dict__.get("_model")
            if ic is not None and hasattr(ic, "conds"):
                return ic.conds
        raise AttributeError(f"'{type(self).__name__}' nesnesinde '{ad}' özniteliği yok")

    def __setattr__(self, ad: str, deger: Any) -> None:
        if ad == "conds":
            ic = self.__dict__.get("_model")
            if ic is None or not hasattr(ic, "conds"):
                raise AttributeError("MLX modeli 'conds' desteklemiyor (referanslı üretim varsayılan sesi ezmez)")
            ic.conds = deger
            return
        super().__setattr__(ad, deger)

    def seed(self, seed: int) -> None:
        """MLX'in kendi rastgele üreteci; mlx yoksa sessizce geçer."""
        try:
            import mlx.core as mx
        except ImportError:
            return
        tohumla = getattr(getattr(mx, "random", None), "seed", None)
        if callable(tohumla):
            tohumla(int(seed))

    @staticmethod
    def tag_text(text: str, emotion: str | None) -> str:
        """``T3_EMOTION_TAGS`` açıkken ``"[mutlu] Merhaba"`` biçiminde duygu öneki (PyTorch arka ucuyla aynı kural).

        ``normal`` ve boş duygu etiket almaz; metin zaten bu etiketle başlıyorsa ikinci kez eklenmez.
        """
        if not config.T3_EMOTION_TAGS or not emotion:
            return text
        tag = tr_lower(str(emotion)).strip()
        if not tag or tag == "normal":
            return text
        if text.lstrip().startswith(f"[{tag}]"):
            return text
        return f"[{tag}] {text}"

    def _ic_parametreler(self, language_id: str, exaggeration: float, cfg_weight: float, temperature: float,
                         audio_prompt_path: Any) -> dict[str, Any]:
        """İç ``generate`` imzasına göre ad eşlemesi; imzada olmayan ad gönderilmez."""
        acik, var_kw = _imza(self._model.generate)
        kw: dict[str, Any] = {}
        dil_adi = _ad_sec(DIL_ADAYLARI, acik, var_kw)
        if dil_adi:
            kw[dil_adi] = language_id
        if audio_prompt_path:
            ref_adi = _ad_sec(REF_ADAYLARI, acik, var_kw)
            if ref_adi is None:
                log.warning("MLX modelinin generate imzasında referans parametresi yok (%s); klon referansı "
                            "kullanılamadı, varsayılan sesle üretiliyor.", ", ".join(REF_ADAYLARI))
            else:
                kw[ref_adi] = str(audio_prompt_path)
        for ad, deger in (("exaggeration", float(exaggeration)), ("cfg_weight", float(cfg_weight)),
                          ("temperature", float(temperature))):
            if ad in acik or var_kw:
                kw[ad] = deger
        if "verbose" in acik:
            kw["verbose"] = False                     # mlx-audio her çağrıda döküm basmasın
        return kw

    def _numpy(self, ses: Any) -> np.ndarray:
        """mx.array → float32: önce doğrudan ``np.asarray`` (hızlı, tampon protokolü), olmazsa ``tolist`` yolu."""
        if ses is not None and not hasattr(ses, "detach") and not isinstance(ses, np.ndarray):
            try:
                x = np.asarray(ses, dtype=np.float32)
                if x.ndim >= 1:
                    return self.to_numpy(x)
            except (TypeError, ValueError, RuntimeError):
                pass                                  # örn. bfloat16 ya da __array__ desteklemeyen dizi
        return self.to_numpy(ses)

    def generate(self, text: str, language_id: str = "tr", exaggeration: float = 0.5, cfg_weight: float = 0.5,
                 temperature: float = 0.8, audio_prompt_path: str | None = None,
                 emotion: str | None = None) -> np.ndarray:
        """Tek parça üretir; mlx-audio üretecinin tüm parçalarını birleştirip mono float32 döndürür."""
        text = self.tag_text(text, emotion)
        kwargs = self._ic_parametreler(language_id, exaggeration, cfg_weight, temperature, audio_prompt_path)
        parcalar = []
        for parca in _parcalar(self._model.generate(text, **kwargs)):
            ses = getattr(parca, "audio", parca)
            if ses is None:
                continue
            x = self._numpy(ses).reshape(-1)
            parca_sr = getattr(parca, "sample_rate", None)
            if parca_sr and int(parca_sr) != int(self.sr):
                log.warning("MLX çıktısının örnekleme hızı (%s) beklenenden (%d) farklı; yeniden örnekleniyor.",
                            parca_sr, self.sr)
                x = _yeniden_ornekle(x, int(parca_sr), int(self.sr))
            parcalar.append(x)
        if not parcalar:
            raise RuntimeError(f"MLX modeli ses üretmedi (metin: {text[:40]!r}).")
        wav = parcalar[0] if len(parcalar) == 1 else np.concatenate(parcalar)
        return np.ascontiguousarray(wav, dtype=np.float32)

    def info(self) -> dict[str, Any]:
        d = super().info()
        d.update({"mlx_model": config.MLX_MODEL, "emotion_tags": bool(config.T3_EMOTION_TAGS)})
        return d


__all__ = ["ChatterboxMlxBackend", "REF_ADAYLARI", "DIL_ADAYLARI"]
