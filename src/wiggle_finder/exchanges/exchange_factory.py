"""
Exchange factory for creating and managing exchange instances.

Enhanced from EventScanner with async initialization and health monitoring.
"""

from typing import List, Dict, Any
import structlog

from wiggle_finder.core.config import get_settings
from wiggle_finder.exchanges.base_exchange import BaseExchange
from wiggle_finder.exchanges.binance_exchange import BinanceExchange
from wiggle_finder.exchanges.coinbase_exchange import CoinbaseExchange

logger = structlog.get_logger(__name__)


class ExchangeFactory:
    """
    Factory for creating and managing exchange instances.
    
    Enhanced from EventScanner with:
    - Async initialization
    - Health monitoring
    - Dynamic exchange configuration
    - Better error handling
    """
    
    def __init__(self):
        self.settings = get_settings()
        self._exchange_classes = {
            "binance": BinanceExchange,
            "coinbase": CoinbaseExchange,
        }
    
    async def create_exchange(self, exchange_name: str) -> BaseExchange:
        """Create a single exchange instance"""
        exchange_name = exchange_name.lower()
        
        if exchange_name not in self._exchange_classes:
            raise ValueError(f"Unknown exchange: {exchange_name}")
        
        exchange_class = self._exchange_classes[exchange_name]
        
        try:
            # Create exchange instance
            exchange = exchange_class()
            
            # Test connection and health
            health_data = await exchange.health_check()
            
            if health_data.get("healthy", False):
                logger.info("Exchange initialized successfully", 
                           exchange=exchange_name,
                           health_data=health_data)
            else:
                logger.warning("Exchange health check failed during initialization",
                             exchange=exchange_name,
                             health_data=health_data)
            
            return exchange
            
        except Exception as e:
            logger.error("Failed to create exchange", 
                        exchange=exchange_name, 
                        error=str(e))
            raise
    
    async def create_all_exchanges(self) -> List[BaseExchange]:
        """Create all configured exchanges"""
        exchanges = []
        
        # Default exchanges to create
        exchange_names = ["binance", "coinbase"]
        
        for exchange_name in exchange_names:
            try:
                exchange = await self.create_exchange(exchange_name)
                exchanges.append(exchange)
                
            except Exception as e:
                logger.error("Failed to initialize exchange", 
                           exchange=exchange_name, 
                           error=str(e))
                # Continue with other exchanges
        
        if not exchanges:
            raise RuntimeError("No exchanges could be initialized")
        
        logger.info("Exchange factory initialization completed",
                   total_exchanges=len(exchanges),
                   exchanges=[ex.name for ex in exchanges])
        
        return exchanges
    
    def get_available_exchanges(self) -> List[str]:
        """Get list of available exchange names"""
        return list(self._exchange_classes.keys())