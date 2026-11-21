from __future__ import annotations

import logging
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUTH_SECRET = os.environ.get('PONYCHAT_DRIVE_AUTH_SECRET', '')
if not AUTH_SECRET or not os.environ.get('PONYCHAT_DRIVE_PASSWORD'):
    raise RuntimeError('Drive requires PONYCHAT_DRIVE_AUTH_SECRET and PONYCHAT_DRIVE_PASSWORD')

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('ponychat.drive')
