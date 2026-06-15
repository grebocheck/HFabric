"""Discovers local model files and hands out (cached) backends for them.

Scanning only reads safetensors headers, so it is instant even for the 16 GB
FLUX file. Backends are created lazily on first use and cached; the arbiter is
what decides which one is actually resident in VRAM.
"""

from __future__ import annotations

from pathlib import Path
import re

from ..config import settings
from ..core.enums import ModelFamily
from ..util import sysmon
from .base import GpuBackend, LoraDescriptor, ModelDescriptor
from .image_diffusers import DiffusersImageBackend
from .inspect import classify_diffusers_dir, classify_image_model, classify_lora_model
from .llm_llamacpp import LlamaCppBackend
from .upscaler import ImageUpscalerBackend

LORA_EXTENSIONS = {".safetensors", ".pt", ".bin"}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _nunchaku_quant(name: str) -> str:
    if "fp4" in name:
        return "nunchaku-fp4"
    if "int4" in name or "awq" in name:
        return "nunchaku-int4"
    return "nunchaku"


def _nunchaku_family(name: str) -> ModelFamily:
    normalized = name.replace("_", "-")
    if "qwen-image" in normalized:
        return ModelFamily.QWEN_IMAGE
    if "z-image" in normalized:
        return ModelFamily.Z_IMAGE
    if "flux.2" in normalized or "flux2" in normalized:
        return ModelFamily.FLUX2
    return ModelFamily.FLUX


def _has_transformer_weights(repo_dir: Path) -> bool:
    """True if a Diffusers repo folder still carries its transformer weights.

    Slimmed fp4 base repos keep transformer/config.json but have the heavy bf16
    ``*.safetensors`` removed; such a folder can only serve as a base for a
    separate Nunchaku fp4 transformer, not load on its own."""
    return any((repo_dir / "transformer").glob("*.safetensors"))


def _is_mmproj(path: Path) -> bool:
    return path.name.lower().startswith("mmproj") and path.suffix.lower() == ".gguf"


# Trailing quantization tag (q4_k_m, iq4_xs, q8_0, f16, bf16, mxfp4, …) so a model
# and its projector compare on their base name, not their (often different) quant.
_QUANT_TAG_RE = re.compile(r"[._-](q\d\w*|iq\d\w*|f16|f32|bf16|fp\d+|mxfp4)$", re.IGNORECASE)


def _model_tokens(stem: str) -> set[str]:
    name = stem.lower().replace("mmproj", "")
    prev = None
    while prev != name:  # strip stacked quant tags, e.g. "-instruct-q4_k_m"
        prev = name
        name = _QUANT_TAG_RE.sub("", name)
    return {tok for tok in re.split(r"[^a-z0-9]+", name) if tok}


def _find_mmproj(path: Path) -> Path | None:
    """Pair a GGUF with its multimodal projector, if any lives beside it.

    Match on base-name token overlap (quant tags stripped) so a stray projector
    never attaches `--mmproj` to an unrelated text model. Only when a folder holds
    exactly one model + projector do we pair them despite a name mismatch (the
    common LLaVA layout, where the projector is named `mmproj-clip`)."""
    candidates = sorted(p for p in path.parent.glob("mmproj*.gguf") if p.is_file())
    if not candidates:
        return None
    model_tokens = _model_tokens(path.stem)
    best: tuple[int, Path] | None = None
    for candidate in candidates:
        overlap = len(model_tokens & _model_tokens(candidate.stem))
        if best is None or overlap > best[0]:
            best = (overlap, candidate)
    if best and best[0] > 0:
        return best[1]
    models = [p for p in path.parent.glob("*.gguf") if p.is_file() and not _is_mmproj(p)]
    return candidates[0] if len(models) == 1 and len(candidates) == 1 else None


def _image_safetensors_paths(root: Path) -> list[Path]:
    paths = set(root.glob("*.safetensors"))
    for path in root.glob("*/*.safetensors"):
        rel_parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in rel_parts[:-1]):
            continue
        name = path.name.lower()
        if "svdq" in name or "nunchaku" in name:
            paths.add(path)
    return sorted(paths)


