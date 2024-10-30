from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)

    API_ID: int
    API_HASH: str

    USE_RANDOM_DELAY_IN_RUN: bool = False
    RANDOM_DELAY_IN_RUN: list[int] = [0, 49800]

    REF_ID: str = '6434058521'

    AUTO_TASK: bool = True
    CLAIM_REWARD: bool = True

    SLEEP_TIME: list[int] = [41200, 80800]

    USE_PROXY: bool = False


settings = Settings()
