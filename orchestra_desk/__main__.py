"""``python -m orchestra_desk read|measure|check``: the reader ``orchestra run`` keeps running as
``desk.reader``, the instrument it runs as ``desk.conditions``, and the configuration check."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
