from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[1]


class Settings(BaseSettings):
    """项目配置。字段名会自动映射到同名环境变量（不区分大小写）。

    注意：PROJECT_ROOT 按 editable 安装（src 布局）推导；如果以后打成 wheel，
    这里会指向 site-packages，需要改成用户目录或显式配置。
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-flash"

    # 联网搜索（按需工具；DeepSeek 原生搜索，Bing RSS 兜底）
    web_search_enabled: bool = True
    web_search_provider: str = "auto"
    web_search_base_url: str = "https://api.deepseek.com/anthropic/v1"
    web_search_model: str = "deepseek-v4-flash"
    web_search_max_results: int = Field(default=5, ge=1, le=10)
    auto_save_web_memes: bool = True
    web_meme_max_per_hour: int = Field(default=3, ge=0)

    persona_path: Path = PACKAGE_DIR / "persona" / "system.md"
    db_path: Path = PROJECT_ROOT / "data" / "luo.db"

    history_limit: int = Field(default=20, ge=1)
    memory_top_k: int = Field(default=8, ge=0, le=50)
    memory_extract_every: int = Field(default=6, ge=1)
    startup_greeting: bool = True
    style_debug: bool = False

    # 跨通道身份映射：raw_key=canonical_key，逗号分隔。
    # 例：qq:3466766306=local 让 QQ 主号和终端共用 "local" 这一份记忆。
    session_aliases: str = ""

    # 主动消息：QQ 会话空闲且还有未完成的事时，主动发一句。
    proactive_enabled: bool = True
    proactive_idle_minutes: int = Field(default=120, ge=0)
    proactive_cooldown_minutes: int = Field(default=720, ge=0)
    proactive_check_seconds: int = Field(default=60, ge=5)

    # QQ（NapCat / OneBot 11，私聊）
    qq_ws_url: str = "ws://127.0.0.1:3001"
    qq_access_token: str = ""
    qq_allowed_users: str = ""
    qq_self_id: str = ""
    qq_burst_max: int = Field(default=3, ge=1, le=5)
    qq_burst_delay: float = Field(default=0.8, ge=0.0, le=5.0)

    # 本地梗图库：文件名就是标签
    memes_dir: Path = PROJECT_ROOT / "memes"
    # QQ 收藏表情同步后的本地库
    stickers_path: Path = PROJECT_ROOT / "state" / "stickers.json"

    # Minecraft 边车（Node WebSocket API）
    mc_ws_url: str = "ws://127.0.0.1:3002"
    mc_bot_name: str = "LuoBot"
    mc_allowed_players: str = ""
