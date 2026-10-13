"""Chatterbox Multilingual (PyTorch) arka ucu — SesKlon'un varsayılan sentez modeli.

Yükleme sırası (``__init__``):

1. ``CHATTERBOX_LOCAL_DIR`` doluysa tüm ağırlıklar o klasörden (``ChatterboxMultilingualTTS.from_local``), yoksa
   Hugging Face'ten (``from_pretrained``). ``T3_MODEL`` (v2 / v3) seçimi yalnızca çağrılan fonksiyonun imzasında
   ``t3_model`` varsa geçirilir; imza farklı bir sürümdeyse parametre sessizce atlanır.
2. ``T3_FINETUNED`` doluysa ince ayarlı T3 ağırlıkları (``.safetensors`` → ``safetensors.torch.load_file``,
   diğer uzantılar → ``torch.load``) ``model.t3``'e ``strict=False`` ile yüklenir. Anahtarlardaki ``module.`` ve
   ``t3.`` önekleri soyulur, eksik/fazla anahtar sayısı loglanır; anahtarların yarısından azı eşleşirse dosya
   yanlış bir model içindir ve Türkçe ``RuntimeError`` fırlatılır.
3. ``T3_EMOTION_TAGS`` açıkken motorun her parça için gönderdiği ``emotion`` metnin başına ``[mutlu] `` olarak
   eklenir — ince ayar verisiyle (``finetune/hazirla.py --etiket``) aynı biçim; ``normal`` etiket almaz.

Motorla konuşulan yüz (``docs/SOZLESME3.md`` §2): ``sr``, ``generate(...)`` (açık parametreler, ``**kwargs`` yok),
``conds`` (iç modelin klon koşullarına delege; motor klonsuz üretimde varsayılanı geri yükler), ``seed``.
"""
from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Any

import numpy as np

from .. import config
from ..tr import tr_lower
from . import BaseBackend

log = logging.getLogger("sesklon.backends.chatterbox")

# State dict anahtarlarından soyulacak önekler (DataParallel sarmalayıcısı, motor sarmalayıcısı, PEFT sarmalayıcısı)
_KEY_PREFIXES = ("base_model.model.", "module.", "t3.")
# Eğitim betiklerinin state dict'i içine koyduğu sarmalayıcı anahtarlar
_WRAPPER_KEYS = ("state_dict", "model_state_dict", "model", "t3")
# Yüklenen anahtarların en az bu oranı modelde bulunmalı; altı "yanlış dosya" demektir
_MIN_MATCH_RATIO = 0.5


