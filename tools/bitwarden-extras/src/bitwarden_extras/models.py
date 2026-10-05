"""Data models and schemas for Bitwarden Extras."""

from collections.abc import Sequence
from enum import IntEnum, StrEnum
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

_CONTROL_CHARS = "".join(chr(c) for c in range(32)) + "\x7f"


def clean_str(val: object) -> str:
    """Strip Unicode whitespace and ASCII control characters (0x00-0x1F, 0x7F)."""
    if val is None:
        return ""
    return str(val).strip().strip(_CONTROL_CHARS).strip()


class OutputFormat(StrEnum):
    """Supported metadata export formats."""

    YAML = "yaml"
    JSON = "json"


class ItemType(IntEnum):
    """Bitwarden item cipher types."""

    LOGIN = 1
    SECURE_NOTE = 2
    CARD = 3
    IDENTITY = 4

    @property
    def label(self) -> str:
        match self:
            case ItemType.LOGIN:
                return "Login"
            case ItemType.SECURE_NOTE:
                return "Secure Note"
            case ItemType.CARD:
                return "Card"
            case ItemType.IDENTITY:
                return "Identity"
            case _:
                return "Other"


def match_type(item_type: int) -> str:
    """Return a human-readable label for a numeric item type."""
    try:
        return ItemType(item_type).label
    except ValueError:
        return "Other"


class LoginUri(BaseModel):
    """A URI entry associated with a login."""

    model_config = ConfigDict(extra="ignore")

    uri: str = ""
    match: int | None = None


class LoginData(BaseModel):
    """Login credentials and URIs."""

    model_config = ConfigDict(extra="ignore")

    username: str | None = None
    password: str | None = None
    uris: list[LoginUri] = Field(default_factory=list)
    totp: str | None = None


class FolderData(BaseModel):
    """A Bitwarden vault folder."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str | None = None


class RawCipherItem(BaseModel):
    """Raw cipher object as returned by Bitwarden."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str | None = None
    type: int = 1
    folderId: str | None = None
    notes: str | None = None
    favorite: bool = False
    reprompt: int = 0
    revisionDate: str | None = None
    creationDate: str | None = None
    login: LoginData | None = None


def extract_domains(login_data: LoginData | dict[str, Any] | None) -> list[str]:
    """Extract distinct hostnames/domains from login URIs."""
    if not login_data:
        return []

    uris: list[Any] = []
    if isinstance(login_data, LoginData):
        uris = [u.uri for u in login_data.uris]
    elif isinstance(login_data, dict):
        raw_uris = login_data.get("uris", [])
        uris = [u.get("uri", "") if isinstance(u, dict) else str(u) for u in raw_uris]

    domains: list[str] = []
    for raw in uris:
        raw_uri = str(raw).strip()
        if not raw_uri:
            continue
        try:
            target = raw_uri if "://" in raw_uri else f"http://{raw_uri}"
            parsed = urlparse(target)
            if (host := parsed.hostname) and host not in domains:
                domains.append(host)
        except ValueError:
            continue
    return domains


class SanitizedItem(BaseModel):
    """A sanitized item strictly omitting sensitive credentials."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    folder: str | None = None
    type: str
    username: str | None = None
    domains: list[str] = Field(default_factory=list)
    notes: str | None = None
    favorite: bool = False
    reprompt: int = 0
    id: str | None = None
    revision_date: str | None = None
    creation_date: str | None = None


class VaultMetadata(BaseModel):
    """Container for processed, sanitized vault metadata."""

    folders: list[str]
    total_items: int
    items: list[SanitizedItem]


def sanitize_item(
    item: RawCipherItem | dict[str, Any],
    folder_map: dict[str, str],
    include_notes: bool = False,
) -> SanitizedItem:
    """Convert a raw cipher item into a SanitizedItem."""
    if isinstance(item, dict):
        item = RawCipherItem.model_validate(item)

    raw_name = clean_str(item.name)
    name = raw_name if raw_name else None

    folder = folder_map.get(item.folderId) if item.folderId else None

    raw_notes = item.notes if include_notes else None
    notes = raw_notes if raw_notes is not None else None

    username = item.login.username if item.login else None
    domains = extract_domains(item.login)

    return SanitizedItem(
        name=name,
        folder=folder,
        type=match_type(item.type),
        username=username,
        domains=domains,
        notes=notes,
        favorite=item.favorite,
        reprompt=item.reprompt,
        id=item.id,
        revision_date=item.revisionDate,
        creation_date=item.creationDate,
    )


def process_vault(
    folders_data: Sequence[FolderData | dict[str, Any]],
    items_data: Sequence[RawCipherItem | dict[str, Any]],
    include_notes: bool = False,
) -> VaultMetadata:
    """Sanitize and structure vault items and folders."""
    folder_map: dict[str, str] = {}
    folder_names: list[str] = []

    for f in folders_data:
        f_obj = f if isinstance(f, FolderData) else FolderData.model_validate(f)
        clean_name = clean_str(f_obj.name) or "Unnamed Folder"
        folder_map[f_obj.id] = clean_name
        if clean_name not in folder_names:
            folder_names.append(clean_name)

    folder_names.sort()

    sanitized_items = [
        sanitize_item(it, folder_map, include_notes=include_notes) for it in items_data
    ]

    return VaultMetadata(
        folders=folder_names,
        total_items=len(sanitized_items),
        items=sanitized_items,
    )
