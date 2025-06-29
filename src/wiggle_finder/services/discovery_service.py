"""
Discovery service for finding arbitrage opportunities.

Core service that coordinates exchange data fetching and opportunity analysis.
"""

import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
import structlog
import uuid

from wiggle_common.models import Token, ChainType, MultiExchangeOpportunity
from wiggle_finder.core.config import get_settings
from wiggle_finder.exchanges.base_exchange import BaseExchange
from wiggle_finder.analyzers.multi_exchange_analyzer import MultiExchangeAnalyzer
from wiggle_finder.services.wiggle_api_client import WiggleAPIClient

logger = structlog.get_logger(__name__)


class DiscoveryService:
    """
    Core discovery service for finding arbitrage opportunities.
    
    Coordinates:
    - Token selection and prioritization
    - Multi-exchange price analysis
    - Opportunity evaluation and filtering
    - Results submission to wiggle-service
    """
    
    def __init__(self, exchanges: List[BaseExchange], wiggle_client: WiggleAPIClient):
        self.exchanges = exchanges
        self.wiggle_client = wiggle_client
        self.settings = get_settings()
        
        # Initialize analyzer
        self.analyzer = MultiExchangeAnalyzer(exchanges)
        
        # Performance tracking
        self.total_analyses = 0
        self.successful_analyses = 0
        self.total_opportunities_found = 0
        self.last_analysis_time: Optional[datetime] = None
    
    async def run_discovery_cycle(self) -> Dict[str, Any]:
        """
        Run a complete discovery cycle.
        
        Enhanced from EventScanner with improved token selection and parallel analysis.
        """
        cycle_start = datetime.now()
        analysis_id = str(uuid.uuid4())
        
        logger.info("Starting discovery cycle", analysis_id=analysis_id)
        
        try:
            # Step 1: Get tokens to analyze
            tokens = await self._get_tokens_to_analyze()
            if not tokens:
                logger.warning("No tokens to analyze")
                return {"status": "no_tokens"}
            
            logger.info("Selected tokens for analysis", 
                       count=len(tokens),
                       tokens=[t.symbol for t in tokens])
            
            # Step 2: Analyze tokens for opportunities
            analysis_results = await self.analyze_tokens([t.symbol for t in tokens])
            
            # Step 3: Submit opportunities to wiggle-service
            submitted_count = await self._submit_opportunities(analysis_results)
            
            # Step 4: Update performance metrics
            cycle_duration = (datetime.now() - cycle_start).total_seconds()
            self._update_performance_metrics(len(tokens), len(analysis_results), cycle_duration)
            
            # Step 5: Submit analysis result for tracking
            await self._submit_analysis_result(
                analysis_id, 
                tokens, 
                analysis_results, 
                cycle_start, 
                cycle_duration
            )
            
            logger.info("Discovery cycle completed",
                       analysis_id=analysis_id,
                       tokens_analyzed=len(tokens),
                       opportunities_found=len(analysis_results),
                       submitted_count=submitted_count,
                       duration_seconds=cycle_duration)
            
            return {
                "status": "completed",
                "analysis_id": analysis_id,
                "tokens_analyzed": len(tokens),
                "opportunities_found": len(analysis_results),
                "submitted_count": submitted_count,
                "duration_seconds": cycle_duration,
            }
            
        except Exception as e:
            logger.error("Discovery cycle failed", 
                        analysis_id=analysis_id, 
                        error=str(e))
            return {"status": "failed", "error": str(e)}
    
    async def analyze_tokens(self, token_symbols: List[str]) -> Dict[str, MultiExchangeOpportunity]:
        """
        Analyze specific tokens for arbitrage opportunities.
        
        Enhanced from EventScanner with concurrent analysis and better error handling.
        """
        logger.info("Starting token analysis", tokens=token_symbols)
        
        # Convert symbols to Token objects
        tokens = [
            Token(symbol=symbol, name=symbol, chain=ChainType.ETHEREUM)  # Default chain
            for symbol in token_symbols
        ]
        
        # Analyze tokens concurrently with controlled concurrency
        semaphore = asyncio.Semaphore(self.settings.service.max_concurrent_analyses)
        
        async def analyze_single_token(token: Token) -> tuple[str, Optional[MultiExchangeOpportunity]]:
            async with semaphore:
                try:
                    result = await self.analyzer.analyze_token_opportunities(token)
                    return token.symbol, result
                except Exception as e:
                    logger.error("Token analysis failed", 
                                token=token.symbol, 
                                error=str(e))
                    return token.symbol, None
        
        # Execute analyses concurrently
        tasks = [analyze_single_token(token) for token in tokens]
        results = await asyncio.gather(*tasks)
        
        # Filter successful results
        opportunities = {
            symbol: opportunity 
            for symbol, opportunity in results 
            if opportunity is not None
        }
        
        logger.info("Token analysis completed",
                   tokens_analyzed=len(token_symbols),
                   opportunities_found=len(opportunities))
        
        return opportunities
    
    async def _get_tokens_to_analyze(self) -> List[Token]:
        """
        Get list of tokens to analyze.
        
        Enhanced token selection based on:
        - Volume and liquidity metrics
        - Historical opportunity frequency
        - Exchange support coverage
        """
        try:
            # Get tokens from wiggle-service
            token_data = await self.wiggle_client.get_tokens_to_analyze(
                limit=self.settings.analysis.max_tokens_per_run
            )
            
            if not token_data:
                # Fallback to default token list (from EventScanner experience)
                default_tokens = [
                    {"symbol": "ETH", "name": "Ethereum", "chain": "ethereum"},
                    {"symbol": "BTC", "name": "Bitcoin", "chain": "bitcoin"},
                    {"symbol": "USDC", "name": "USD Coin", "chain": "ethereum"},
                    {"symbol": "USDT", "name": "Tether", "chain": "ethereum"},
                    {"symbol": "MATIC", "name": "Polygon", "chain": "ethereum"},
                ]
                token_data = default_tokens
                logger.info("Using fallback token list", count=len(default_tokens))
            
            # Convert to Token objects
            tokens = []
            for data in token_data:
                try:
                    chain = ChainType(data.get("chain", "ethereum").lower())
                    token = Token(
                        symbol=data["symbol"],
                        name=data.get("name", data["symbol"]),
                        address=data.get("address"),
                        chain=chain
                    )
                    tokens.append(token)
                except Exception as e:
                    logger.warning("Invalid token data", data=data, error=str(e))
            
            # Filter tokens based on exchange support
            supported_tokens = []
            for token in tokens:
                # Check if at least 2 exchanges support this token
                supporting_exchanges = [
                    ex for ex in self.exchanges 
                    if ex.supports_token(token)
                ]
                
                if len(supporting_exchanges) >= self.settings.analysis.min_exchanges_per_analysis:
                    supported_tokens.append(token)
                else:
                    logger.debug("Token not supported by enough exchanges",
                               token=token.symbol,
                               supporting_exchanges=len(supporting_exchanges))
            
            return supported_tokens
            
        except Exception as e:
            logger.error("Failed to get tokens to analyze", error=str(e))
            return []
    
    async def _submit_opportunities(
        self, 
        opportunities: Dict[str, MultiExchangeOpportunity]
    ) -> int:
        """Submit discovered opportunities to wiggle-service"""
        submitted_count = 0
        
        for symbol, opportunity in opportunities.items():
            try:
                success = await self.wiggle_client.submit_opportunity(opportunity)
                if success:
                    submitted_count += 1
                    logger.debug("Opportunity submitted", symbol=symbol)
                else:
                    logger.warning("Failed to submit opportunity", symbol=symbol)
                    
            except Exception as e:
                logger.error("Error submitting opportunity", 
                           symbol=symbol, 
                           error=str(e))
        
        return submitted_count
    
    def _update_performance_metrics(
        self, 
        tokens_analyzed: int, 
        opportunities_found: int, 
        duration_seconds: float
    ):
        """Update performance tracking metrics"""
        self.total_analyses += 1
        if opportunities_found > 0:
            self.successful_analyses += 1
        
        self.total_opportunities_found += opportunities_found
        self.last_analysis_time = datetime.now()
        
        # Log performance summary
        success_rate = self.successful_analyses / max(self.total_analyses, 1) * 100
        avg_opportunities = self.total_opportunities_found / max(self.total_analyses, 1)
        
        logger.info("Performance metrics updated",
                   total_analyses=self.total_analyses,
                   success_rate_percent=round(success_rate, 2),
                   avg_opportunities_per_run=round(avg_opportunities, 2),
                   last_duration_seconds=duration_seconds)
    
    async def _submit_analysis_result(
        self,
        analysis_id: str,
        tokens: List[Token],
        opportunities: Dict[str, MultiExchangeOpportunity],
        start_time: datetime,
        duration_seconds: float
    ):
        """Submit analysis result for tracking and analytics"""
        try:
            # Calculate summary statistics
            total_opportunities = sum(
                opp.total_opportunities for opp in opportunities.values()
            )
            
            best_return = max(
                (opp.best_overall_return for opp in opportunities.values()),
                default=0.0
            )
            
            avg_return = sum(
                opp.best_overall_return for opp in opportunities.values()
            ) / max(len(opportunities), 1)
            
            # Build analysis result
            analysis_result = {
                "analysis_id": analysis_id,
                "analysis_type": "multi_exchange_discovery",
                "tokens_analyzed": [token.symbol for token in tokens],
                "exchanges_used": [ex.name for ex in self.exchanges],
                "total_opportunities_found": total_opportunities,
                "total_tokens_with_opportunities": len(opportunities),
                "best_opportunity_return": best_return,
                "average_opportunity_return": avg_return,
                "analysis_duration_seconds": duration_seconds,
                "api_calls_made": sum(ex.request_count for ex in self.exchanges),
                "errors_encountered": sum(ex.error_count for ex in self.exchanges),
                "opportunities_by_token": {
                    symbol: opp.total_opportunities 
                    for symbol, opp in opportunities.items()
                },
                "opportunities_by_exchange_pair": self._calculate_pair_stats(opportunities),
                "analysis_config": {
                    "min_return_threshold": self.settings.analysis.minimum_return_percent,
                    "gas_cost_usd": self.settings.analysis.default_gas_cost_usd,
                    "trading_fee_percent": self.settings.analysis.default_trading_fee_percent,
                },
                "started_at": start_time.isoformat(),
                "completed_at": datetime.now().isoformat(),
            }
            
            await self.wiggle_client.submit_analysis_result(analysis_result)
            
        except Exception as e:
            logger.error("Failed to submit analysis result", error=str(e))
    
    def _calculate_pair_stats(
        self, 
        opportunities: Dict[str, MultiExchangeOpportunity]
    ) -> Dict[str, int]:
        """Calculate opportunity count by exchange pair"""
        pair_stats = {}
        
        for opportunity in opportunities.values():
            for pair, opps in opportunity.exchange_pair_opportunities.items():
                if pair not in pair_stats:
                    pair_stats[pair] = 0
                pair_stats[pair] += len(opps)
        
        return pair_stats
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get discovery service performance statistics"""
        analyzer_stats = self.analyzer.get_performance_stats()
        
        return {
            "discovery_service": {
                "total_analyses": self.total_analyses,
                "successful_analyses": self.successful_analyses,
                "success_rate": self.successful_analyses / max(self.total_analyses, 1),
                "total_opportunities_found": self.total_opportunities_found,
                "avg_opportunities_per_run": self.total_opportunities_found / max(self.total_analyses, 1),
                "last_analysis_time": self.last_analysis_time.isoformat() if self.last_analysis_time else None,
            },
            "analyzer": analyzer_stats,
            "exchanges": [ex.get_performance_stats() for ex in self.exchanges],
        }