"""Image-edit preparation, mask processing, and ControlNet inputs."""

from __future__ import annotations

from typing import Any

from ...config import settings
from ...core.enums import ModelFamily


class ImageEditingMixin:
    @staticmethod
    def _strength(
        params: dict[str, Any],
        family: ModelFamily | None = None,
    ) -> float:
        """Return img2img denoise strength, clamped to a sane range."""
        default = settings.img2img_default_strength
        if family is ModelFamily.QWEN_IMAGE:
            default = settings.qwen_image_img2img_strength
        elif family is ModelFamily.Z_IMAGE:
            default = settings.z_image_img2img_strength
        elif family is ModelFamily.ANIMA:
            default = settings.anima_img2img_strength
        try:
            value = float(params.get("strength", default))
        except (TypeError, ValueError):
            value = default
        return max(0.05, min(1.0, value))

    @classmethod
    def _effective_strength(
        cls,
        params: dict[str, Any],
        steps: int,
        family: ModelFamily | None = None,
        min_effective_steps: int = 1,
    ) -> float:
        """Avoid a zero-length denoise schedule for low-step img2img jobs."""
        return max(
            cls._strength(params, family),
            min(max(1, int(min_effective_steps)), max(1, int(steps))) / max(1, int(steps)),
        )

    def _resolved_strength(
        self,
        params: dict[str, Any],
        steps: int,
    ) -> float:
        minimum = settings.img2img_min_effective_steps if self._is_z_image_turbo() else 1
        return self._effective_strength(
            params,
            steps,
            self.descriptor.family,
            minimum,
        )

    def _add_strength_meta(
        self,
        meta: dict[str, Any],
        params: dict[str, Any],
        steps: int,
    ) -> None:
        if not params.get("init_image"):
            return
        requested = self._strength(params, self.descriptor.family)
        effective = self._resolved_strength(params, steps)
        meta["strength"] = effective
        if effective != requested:
            meta["requested_strength"] = requested

    def _add_edit_meta(
        self,
        meta: dict[str, Any],
        params: dict[str, Any],
        steps: int,
    ) -> None:
        if not params.get("init_image"):
            return
        mode = self._edit_mode(params)
        meta["edit_mode"] = mode
        meta["resize_mode"] = self._resize_mode(params)
        if self.descriptor.family in (
            ModelFamily.QWEN_IMAGE_EDIT,
            ModelFamily.FLUX_KONTEXT,
        ):
            meta["instruction_edit"] = True
        elif (
            self.descriptor.family is ModelFamily.FLUX2 and mode == "img2img" and not params.get("mask_image")
        ):
            meta["flux2_reference"] = True
        else:
            self._add_strength_meta(meta, params, steps)
        if params.get("mask_image") or mode == "outpaint":
            meta["inpaint"] = True
            meta["mask_blur"] = self._mask_blur(params)
            meta["mask_grow"] = self._mask_grow(params)
            meta["mask_invert"] = bool(params.get("mask_invert", False))
            meta["padding_mask_crop"] = self._padding_mask_crop(params)
        if mode == "outpaint":
            meta["outpaint"] = self._outpaint_margins(params)

    @staticmethod
    def _edit_mode(params: dict[str, Any]) -> str:
        inferred = "inpaint" if params.get("mask_image") else "img2img"
        mode = str(params.get("edit_mode") or inferred).lower().strip()
        allowed = {
            "img2img",
            "inpaint",
            "outpaint",
            "instruction",
            "controlnet",
        }
        return mode if mode in allowed else "img2img"

    @staticmethod
    def _resize_mode(params: dict[str, Any]) -> str:
        mode = str(params.get("resize_mode") or settings.image_edit_resize_mode).lower().strip()
        return mode if mode in {"crop", "pad", "stretch"} else "crop"

    @staticmethod
    def _mask_blur(params: dict[str, Any]) -> float:
        try:
            return max(
                0.0,
                min(
                    128.0,
                    float(
                        params.get(
                            "mask_blur",
                            settings.inpaint_mask_blur,
                        )
                    ),
                ),
            )
        except (TypeError, ValueError):
            return float(settings.inpaint_mask_blur)

    @staticmethod
    def _mask_grow(params: dict[str, Any]) -> int:
        try:
            return max(
                -128,
                min(
                    128,
                    int(
                        params.get(
                            "mask_grow",
                            settings.inpaint_mask_grow,
                        )
                    ),
                ),
            )
        except (TypeError, ValueError):
            return int(settings.inpaint_mask_grow)

    @staticmethod
    def _padding_mask_crop(params: dict[str, Any]) -> int | None:
        try:
            value = int(
                params.get(
                    "padding_mask_crop",
                    settings.inpaint_padding_mask_crop,
                )
            )
        except (TypeError, ValueError):
            value = int(settings.inpaint_padding_mask_crop)
        return max(0, min(512, value)) or None

    @staticmethod
    def _outpaint_margins(params: dict[str, Any]) -> dict[str, int]:
        def margin(key: str) -> int:
            try:
                return max(0, min(1024, int(params.get(key, 0))))
            except (TypeError, ValueError):
                return 0

        return {side: margin(f"outpaint_{side}") for side in ("left", "right", "top", "bottom")}

    @staticmethod
    def _fit_image(
        image,
        width: int,
        height: int,
        mode: str,
        *,
        mask: bool = False,
    ):
        from PIL import Image as PILImage  # noqa: PLC0415
        from PIL import ImageOps  # noqa: PLC0415

        resample = PILImage.Resampling.NEAREST if mask else PILImage.Resampling.LANCZOS
        if mode == "stretch":
            return image.resize((width, height), resample)
        if mode == "pad":
            color = 0 if mask else (24, 28, 36)
            return ImageOps.pad(
                image,
                (width, height),
                method=resample,
                color=color,
                centering=(0.5, 0.5),
            )
        return ImageOps.fit(
            image,
            (width, height),
            method=resample,
            centering=(0.5, 0.5),
        )

    def _outpaint_canvas(
        self,
        image,
        width: int,
        height: int,
        params: dict[str, Any],
        *,
        mask: bool = False,
    ):
        from PIL import Image as PILImage  # noqa: PLC0415
        from PIL import ImageOps  # noqa: PLC0415

        margins = self._outpaint_margins(params)
        inner_w = max(1, width - margins["left"] - margins["right"])
        inner_h = max(1, height - margins["top"] - margins["bottom"])
        if mask:
            canvas = PILImage.new("L", (width, height), 255)
            canvas.paste(
                0,
                (
                    margins["left"],
                    margins["top"],
                    width - margins["right"],
                    height - margins["bottom"],
                ),
            )
            return canvas
        resample = PILImage.Resampling.NEAREST if mask else PILImage.Resampling.LANCZOS
        fitted = ImageOps.contain(
            image,
            (inner_w, inner_h),
            method=resample,
        )
        x = margins["left"] + (inner_w - fitted.width) // 2
        y = margins["top"] + (inner_h - fitted.height) // 2
        canvas = PILImage.new("RGB", (width, height), (24, 28, 36))
        canvas.paste(fitted, (x, y))
        return canvas

    def _load_init_image(
        self,
        token: str,
        width: int,
        height: int,
        params: dict[str, Any] | None = None,
    ):
        """Open and normalize an uploaded img2img source."""
        from PIL import Image as PILImage  # noqa: PLC0415

        from ...util import uploads as uploads_util  # noqa: PLC0415

        path = uploads_util.resolve_upload(token)
        if path is None or not path.exists():
            raise ValueError("img2img source image not found (re-upload it)")
        params = params or {}
        image = PILImage.open(path).convert("RGB")
        if self._edit_mode(params) == "outpaint":
            return self._outpaint_canvas(
                image,
                width,
                height,
                params,
            )
        return self._fit_image(
            image,
            width,
            height,
            self._resize_mode(params),
        )

    def _load_mask_image(
        self,
        token: str | None,
        width: int,
        height: int,
        params: dict[str, Any] | None = None,
    ):
        """Open and normalize a mask where white pixels are repainted."""
        from PIL import Image as PILImage  # noqa: PLC0415

        from ...util import uploads as uploads_util  # noqa: PLC0415

        params = params or {}
        if self._edit_mode(params) == "outpaint":
            mask = self._outpaint_canvas(
                PILImage.new("L", (1, 1), 0),
                width,
                height,
                params,
                mask=True,
            )
        else:
            path = uploads_util.resolve_upload(token or "")
            if path is None or not path.exists():
                raise ValueError("inpainting mask not found (re-upload it)")
            raw = PILImage.open(path).convert("L")
            mask = self._fit_image(
                raw,
                width,
                height,
                self._resize_mode(params),
                mask=True,
            )
        return self._apply_mask_ops(mask, params)

    @classmethod
    def _apply_mask_ops(cls, mask, params: dict[str, Any]):
        from PIL import ImageFilter, ImageOps  # noqa: PLC0415

        grow = cls._mask_grow(params)
        if grow:
            kernel = min(255, abs(grow) * 2 + 1)
            if kernel % 2 == 0:
                kernel += 1
            mask = mask.filter(ImageFilter.MaxFilter(kernel) if grow > 0 else ImageFilter.MinFilter(kernel))
        blur = cls._mask_blur(params)
        if blur:
            mask = mask.filter(ImageFilter.GaussianBlur(blur))
        if params.get("mask_invert"):
            mask = ImageOps.invert(mask)
        return mask

    @staticmethod
    def _control_scale(params: dict[str, Any]) -> float:
        try:
            value = float(
                params.get(
                    "control_scale",
                    settings.sdxl_controlnet_default_scale,
                )
            )
        except (TypeError, ValueError):
            value = settings.sdxl_controlnet_default_scale
        return max(0.0, min(2.0, value))

    def _load_control_image(
        self,
        token: str,
        width: int,
        height: int,
        control_type: Any,
    ):
        from PIL import Image as PILImage  # noqa: PLC0415
        from PIL import ImageFilter, ImageOps  # noqa: PLC0415

        from ...util import uploads as uploads_util  # noqa: PLC0415

        control = str(control_type or "canny").lower().strip()
        if control.startswith("union-"):
            control = control.removeprefix("union-")
        if control not in {"canny", "depth", "pose", "scribble"}:
            raise ValueError("ControlNet type must be canny, depth, pose, or scribble")
        path = uploads_util.resolve_upload(token)
        if path is None or not path.exists():
            raise ValueError("ControlNet source image not found (re-upload it)")
        img = PILImage.open(path).convert("RGB").resize((width, height))
        if control == "pose":
            return img
        grey = ImageOps.grayscale(img)
        if control == "depth":
            grey = ImageOps.autocontrast(grey)
        else:
            grey = ImageOps.autocontrast(grey.filter(ImageFilter.FIND_EDGES))
            if control == "scribble":
                grey = grey.point(lambda value: 255 if value > 32 else 0)
        return PILImage.merge("RGB", (grey, grey, grey))

    @staticmethod
    def _controlnet_mode_kwargs(
        control_type: str,
    ) -> dict[str, int]:
        if not control_type.startswith("union-"):
            return {}
        subtype = control_type.removeprefix("union-")
        return {
            "control_mode": {
                "pose": 0,
                "depth": 1,
                "scribble": 2,
                "canny": 3,
            }[subtype]
        }