def _filter_kwargs(fn: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """``fn`` imzasında tanımlı anahtarları bırakır (``**kwargs`` kabul ediyorsa hepsini geçirir)."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return dict(kwargs)
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(kwargs)
    return {k: v for k, v in kwargs.items() if k in params}


def _unwrap_state_dict(obj: Any, source: str) -> dict:
    """Eğitim betiklerinin sarmalayıcısını açar: ``{"state_dict": …}`` / ``{"model": …}`` → düz anahtar→tensör sözlüğü."""
    if not isinstance(obj, dict):
        raise RuntimeError(f"İnce ayar dosyası bir state dict (anahtar → tensör sözlüğü) içermiyor: {source} "
                           f"({type(obj).__name__} bulundu)")
    for key in _WRAPPER_KEYS:
        inner = obj.get(key)
        if isinstance(inner, dict):
            return inner
    return obj


def strip_key_prefixes(sd: dict) -> tuple[dict, int]:
    """``module.`` / ``t3.`` (ve PEFT ``base_model.model.``) öneklerini soyar; (yeni sözlük, yeniden adlandırılan sayısı)."""
    out: dict = {}
    renamed = 0
    for key, value in sd.items():
        name = str(key)
        changed = True
        while changed:                      # "module.t3.x" gibi iç içe önekler sırayla gider
            changed = False
            for prefix in _KEY_PREFIXES:
                if name.startswith(prefix) and len(name) > len(prefix):
                    name = name[len(prefix):]
                    changed = True
        if name != key:
            renamed += 1
        out[name] = value
    return out, renamed


def _incompatible_keys(result: Any) -> tuple[list[str], list[str]]:
    """``load_state_dict`` dönüşünü (``_IncompatibleKeys`` ya da ``(missing, unexpected)`` ikilisi) ayrıştırır."""
    if result is None:
        return [], []
    missing = getattr(result, "missing_keys", None)
    unexpected = getattr(result, "unexpected_keys", None)
    if missing is None or unexpected is None:
        try:
            missing, unexpected = result
        except (TypeError, ValueError):
            return [], []
    return list(missing), list(unexpected)


def _read_state_dict(path: Path, device: str) -> dict:
    """Dosyadan ham state dict: ``.safetensors`` → safetensors, aksi hâlde ``torch.load(map_location=device)``."""
    if path.suffix == ".safetensors":
        from safetensors.torch import load_file

        return load_file(str(path))          # CPU'da okunur; load_state_dict kopyalarken cihaza taşır
    import torch

    return torch.load(str(path), map_location=device)


def load_finetuned_t3(model: Any, path_str: str, device: str) -> dict[str, Any]:
    """İnce ayarlı T3 ağırlıklarını ``model.t3``'e ``strict=False`` ile yükler.

    Döndürür: ``{"path", "matched", "missing", "unexpected", "renamed"}``. Dosya yoksa ``FileNotFoundError``;
    anahtarların yarısından azı modelde bulunuyorsa ``RuntimeError`` (yanlış model için üretilmiş dosya).
    """
    path = Path(path_str).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"İnce ayar ağırlık dosyası bulunamadı: {path} — T3_FINETUNED bir .safetensors "
                                f"ya da .pt dosyasını göstermeli (finetune/merge_lora.py çıktısı).")
    t3 = getattr(model, "t3", None)
    if t3 is None or not hasattr(t3, "load_state_dict"):
        raise RuntimeError("Yüklenen Chatterbox modelinde T3 alt modeli yok; ince ayar ağırlıkları uygulanamadı.")
    log.info("İnce ayarlı T3 ağırlıkları yükleniyor: %s", path)
    sd, renamed = strip_key_prefixes(_unwrap_state_dict(_read_state_dict(path, device), str(path)))
    if not sd:
        raise RuntimeError(f"İnce ayar dosyası boş, hiç ağırlık içermiyor: {path}")
    if renamed:
        log.info("İnce ayar anahtarlarında önek soyuldu (%d anahtar): module. / t3.", renamed)
    try:
        result = t3.load_state_dict(sd, strict=False)
    except RuntimeError as e:                 # boyut uyuşmazlığı (farklı sözlük boyutu / farklı mimari)
        raise RuntimeError(f"İnce ayar ağırlıkları T3 ile uyumsuz ({path.name}); aynı tokenizer ve aynı T3 "
                           f"mimarisiyle eğitilmiş olmalı. Ayrıntı: {e}") from e
    missing, unexpected = _incompatible_keys(result)
    matched = len(sd) - len(unexpected)
    log.info("İnce ayar yüklendi: %s — eşleşen %d, modelde eksik kalan %d, dosyada fazla %d anahtar",
             path.name, matched, len(missing), len(unexpected))
    if matched < len(sd) * _MIN_MATCH_RATIO:
        ornek = ", ".join(unexpected[:3])
        raise RuntimeError(f"İnce ayar ağırlıkları T3 ile eşleşmiyor: {len(sd)} anahtardan yalnızca {matched} tanesi "
                           f"modelde var (örn. {ornek}). Dosya Chatterbox T3 state dict'i olmalı "
                           f"(finetune/merge_lora.py çıktısı ya da model.t3.state_dict()).")
    if missing:
        log.warning("İnce ayar dosyasında %d T3 anahtarı yok, temel ağırlıklar korunuyor (ilk birkaçı: %s)",
                    len(missing), ", ".join(missing[:5]))
    if unexpected:
        log.warning("İnce ayar dosyasındaki %d anahtar modelde kullanılmadı (ilk birkaçı: %s)",
                    len(unexpected), ", ".join(unexpected[:5]))
    if hasattr(t3, "eval"):
        t3.eval()
    if hasattr(t3, "to"):
        t3.to(device)
    return {"path": str(path), "matched": matched, "missing": len(missing), "unexpected": len(unexpected),
            "renamed": renamed}


class ChatterboxBackend(BaseBackend):
    """Chatterbox Multilingual V3 (resemble-ai/chatterbox, MIT) — PyTorch; cuda / mps / cpu."""

    name = "chatterbox"
    label = "Chatterbox Multilingual (PyTorch)"
    license = "MIT — ticari kullanım serbest"
    model_id = "chatterbox-multilingual-v3"
    sr = 24000
    commercial = True
    supports_emotion_controls = True
    needs_torch = True
    required_modules = ("torch", "chatterbox")
    install_hint = "pip install 'chatterbox-tts @ git+https://github.com/resemble-ai/chatterbox.git'"

    def __init__(self, device: str = "cpu") -> None:
        super().__init__(device)
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        self.t3_model: str = config.T3_MODEL
        self.local_dir: str | None = config.CHATTERBOX_LOCAL_DIR
        self.finetuned: str | None = config.T3_FINETUNED
        self.finetune_report: dict[str, Any] | None = None
        self.model_id = f"chatterbox-multilingual-{self.t3_model}"

        if self.local_dir:
            ckpt_dir = Path(self.local_dir).expanduser()
            if not ckpt_dir.is_dir():
                raise FileNotFoundError(f"CHATTERBOX_LOCAL_DIR klasörü bulunamadı: {ckpt_dir}")
            log.info("Chatterbox Multilingual yerel klasörden yükleniyor: %s (cihaz=%s, t3=%s)",
                     ckpt_dir, device, self.t3_model)
            extra = _filter_kwargs(ChatterboxMultilingualTTS.from_local, {"t3_model": self.t3_model})
            self._model = ChatterboxMultilingualTTS.from_local(str(ckpt_dir), device, **extra)
            self.model_id += f"@{ckpt_dir}"
        else:
            log.info("Chatterbox Multilingual Hugging Face'ten yükleniyor (cihaz=%s, t3=%s)", device, self.t3_model)
            kwargs = _filter_kwargs(ChatterboxMultilingualTTS.from_pretrained,
                                    {"device": device, "t3_model": self.t3_model})
            self._model = ChatterboxMultilingualTTS.from_pretrained(**kwargs)

        self.sr = int(getattr(self._model, "sr", self.sr))
        if self.finetuned:
            # from_pretrained mps yoksa sessizce cpu'ya düşer; T3'ü modelin gerçekten bulunduğu cihaza taşı
            actual_device = str(getattr(self._model, "device", None) or device)
            self.finetune_report = load_finetuned_t3(self._model, self.finetuned, actual_device)
            self.model_id += f"+ince-ayar:{Path(self.finetuned).name}"
        log.info("Chatterbox hazır: %s (sr=%d)", self.model_id, self.sr)

    # --- motorun kullandığı yüz ---
    @property
    def conds(self) -> Any:
        """Klon koşulları — iç modelin ``conds``'una delege (motor klonsuz üretimde varsayılanı geri yükler)."""
        return getattr(self._model, "conds", None)

    @conds.setter
    def conds(self, value: Any) -> None:
        self._model.conds = value

    def seed(self, seed: int) -> None:
        """PyTorch tohumu (+ CUDA); torch yoksa sessizce geçer."""
        try:
            import torch
        except ImportError:
            return
        torch.manual_seed(int(seed))
        try:
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(int(seed))
        except Exception as e:  # noqa: BLE001 - CUDA tohumu başarısızsa üretim yine de sürer
            log.debug("CUDA tohumu verilemedi: %s", e)

    @staticmethod
    def tag_text(text: str, emotion: str | None) -> str:
        """``T3_EMOTION_TAGS`` açıkken parça duygusunu ince ayar verisindeki biçimle ekler: ``"[mutlu] Merhaba"``.

        ``normal`` ve boş duygu etiket almaz (veri hazırlama ile aynı kural); metin zaten etiketle başlıyorsa
        ikinci kez eklenmez.
        """
        if not config.T3_EMOTION_TAGS or not emotion:
            return text
        tag = tr_lower(str(emotion)).strip()
        if not tag or tag == "normal":
            return text
        if text.lstrip().startswith(f"[{tag}]"):
            return text
        return f"[{tag}] {text}"

    def generate(self, text: str, language_id: str = "tr", exaggeration: float = 0.5, cfg_weight: float = 0.5,
                 temperature: float = 0.8, audio_prompt_path: str | None = None,
                 emotion: str | None = None) -> np.ndarray:
        """Tek parça üretir; iç modelin ``generate``'ine yalnızca imzasında tanımlı parametreler geçer."""
        text = self.tag_text(text, emotion)
        kwargs = _filter_kwargs(self._model.generate, {
            "language_id": language_id,
            "exaggeration": float(exaggeration),
            "cfg_weight": float(cfg_weight),
            "temperature": float(temperature),
            "audio_prompt_path": str(audio_prompt_path) if audio_prompt_path else None,
        })
        wav = self._model.generate(text, **kwargs)
        return self.to_numpy(wav)

    def info(self) -> dict[str, Any]:
        d = super().info()
        d.update({"finetuned": self.finetuned, "t3_model": self.t3_model,
                  "emotion_tags": bool(config.T3_EMOTION_TAGS), "local_dir": self.local_dir})
        if self.finetune_report:
            d["finetune_keys"] = {k: self.finetune_report[k] for k in ("matched", "missing", "unexpected")}
        return d


__all__ = ["ChatterboxBackend", "load_finetuned_t3", "strip_key_prefixes"]
