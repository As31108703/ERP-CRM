from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseModel):
    # 寫入請求允許的 Origin；空清單時改用 X-Forwarded-* / Host 組出的 origin 比對
    allowed_origins: list[str] = []
    # true：公開展示模式，工作區 72 小時無存取即刪除
    public_demo: bool = False
    # true：新工作區自動以預設值完成初始設定
    auto_setup: bool = False
    default_industry: str = "retail"
    default_company: str = "星軌示範商店"
    # None 表示依產業預設啟用的模組
    default_modules: list[str] | None = None


class DatabaseConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432
    user: str = "erpcrm"
    # 只檢查型別，不做強度規則：密碼由部署環境決定，驗證錯誤也不應把值印進日誌
    password: str = ""
    name: str = "erpcrm"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    app: AppConfig = AppConfig()
    database: DatabaseConfig = DatabaseConfig()
