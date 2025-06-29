"""
Configuration management for Wiggle Finder.

Enhanced from EventScanner with multi-exchange and async support.
"""

from typing import List, Dict, Any, Optional
from pydantic import Field, validator
from pydantic_settings import BaseSettings


class ServiceConfig(BaseSettings):
    """Core service configuration"""
    
    # Service identity
    service_name: str = Field(default="wiggle-finder")
    environment: str = Field(default="development")
    debug: bool = Field(default=False)
    
    # Worker configuration
    max_concurrent_analyses: int = Field(default=10, ge=1)
    analysis_timeout_seconds: int = Field(default=300, ge=30)
    
    class Config:
        env_prefix = "WIGGLE_FINDER_"


class WiggleServiceConfig(BaseSettings):
    """Configuration for connecting to wiggle-service API"""
    
    base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL of wiggle-service API"
    )
    api_key: Optional[str] = Field(default=None, description="API key for authentication")
    timeout_seconds: int = Field(default=30, ge=1)
    max_retries: int = Field(default=3, ge=0)
    
    class Config:
        env_prefix = "WIGGLE_SERVICE_"


class ExchangeConfig(BaseSettings):
    """Exchange API configuration - enhanced from EventScanner"""
    
    # Rate limits (requests per minute) - from EventScanner analysis
    coingecko_rate_limit: int = Field(default=50, ge=1)
    binance_rate_limit: int = Field(default=1200, ge=1)
    coinbase_rate_limit: int = Field(default=300, ge=1)
    uniswap_rate_limit: int = Field(default=100, ge=1)
    sushiswap_rate_limit: int = Field(default=100, ge=1)
    
    # API keys (optional - many endpoints work without keys)
    binance_api_key: Optional[str] = Field(default=None)
    binance_secret_key: Optional[str] = Field(default=None)
    coinbase_api_key: Optional[str] = Field(default=None)
    coinbase_secret_key: Optional[str] = Field(default=None)
    
    # Timeouts and retry configuration
    api_timeout_seconds: int = Field(default=30, ge=1)
    max_retries: int = Field(default=3, ge=0)
    retry_delay_seconds: float = Field(default=1.0, ge=0.1)
    
    # Data validation - from EventScanner learnings
    max_price_deviation_percent: float = Field(default=50.0, ge=1.0)
    min_volume_usd: float = Field(default=1000.0, ge=0)
    
    # Historical data configuration
    default_historical_days: int = Field(default=30, ge=1, le=365)
    max_historical_points: int = Field(default=720, ge=100)  # Binance limit
    
    class Config:
        env_prefix = "WIGGLE_EXCHANGE_"


class AnalysisConfig(BaseSettings):
    """Analysis and opportunity detection configuration"""
    
    # Profitability thresholds - from EventScanner context analysis
    minimum_return_percent: float = Field(default=6.0, ge=0.1)
    historical_threshold_percent: float = Field(default=1.5, ge=0.1)
    
    # Cost estimates - from EventScanner learnings
    default_gas_cost_usd: float = Field(default=35.0, ge=0.1)
    default_trading_fee_percent: float = Field(default=0.6, ge=0.0)
    
    # Multi-exchange analysis
    min_exchanges_per_analysis: int = Field(default=2, ge=2)
    max_exchanges_per_analysis: int = Field(default=10, ge=2)
    
    # Token selection and filtering
    max_tokens_per_run: int = Field(default=50, ge=1)
    min_token_volume_usd: float = Field(default=100000.0, ge=1000)
    
    # Opportunity scoring and prioritization
    high_priority_return_threshold: float = Field(default=10.0, ge=1.0)
    medium_priority_return_threshold: float = Field(default=5.0, ge=1.0)
    confidence_threshold: float = Field(default=70.0, ge=0, le=100)
    
    # Analysis intervals and scheduling
    fast_scan_interval_minutes: int = Field(default=5, ge=1)
    normal_scan_interval_minutes: int = Field(default=15, ge=1)
    deep_scan_interval_minutes: int = Field(default=60, ge=1)
    
    class Config:
        env_prefix = "WIGGLE_ANALYSIS_"


