from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """CDS API configuration, read from the environment (or a .env in the cwd).

    There is no API-key setting: the CDS key is per calling user, sent as the
    `x-cds-token` HTTP header on each MCP request (see `tools._client`).
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    cds_api_url: str = "https://cds.climate.copernicus.eu/api/retrieve/v1"
    cds_catalogue_url: str = "https://cds.climate.copernicus.eu/api/catalogue/v1"


settings = Settings()
