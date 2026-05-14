"""Parse and format the three identifier shapes used across image-compile and agent-compile.

Contract: ../../../docs/contracts/identifier-format-v0_1.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Union

_FLAVOUR_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_VERSION_RE = re.compile(r"^v([1-9][0-9]*)$")
_IMAGE_VERSION_RE = re.compile(r"^[0-9][0-9a-z.\-]*-r([1-9][0-9]*)$")

_RESERVED_NAMES = {"image_defaults"}


class IdentifierError(ValueError):
    """Raised when an identifier string fails to parse or validate."""


@dataclass(frozen=True)
class TemplateID:
    flavour: str
    name: str
    version: int

    def __str__(self) -> str:
        return f"{self.flavour}:{self.name}:v{self.version}"


@dataclass(frozen=True)
class ImageDefaultsRef:
    flavour: str
    image_version: str

    def __str__(self) -> str:
        return f"image_defaults:{self.flavour}:{self.image_version}"


@dataclass(frozen=True)
class ImageRef:
    flavour: str
    image_version: str

    def __str__(self) -> str:
        return f"{self.flavour}:{self.image_version}"


Identifier = Union[TemplateID, ImageDefaultsRef, ImageRef]


def _validate_flavour(s: str) -> str:
    if not _FLAVOUR_RE.match(s):
        raise IdentifierError(f"invalid flavour: {s!r}")
    return s


def _validate_name(s: str) -> str:
    if s in _RESERVED_NAMES:
        raise IdentifierError(f"reserved template name: {s!r}")
    if not _NAME_RE.match(s):
        raise IdentifierError(f"invalid template name: {s!r}")
    return s


def _validate_version(s: str) -> int:
    m = _VERSION_RE.match(s)
    if not m:
        raise IdentifierError(f"invalid version: {s!r} (expected v<positive-int>)")
    return int(m.group(1))


def _validate_image_version(s: str) -> str:
    if not _IMAGE_VERSION_RE.match(s):
        raise IdentifierError(
            f"invalid image_version: {s!r} (expected <upstream>-r<rev>)"
        )
    return s


def parse(identifier: str) -> Identifier:
    """Parse an identifier string into the appropriate dataclass.

    Three shapes are recognised:

    - ``<flavour>:<image_version>``         → ImageRef
    - ``image_defaults:<flavour>:<image_version>`` → ImageDefaultsRef
    - ``<flavour>:<name>:v<n>``             → TemplateID
    """
    if not isinstance(identifier, str):
        raise IdentifierError(f"identifier must be a string, got {type(identifier).__name__}")
    if not identifier:
        raise IdentifierError("empty identifier")
    parts = identifier.split(":")
    if any(p == "" for p in parts):
        raise IdentifierError(f"identifier has empty field: {identifier!r}")
    if len(parts) == 2:
        return ImageRef(
            flavour=_validate_flavour(parts[0]),
            image_version=_validate_image_version(parts[1]),
        )
    if len(parts) == 3:
        if parts[0] == "image_defaults":
            return ImageDefaultsRef(
                flavour=_validate_flavour(parts[1]),
                image_version=_validate_image_version(parts[2]),
            )
        return TemplateID(
            flavour=_validate_flavour(parts[0]),
            name=_validate_name(parts[1]),
            version=_validate_version(parts[2]),
        )
    raise IdentifierError(
        f"invalid identifier: {identifier!r} (expected 2 or 3 colon-separated fields)"
    )


def parse_template_id(identifier: str) -> TemplateID:
    parsed = parse(identifier)
    if not isinstance(parsed, TemplateID):
        raise IdentifierError(
            f"expected template ID, got {type(parsed).__name__}: {identifier!r}"
        )
    return parsed


def parse_image_ref(identifier: str) -> ImageRef:
    parsed = parse(identifier)
    if not isinstance(parsed, ImageRef):
        raise IdentifierError(
            f"expected image reference, got {type(parsed).__name__}: {identifier!r}"
        )
    return parsed


def parse_image_defaults_ref(identifier: str) -> ImageDefaultsRef:
    parsed = parse(identifier)
    if not isinstance(parsed, ImageDefaultsRef):
        raise IdentifierError(
            f"expected image-defaults reference, got {type(parsed).__name__}: {identifier!r}"
        )
    return parsed


def parse_template_handle(handle: str) -> tuple[str, str]:
    """Parse ``<flavour>:<name>`` (no version). Used by ``template new``."""
    if not isinstance(handle, str) or not handle:
        raise IdentifierError(f"invalid template handle: {handle!r}")
    parts = handle.split(":")
    if len(parts) != 2 or any(p == "" for p in parts):
        raise IdentifierError(
            f"invalid template handle: {handle!r} (expected <flavour>:<name>)"
        )
    return _validate_flavour(parts[0]), _validate_name(parts[1])
