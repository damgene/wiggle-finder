"""
Coinbase exchange implementation for Wiggle Finder.

Enhanced from EventScanner with improved 300-point limit handling and better error recovery.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import structlog

from wiggle_common.models import Token, Price, ExchangeType, ChainType
from wiggle_finder.exchanges.base_exchange import BaseExchange

logger = structlog.get_logger(__name__)


class CoinbaseExchange(BaseExchange):
    """
    Coinbase Pro exchange implementation.
    
    Enhanced from EventScanner with fixes for:
    - 300-point historical data limit
    - Better error handling for 400 responses
    - Improved granularity selection
    - Rate limit compliance
    """
    
    def __init__(self):
        super().__init__("coinbase", ExchangeType.CEX)
        self.base_url = "https://api.exchange.coinbase.com"
        
        # Coinbase-specific configuration
        self.product_cache: Dict[str, str] = {}  # token_symbol -> product_id
        self.supported_products: Optional[List[Dict]] = None
    
    def get_supported_chains(self) -> List[ChainType]:
        """Coinbase supports various blockchain tokens"""
        return [ChainType.ETHEREUM, ChainType.BITCOIN]
    
    def supports_token(self, token: Token) -> bool:
        """Check if Coinbase supports trading this token"""
        product_id = self._get_coinbase_product_id(token.symbol)
        return product_id is not None
    
    def _get_coinbase_product_id(self, token_symbol: str) -> Optional[str]:
        """
        Get Coinbase product ID for a token.
        
        Enhanced from EventScanner with better symbol mapping.
        """
        # Check cache first
        if token_symbol in self.product_cache:
            return self.product_cache[token_symbol]
        
        # Common trading pairs to try
        possible_pairs = [
            f"{token_symbol}-USD",
            f"{token_symbol}-USDC",
            f"{token_symbol}-BTC",
            f"{token_symbol}-ETH",
        ]
        
        # Handle special cases from EventScanner experience
        symbol_mappings = {
            "WETH": "ETH-USD",
            "WBTC": "BTC-USD",
            "MATIC": "MATIC-USD",
        }
        
        if token_symbol in symbol_mappings:
            product_id = symbol_mappings[token_symbol]
            self.product_cache[token_symbol] = product_id
            return product_id
        
        # Default to USD pair
        product_id = f"{token_symbol}-USD"
        self.product_cache[token_symbol] = product_id
        return product_id
    
    async def get_current_price(self, token: Token) -> Optional[Price]:
        """
        Get current price for a token from Coinbase.
        
        Enhanced from EventScanner with better error handling.
        """
        try:
            product_id = self._get_coinbase_product_id(token.symbol)
            if not product_id:
                logger.warning("No Coinbase product ID found", token=token.symbol)
                return None
            
            # Get 24hr stats
            url = f"{self.base_url}/products/{product_id}/stats"
            
            response = await self.make_request("GET", url)
            if not response:
                return None
            
            price = float(response["last"])
            volume_24h = float(response.get("volume", 0)) * price  # Convert to USD volume
            
            # Validate price
            if not self.validate_price_realistic(price):
                logger.warning("Unrealistic price detected", 
                             exchange=self.name, 
                             token=token.symbol, 
                             price=price)
                return None
            
            logger.debug("Retrieved current price", 
                        exchange=self.name, 
                        token=token.symbol, 
                        price=price)
            
            return self.format_price_data(price, volume_24h)
            
        except Exception as e:
            logger.error("Failed to get current price", 
                        exchange=self.name, 
                        token=token.symbol, 
                        error=str(e))
            return None
    
    async def get_historical_prices(
        self, 
        token: Token, 
        days: int = 30, 
        interval: str = "1h"
    ) -> List[Tuple[int, float]]:
        """
        Get historical prices using Coinbase candles.
        
        Enhanced from EventScanner with 300-point limit compliance and better granularity.
        """
        try:
            product_id = self._get_coinbase_product_id(token.symbol)
            if not product_id:
                logger.warning("No Coinbase product ID found for historical data", token=token.symbol)
                return []
            
            # Map interval to Coinbase granularity (seconds)
            granularity_map = {
                "1m": 60,
                "5m": 300, 
                "15m": 900,
                "1h": 3600,
                "6h": 21600,
                "1d": 86400,
            }
            
            granularity = granularity_map.get(interval, 3600)  # Default to 1 hour
            
            # Calculate time range with 300-point limit consideration
            end_time = datetime.now()
            
            # Coinbase has a 300-point limit, so adjust the time range accordingly
            max_points = 300
            max_duration_seconds = max_points * granularity
            max_days = max_duration_seconds / 86400  # Convert to days
            
            # Use the smaller of requested days or max allowed days
            actual_days = min(days, max_days)
            start_time = end_time - timedelta(days=actual_days)
            
            if actual_days < days:
                logger.info("Adjusted time range due to Coinbase 300-point limit",
                           exchange=self.name,
                           token=token.symbol,
                           requested_days=days,
                           actual_days=actual_days)
            
            # Convert to ISO format (Coinbase requirement)
            start_iso = start_time.isoformat() + "Z"
            end_iso = end_time.isoformat() + "Z"
            
            # Coinbase candles endpoint
            url = f"{self.base_url}/products/{product_id}/candles"
            params = {
                "start": start_iso,
                "end": end_iso,
                "granularity": granularity
            }
            
            response = await self.make_request("GET", url, params=params)
            if not response:
                return []
            
            # Process candles data
            # Format: [timestamp, low, high, open, close, volume]
            historical_data = []
            for candle in response:
                if len(candle) >= 5:
                    timestamp = int(candle[0])  # Already in seconds
                    close_price = float(candle[4])
                    
                    # Validate price
                    if self.validate_price_realistic(close_price):
                        historical_data.append((timestamp, close_price))
            
            # Sort by timestamp (Coinbase may return unsorted data)
            historical_data.sort(key=lambda x: x[0])
            
            logger.info("Retrieved historical prices", 
                       exchange=self.name, 
                       token=token.symbol, 
                       points=len(historical_data),
                       days=actual_days,
                       granularity=granularity)
            
            return historical_data
            
        except Exception as e:
            logger.error("Failed to get historical prices", 
                        exchange=self.name, 
                        token=token.symbol, 
                        error=str(e))
            return []
    
    async def _perform_health_check(self) -> Dict[str, Any]:
        """Perform Coinbase-specific health check"""
        try:
            # Check server time and status
            url = f"{self.base_url}/time"
            response = await self.make_request("GET", url)
            
            if response and "iso" in response:
                server_time_iso = response["iso"]
                epoch_time = float(response.get("epoch", 0))
                
                # Check if server time is reasonable
                current_time = datetime.now().timestamp()
                time_diff = abs(epoch_time - current_time)
                
                return {
                    "server_time_iso": server_time_iso,
                    "server_epoch": epoch_time,
                    "time_diff_seconds": time_diff,
                    "time_sync_ok": time_diff < 60,  # 1 minute tolerance
                }
            
            return {"status": "unknown"}
            
        except Exception as e:
            logger.error("Coinbase health check failed", error=str(e))
            return {"error": str(e)}
    
    async def get_products(self) -> List[Dict[str, Any]]:
        """
        Get Coinbase products (trading pairs).
        
        Useful for validating supported products and trading rules.
        """
        try:
            url = f"{self.base_url}/products"
            response = await self.make_request("GET", url)
            
            if response and isinstance(response, list):
                # Cache supported products
                self.supported_products = [
                    product for product in response
                    if product.get("status") == "online"
                ]
                
                logger.info("Updated Coinbase products", 
                           products_count=len(self.supported_products))
            
            return response or []
            
        except Exception as e:
            logger.error("Failed to get products", error=str(e))
            return []
    
    def is_product_supported(self, product_id: str) -> bool:
        """Check if a product is supported for trading"""
        if self.supported_products is None:
            # Product list not loaded yet, assume supported
            return True
        
        return any(
            product["id"] == product_id 
            for product in self.supported_products
        )