def main() -> None:
    from .channels.terminal import run
    from .config import Settings

    try:
        run(Settings())
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"启动失败：{exc}")
        raise SystemExit(1) from None
