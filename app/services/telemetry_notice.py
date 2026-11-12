"""One local disclosure before automatic telemetry, including on upgrades."""
from __future__ import annotations

import logging
from typing import Any, Callable

from app.i18n import _
from app.widgets.update_bar import TelemetryBar
from core.config import save_config
from core.stats import TELEMETRY_NOTICE_VERSION, forget_install_id, telemetry_notice_seen

logger = logging.getLogger(__name__)
_RETRY_MS = 500


class TelemetryNotice:
    def __init__(self, app: Any, *, on_ready: Callable[[], None]) -> None:
        self.app = app
        self._on_ready = on_ready
        self._started = False
        self._ready = False
        self._bar: Any = None

    def start(self) -> None:
        if not self._started:
            self._started = True
            self.app.after_idle(self._try_show)

    def _available(self) -> bool:
        return (not getattr(self.app, "_closing", False)
                and bool(self.app.winfo_viewable())
                and not any(getattr(self.app, name, False) for name in
                            ("_quick_start_open", "_hub_setup_open", "_model_question_open")))

    def _activate(self) -> None:
        if not self._ready:
            self._ready = True
            try:
                self._on_ready()
            except Exception:  # noqa: BLE001 - optional telemetry cannot break startup
                logger.warning("Optional telemetry could not start", exc_info=True)

    def _try_show(self) -> None:
        if getattr(self.app, "_closing", False):
            return
        if telemetry_notice_seen(self.app.app_config):
            self._activate()
            return
        try:
            if not self._available():
                self.app.after(_RETRY_MS, self._try_show)
                return
            if self._bar is None:
                self._bar = TelemetryBar(self.app, on_keep=self.keep, on_off=self.turn_off)
                if self.app.app_config.get("telemetry_opt_in", True):
                    text = _("Usage statistics are on. The app sends model, language, timing and error codes, "
                             "coarse hardware details, and a random installation ID to help fix problems. "
                             "Audio, transcripts and file paths are excluded. You can turn this off at any time.")
                else:
                    text = _("Usage statistics are off and will stay off. If enabled, they include model, language, "
                             "timing and error codes, coarse hardware details, and a random installation ID. "
                             "Audio, transcripts and file paths are excluded.")
                self._bar.show(text, before=self.app.nb)
            # Packing a widget does not mean it has been painted. Do not persist
            # the marker or enable senders until Tk reports the bar as viewable.
            self.app.after_idle(self._record_visible)
        except Exception:  # noqa: BLE001 - no display means no marker and no automatic telemetry
            logger.warning("Usage-statistics notice could not be displayed", exc_info=True)

    def _record_visible(self) -> None:
        if getattr(self.app, "_closing", False):
            return
        try:
            if not self._available() or self._bar is None or not self._bar.winfo_viewable():
                self.app.after(_RETRY_MS, self._record_visible)
                return
            cfg = self.app.app_config
            if telemetry_notice_seen(cfg):
                self._activate()
                return
            previous = cfg.get("telemetry_notice_version", 0)
            cfg["telemetry_notice_version"] = TELEMETRY_NOTICE_VERSION
            try:
                save_config(cfg)
            except Exception:  # noqa: BLE001
                cfg["telemetry_notice_version"] = previous
                self._bar.show(_("Could not save the statistics notice. Automatic reports remain paused. "
                                 "Choose Got it to retry, or turn statistics off."), before=self.app.nb)
                logger.warning("Usage-statistics notice could not be saved", exc_info=True)
                return
            self._activate()
        except Exception:  # noqa: BLE001 - a destroyed widget cannot imply disclosure
            logger.debug("Usage-statistics notice is no longer visible", exc_info=True)

    def keep(self) -> None:
        self._record_visible()
        if telemetry_notice_seen(self.app.app_config) and self._bar is not None:
            self._bar.hide()

    def turn_off(self) -> None:
        self.app.app_config["telemetry_opt_in"] = False
        forget_install_id(self.app.app_config)
        sync = getattr(self.app, "_sync_telemetry_menu", None)
        if sync is not None:
            sync()
        try:
            save_config(self.app.app_config)
        except Exception:  # noqa: BLE001 - off still applies to this running instance
            logger.warning("Usage-statistics choice could not be saved", exc_info=True)
            if self._bar is not None:
                self._bar.show(_("Statistics are off for this session, but the choice could not be saved. "
                                 "It may be on again after restarting. Try turning it off again."), before=self.app.nb)
            return
        self.keep()
