import uvicorn

from webgate.config import settings


def main() -> None:
    uvicorn.run(
        "webgate.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=False,
    )


if __name__ == "__main__":
    main()
