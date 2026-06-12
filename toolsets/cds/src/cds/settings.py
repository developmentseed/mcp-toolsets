from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """CDS API configuration, read from the environment (or a .env in the cwd).

    `cds_api_key` defaults to empty so the toolset imports and serves without
    credentials; calls then return structured auth errors until CDS_API_KEY
    is provided (in k8s, via the Secret listed in toolset.yaml).
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    cds_api_key: str = ""
    cds_api_url: str = "https://cds.climate.copernicus.eu/api/retrieve/v1"
    cds_catalogue_url: str = "https://cds.climate.copernicus.eu/api/catalogue/v1"


settings = Settings()
