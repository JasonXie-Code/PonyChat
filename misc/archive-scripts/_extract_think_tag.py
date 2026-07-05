# -*- coding: utf-8 -*-
import pathlib
import re
t = pathlib.Path(
    r"p:/PonyChat/app/app/src/main/java/top/ponychat/webview/ui/chat/ChatScreen.kt"
).read_text(encoding="utf-8")
m = re.search(
    r'else "([^"]+)"\s*\n\s*if \(!afterTag\.contains\(closeTag',
    t,
)
print("close else branch:", repr(m.group(1)) if m else "none")
