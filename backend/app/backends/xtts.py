"""Coqui XTTS-v2 arka ucu — Chatterbox ile A/B kıyaslaması için (CPML: yalnızca ticari olmayan kullanım).

Gerçek API (idiap/coqui-ai-TTS ``dev`` dalı ve özgün coqui-ai/TTS kaynağından doğrulandı):

* Kurulum: ``pip install coqui-tts`` (idiap çatalı; Python 3.10–3.14). 0.27.4 sürümünden beri PyTorch pakete dahil
  değil, ayrıca kurulur (``pip install torch torchaudio``). Eski Python'da özgün paket: ``pip install TTS``.
* Yükleme: ``from TTS.api import TTS``; ``TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)``.
  ``TTS`` bir ``torch.nn.Module`` alt sınıfıdır; ``gpu=`` parametresi kullanımdan kalkıyor, ``.to(device)`` önerilir.
* Üretim: ``tts.tts(text=…, speaker=None, language=…, speaker_wav=…, emotion=None, split_sentences=True, **kwargs)``.
  Dönüş Python listesidir (öğeleri numpy sayıları; ``Synthesizer.tts`` içinde ``wavs += list(waveform)``). Fazladan
  anahtarlar (``speed``, ``temperature``, ``top_p`` …) ``Synthesizer.tts`` → ``Xtts.synthesize`` →
  ``inference_settings.update(kwargs)`` → ``Xtts.inference(..., speed=1.0, enable_text_splitting=False)`` yoluyla
  modele ulaşır. Özgün coqui-ai/TTS 0.22'de ``tts(..., speed=None, ...)`` açık parametredir ama modele İLETİLMEZ —
  bu yüzden ``speed`` imzaya göre süzülerek geçirilir ve özgün pakette etkisizdir.
* ``_check_arguments``: çok dilli modelde ``language`` yoksa ``ValueError``; ``speaker_wav`` denetlenmez — referans
  zorunluluğunu bu adaptör kendisi uygular (Türkçe hata).
* Örnekleme hızı: ``tts.synthesizer.output_sample_rate`` (XTTS-v2 için 24000; ``audio.output_sample_rate``).
* Diller (17): en, es, fr, de, it, pt, pl, tr, ru, nl, cs, ar, zh-cn, ja, hu, ko, hi — Türkçe (``tr``) VAR.
  Desteklenmeyen dilde ``Xtts.synthesize`` İngilizce bir assert fırlatır; bu adaptör önce Türkçe ``ValueError`` verir.
* Metin sınırı: XTTS belirteçleyicisi Türkçe için 226 karakter sınırı uygular (aşılırsa "truncated audio" uyarısı),
  GPT tarafı en çok 400 belirteç kabul eder. ``split_sentences=False`` bağlamı korur (daha tutarlı tonlama) ama uzun
  metinde sınırı aşabilir; bu yüzden parça dil sınırını aşıyorsa cümle bölme otomatik açılır. Motorun parçaları
  (``CHUNK_CHARS=170``) normalde sınırın altında kalır.
* ``Synthesizer.tts`` her cümlenin (sonuncusu dahil) ardına 10000 örneklik (~0,42 sn) sessizlik ekler; motor
  ``trim_silence`` ile baş/son sessizliği zaten kırpar.
* Lisans onayı: model ilk kez indirilirken ``ModelManager`` CPML onayını ``input()`` ile sorar (``[y/n]``); ret ya da
  etkileşimsiz ortam (sunucu, ``EOFError``) yüklemeyi düşürür. ``COQUI_TOS_AGREED=1`` ortam değişkeni soruyu atlar
  (CPML'yi kabul ettiğiniz anlamına gelir). Model diske indirildikten sonra soru bir daha sorulmaz.
* ``XTTS_MODEL`` bir klasörü gösteriyorsa (``model.pth`` + ``config.json``) indirme yapılmaz:
  ``TTS(model_path=klasör, config_path=klasör/config.json)``.

Motorla konuşulan yüz (``docs/SOZLESME3.md`` §2): ``sr``, ``generate(text, language_id, audio_prompt_path, speed)``
(açık parametreler; ``exaggeration``/``cfg_weight``/``temperature`` XTTS'te karşılığı olmadığı için TANIMLANMAZ,
motor bunları süzer), ``seed``. ``conds`` yoktur: XTTS her çağrıda referansı ``speaker_wav`` ile alır.
"""
from __future__ import annotations

