"""
Base exchange implementation for Wiggle Finder.

Enhanced from EventScanner with async support and improved error handling.
"""

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from wiggle_common.models import Token, Price, ExchangeType, ChainType
from wiggle_common.interfaces import ExchangeInterface
from wiggle_common.utils import RateLimiter
from wiggle_finder.core.config import get_settings

logger = structlog.get_logger(__name__)


class BaseExchange(ExchangeInterface):
    """
    Enhanced base exchange implementation with async support.
    
    Migrated from EventScanner with improved:
    - Async HTTP operations
    - Better rate limiting
    - Comprehensive error handling
    - Performance monitoring
    """
    
    def __init__(self, name: str, exchange_type: ExchangeType):
        self.name = name
        self.exchange_type = exchange_type
        self.settings = get_settings()
        
        # Rate limiting
        rate_limit = self.settings.get_exchange_rate_limit(name)
        self.rate_limiter = RateLimiter(rate_limit)  # requests per minute
        
        # HTTP client with timeouts and retries
        timeout = httpx.Timeout(self.settings.exchange.api_timeout_seconds)
        self.client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100)
        )
        
        # Performance tracking
        self.request_count = 0
        self.error_count = 0
        self.last_request_time: Optional[datetime] = None
        self.average_response_time = 0.0
        
        # Health status
        self.is_healthy = True
        self.consecutive_errors = 0
        self.last_error: Optional[str] = None
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
    
    async def close(self):
        """Close HTTP client and cleanup resources"""
        await self.client.aclose()
    
    @abstractmethod
    async def get_current_price(self, token: Token) -> Optional[Price]:
        """Get current price for a token"""
        pass
    
    @abstractmethod
    async def get_historical_prices(
        self, 
        token: Token, 
        days: int = 30, 
        interval: str = "1h"
    ) -> List[Tuple[int, float]]:
        """Get historical prices for a token"""
        pass
    
    @abstractmethod
    def supports_token(self, token: Token) -> bool:
        """Check if exchange supports a specific token"""
        pass
    
    @abstractmethod
    def get_supported_chains(self) -> List[ChainType]:
        """Get list of supported blockchain networks"""
        pass
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10)
    )
    async def make_request(
        self, 
        method: str, 
        url: str, 
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """
        Make HTTP request with rate limiting, retries, and error handling.
        
        Enhanced from EventScanner with async support and better monitoring.
        """
        # Apply rate limiting  
        self.rate_limiter.wait_if_needed()
        
        start_time = datetime.now()
        
        try:
            logger.debug("Making API request", exchange=self.name, method=method, url=url)
            
            response = await self.client.request(method, url, **kwargs)
            response.raise_for_status()
            
            # Record successful request for rate limiting
            self.rate_limiter.record_request()
            
            # Update performance metrics
            duration = (datetime.now() - start_time).total_seconds()
            self._update_performance_metrics(duration, success=True)
            
            # Parse JSON response
            data = response.json()
            logger.debug("API request successful", exchange=self.name, duration=duration)
            
            return data
            
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            self._handle_request_error(error_msg)
            logger.error("HTTP error", exchange=self.name, error=error_msg)
            raise
            
        except httpx.RequestError as e:
            error_msg = f"Request error: {str(e)}"
            self._handle_request_error(error_msg)
            logger.error("Request error", exchange=self.name, error=error_msg)
            raise
            
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            self._handle_request_error(error_msg)
            logger.error("Unexpected error", exchange=self.name, error=error_msg)
            raise
    
    def _update_performance_metrics(self, duration: float, success: bool = True):
        """Update performance tracking metrics"""
        self.request_count += 1
        self.last_request_time = datetime.now()
        
        # Update average response time (exponential moving average)
        if self.average_response_time == 0:
            self.average_response_time = duration
        else:
            alpha = 0.1  # Smoothing factor
            self.average_response_time = (
                alpha * duration + (1 - alpha) * self.average_response_time
            )
        
        if success:
            self.consecutive_errors = 0
            self.is_healthy = True
        else:
            self.error_count += 1
            self.consecutive_errors += 1
            
            # Mark as unhealthy after multiple consecutive errors
            if self.consecutive_errors >= 3:
                self.is_healthy = False
                logger.warning(
                    "Exchange marked as unhealthy",
                    exchange=self.name,
                    consecutive_errors=self.consecutive_errors
                )
    
    def _handle_request_error(self, error_message: str):
        """Handle request errors and update health status"""
        self.last_error = error_message
        self._update_performance_metrics(0, success=False)
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check for this exchange.
        
        Returns health status and performance metrics.
        """
        try:
            # Simple health check - attempt to get a basic response
            health_data = await self._perform_health_check()
            
            return {
                "exchange": self.name,
                "healthy": self.is_healthy,
                "consecutive_errors": self.consecutive_errors,
                "total_requests": self.request_count,
                "total_errors": self.error_count,
                "average_response_time": self.average_response_time,
                "last_request": self.last_request_time.isoformat() if self.last_request_time else None,
                "last_error": self.last_error,
                "additional_data": health_data,
            }
            
        except Exception as e:
            logger.error("Health check failed", exchange=self.name, error=str(e))
            return {
                "exchange": self.name,
                "healthy": False,
                "error": str(e),
            }
    
    @abstractmethod
    async def _perform_health_check(self) -> Dict[str, Any]:
        """Perform exchange-specific health check"""
        pass
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics for monitoring"""
        return {
            "exchange": self.name,
            "exchange_type": self.exchange_type.value,
            "request_count": self.request_count,
            "error_count": self.error_count,
            "error_rate": self.error_count / max(self.request_count, 1),
            "average_response_time": self.average_response_time,
            "is_healthy": self.is_healthy,
            "consecutive_errors": self.consecutive_errors,
            "last_request": self.last_request_time.isoformat() if self.last_request_time else None,
        }
    
    # EventScanner compatibility methods
    def validate_price_realistic(self, price: float, reference_price: Optional[float] = None) -> bool:
        """
        Validate if price is realistic.
        
        From EventScanner: reject prices >50x different to prevent cross-chain confusion.
        """
        if price <= 0:
            return False
        
        if reference_price and reference_price > 0:
            max_deviation = self.settings.exchange.max_price_deviation_percent / 100
            ratio = max(price, reference_price) / min(price, reference_price)
            return ratio <= (1 + max_deviation)
        
        return True
    
    def format_price_data(self, price: float, volume_24h: Optional[float] = None) -> Price:
        """Format price data into standardized Price model"""
        return Price(
            price_usd=price,
            source=self.name,
            volume_24h=volume_24h,
            confidence="HIGH" if self.is_healthy else "MEDIUM"
        )
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}', type='{self.exchange_type}', healthy={self.is_healthy})>"