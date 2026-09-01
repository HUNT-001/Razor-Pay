from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    razorpay_key_id: str = "rzp_test_placeholder"
    razorpay_key_secret: str = "placeholder"
    razorpay_webhook_secret: str = "placeholder"

    database_url: str = "sqlite:///./recoverai.db"
    llm_mode: str = "stub"  # stub | anthropic | openai
    log_level: str = "INFO"


settings = Settings()
