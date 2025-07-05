"""
Binance exchange implementation for Wiggle Finder.

Enhanced from EventScanner with async support and improved historical data handling.
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import structlog

from wiggle_common.models import Token, Price, ExchangeType, ChainType, Liquidity
from wiggle_finder.exchanges.base_exchange import BaseExchange

logger = structlog.get_logger(__name__)


class BinanceExchange(BaseExchange):
    """
    Binance exchange implementation with enhanced historical data support.
    
    Migrated from EventScanner with improvements:
    - Async operations
    - Better klines data handling
    - 720-point limit compliance
    - Improved error handling
    """
    
    def __init__(self):
        super().__init__("binance", ExchangeType.CEX)
        self.base_url = "https://api.binance.com/api/v3"
        
        # Binance-specific configuration
        self.symbol_cache: Dict[str, str] = {}  # token_symbol -> binance_symbol
        self.supported_symbols: Optional[List[str]] = None
    
    def get_supported_chains(self) -> List[ChainType]:
        """Binance primarily supports tokens via trading pairs"""
        return [ChainType.ETHEREUM, ChainType.BSC]  # Main chains for most tokens
    
    def supports_token(self, token: Token) -> bool:
        """Check if Binance supports trading this token"""
        # For Binance, we check if there's a USDT trading pair
        binance_symbol = self._get_binance_symbol(token.symbol)
        return binance_symbol is not None
    
    def _get_binance_symbol(self, token_symbol: str) -> Optional[str]:
        """
        Get Binance trading pair symbol for a token.
        
        Enhanced from EventScanner to handle more symbol variations.
        """
        # Check cache first
        if token_symbol in self.symbol_cache:
            return self.symbol_cache[token_symbol]
        
        # Common trading pairs to try
        possible_pairs = [
            f"{token_symbol}USDT",
            f"{token_symbol}BUSD", 
            f"{token_symbol}USDC",
            f"{token_symbol}BTC",
            f"{token_symbol}ETH",
        ]
        
        # Handle special cases from EventScanner experience
        symbol_mappings = {
            "WETH": "ETHUSDT",
            "WBTC": "BTCUSDT", 
            "MATIC": "MATICUSDT",
            "BNB": "BNBUSDT",
        }
        
        if token_symbol in symbol_mappings:
            binance_symbol = symbol_mappings[token_symbol]
            self.symbol_cache[token_symbol] = binance_symbol
            return binance_symbol
        
        # For now, default to USDT pair
        # TODO: Implement symbol validation via /exchangeInfo endpoint
        binance_symbol = f"{token_symbol}USDT"
        self.symbol_cache[token_symbol] = binance_symbol
        return binance_symbol
    
    async def get_current_price(self, token: Token) -> Optional[Price]:
        """
        Get current price for a token from Binance.
        
        Enhanced from EventScanner with better error handling.
        """
        try:
            binance_symbol = self._get_binance_symbol(token.symbol)
            if not binance_symbol:
                logger.warning("No Binance symbol found", token=token.symbol)
                return None
            
            # Get 24hr ticker statistics
            url = f"{self.base_url}/ticker/24hr"
            params = {"symbol": binance_symbol}
            
            response = await self.make_request("GET", url, params=params)
            if not response:
                return None
            
            price = float(response["lastPrice"])
            volume_24h = float(response["quoteVolume"])  # Volume in quote currency (USDT)
            
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
        Get historical prices using Binance klines.
        
        Enhanced from EventScanner with 720-point limit compliance and better data handling.
        """
        try:
            binance_symbol = self._get_binance_symbol(token.symbol)
            if not binance_symbol:
                logger.warning("No Binance symbol found for historical data", token=token.symbol)
                return []
            
            # Calculate time range
            end_time = datetime.now()
            start_time = end_time - timedelta(days=days)
            
            # Convert to Binance timestamps (milliseconds)
            start_ms = int(start_time.timestamp() * 1000)
            end_ms = int(end_time.timestamp() * 1000)
            
            # Binance klines endpoint
            url = f"{self.base_url}/klines"
            params = {
                "symbol": binance_symbol,
                "interval": interval,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 720  # Binance limit from EventScanner analysis
            }
            
            response = await self.make_request("GET", url, params=params)
            if not response:
                return []
            
            # Process klines data
            # Format: [timestamp, open, high, low, close, volume, ...]
            historical_data = []
            for kline in response:
                timestamp = int(kline[0]) // 1000  # Convert to seconds
                close_price = float(kline[4])
                
                # Validate price
                if self.validate_price_realistic(close_price):
                    historical_data.append((timestamp, close_price))
            
            logger.info("Retrieved historical prices", 
                       exchange=self.name, 
                       token=token.symbol, 
                       points=len(historical_data),
                       days=days)
            
            return historical_data
            
        except Exception as e:
            logger.error("Failed to get historical prices", 
                        exchange=self.name, 
                        token=token.symbol, 
                        error=str(e))
            return []
    
    async def _perform_health_check(self) -> Dict[str, Any]:
        """Perform Binance-specific health check"""
        try:
            # Check server time and connectivity
            url = f"{self.base_url}/time"
            response = await self.make_request("GET", url)
            
            if response and "serverTime" in response:
                server_time = response["serverTime"]
                local_time = int(datetime.now().timestamp() * 1000)
                time_diff = abs(server_time - local_time)
                
                return {
                    "server_time": server_time,
                    "time_diff_ms": time_diff,
                    "time_sync_ok": time_diff < 5000,  # 5 second tolerance
                }
            
            return {"status": "unknown"}
            
        except Exception as e:
            logger.error("Binance health check failed", error=str(e))
            return {"error": str(e)}
    
    async def get_exchange_info(self) -> Dict[str, Any]:
        """
        Get Binance exchange information.
        
        Useful for validating supported symbols and trading rules.
        """
        try:
            url = f"{self.base_url}/exchangeInfo"
            response = await self.make_request("GET", url)
            
            if response and "symbols" in response:
                # Cache supported symbols
                self.supported_symbols = [
                    symbol["symbol"] for symbol in response["symbols"]
                    if symbol["status"] == "TRADING"
                ]
                
                logger.info("Updated Binance exchange info", 
                           symbols_count=len(self.supported_symbols))
            
            return response or {}
            
        except Exception as e:
            logger.error("Failed to get exchange info", error=str(e))
            return {}
    
    def is_symbol_supported(self, symbol: str) -> bool:
        """Check if a symbol is supported for trading"""
        if self.supported_symbols is None:
            # Symbol list not loaded yet, assume supported
            return True
        
        return symbol in self.supported_symbols
    
    # Required abstract method implementations
    def get_exchange_type(self) -> ExchangeType:
        """Return exchange type"""
        return ExchangeType.CEX
    
    def get_price(self, token: Token) -> Optional[Price]:
        """Get current USD price for a token (sync wrapper)"""
        try:
            # This is a sync method, so we need to handle async properly
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're already in an async context, we can't use run_until_complete
                logger.warning("get_price called from async context, use get_current_price instead")
                return None
            return loop.run_until_complete(self.get_current_price(token))
        except Exception as e:
            logger.error("Failed to get price", token=token.symbol, error=str(e))
            return None
    
    def get_liquidity(self, token: Token) -> Optional[Liquidity]:
        """Get liquidity information for a token"""
        try:
            # For Binance (CEX), we can estimate liquidity from 24h volume
            binance_symbol = self._get_binance_symbol(token.symbol)
            if not binance_symbol:
                return None
            
            # This would need to be implemented with actual API calls
            # For now, return a placeholder
            logger.info("Liquidity calculation not yet implemented for Binance")
            return None
        except Exception as e:
            logger.error("Failed to get liquidity", token=token.symbol, error=str(e))
            return None
    
    def estimate_slippage(self, token: Token, trade_amount_usd: float) -> float:
        """Estimate slippage percentage for a given trade size"""
        try:
            # For CEX like Binance, slippage is typically low
            # Basic estimation based on trade size
            if trade_amount_usd < 1000:
                return 0.1  # 0.1% for small trades
            elif trade_amount_usd < 10000:
                return 0.2  # 0.2% for medium trades
            else:
                return 0.5  # 0.5% for large trades
        except Exception as e:
            logger.error("Failed to estimate slippage", token=token.symbol, error=str(e))
            return 1.0  # Conservative 1% if calculation fails
    
    def is_token_supported(self, token: Token) -> bool:
        """Check if token is supported on this exchange"""
        return self.supports_token(token)