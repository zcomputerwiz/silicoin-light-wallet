import os
from pathlib import Path

DEFAULT_ROOT_PATH = Path(os.path.expanduser(os.getenv("SILICOIN_ROOT", "~/.silicoin/standalone_wallet"))).resolve()

DEFAULT_KEYS_ROOT_PATH = Path(os.path.expanduser(os.getenv("SILICOIN_KEYS_ROOT", "~/.silicoin_keys"))).resolve()
