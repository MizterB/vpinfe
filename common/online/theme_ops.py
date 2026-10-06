"""Frontend themes: what is available, what is installed, and which one plays.

"Theme" unqualified means the frontend's, which is a decision the tree already made - a
game's `themes` are what a machine is about.

Reading the registry reaches the network, so it is held per process and refreshed only
when a caller asks. Re-reading it on every draw would spend a round trip per render on a
list that changes when somebody publishes a release.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from common import service_errors
from common.atomic_write import write_atomic
from common.failures import why
from common.i18n import t
from common.online import theme_service, theme_source_checks, theme_sources, theme_sync
from common.online.theme_registry_client import ThemeRegistryError
from common.online.themes import ThemeRegistry
from common.paths import THEME_CACHE_PATH, get_ini_config

logger = logging.getLogger("vpinfe.common.online.theme_ops")


class SourceUnavailableError(service_errors.ServiceError):
    """A theme source that will not load. Nothing about this install is wrong."""


class InstallFailedError(service_errors.ServiceError):
    """The registry was read and the install did not finish."""


class RemoveFailedError(service_errors.ServiceError):
    """The theme is installed and could not be taken away."""


_lock = threading.RLock()
_registry: Any = None
# What each source said when the last read found none of them usable. Nothing else
# holds it: that read builds no registry to keep.
_unread: dict[str, dict[str, Any]] = {}


def _loaded(refresh: bool = False) -> ThemeRegistry:
    """The registry: from memory, else from the last read kept on disk, else - or when
    asked - from the sources, which is network work and not per request."""
    global _registry, _unread
    with _lock:
        if _registry is None and not refresh:
            _registry = _cached()
        if _registry is None or refresh:
            before = _registry or _cached()
            try:
                fresh = theme_service.load_registry(previous=before)
            except theme_source_checks.NothingReadError as exc:
                _unread = exc.reports
                raise
            _unread = {}
            _carry_dates(fresh, before)
            _keep(fresh)
            if _answered(fresh):
                theme_sync.stamp(get_ini_config())
            _registry = fresh
        return _registry


def _answered(registry: ThemeRegistry) -> bool:
    """Whether any source gave an answer this read, as opposed to every one failing and
    the listing being what an earlier read kept."""
    states = [report["state"] for report in registry.reports.values()]
    return not states or any(state not in theme_source_checks.BAD for state in states)


def _sources_now() -> dict[str, list[str]]:
    said = theme_sources.from_config(get_ini_config())
    return {"registries": list(said.registries), "repositories": list(said.repositories)}


def _cached() -> ThemeRegistry | None:
    """The last read, unless the configured sources have changed since."""
    try:
        held = json.loads(THEME_CACHE_PATH.read_text(encoding="utf-8"))
        if held.get("sources") != _sources_now():
            return None
        registry = ThemeRegistry()
        registry.restore(held)
        return registry
    except FileNotFoundError:
        return None
    except Exception:  # noqa: BLE001 - a copy this build cannot read is read again
        logger.warning("Could not use the kept theme list; reading the sources",
                       exc_info=True)
        return None


def _keep(registry: ThemeRegistry) -> None:
    try:
        kept = {**registry.snapshot(), "sources": _sources_now()}
        THEME_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(THEME_CACHE_PATH, lambda out: json.dump(kept, out))
    except Exception:  # noqa: BLE001 - an unwritten copy costs the next start a read
        logger.warning("Could not keep the theme list", exc_info=True)


def _ref(entry: dict[str, Any]) -> str:
    return str(getattr(entry.get("release"), "ref", "") or "")


def _carry_dates(fresh: ThemeRegistry, before: ThemeRegistry | None) -> None:
    """A date the host would not give this time is the one it gave last, while the
    release it dates is still the one on offer."""
    if before is None:
        return
    for key, entry in fresh.themes.items():
        known = before.themes.get(key) or {}
        if not entry.get("updated") and known.get("updated") and _ref(known) == _ref(entry):
            entry["updated"] = known["updated"]


def _described(registry: ThemeRegistry, active: str) -> list[dict[str, Any]]:
    found = registry.get_themes()
    try:
        updates = registry.check_for_updates(list(found))
    except Exception:  # noqa: BLE001 - an update check that fails is not a broken list
        logger.warning("Could not check themes for updates", exc_info=True)
        updates = {}

    out: list[dict[str, Any]] = []
    for key, entry in found.items():
        manifest = dict(entry.get("manifest") or {})
        info = dict(entry.get("registry_info") or {})
        installed = registry.is_installed(key)
        update = updates.get(key) or {}
        schema = (theme_service.load_theme_option_schema(key, registry)
                  if installed else None)
        out.append({
            "key": key,
            "name": str(manifest.get("name") or key),
            "author": str(manifest.get("author") or ""),
            "description": str(manifest.get("description") or ""),
            "version": str(update.get("remote_version")
                           or manifest.get("version") or ""),
            "installed_version": str(update.get("installed_version") or ""),
            # What it needs to show itself: 1 is a desktop, 3 is a cabinet.
            "screens": manifest.get("supported_screens"),
            "type": str(manifest.get("type") or ""),
            "url": str(info.get("theme_base_url") or info.get("url") or ""),
            "registry": ("" if info.get(theme_sources.NAMED_BY_MANIFEST)
                         else str(entry.get("source") or "")),
            # Where the picture is, resolved here rather than by each client: an
            # installed theme serves its own from /themes/, and one that is not has to
            # be fetched from where its manifest lives.
            "preview": _preview(key, manifest, info, installed),
            "change_log": str(manifest.get("change_log") or ""),
            "updated": str(entry.get("updated") or ""),
            "installed": installed,
            "active": key == active,
            "default_install": bool(info.get("default_install")),
            "update_available": bool(update.get("update_available")) and installed,
            "configurable": bool(schema and schema.get("options")),
            "origin": "registry",
        })
    for key, manifest in registry.local_themes().items():
        schema = theme_service.load_theme_option_schema(key, registry)
        out.append({
            "key": key,
            "name": str(manifest.get("name") or key),
            "author": str(manifest.get("author") or ""),
            "description": str(manifest.get("description") or ""),
            "version": str(manifest.get("version") or ""),
            "installed_version": str(manifest.get("version") or ""),
            "screens": manifest.get("supported_screens"),
            "type": str(manifest.get("type") or ""),
            "url": "",
            "registry": "",
            "preview": _preview(key, manifest, {}, True),
            "change_log": str(manifest.get("change_log") or ""),
            "updated": "",
            "installed": True,
            "active": key == active,
            "default_install": False,
            "update_available": False,
            "configurable": bool(schema and schema.get("options")),
            "origin": "local",
        })
    # Active first, then installed, then the rest - the order somebody scans in.
    out.sort(key=lambda one: (not one["active"], not one["installed"],
                              one["name"].lower()))
    return out


def _preview(key: str, manifest: dict, info: dict, installed: bool) -> str:
    name = str(manifest.get("preview_image") or "").strip()
    if not name:
        return ""
    if name.startswith("http"):
        return name
    if installed:
        return f"/themes/{key}/{name}"
    where = str(info.get("theme_manifest_url") or "")
    return f"{where.rsplit('/', 1)[0]}/{name}" if where else ""


def _readable(refresh: bool = False) -> ThemeRegistry:
    """The registry, or SourceUnavailableError in words."""
    try:
        return _loaded(refresh)
    except ThemeRegistryError as exc:
        raise SourceUnavailableError(why(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - a source that will not load is news
        raise SourceUnavailableError(why(exc)) from exc


def listing(refresh: bool = False) -> dict[str, Any]:
    """Active first, then installed, then the rest.

    `refresh` re-reads the sources. Without it the answer is whatever was read when this
    process first asked, which is right for a page that draws several times a minute.
    """
    registry = _readable(refresh)
    active = theme_service.get_active_theme()
    return {"active": active, "themes": _described(registry, active),
            "checked": theme_sync.checked_at(get_ini_config())}


def _known() -> ThemeRegistry | None:
    """The last read, from memory or from disk. Never reaches the network."""
    with _lock:
        return _registry if _registry is not None else _cached()


def sources() -> dict[str, Any]:
    """What each configured source said when it was last read, in the order they are
    configured. A source never read, or added since, is Not checked.

    Does not read the sources: the page that draws this asks on every visit.
    """
    checks = theme_source_checks
    said = theme_sources.from_config(get_ini_config())
    known = _known()
    held = _unread or (known.reports if known is not None else {})

    def row(address: str, kind: str) -> dict[str, Any]:
        found = held.get(address)
        if found is None or found["kind"] != kind:
            found = checks.waiting(address, kind)
        return {**found, "level": checks.level(found["state"])}

    return {"registries": [row(url, checks.LIST) for url in said.registries if url.strip()],
            "repositories": [row(url, checks.THEME) for url in said.repositories
                             if url.strip()],
            "checked": theme_sync.checked_at(get_ini_config())}


def _configured_kinds() -> dict[str, str]:
    """Every configured address, as written and as parsed, with the kind it is held as."""
    said = theme_sources.from_config(get_ini_config())
    held: dict[str, str] = {}
    for kind, urls in ((theme_source_checks.LIST, said.registries),
                       (theme_source_checks.THEME, said.repositories)):
        for url in urls:
            where = theme_sources.parse(url)
            held[url] = held[where.url if where else url] = kind
    return held


def _read_alone(address: str, kind: str) -> tuple[dict[str, Any], ThemeRegistry]:
    """A source read on its own, through the path the real read takes."""
    alone = theme_sources.ThemeSources(
        registries=(address,) if kind == theme_source_checks.LIST else (),
        repositories=(address,) if kind == theme_source_checks.THEME else ())
    registry = ThemeRegistry(sources=alone)
    try:
        registry.load_registry()
        if kind == theme_source_checks.THEME:
            registry.load_theme_manifests(dates=False)
    except ThemeRegistryError:
        pass  # every source failing is raised, and what each said is kept
    return registry.reports[address], registry


def check_source(address: str) -> dict[str, Any]:
    """What adding `address` would be, found out without adding it.

    Reads the address and says what it is: its kind, its state and the address it would
    be saved under. `addable` is false for the states Add refuses. Reads JSON only; no
    theme is downloaded.
    """
    checks = theme_source_checks
    where = theme_sources.parse(str(address or ""))
    if where is None:
        bad = checks.failed(str(address or "").strip(), checks.THEME, checks.NOT_A_THEME,
                            t("themes.source.bad_address"))
        return _checked(bad)
    held = _configured_kinds()
    if where.url in held:
        return _checked(checks.failed(where.url, held[where.url], checks.ALREADY_ADDED,
                                      t("themes.source.already_added")))

    kind = checks.LIST if where.is_file else checks.THEME
    report, read = _read_alone(where.url, kind)
    if (kind == checks.THEME and report["state"] == checks.NOT_A_THEME
            and report["reason"] == t("themes.source.no_manifest")):
        # No theme here, but a repository can be a list instead.
        file = theme_sources.list_file(where)
        added = file if file in held else _list_added_from(where, held)
        if added:
            return _checked(checks.failed(added, checks.LIST, checks.ALREADY_ADDED,
                                          t("themes.source.already_added")))
        as_list, listed = _read_alone(file, checks.LIST)
        if as_list["state"] == checks.READY:
            report, read = as_list, listed
    return _checked(report, _offered_elsewhere(report, read))


def _list_added_from(where: theme_sources.Address, held: dict[str, str]) -> str:
    """The configured list that is this repository's `themes.json`, on whatever branch."""
    for address, kind in held.items():
        other = theme_sources.parse(address)
        if (kind == theme_source_checks.LIST and other is not None and other.repo == where.repo
                and address.endswith(f"/{theme_sources.LIST_FILE}")):
            return address
    return ""