import inspect
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

from .. import config
from ..tr import tr_lower
from . import BaseBackend, BackendUnavailable

log = logging.getLogger("sesklon.backends.xtts")

# XTTS-v2'nin desteklediği diller (model yapılandırmasındaki ``languages`` listesi)
XTTS_LANGUAGES: tuple[str, ...] = ("en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", "zh-cn",
                                   "ja", "hu", "ko", "hi")
# SesKlon dil kodu → XTTS dil kodu
_LANG_ALIASES = {"zh": "zh-cn", "zh-tw": "zh-cn"}
# XTTS belirteçleyicisinin dil başına karakter sınırı (TTS/tts/layers/xtts/tokenizer.py ``char_limits``)
CHAR_LIMITS = {"en": 250, "de": 253, "fr": 273, "es": 239, "it": 213, "pt": 203, "pl": 224, "zh-cn": 82, "ar": 166,
               "cs": 186, "ru": 182, "nl": 251, "tr": 226, "ja": 71, "hu": 224, "ko": 95, "hi": 150}
_DEFAULT_CHAR_LIMIT = 200
DEFAULT_SR = 24000


def _filter_kwargs(fn: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """``fn`` imzasında tanımlı anahtarları bırakır (``**kwargs`` kabul ediyorsa hepsini geçirir)."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return dict(kwargs)
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(kwargs)
    return {k: v for k, v in kwargs.items() if k in params}


def xtts_language(language_id: str | None) -> str:
    """SesKlon dil kodunu XTTS koduna çevirir (``"TR"`` → ``"tr"``, ``"zh"`` → ``"zh-cn"``)."""
    code = tr_lower(str(language_id or "")).strip().replace("_", "-")
    return _LANG_ALIASES.get(code, code)


class XttsBackend(BaseBackend):
    """Coqui XTTS-v2 (``TTS.api``) — sıfır atışlı ses klonlama; referans kayıt zorunlu."""

    name = "xtts"
    label = "Coqui XTTS-v2 (A/B için)"
    license = "CPML — yalnızca ticari olmayan kullanım"
    model_id = "xtts_v2"
    sr = DEFAULT_SR
    commercial = False
    supports_emotion_controls = False
    needs_torch = True
    required_modules = ("torch", "TTS")
    install_hint = "pip install coqui-tts  (Python ≥ 3.12 için idiap çatalı; eski Python'da: pip install TTS)"

    def __init__(self, device: str = "cpu") -> None:
        super().__init__(device)
        from TTS.api import TTS

        self.xtts_model: str = config.XTTS_MODEL
        if os.environ.get("COQUI_TOS_AGREED") != "1":
            log.info("COQUI_TOS_AGREED=1 tanımlı değil: model henüz indirilmediyse Coqui CPML lisans onayı "
                     "sorulacak (etkileşimsiz ortamda yükleme başarısız olur).")
        local = Path(self.xtts_model).expanduser()
        try:
            if local.is_dir():
                log.info("XTTS yerel klasörden yükleniyor: %s (cihaz=%s)", local, device)
                self.model = TTS(model_path=str(local), config_path=str(local / "config.json"))
            else:
                log.info("XTTS yükleniyor: %s (cihaz=%s)", self.xtts_model, device)
                self.model = TTS(self.xtts_model)
        except EOFError as e:        # ModelManager.ask_tos → input(): sunucuda stdin yok
            raise BackendUnavailable("XTTS lisans onayı (Coqui CPML) etkileşimsiz ortamda sorulamadı. Ticari olmayan "
                                     "CPML koşullarını kabul ediyorsanız COQUI_TOS_AGREED=1 ile yeniden başlatın.") from e
        except RuntimeError as e:
            if "terms of service" in str(e):
                raise BackendUnavailable("XTTS lisans onayı (Coqui CPML) verilmedi; model kullanılamaz. Kabul "
                                         "ediyorsanız COQUI_TOS_AGREED=1 tanımlayın.") from e
            raise
        self._move_to(device)
        synth = getattr(self.model, "synthesizer", None)
        self.sr = int(getattr(synth, "output_sample_rate", None) or DEFAULT_SR)
        self.model_id = self.xtts_model
        log.info("XTTS hazır: %s (sr=%d, cihaz=%s)", self.model_id, self.sr, self.device)

    def _move_to(self, device: str) -> None:
        """Modeli cihaza taşır; mps (ya da başka bir cihaz) sorun çıkarırsa cpu'ya düşer."""
        if not hasattr(self.model, "to"):
            return
        try:
            moved = self.model.to(device)
            if moved is not None:
                self.model = moved
        except Exception as e:  # noqa: BLE001 - XTTS'in bazı katmanları mps'te desteklenmiyor
            if device == "cpu":
                raise
            log.warning("XTTS '%s' cihazına taşınamadı (%s); cpu'ya düşülüyor.", device, e)
            moved = self.model.to("cpu")
            if moved is not None:
                self.model = moved
            self.device = "cpu"

    # --- motorun kullandığı yüz ---
    def languages(self) -> tuple[str, ...]:
        """Modelin bildirdiği diller (``TTS.languages``), yoksa XTTS-v2'nin sabit listesi."""
        try:
            langs = getattr(self.model, "languages", None)
        except Exception:  # noqa: BLE001 - özellik iç modele erişir; yüklenmemişse sabit liste
            langs = None
        if isinstance(langs, (list, tuple)) and langs:
            return tuple(str(x) for x in langs)
        return XTTS_LANGUAGES

    def seed(self, seed: int) -> None:
        """PyTorch tohumu; torch yoksa sessizce geçer (XTTS örneklemesi torch üretecini kullanır)."""
        try:
            import torch
        except ImportError:
            return
        manual_seed = getattr(torch, "manual_seed", None)
        if manual_seed is not None:
            manual_seed(int(seed))

    def generate(self, text: str, language_id: str = "tr", audio_prompt_path: str | None = None,
                 speed: float = 1.0) -> np.ndarray:
        """Tek parça üretir: ``tts.tts(text, speaker_wav, language, split_sentences, speed)`` → float32 mono."""
        if not audio_prompt_path:
            raise ValueError("XTTS referans kayıt olmadan konuşamaz: bir ses seçin ya da referans WAV yükleyin "
                             "(audio_prompt_path zorunlu).")
        ref = Path(str(audio_prompt_path)).expanduser()
        if not ref.is_file():
            raise FileNotFoundError(f"XTTS referans kaydı bulunamadı: {ref}")
        lang = xtts_language(language_id)
        desteklenen = self.languages()
        if lang not in desteklenen:
            raise ValueError(f"XTTS '{language_id}' dilini desteklemiyor. Desteklenen diller: {', '.join(desteklenen)}")
        split = len(text) > CHAR_LIMITS.get(lang, _DEFAULT_CHAR_LIMIT)
        if split:
            log.info("XTTS: parça %d karakter, '%s' sınırını aşıyor; cümle bölme açıldı.", len(text), lang)
        kwargs = _filter_kwargs(self.model.tts, {
            "text": text, "speaker_wav": str(ref), "language": lang, "split_sentences": split, "speed": float(speed),
        })
        wav = self.model.tts(**kwargs)
        return self.to_numpy(wav)

    def info(self) -> dict[str, Any]:
        d = super().info()
        d.update({"xtts_model": self.xtts_model})
        return d


__all__ = ["XttsBackend", "XTTS_LANGUAGES", "CHAR_LIMITS", "xtts_language"]
