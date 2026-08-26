from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "OptiStock"
    DATABASE_URL: str = (
        "postgresql://optistock:optistock_password@127.0.0.1:5433/optistock_db"
    )
    # 127.0.0.1:6380, and both halves are deliberate.
    #
    # Not "localhost": compose publishes Redis on the IPv4 loopback only, while
    # localhost resolves to ::1 first on Windows. Not 6379: a stock Redis
    # install runs there as a service, so the default would reach that one
    # instead. Either mistake produces the same silent failure -- the relay
    # publishes to one broker, the consumers read from another, and events
    # disappear with nothing logged. Inside compose the containers use
    # redis://redis:6379/0 over the internal network and never see this.
    REDIS_URL: str = "redis://127.0.0.1:6380/0"
    # No default — app MUST crash if SECRET_KEY is missing in production.
    # For local dev, set it in the .env file.
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # --- Assistant ---------------------------------------------------------
    # Deliberately defaults to empty rather than being required. The whole app
    # must run without it -- a missing key disables one screen and says so,
    # instead of stopping the server from booting.
    # Which LLMRuntime answers questions. One name, so swapping vendors is a
    # config change and a subclass rather than a rewrite -- this project has
    # already moved providers once and the move touched everything.
    LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""
    # demo | production. Defaults to demo deliberately: the safe value is the
    # one you get by forgetting to set it. Sending real identifiers to a
    # third-party model has to be an explicit decision, not an oversight.
    LLM_DATA_MODE: str = "demo"
    # A hard ceiling on tool calls per question. The provider SDK owns the
    # agentic loop now, so without this a model that keeps calling tools keeps
    # billing and keeps holding the request open.
    MAX_TOOL_CALLS: int = 5
    # How long a tool result may be reused. Short on purpose -- this is stock
    # data, and a stale answer is worse than a slow one.
    TOOL_CACHE_TTL_SECONDS: int = 45
    # Gemini 3.x. The 2.5 Flash models are no longer served to new API keys,
    # so an older default would 404 for anyone setting this up today.
    ASSISTANT_MODEL: str = "gemini-3.6-flash"
    # How much silent reasoning the model may do before answering. Measured
    # rather than assumed: on this workload the tools have already done the
    # arithmetic and handed the model finished numbers, so a turn spends about
    # 150 thinking tokens to produce a 45-token answer. "low" cuts that to
    # near zero without changing what the answer says. Set to "high" if you
    # ever give the assistant a job that needs it to reason rather than report.
    ASSISTANT_THINKING_LEVEL: str = "low"
    # A ceiling on trips to the model for one question. Distinct from
    # MAX_TOOL_CALLS: one round can carry several tool calls, and this bounds
    # the round trips rather than the lookups.
    ASSISTANT_MAX_ROUNDS: int = 4
    # Free-tier keys are rate limited hard enough that a burst of two questions
    # can trip them. A 429 is a wait, not a failure, so it is retried -- but
    # only a couple of times, because a person is watching a spinner.
    ASSISTANT_RETRY_ATTEMPTS: int = 2
    # Models to fall back to when the primary has spent its allowance, in
    # order, comma separated. The Gemini free tier's daily cap is per PROJECT
    # PER MODEL -- the quota that refuses gemini-3.6-flash says nothing about
    # gemini-3.5-flash -- so a chain multiplies the free allowance by the
    # number of models on it. Measured, not assumed: 3.6-flash was returning
    # 429 for every request while 3.1-flash-lite answered normally on the same
    # key. Empty by default, because a fallback is a deliberate acceptance that
    # some answers will come from a weaker model.
    ASSISTANT_FALLBACK_MODELS: str = ""
    # How long a model that reported a DAILY quota failure is skipped. Not a
    # calculated reset time on purpose: the reset is a wall-clock event in
    # Google's timezone rather than ours, and hard-coding a guess about it
    # fails silently and permanently if the guess is wrong. Re-probing costs
    # one request per model per hour and cannot get stuck.
    ASSISTANT_MODEL_COOLDOWN_SECONDS: int = 3600
    # Repeat questions served without spending a request. Shorter than it could
    # be for the same reason the tool cache is short -- see cache.py -- and set
    # to zero to switch it off entirely.
    ANSWER_CACHE_TTL_SECONDS: int = 60

    # Where the nightly ETL writes Parquet. Must be backed by a Docker volume in
    # any deployed environment or the analytical history is destroyed on restart.
    DATA_LAKE_DIR: str = "data_lake"
    # Trailing window the demand forecast reads. Also the divisor for average
    # daily velocity, so it must be a fixed span rather than "days that had sales".
    FORECAST_LOOKBACK_DAYS: int = 30
    FORECAST_HORIZON_DAYS: int = 7

    # --- Reorder policy ----------------------------------------------------
    # EOQ and safety stock need three numbers this schema does not hold. They
    # are settings rather than hardcoded constants, and the screen states them
    # beside the figures they produce -- an optimal order quantity is only as
    # meaningful as the costs it was optimised against, and a reader who cannot
    # see the assumption cannot judge the answer.
    #
    # Fixed cost of raising one order: paperwork, delivery, receiving.
    ORDER_COST: float = 500.0
    # Annual cost of holding one unit, as a fraction of its value -- capital,
    # storage, insurance, obsolescence. 20% is the usual industry starting
    # point and is meant to be tuned per business.
    HOLDING_COST_RATE: float = 0.20
    # Days between placing an order and it landing on the shelf. A single
    # figure because no supplier lead time is measured yet; when purchase
    # orders carry real delivery dates this should come from them.
    SUPPLIER_LEAD_TIME_DAYS: int = 7

    # .env is shared between this application and docker-compose.yml, which needs
    # infrastructure variables the app does not own (POSTGRES_PASSWORD, PGADMIN_*).
    # Ignore anything undeclared here rather than refusing to boot; the fields
    # above are still validated, and SECRET_KEY is still mandatory.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
