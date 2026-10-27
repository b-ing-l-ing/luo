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

    persona_path: Path = PACKAGE_DIR / "persona" / "system.md"
    db_path: Path = PROJECT_ROOT / "data" / "luo.db"

    history_limit: int = Field(default=20, ge=1)
    memory_top_k: int = Field(default=8, ge=0, le=50)
    memory_extract_every: int = Field(default=6, ge=1)
