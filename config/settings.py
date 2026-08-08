# single source file for all the configuration for the pipeline
# without centralized settings, devs os.getenv() is scatterred across 30 files 
# for ex, if the env var names changes then it requires manual changing looking into all the dependencies
# all the envs are defined in one places - settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict
# BaseSettings it knows how to read env vars and validate them
# SettingsConfigDict it knows how to read .env file and validate them

from pydantic import Field # Field adds metadata to each setting

class Settings(BaseSettings):
    ''' Define all configurations in one place only,they are case insensitive and can be read from .env file or env vars'''
    model_config = SettingsConfigDict(env_file=".env", 
                                    env_file_encoding="utf-8", 
                                    case_sensitive=False,
                                    extra="ignore",) # ignore any extra env vars that are not defined in this class
    
    
    openai_api_key: str = Field(..., env="OPENAI_API_KEY", description="OpenAI API key for accessing OpenAI services")
    openai_embedding_model: str = Field(default="text-embedding-3-small", description="OpenAI embedding model to use for generating embeddings")
    openai_chat_model: str = Field(default="gpt-4o", description="OpenAI chat model to use for generating responses and agent reasoning")
    langsmith_api_key: str = Field(..., description="LangSmith API key for tracing and monitoring LangChain applications")
    langsmith_project: str = Field(default="Clinical-Trial-Intelligence", description="LangSmith project name for organizing and managing LangChain applications")
    langsmith_tracing_v2: bool = Field(default=True, description="Enable or disable LangSmith tracing for LangChain applications")
    gcp_project_id: str = Field(..., env="GCP_PROJECT_ID", description="Google Cloud Project ID for accessing GCP services")
    gcp_region: str = Field(default="us-central1", description="Google Cloud region for deploying and accessing GCP services")
    gcs_bucket_name: str = Field(..., description="Google Cloud Storage bucket name for storing and retrieving data")
    db_host: str = Field(..., description="Cloud SQL host or socket path for (Cloud Run)")
    db_port: int = Field(default=5432, description="Cloud SQL port for connecting to the database")
    db_name: str = Field(
        default="clinical_trial_db",
        # The name of the database inside the Cloud SQL instance.
        # Created with: gcloud sql databases create clinical_trial_db
        description="PostgreSQL database name"
    )
    db_user: str = Field(..., description="Cloud SQL database user")
    db_password: str = Field(..., description="Cloud SQL database password")
    
     # ── CLINICALTRIALS.GOV ────────────────────────────────────

    clinical_trials_base_url: str = Field(
        default="https://clinicaltrials.gov/api/v2",
        # The base URL for the ClinicalTrials.gov API version 2.
        # All endpoint calls in clinical_trials_client.py are built
        # from this base URL.
        description="ClinicalTrials.gov API V2 base url"
    )

    clinical_trials_page_size: int = Field(
        default=100,
        # How many studies to request per API page.
        # ClinicalTrials.gov maximum is 1000 but 100 is safer
        # for rate limits and memory — the client paginates automatically.
        description="Number of studies to fetch per API page"
    )
 # ── PUBMED ────────────────────────────────────────────────

    pubmed_base_url: str = Field(
        default="https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        # The base URL for PubMed's eUtils API.
        # Two endpoints we use:
        #   /esearch.fcgi → search for paper IDs matching a query
        #   /efetch.fcgi  → fetch full paper details by those IDs
        description="Pubmed eutils API base url"
    )

    # ── API SERVER ────────────────────────────────────────────

    api_host: str = Field(
        default="0.0.0.0",
        # 0.0.0.0 means: listen on ALL network interfaces.
        # Required for Cloud Run — the container must be reachable
        # from outside, not just from localhost (127.0.0.1).
        description="FAST API Host address"
    )

    api_port: int = Field(
        default=8000,
        # The port FastAPI listens on.
        # Local: http://localhost:8000
        # Cloud Run: port 8000 exposed via EXPOSE in Dockerfile
        description="FAST API port"
    )

    api_env: str = Field(
        default="development",
        # "development" or "production"
        # Controls logging verbosity and error detail level.
        description="Environment name : development or production"
    )
    
    # ---COMPUTED POPERTIES ------------
    
    @property
    def database_url(self) -> str:
        """ Builds the full async PostgreSQL connection string from parts.

        We use asyncpg as the async PostgreSQL driver.
        asyncpg requires the connection string to start with:
        postgresql+asyncpg://

        Returns:
            str: Full connection URL ready for asyncpg.create_pool()
            Example: postgresql+asyncpg://mosaic_user:password@35.232.74.203:5432/clinical_trial_db
        """
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
    
    @property
    def is_production(self) -> bool:
        """"
        Returns True if the API environment is set to "production", otherwise False.
        """
        return self.api_env.lower() == "production"
    
# ── SINGLETON INSTANCE ────────────────────────────────────────
settings = Settings()
# Create ONE instance when this module is first imported.
# Every other file imports this same instance:
#   from config.settings import settings
#
# .env is read exactly ONCE at startup.
# All fields are validated ONCE at startup.
# If anything required is missing → clear error immediately.

# from config.settings import settings