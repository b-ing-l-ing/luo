import asyncio


def main() -> None:
    from .channels.terminal import TerminalChannel
    from .config import Settings
    from .runtime import CompanionRuntime

    try:
        asyncio.run(CompanionRuntime(Settings(), TerminalChannel()).run())
    except KeyboardInterrupt:
        pass
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"启动失败：{exc}")
        raise SystemExit(1) from None


def main_qq() -> None:
    import logging

    from .channels.qq import QQChannel
    from .config import Settings
    from .runtime import CompanionRuntime

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings()
    try:
        asyncio.run(CompanionRuntime(settings, QQChannel(settings)).run())
    except KeyboardInterrupt:
        pass
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"启动失败：{exc}")
        raise SystemExit(1) from None