class SchedulerConfig(BaseSettings):
    """Background task and scheduling configuration"""
    
    # Celery configuration
    broker_url: str = Field(
        default="redis://localhost:6379/0",
        description="Message broker URL for Celery"
    )
    result_backend: str = Field(
        default="redis://localhost:6379/1",
        description="Result backend URL for Celery"
    )
    
    # Task configuration
    task_soft_time_limit: int = Field(default=300, ge=30)  # 5 minutes
    task_time_limit: int = Field(default=600, ge=60)       # 10 minutes
    
    # Scheduling
    enable_scheduler: bool = Field(default=True)
    scheduler_timezone: str = Field(default="UTC")
    
    # Task priorities (1-10, higher = more priority)
    high_priority_task_priority: int = Field(default=9, ge=1, le=10)
    normal_priority_task_priority: int = Field(default=5, ge=1, le=10)
    low_priority_task_priority: int = Field(default=1, ge=1, le=10)
    
    class Config:
        env_prefix = "WIGGLE_SCHEDULER_"


class MonitoringConfig(BaseSettings):
    """Monitoring and logging configuration"""
    
    # Logging
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="json")
    
    # Metrics and monitoring
    enable_metrics: bool = Field(default=True)
    metrics_port: int = Field(default=9091, ge=1, le=65535)
    
    # Performance tracking
    track_api_performance: bool = Field(default=True)
    track_analysis_performance: bool = Field(default=True)
    
    # Alerting thresholds
    max_consecutive_failures: int = Field(default=3, ge=1)
    max_analysis_duration_minutes: int = Field(default=10, ge=1)
    
    class Config:
        env_prefix = "WIGGLE_MONITORING_"


class Settings(BaseSettings):
    """Main application settings"""
    
    # Sub-configurations
    service: ServiceConfig = Field(default_factory=ServiceConfig)
    wiggle_service: WiggleServiceConfig = Field(default_factory=WiggleServiceConfig)
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    
    @validator("service")
    def validate_service_environment(cls, v):
        allowed = ["development", "staging", "production"]
        if v.environment not in allowed:
            raise ValueError(f"Environment must be one of {allowed}")
        return v
    
    @property
    def is_production(self) -> bool:
        return self.service.environment == "production"
    
    @property
    def is_development(self) -> bool:
        return self.service.environment == "development"
    
    # Exchange configuration helpers
    def get_exchange_rate_limit(self, exchange_name: str) -> int:
        """Get rate limit for specific exchange"""
        rate_limits = {
            "coingecko": self.exchange.coingecko_rate_limit,
            "binance": self.exchange.binance_rate_limit,
            "coinbase": self.exchange.coinbase_rate_limit,
            "uniswap": self.exchange.uniswap_rate_limit,
            "sushiswap": self.exchange.sushiswap_rate_limit,
        }
        return rate_limits.get(exchange_name.lower(), 60)  # Default 60/min
    
    def get_exchange_credentials(self, exchange_name: str) -> Dict[str, Optional[str]]:
        """Get API credentials for exchange"""
        if exchange_name.lower() == "binance":
            return {
                "api_key": self.exchange.binance_api_key,
                "secret": self.exchange.binance_secret_key,
            }
        elif exchange_name.lower() == "coinbase":
            return {
                "api_key": self.exchange.coinbase_api_key,
                "secret": self.exchange.coinbase_secret_key,
            }
        return {}
    
    class Config:
        env_prefix = "WIGGLE_"
        case_sensitive = False
        env_file = ".env"
        env_file_encoding = "utf-8"


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get the global settings instance"""
    return settings


def reload_settings() -> Settings:
    """Reload settings from environment (useful for testing)"""
    global settings
    settings = Settings()
    return settings