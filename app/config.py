from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    razorpay_key_id: str = "rzp_test_placeholder"
    razorpay_key_secret: str = "placeholder"
    razorpay_webhook_secret: str = "placeholder"

    database_url: str = "sqlite:///./recoverai.db"
    llm_mode: str = "stub"  # stub | anthropic | groq
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-haiku-latest"
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"

    # Escalation destination (Slack incoming webhook URL or leave blank)
    escalation_webhook_url: str = ""

    # Per-action cost in INR — used for ROI reporting on /analytics/summary
    cost_per_llm_decision_inr: float = 0.05
    cost_per_payment_link_inr: float = 0.50   # SMS + email notify surcharge
    cost_per_simulated_action_inr: float = 0.01

    log_level: str = "INFO"


settings = Settings()
