from __future__ import annotations

import uvicorn

from .config import IssueGraphConfig


def main() -> None:
    config = IssueGraphConfig.from_env()
    uvicorn.run(
        "gui.yura_issue_graph.server:app",
        host=config.host,
        port=config.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
