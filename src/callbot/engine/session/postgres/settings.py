from pydantic_settings import BaseSettings, SettingsConfigDict


class SessionStoreSettings(BaseSettings):
    # .env dùng chung với các module khác nên bỏ qua key lạ
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # postgresql://user:password@host:5432/db — bắt buộc với ứng dụng HTTP
    session_database_url: str = ""
    session_pool_min_size: int = 1
    # Mỗi request đang xử lý giữ 1 connection khóa + mượn thêm 1 connection ghi
    session_pool_max_size: int = 10
    session_pool_timeout_s: float = 5.0
