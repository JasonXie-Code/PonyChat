"""Compatibility loader for `companion_chat route` implementation modules.

The implementation lives in `companion_chat_impl/` and is executed into this module's
namespace so existing imports and monkeypatch targets keep working.
"""
from __future__ import annotations

import pathlib as _impl_pathlib
import sys as _impl_sys


def _load_implementation_modules() -> None:
    impl_modules = (
        "session_routes.py",
        "message_routes.py",
    )
    impl_dir = _impl_pathlib.Path(_impl_sys._getframe().f_code.co_filename).with_name("companion_chat_impl")
    for impl_module in impl_modules:
        impl_path = impl_dir / impl_module
        exec(
            compile(impl_path.read_text(encoding="utf-8"), str(impl_path), "exec"),
            globals(),
            globals(),
        )


_load_implementation_modules()
globals().pop("_load_implementation_modules", None)
globals().pop("_impl_pathlib", None)
globals().pop("_impl_sys", None)