import os

from pydantic import BaseSettings, Field

from .loader import SecretsLoader


class AppSettings(BaseSettings):
    REGION_ID: str = Field(..., env="REGION_ID")
    TABLE_NAME: str = Field(..., env="TABLE_NAME")
    BUCKET_NAME: str = Field(..., env="BUCKET_NAME")
    PRIVACY_KB_ID: str = Field(..., env="PRIVACY_KB_ID")
    ALEXION_ID: str = Field(..., env="ALEXION_ID")
    GEN_ENQ_KB_ID: str = Field(..., env="GEN_ENQ_KB_ID")
    API_KEY: str = Field(..., env="API_KEY")
    MODEL_ID: str = Field(..., env="MODEL_ID")

    class Config:
        # first load AWS secrets, then fall back to real env vars
        @classmethod
        def customise_sources(
            cls, init_settings, env_settings, file_secret_settings
        ):
            loader = SecretsLoader(
                region_name=os.getenv("AWS_REGION", "us-east-1"),
                secret_name=os.getenv("SECRET_NAME", "your-default-secret"),
            )
            return (
                init_settings,
                lambda _: loader.load(),
                env_settings,
            )


# create a singleton
settings = AppSettings()
