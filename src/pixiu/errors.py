"""Custom errors for pixiu wrapper."""


class PixiuError(Exception):
    """Base exception for all pixiu-related failures."""


class ConfigError(PixiuError):
    """Raised when pixiu configuration is missing or invalid."""


class BucketAliasError(PixiuError):
    """Raised when a bucket alias cannot be resolved."""


class DownloadModeError(PixiuError):
    """Raised when download arguments do not match a valid mode."""
