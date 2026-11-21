"""Reset the live demo now: `python -m app.demo_reset`. Refuses unless DEMO_SITE is on."""

import sys

from sqlalchemy.orm import Session

from app.config import AppConfig, get_config
from app.db import make_engine
from app.demo.reset import reset_demo


def main(config: AppConfig | None = None) -> int:
    config = config or get_config()
    if not config.demo_site:
        print("DEMO_SITE is off: refusing to reset", file=sys.stderr)
        return 1
    engine = make_engine(config.database_url)
    try:
        with Session(engine) as session:
            reset_demo(session)
            session.commit()
    finally:
        engine.dispose()
    print("Demo reset complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
