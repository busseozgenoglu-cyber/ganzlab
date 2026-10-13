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
* F5, referans kaydı ~12 sn'ye kırpar (sessizliklerden); 5–10 sn temiz referans idealdir.

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
import os
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
        self.model_id = f"f5-tts-turkish:{ckpt.name}"

        log.info("F5-TTS Türkçe yükleniyor: %s (yapılandırma=%s, cihaz=%s)", ckpt, self.config_name, device)
        kwargs = _filter_kwargs(F5TTS, {"model": self.config_name, "ckpt_file": self.ckpt,
                                        "vocab_file": self.vocab, "device": device})
        self._model = F5TTS(**kwargs)
        self.sr = int(getattr(self._model, "target_sample_rate", None) or 24000)
        log.info("F5-TTS Türkçe hazır: %s (sr=%d, nfe=%d)", self.model_id, self.sr, self.nfe_step)

    # --- motorun kullandığı yüz ---
    def seed(self, seed: int) -> None:
        """Tohumu saklar (her ``infer``'e geçirilir) ve varsa PyTorch tohumunu da verir."""
        self._seed = int(seed)
        try:
            import torch
        except ImportError:
            return
        manual_seed = getattr(torch, "manual_seed", None)
        if callable(manual_seed):
            manual_seed(self._seed)

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
        """
        if not audio_prompt_path:
            raise ValueError("F5-TTS referans kaydı olmadan üretemez: audio_prompt_path (bir ses klonu) gerekli.")
        if not str(text or "").strip():
            raise ValueError("F5-TTS için üretilecek metin boş.")
        dil = tr_lower(str(language_id or "tr")).strip()
        if dil != "tr":
            log.warning("F5-TTS Türkçe modeli yalnızca Türkçe ile eğitildi; '%s' dili için çıktı kötü olabilir", dil)
        ref = str(audio_prompt_path)
        ref_text = str(ref_text or "").strip() or self.transcript_for(ref)
        kwargs = _filter_kwargs(self._model.infer, {
            "ref_file": ref, "ref_text": ref_text, "gen_text": text, "show_info": _f5_bilgi,
            "nfe_step": int(self.nfe_step), "speed": float(speed), "remove_silence": False, "seed": self._seed,
        })
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


__all__ = ["F5TurkishBackend"]