def _offered_elsewhere(report: dict[str, Any], read: ThemeRegistry) -> dict[str, Any]:
    """What a source about to be added would meet among the themes already offered."""
    known = _known()
    sources_in_use = theme_sources.from_config(get_ini_config())
    offered = {key: str(entry.get("source") or "")
               for key, entry in (known.themes.items() if known is not None else [])}
    if report["kind"] == theme_source_checks.THEME:
        name = report["name"]
        if name not in offered:
            return {}
        if offered[name] in sources_in_use.repositories:
            return {"state": theme_source_checks.NOT_USED,
                    "reason": t("themes.source.not_used", name=name)}
        return {"replaces": [name]}
    # A list is added below every source there is, so each name it shares is one it loses.
    return {"took": [key for key in read.themes_index if key in offered]}


def _checked(report: dict[str, Any], more: dict[str, Any] | None = None) -> dict[str, Any]:
    checks = theme_source_checks
    out = {**report, **(more or {})}
    out.setdefault("replaces", [])
    out["level"] = checks.level(out["state"])
    out["group"] = "registries" if out["kind"] == checks.LIST else "repositories"
    out["addable"] = out["state"] not in checks.REFUSED
    return out


def install(key: str) -> dict[str, Any]:
    """One call for both. Installing over an existing copy is what an update is, and two
    endpoints doing it would be two names for one act."""
    registry = _readable()
    try:
        theme_service.install_theme(registry, key)
    except ThemeRegistryError as exc:
        raise InstallFailedError(why(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise InstallFailedError(why(exc)) from exc
    return {"key": key, "installed": registry.is_installed(key)}


def remove(key: str) -> dict[str, Any]:
    registry = _readable()
    if not registry.is_installed(key):
        raise service_errors.NotFoundError(t("error.themes.not_installed", key=(key)))
    if key == theme_service.get_active_theme():
        # Refused rather than allowed with a warning: the frontend would come up with
        # no theme at all, and the way out of that is a config file.
        raise service_errors.RefusedError(
            t("error.themes.still_active", key=(key)))
    try:
        theme_service.delete_theme(registry, key)
    except ThemeRegistryError as exc:
        raise service_errors.RefusedError(why(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise RemoveFailedError(why(exc)) from exc
    return {"key": key, "installed": False}


def activate(key: str) -> dict[str, Any]:
    """Written to the config. It takes effect when the frontend next starts, which the
    caller is expected to say - this endpoint changes a setting rather than restarting
    anything."""
    key = str(key or "").strip()
    if not key:
        raise service_errors.RefusedError(t("error.themes.none_named"))
    if not _readable().is_installed(key):
        raise service_errors.RefusedError(t("error.themes.not_installed", key=key))
    theme_service.set_active_theme(key)
    return {"active": theme_service.get_active_theme()}


def options(key: str) -> dict[str, Any]:
    """The schema a theme declares, and what it is currently set to.

    Its own shape rather than the install's config schema: these belong to the theme,
    live in its `theme.json`, and a theme can declare a control this install has never
    heard of.
    """
    registry = _readable()
    if not registry.is_installed(key):
        raise service_errors.NotFoundError(t("error.themes.not_installed", key=(key)))
    schema = theme_service.load_theme_option_schema(key, registry)
    if not schema:
        return {"key": key, "title": "", "description": "", "options": [], "values": {}}
    return {"key": key, "title": schema.get("title", ""),
            "description": schema.get("description", ""),
            "options": schema.get("options") or [],
            "values": theme_service.get_theme_option_values(key, registry)}


def save_options(key: str, values: dict[str, Any]) -> dict[str, Any]:
    """Kept beside the config rather than inside the theme.

    The package is deleted by an update, so values written into it were reset by the
    next one - every time, with no warning. The theme still declares what its options
    *are*; this is only what somebody chose.
    """
    registry = _readable()
    if not registry.is_installed(key):
        raise service_errors.NotFoundError(t("error.themes.not_installed", key=(key)))
    try:
        theme_service.save_theme_option_values(key, dict(values or {}), registry)
    except ValueError as exc:
        raise service_errors.RefusedError(why(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise service_errors.RefusedError(why(exc)) from exc
    return {"key": key, "values": theme_service.get_theme_option_values(key, registry)}
