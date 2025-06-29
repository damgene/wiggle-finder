"""
Multi-exchange arbitrage analyzer for Wiggle Finder.

Enhanced from EventScanner with support for all exchange pair combinations and async analysis.
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass
import structlog

from wiggle_common.models import (
    Token, MultiExchangeOpportunity, ExchangePairOpportunity, 
    create_multi_exchange_opportunity
)
from wiggle_common.utils import calculate_return_percent, calculate_net_return
from wiggle_finder.core.config import get_settings
from wiggle_finder.exchanges.base_exchange import BaseExchange

logger = structlog.get_logger(__name__)


@dataclass
class ExchangePriceData:
    """Price data from a specific exchange"""
    exchange_name: str
    price: float
    volume_24h: float
    timestamp: datetime
    confidence: str


@dataclass
class ArbitrageOpportunity:
    """Individual arbitrage opportunity between two exchanges"""
    token_symbol: str
    exchange_from: str
    exchange_to: str
    price_from: float
    price_to: float
    return_percent: float
    volume_from: float
    volume_to: float
    timestamp: datetime


class MultiExchangeAnalyzer:
    """
    Enhanced multi-exchange analyzer supporting all trading pair combinations.
    
    NEW for Wiggle - supports directional analysis:
    - CEX → CEX arbitrage
    - DEX → CEX arbitrage  
    - CEX → DEX arbitrage
    - DEX → DEX arbitrage
    
    Migrated from EventScanner with async architecture and improved cost awareness.
    """
    
    def __init__(self, exchanges: List[BaseExchange]):
        self.exchanges = {ex.name: ex for ex in exchanges}
        self.settings = get_settings()
        
        # Analysis configuration
        self.min_return_threshold = self.settings.analysis.minimum_return_percent
        self.gas_cost_usd = self.settings.analysis.default_gas_cost_usd
        self.trading_fee_percent = self.settings.analysis.default_trading_fee_percent
        
        # Performance tracking
        self.analysis_count = 0
        self.opportunities_found = 0
        self.last_analysis_duration = 0.0
    
    async def analyze_token_opportunities(
        self, 
        token: Token,
        include_historical: bool = True
    ) -> Optional[MultiExchangeOpportunity]:
        """
        Analyze arbitrage opportunities for a single token across all exchanges.
        
        Enhanced from EventScanner with:
        - All exchange pair combinations
        - Async price fetching
        - Cost-aware opportunity evaluation
        - Historical analysis integration
        """
        start_time = datetime.now()
        
        try:
            logger.info("Starting token analysis", token=token.symbol)
            
            # Step 1: Get current prices from all exchanges
            price_data = await self._fetch_current_prices(token)
            
            if len(price_data) < 2:
                logger.warning("Insufficient price data", 
                             token=token.symbol, 
                             exchanges_with_data=len(price_data))
                return None
            
            # Step 2: Find current arbitrage opportunities
            current_opportunities = self._find_arbitrage_opportunities(token, price_data)
            
            # Step 3: Get historical analysis if requested
            historical_opportunities = {}
            if include_historical:
                historical_opportunities = await self._analyze_historical_opportunities(token)
            
            # Step 4: Combine current and historical opportunities
            all_opportunities = self._combine_opportunities(
                current_opportunities, 
                historical_opportunities
            )
            
            if not any(all_opportunities.values()):
                logger.info("No opportunities found", token=token.symbol)
                return None
            
            # Step 5: Create multi-exchange opportunity
            supported_exchanges = list(self.exchanges.keys())
            
            multi_opportunity = create_multi_exchange_opportunity(
                symbol=token.symbol,
                name=token.name or token.symbol,
                supported_exchanges=supported_exchanges,
                exchange_opportunities=all_opportunities,
                contract_address=token.address
            )
            
            # Update performance metrics
            duration = (datetime.now() - start_time).total_seconds()
            self.analysis_count += 1
            self.last_analysis_duration = duration
            
            if multi_opportunity.total_opportunities > 0:
                self.opportunities_found += 1
                
                logger.info("Analysis completed successfully",
                           token=token.symbol,
                           total_opportunities=multi_opportunity.total_opportunities,
                           best_return=multi_opportunity.best_overall_return,
                           duration_seconds=duration)
            
            return multi_opportunity
            
        except Exception as e:
            logger.error("Token analysis failed", 
                        token=token.symbol, 
                        error=str(e))
            return None
    
    async def _fetch_current_prices(self, token: Token) -> List[ExchangePriceData]:
        """Fetch current prices from all supported exchanges concurrently"""
        tasks = []
        
        for exchange_name, exchange in self.exchanges.items():
            if exchange.supports_token(token):
                task = self._fetch_exchange_price(exchange, token)
                tasks.append(task)
        
        # Execute all price fetches concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter successful results
        price_data = []
        for result in results:
            if isinstance(result, ExchangePriceData):
                price_data.append(result)
            elif isinstance(result, Exception):
                logger.warning("Price fetch failed", error=str(result))
        
        return price_data
    
    async def _fetch_exchange_price(
        self, 
        exchange: BaseExchange, 
        token: Token
    ) -> Optional[ExchangePriceData]:
        """Fetch price from a single exchange"""
        try:
            price_info = await exchange.get_current_price(token)
            
            if price_info:
                return ExchangePriceData(
                    exchange_name=exchange.name,
                    price=price_info.price_usd,
                    volume_24h=price_info.volume_24h or 0.0,
                    timestamp=price_info.timestamp,
                    confidence=price_info.confidence
                )
            
            return None
            
        except Exception as e:
            logger.error("Failed to fetch price", 
                        exchange=exchange.name, 
                        token=token.symbol, 
                        error=str(e))
            return None
    
    def _find_arbitrage_opportunities(
        self, 
        token: Token, 
        price_data: List[ExchangePriceData]
    ) -> List[ArbitrageOpportunity]:
        """
        Find arbitrage opportunities from current price data.
        
        Enhanced from EventScanner to support all exchange pair combinations.
        """
        opportunities = []
        
        # Compare every exchange pair (directional)
        for i, price_from in enumerate(price_data):
            for j, price_to in enumerate(price_data):
                if i == j:  # Skip same exchange
                    continue
                
                # Calculate potential return
                return_percent = calculate_return_percent(
                    price_from.price, 
                    price_to.price
                )
                
                # Only consider profitable opportunities
                if return_percent > 0:
                    # Calculate net return after costs
                    net_return = self._calculate_net_return(
                        return_percent,
                        price_from.price * 1000  # Assume $1000 trade size for calculation
                    )
                    
                    # Check if it meets minimum threshold
                    if net_return >= self.min_return_threshold:
                        opportunity = ArbitrageOpportunity(
                            token_symbol=token.symbol,
                            exchange_from=price_from.exchange_name,
                            exchange_to=price_to.exchange_name,
                            price_from=price_from.price,
                            price_to=price_to.price,
                            return_percent=return_percent,
                            volume_from=price_from.volume_24h,
                            volume_to=price_to.volume_24h,
                            timestamp=datetime.now()
                        )
                        opportunities.append(opportunity)
        
        return opportunities
    
    def _calculate_net_return(self, gross_return_percent: float, trade_size_usd: float) -> float:
        """Calculate net return after gas costs and trading fees"""
        return calculate_net_return(
            gross_return_percent=gross_return_percent,
            gas_cost_usd=self.gas_cost_usd,
            capital_usd=trade_size_usd,
            trading_fee_percent=self.trading_fee_percent
        )
    
    async def _analyze_historical_opportunities(
        self, 
        token: Token
    ) -> Dict[str, List[ExchangePairOpportunity]]:
        """
        Analyze historical price data for opportunities.
        
        Enhanced from EventScanner with async data fetching and improved analysis.
        """
        try:
            # Fetch historical data from all exchanges
            historical_data = await self._fetch_historical_data(token)
            
            if len(historical_data) < 2:
                return {}
            
            # Analyze historical opportunities
            opportunities = self._find_historical_arbitrage_opportunities(token, historical_data)
            
            return opportunities
            
        except Exception as e:
            logger.error("Historical analysis failed", 
                        token=token.symbol, 
                        error=str(e))
            return {}
    
    async def _fetch_historical_data(
        self, 
        token: Token
    ) -> Dict[str, List[Tuple[int, float]]]:
        """Fetch historical price data from all exchanges"""
        tasks = []
        exchange_names = []
        
        for exchange_name, exchange in self.exchanges.items():
            if exchange.supports_token(token):
                task = exchange.get_historical_prices(
                    token, 
                    days=self.settings.exchange.default_historical_days,
                    interval="1h"
                )
                tasks.append(task)
                exchange_names.append(exchange_name)
        
        # Execute all historical data fetches concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Build historical data dictionary
        historical_data = {}
        for exchange_name, result in zip(exchange_names, results):
            if isinstance(result, list) and result:
                historical_data[exchange_name] = result
            elif isinstance(result, Exception):
                logger.warning("Historical data fetch failed", 
                             exchange=exchange_name, 
                             error=str(result))
        
        return historical_data
    
    def _find_historical_arbitrage_opportunities(
        self, 
        token: Token,
        historical_data: Dict[str, List[Tuple[int, float]]]
    ) -> Dict[str, List[ExchangePairOpportunity]]:
        """Find arbitrage opportunities from historical data"""
        opportunities = {}
        exchange_names = list(historical_data.keys())
        
        # Compare every exchange pair
        for i, exchange_from in enumerate(exchange_names):
            for j, exchange_to in enumerate(exchange_names):
                if i == j:  # Skip same exchange
                    continue
                
                pair_key = f"{exchange_from}→{exchange_to}"
                pair_opportunities = self._analyze_exchange_pair_history(
                    token,
                    exchange_from,
                    exchange_to,
                    historical_data[exchange_from],
                    historical_data[exchange_to]
                )
                
                if pair_opportunities:
                    opportunities[pair_key] = pair_opportunities
        
        return opportunities
    
    def _analyze_exchange_pair_history(
        self,
        token: Token,
        exchange_from: str,
        exchange_to: str,
        data_from: List[Tuple[int, float]],
        data_to: List[Tuple[int, float]]
    ) -> List[ExchangePairOpportunity]:
        """Analyze historical opportunities between two specific exchanges"""
        opportunities = []
        
        # Convert to timestamp-indexed dictionaries for easier lookup
        prices_from = {timestamp: price for timestamp, price in data_from}
        prices_to = {timestamp: price for timestamp, price in data_to}
        
        # Find common timestamps
        common_timestamps = set(prices_from.keys()) & set(prices_to.keys())
        
        for timestamp in sorted(common_timestamps):
            price_from = prices_from[timestamp]
            price_to = prices_to[timestamp]
            
            return_percent = calculate_return_percent(price_from, price_to)
            
            # Check if profitable above historical threshold
            if return_percent >= self.settings.analysis.historical_threshold_percent:
                opportunity = ExchangePairOpportunity(
                    date=datetime.fromtimestamp(timestamp),
                    exchange_from=exchange_from,
                    exchange_to=exchange_to,
                    price_from=price_from,
                    price_to=price_to,
                    return_percent=return_percent,
                    price_difference=price_to - price_from,
                    volume_from=0.0,  # Historical volume not available
                    volume_to=0.0
                )
                opportunities.append(opportunity)
        
        # Filter to significant opportunities only
        if len(opportunities) > 10:
            # Keep top 10 by return percentage
            opportunities.sort(key=lambda x: x.return_percent, reverse=True)
            opportunities = opportunities[:10]
        
        return opportunities
    
    def _combine_opportunities(
        self,
        current_opportunities: List[ArbitrageOpportunity],
        historical_opportunities: Dict[str, List[ExchangePairOpportunity]]
    ) -> Dict[str, List[ExchangePairOpportunity]]:
        """Combine current and historical opportunities"""
        combined = dict(historical_opportunities)  # Start with historical
        
        # Add current opportunities
        for opp in current_opportunities:
            pair_key = f"{opp.exchange_from}→{opp.exchange_to}"
            
            # Convert to ExchangePairOpportunity format
            pair_opportunity = ExchangePairOpportunity(
                date=opp.timestamp,
                exchange_from=opp.exchange_from,
                exchange_to=opp.exchange_to,
                price_from=opp.price_from,
                price_to=opp.price_to,
                return_percent=opp.return_percent,
                price_difference=opp.price_to - opp.price_from,
                volume_from=opp.volume_from,
                volume_to=opp.volume_to
            )
            
            if pair_key not in combined:
                combined[pair_key] = []
            
            combined[pair_key].append(pair_opportunity)
        
        return combined
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get analyzer performance statistics"""
        return {
            "analysis_count": self.analysis_count,
            "opportunities_found": self.opportunities_found,
            "success_rate": self.opportunities_found / max(self.analysis_count, 1),
            "last_analysis_duration": self.last_analysis_duration,
            "exchanges_configured": len(self.exchanges),
            "min_return_threshold": self.min_return_threshold,
        }