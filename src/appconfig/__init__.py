"""Cấu hình mặc định nằm ở `config/<module>.yaml`; không field nào có giá trị mặc định trong code.

Thứ tự ưu tiên (cao → thấp): tham số khởi tạo > biến môi trường > `.env` > file YAML. Biến env
rỗng (`KEY=`) nghĩa là "dùng giá trị YAML". Secret (API key, token) không nằm trong YAML, chỉ đặt
qua env / `.env`; lớp con giữ default rỗng cho riêng các field đó.

Thư mục `config/`: biến môi trường CALLBOT_CONFIG_DIR nếu có (image Docker đặt `/app/config`),
không thì `<repo>/config` cạnh `src/` — đúng với `pip install -e`, không phụ thuộc thư mục chạy.
"""

import os
from pathlib import Path
from typing import Any

from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

CONFIG_DIR = Path(
    os.environ.get("CALLBOT_CONFIG_DIR") or Path(__file__).resolve().parents[2] / "config"
)


def yaml_config(file: str, section: str | None = None, **extra: Any) -> SettingsConfigDict:
    """`model_config` của lớp con: file YAML trong `config/` và (tuỳ chọn) section bên trong."""
    return SettingsConfigDict(yaml_file=CONFIG_DIR / file, yaml_config_section=section, **extra)


class _EnvLayer(PydanticBaseSettingsSource):
    """Gộp env + `.env` (env thắng) rồi mới bỏ giá trị rỗng để rơi về YAML.

    Không dùng `env_ignore_empty` của pydantic-settings: nó bỏ `KEY=` ở env TRƯỚC khi so với
    `.env`, nên `OPENAI_API_KEY=` (test chặn key thật) lại để `.env` thắng.
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        env: PydanticBaseSettingsSource,
        dotenv: PydanticBaseSettingsSource,
    ):
        super().__init__(settings_cls)
        self._env = env
        self._dotenv = dotenv

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        raise NotImplementedError  # __call__ đọc thẳng từ hai source con

    def __call__(self) -> dict[str, Any]:
        merged = {**self._dotenv(), **self._env()}
        return {
            key: value
            for key, value in merged.items()
            if not (isinstance(value, str) and not value.strip())
        }


class YamlSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        yaml_file_encoding="utf-8",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        yaml_file = settings_cls.model_config.get("yaml_file")
        if yaml_file is None:
            raise TypeError(f"{settings_cls.__name__} thiếu model_config = yaml_config(...)")
        # pydantic-settings bỏ qua im lặng file không tồn tại → lỗi "Field required" khó hiểu.
        if not Path(yaml_file).is_file():
            raise FileNotFoundError(
                f"Không thấy {yaml_file} (cần cho {settings_cls.__name__}); "
                "đặt CALLBOT_CONFIG_DIR trỏ tới thư mục config/"
            )
        return (
            init_settings,
            _EnvLayer(settings_cls, env_settings, dotenv_settings),
            YamlConfigSettingsSource(settings_cls),
        )
