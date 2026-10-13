"""Takılabilir sentez arka uçları — motor, modeli bu kayıt defteri üzerinden yükler.

Motor (``engine.Engine``) modelle yalnızca üç şey üzerinden konuşur:

* ``model.sr`` — çıktının örnekleme hızı (int)
* ``model.generate(text, language_id=…, exaggeration=…, cfg_weight=…, temperature=…, audio_prompt_path=…)``
  → tek kanallı float32 ``np.ndarray`` (ya da ``.detach().cpu()`` destekleyen tensör)
* (isteğe bağlı) ``model.conds`` — Chatterbox'ın klon koşulları; motor klonsuz üretimde varsayılanı geri yükler

Motor çağırmadan önce ``_filter_kwargs`` ile ``generate`` imzasına bakar: arka uç hangi parametreleri
tanımlıyorsa yalnızca onları alır. Bu yüzden arka uçlar ``generate``'i **açık parametrelerle** yazar,
``**kwargs`` KULLANMAZ — F5 gibi ``exaggeration`` bilmeyen bir model bu parametreyi hiç görmez.

Kayıt defteri::

    from app import backends
    backends.names()                    # ["chatterbox", "chatterbox-mlx", "f5-tr", "xtts", "fake"]
    backends.describe()                 # her arka uç: ad, etiket, lisans, kurulu mu, neden değil
    model = backends.create("fake")     # ya da create(None) → TTS_BACKEND ortam değişkeni → "chatterbox"

Ortam değişkenleri (``config.py``): ``TTS_BACKEND``, ``T3_FINETUNED`` (ince ayarlı T3 ağırlıkları),
``CHATTERBOX_LOCAL_DIR``, ``MLX_MODEL``, ``F5_TR_CKPT``, ``F5_TR_VOCAB``, ``XTTS_MODEL``.

Sözleşme: ``docs/SOZLESME3.md`` §2.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import os
from typing import Any

import numpy as np

log = logging.getLogger("sesklon.backends")

DEFAULT_BACKEND = "chatterbox"


class BackendUnavailable(RuntimeError):
    """Arka uç bu makinede kurulu/çalışır değil; mesaj Türkçe ve kurulum ipucu içerir."""


class BaseBackend:
    """Tüm arka uçların ortak yüzü. Alt sınıflar ``name``, ``label``, ``license``, ``sr`` ve ``generate`` tanımlar."""

    name: str = "taban"
    label: str = "Taban arka uç"
    license: str = ""                # örn. "MIT — ticari kullanım serbest"
    model_id: str = ""               # yüklenen ağırlıkların kimliği (HF kimliği, yerel yol, …)
    sr: int = 24000
    commercial: bool = True          # lisans ticari kullanıma izin veriyor mu
    supports_emotion_controls: bool = False   # exaggeration/cfg_weight anlamlı mı
    needs_torch: bool = True

    def __init__(self, device: str = "cpu") -> None:
        self.device = device

    # --- kurulum denetimi (ucuz: import etmeden find_spec ile bakar) ---
    required_modules: tuple[str, ...] = ()
    install_hint: str = ""

    @classmethod
    def available(cls) -> tuple[bool, str]:
        """(kurulu mu, açıklama). Modülleri yüklemez; yalnızca varlığına bakar."""
        for mod in cls.required_modules:
            try:
                found = importlib.util.find_spec(mod) is not None
            except (ImportError, ValueError):
                found = False
            if not found:
                return False, f"'{mod}' paketi kurulu değil. Kurulum: {cls.install_hint}".strip()
        return True, "kurulu"

    # --- üretim ---
    def generate(self, text: str, language_id: str = "tr", audio_prompt_path: str | None = None) -> np.ndarray:
        raise NotImplementedError

    def seed(self, seed: int) -> None:
        """Rastgelelik tohumu (varsa çerçevenin kendi üreteci)."""

    def info(self) -> dict[str, Any]:
        return {"name": self.name, "label": self.label, "license": self.license, "model_id": self.model_id,
                "sr": int(self.sr), "device": self.device, "commercial": self.commercial,
                "emotion_controls": self.supports_emotion_controls}

    @staticmethod
    def to_numpy(wav: Any) -> np.ndarray:
        """Tensör / liste / mx.array → tek kanallı float32 numpy."""
        if hasattr(wav, "detach"):
            wav = wav.detach().cpu().float().numpy()
        elif hasattr(wav, "tolist") and not isinstance(wav, np.ndarray):
            wav = np.asarray(wav.tolist(), dtype=np.float32)     # mlx.core.array vb.
        x = np.asarray(wav, dtype=np.float32)
        if x.ndim > 1:
            x = x.mean(axis=0) if x.shape[0] <= 2 else x.mean(axis=1)
        return np.ascontiguousarray(x.squeeze())


# ad → "modül:Sınıf" (tembel import: arka uç modülleri yalnızca istenince yüklenir)
REGISTRY: dict[str, str] = {
    "chatterbox": "app.backends.chatterbox:ChatterboxBackend",
    "chatterbox-mlx": "app.backends.chatterbox_mlx:ChatterboxMlxBackend",
    "f5-tr": "app.backends.f5_turkish:F5TurkishBackend",
    "xtts": "app.backends.xtts:XttsBackend",
    "fake": "app.backends.fake:FakeBackend",
}

_ALIASES = {
    "": DEFAULT_BACKEND, "torch": "chatterbox", "pytorch": "chatterbox", "cb": "chatterbox",
    "mlx": "chatterbox-mlx", "f5": "f5-tr", "f5-turkish": "f5-tr", "xtts-v2": "xtts", "xtts2": "xtts",
    "sahte": "fake", "test": "fake",
}


def normalize_name(name: str | None) -> str:
    from ..tr import tr_lower

    key = tr_lower((name or "").strip()).replace("_", "-")
    key = _ALIASES.get(key, key)
    if key not in REGISTRY:
        raise KeyError(f"Bilinmeyen arka uç: '{name}'. Seçenekler: {', '.join(REGISTRY)}")
    return key


def names() -> list[str]:
    return list(REGISTRY)


def get_class(name: str | None) -> type[BaseBackend]:
    key = normalize_name(name)
    mod_name, _, cls_name = REGISTRY[key].partition(":")
    mod = importlib.import_module(mod_name)
    return getattr(mod, cls_name)


def describe() -> list[dict[str, Any]]:
    """Her arka uç için ad/etiket/lisans ve kurulu olup olmadığı (modelleri yüklemeden)."""
    out = []
    for key in REGISTRY:
        try:
            cls = get_class(key)
            ok, reason = cls.available()
            out.append({"name": key, "label": cls.label, "license": cls.license, "commercial": cls.commercial,
                        "emotion_controls": cls.supports_emotion_controls, "available": ok, "reason": reason})
        except Exception as e:  # noqa: BLE001 - bozuk bir arka uç modülü listeyi düşürmesin
            out.append({"name": key, "label": key, "license": "", "commercial": False, "emotion_controls": False,
                        "available": False, "reason": f"yüklenemedi: {e}"})
    return out


def create(name: str | None = None, device: str = "cpu", **kwargs: Any) -> BaseBackend:
    """Arka ucu kurar (model ağırlıkları bu çağrıda yüklenir). Kurulu değilse ``BackendUnavailable``."""
    key = normalize_name(name if name is not None else os.getenv("TTS_BACKEND", DEFAULT_BACKEND))
    cls = get_class(key)
    ok, reason = cls.available()
    if not ok:
        raise BackendUnavailable(f"'{key}' arka ucu kullanılamıyor: {reason}")
    log.info("Arka uç kuruluyor: %s (%s) cihaz=%s", key, cls.label, device)
    return cls(device=device, **kwargs)


__all__ = ["BaseBackend", "BackendUnavailable", "REGISTRY", "DEFAULT_BACKEND", "names", "describe", "create",
           "get_class", "normalize_name"]