class ModelRegistry:
    def __init__(self) -> None:
        self._descriptors: dict[str, ModelDescriptor] = {}
        self._loras: dict[str, LoraDescriptor] = {}
        self._backends: dict[str, GpuBackend] = {}

    def scan(self) -> None:
        self._descriptors.clear()
        self._loras.clear()
        diffusers_dirs = sorted(
            (sub, family)
            for sub in settings.image_models_dir.iterdir()
            if sub.is_dir() and (family := classify_diffusers_dir(sub)) is not None
        )
        flux2_dirs = [sub for sub, family in diffusers_dirs if family is ModelFamily.FLUX2]
        for path in _image_safetensors_paths(settings.image_models_dir):
            name = path.stem.lower()
            if "svdq" in name or "nunchaku" in name:
                # SVDQuant transformer-only checkpoint (Blackwell fp4/int4 turbo)
                fam = _nunchaku_family(name)
                quant = _nunchaku_quant(name)
                if fam is ModelFamily.FLUX2 and quant == "nunchaku-int4" and sysmon.is_blackwell_gpu():
                    # nunchaku rejects FLUX.2 int4 on Blackwell at load time:
                    # "Please use fp4 quantization for Blackwell GPUs."
                    continue
                self._add(path, fam, quant=quant)
            else:
                fam = classify_image_model(path)
                if fam is ModelFamily.FLUX2 and flux2_dirs:
                    # Keep the original-format transformer as a local conversion
                    # source; prefer the validated diffusers repo folder at run time.
                    continue
                quant = settings.flux2_quant if fam is ModelFamily.FLUX2 else None
                self._add(path, fam, quant=quant)
        # Multi-file Diffusers repos (FLUX.2 [klein], Qwen-Image, Z-Image).
        for sub, family in diffusers_dirs:
            if family in (ModelFamily.QWEN_IMAGE, ModelFamily.Z_IMAGE) and not _has_transformer_weights(sub):
                # A "slimmed" base repo (transformer/ weights deleted): it only
                # supplies the text encoder / VAE / tokenizer to a separate Nunchaku
                # fp4 transformer, so don't expose it as a standalone (it would fail
                # to load with no transformer). The fp4 .safetensors is the model.
                continue
            if family is ModelFamily.FLUX2:
                quant = settings.flux2_quant
            elif family is ModelFamily.QWEN_IMAGE:
                quant = settings.qwen_image_quant
            else:
                quant = None
            self._add(sub, family, quant=quant)
        for root in (settings.llm_models_dir, settings.vision_models_dir):
            if not root.exists():
                continue
            for path in sorted(root.glob("*.gguf")):
                if _is_mmproj(path):
                    continue
                self._add(path, ModelFamily.GGUF, mmproj_path=_find_mmproj(path))
        self._add_upscaler()
        for root in self._lora_scan_roots():
            if not root.exists():
                continue
            for path in sorted(p for p in root.rglob("*") if p.suffix.lower() in LORA_EXTENSIONS):
                self._add_lora(path)

    def _lora_scan_roots(self) -> list[Path]:
        roots = [
            settings.lora_models_dir,
            settings.image_models_dir / "lora",
            settings.image_models_dir / "loras",
        ]
        deduped: list[Path] = []
        seen: set[Path] = set()
        for root in roots:
            resolved = root.resolve()
            if resolved not in seen:
                deduped.append(root)
                seen.add(resolved)
        return deduped

    @staticmethod
    def _path_size(path: Path) -> int:
        if path.is_dir():
            return sum(
                f.stat().st_size for f in path.rglob("*.safetensors") if f.is_file()
            )
        try:
            return path.stat().st_size
        except OSError:
            return 0

    def _add(
        self,
        path,
        family: ModelFamily,
        quant: str | None = None,
        mmproj_path: Path | None = None,
    ) -> None:
        mid = _slug(path.stem)
        if mid in self._descriptors:
            try:
                rel = Path(path).relative_to(settings.root)
                mid = _slug(rel.with_suffix("").as_posix())
            except ValueError:
                pass
        size = self._path_size(path)
        mmproj_size = self._path_size(mmproj_path) if mmproj_path else 0
        self._descriptors[mid] = ModelDescriptor(
            id=mid,
            name=path.stem,
            family=family,
            path=path,
            size_bytes=size + mmproj_size,
            quant=quant,
            mmproj_path=mmproj_path,
            mmproj_size_bytes=mmproj_size,
        )

    def _add_upscaler(self) -> None:
        path = settings.upscaler_model_path
        size = self._path_size(path) if path.exists() else 0
        self._descriptors[settings.upscaler_model_id] = ModelDescriptor(
            id=settings.upscaler_model_id,
            name=settings.upscaler_model_name,
            family=ModelFamily.UPSCALER,
            path=path,
            size_bytes=size,
        )

    def _add_lora(self, path: Path) -> None:
        try:
            rel = path.relative_to(settings.root)
        except ValueError:
            rel = Path(path.name)
        lid = _slug(rel.with_suffix("").as_posix())
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        self._loras[lid] = LoraDescriptor(
            id=lid,
            name=path.stem,
            path=path,
            size_bytes=size,
            family=classify_lora_model(path),
        )

    def descriptors(self) -> list[ModelDescriptor]:
        return list(self._descriptors.values())

    def get_descriptor(self, model_id: str) -> ModelDescriptor:
        if model_id not in self._descriptors:
            raise KeyError(f"unknown model id: {model_id}")
        return self._descriptors[model_id]

    def loras(self, family: ModelFamily | None = None) -> list[LoraDescriptor]:
        loras = list(self._loras.values())
        if family is None:
            return loras
        return [l for l in loras if l.family is None or l.family is family]

    def get_lora(self, lora_id: str) -> LoraDescriptor:
        if lora_id not in self._loras:
            raise KeyError(f"unknown lora id: {lora_id}")
        return self._loras[lora_id]

    def get_backend(self, model_id: str) -> GpuBackend:
        if model_id in self._backends:
            return self._backends[model_id]
        desc = self.get_descriptor(model_id)
        backend: GpuBackend
        if desc.family is ModelFamily.GGUF:
            backend = LlamaCppBackend(desc)
        elif desc.family is ModelFamily.UPSCALER:
            backend = ImageUpscalerBackend(desc)
        else:
            backend = DiffusersImageBackend(desc)
        self._backends[model_id] = backend
        return backend

    def peek_backend(self, model_id: str) -> GpuBackend | None:
        return self._backends.get(model_id)

    def loaded_backends(self) -> list[GpuBackend]:
        return [b for b in self._backends.values() if b.loaded]
