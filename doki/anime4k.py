"""Anime4K shader presets, following the Anime4K v4.0 Windows instructions."""

import os

from .paths import app_path

USER_CONFIG = "Use my mpv config"
OFF = "Off"

# Quality-dependent shader sizes: (restore/first upscale, final upscale).
SIZES = {"HQ": ("VL", "M"), "Fast": ("M", "S")}
MODES = {
    "A": ("Clamp_Highlights", "Restore_CNN_{big}", "Upscale_CNN_x2_{big}", "AutoDownscalePre_x2", "AutoDownscalePre_x4", "Upscale_CNN_x2_{small}"),
    "B": ("Clamp_Highlights", "Restore_CNN_Soft_{big}", "Upscale_CNN_x2_{big}", "AutoDownscalePre_x2", "AutoDownscalePre_x4", "Upscale_CNN_x2_{small}"),
    "C": ("Clamp_Highlights", "Upscale_Denoise_CNN_x2_{big}", "AutoDownscalePre_x2", "AutoDownscalePre_x4", "Upscale_CNN_x2_{small}"),
    "A+A": ("Clamp_Highlights", "Restore_CNN_{big}", "Upscale_CNN_x2_{big}", "Restore_CNN_{small}", "AutoDownscalePre_x2", "AutoDownscalePre_x4", "Upscale_CNN_x2_{small}"),
    "B+B": ("Clamp_Highlights", "Restore_CNN_Soft_{big}", "Upscale_CNN_x2_{big}", "AutoDownscalePre_x2", "AutoDownscalePre_x4", "Restore_CNN_Soft_{small}", "Upscale_CNN_x2_{small}"),
    "C+A": ("Clamp_Highlights", "Upscale_Denoise_CNN_x2_{big}", "AutoDownscalePre_x2", "AutoDownscalePre_x4", "Restore_CNN_{small}", "Upscale_CNN_x2_{small}"),
}
MODE_HINTS = {
    "A": "most 1080p anime",
    "B": "720p / softer sources",
    "C": "480p / noisy sources",
}


def preset_label(mode, quality):
    hint = MODE_HINTS.get(mode)
    return f"Mode {mode} ({quality})" + (f" - {hint}" if hint else "")


def shader_directory():
    return app_path("mpv", "portable_config", "shaders")


def shader_files(mode, quality):
    big, small = SIZES[quality]
    return [
        os.path.join(shader_directory(), "Anime4K_" + name.format(big=big, small=small) + ".glsl")
        for name in MODES[mode]
    ]


def shaders_available():
    return all(os.path.isfile(path) for path in shader_files("A+A", "HQ") + shader_files("C+A", "Fast"))


def preset_options():
    """Returns {label: shader list or None}; None means leave mpv's shaders alone."""
    options = {}
    if shaders_available():
        for quality in ("HQ", "Fast"):
            for mode in MODES:
                options[preset_label(mode, quality)] = shader_files(mode, quality)
        options[OFF] = []
    options[USER_CONFIG] = None
    return options


def default_preset(options):
    preferred = preset_label("A", "HQ")
    return preferred if preferred in options else USER_CONFIG


def shader_arguments(shaders):
    if shaders is None:
        return []
    return ["--glsl-shaders=" + os.pathsep.join(shaders)]
