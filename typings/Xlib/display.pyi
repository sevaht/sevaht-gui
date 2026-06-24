from typing import Any

from Xlib.protocol import event as event

# A union of the event fields the tray reads; python-xlib delivers a different
# concrete event class per type, but they share these attributes.
class Event:
    type: int
    window: Any
    detail: int
    client_type: int
    data: Any

# RandR reply objects (only the fields the monitor lookup reads). The
# screen-resources / output-primary replies come off a window object typed as
# Any, so only these two Display-level RandR calls need real types.
class OutputInfo:
    crtc: int

class CrtcInfo:
    x: int
    y: int
    width: int
    height: int

# Resource objects (windows, GCs, pixmaps) and screens are returned as Any:
# python-xlib builds them dynamically and the tray code treats them loosely.
class Display:
    def __init__(self, display: str | None = ...) -> None: ...
    def screen(self, sno: int | None = ...) -> Any: ...
    def intern_atom(self, name: str, only_if_exists: bool = ...) -> int: ...
    def get_default_screen(self) -> int: ...
    def get_selection_owner(self, selection: int) -> Any: ...
    def create_resource_object(self, rtype: str, rid: int) -> Any: ...
    def grab_server(self) -> None: ...
    def ungrab_server(self) -> None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...
    def next_event(self) -> Event: ...
    def xrandr_get_output_info(
        self, output: int, config_timestamp: int
    ) -> OutputInfo: ...
    def xrandr_get_crtc_info(
        self, crtc: int, config_timestamp: int
    ) -> CrtcInfo: ...
    def send_event(
        self,
        destination: Any,
        event: Any,
        event_mask: int = ...,
        propagate: bool = ...,
        onerror: Any = ...,
    ) -> None: ...
