from .bootstrap import maybe_reexec_with_frozen_code

maybe_reexec_with_frozen_code()

from .main import main

if __name__ == "__main__":
    raise SystemExit(main())
