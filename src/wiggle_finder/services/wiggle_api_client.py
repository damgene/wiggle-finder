"""
API client for communicating with wiggle-service.

Handles all HTTP communication with the central Wiggle API.
"""

from typing import List, Dict, Any, Optional
import httpx
import structlog
from datetime import datetime

from wiggle_common.models import MultiExchangeOpportunity, Token

logger = structlog.get_logger(__name__)


class WiggleAPIClient:
    """
    HTTP client for wiggle-service API.
    
    Provides methods for:
    - Submitting discovered opportunities
    - Fetching tokens to analyze
    - Health checks and monitoring
    """
    
    def __init__(self, base_url: str, api_key: Optional[str] = None, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        
        # Configure HTTP client
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        self.client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)
        )
    
    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()
    
    async def health_check(self) -> bool:
        """Check if wiggle-service is healthy"""
        try:
            response = await self.client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except Exception as e:
            logger.error("Health check failed", error=str(e))
            return False
    
    async def get_tokens_to_analyze(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get list of tokens that should be analyzed"""
        try:
            params = {"page_size": limit, "is_active": True}
            response = await self.client.get(f"{self.base_url}/api/v1/tokens", params=params)
            response.raise_for_status()
            
            data = response.json()
            return data.get("tokens", [])
            
        except Exception as e:
            logger.error("Failed to get tokens", error=str(e))
            return []
    
    async def submit_opportunity(self, opportunity: MultiExchangeOpportunity) -> bool:
        """Submit a discovered multi-exchange opportunity"""
        try:
            # Convert to API format
            opportunity_data = {
                "symbol": opportunity.symbol,
                "name": opportunity.name,
                "contract_address": opportunity.contract_address,
                "supported_exchanges": opportunity.supported_exchanges,
                "exchange_pair_opportunities": {
                    pair: [
                        {
                            "date": opp.date.isoformat(),
                            "exchange_from": opp.exchange_from,
                            "exchange_to": opp.exchange_to,
                            "price_from": opp.price_from,
                            "price_to": opp.price_to,
                            "return_percent": opp.return_percent,
                            "price_difference": opp.price_difference,
                            "volume_from": opp.volume_from,
                            "volume_to": opp.volume_to,
                        }
                        for opp in opps
                    ]
                    for pair, opps in opportunity.exchange_pair_opportunities.items()
                },
                "best_spreads_per_pair": {
                    pair: {
                        "date": opp.date.isoformat(),
                        "exchange_from": opp.exchange_from,
                        "exchange_to": opp.exchange_to,
                        "price_from": opp.price_from,
                        "price_to": opp.price_to,
                        "return_percent": opp.return_percent,
                        "price_difference": opp.price_difference,
                        "volume_from": opp.volume_from,
                        "volume_to": opp.volume_to,
                    }
                    for pair, opp in opportunity.best_spreads_per_pair.items()
                },
                "priority": opportunity.priority,
                "scan_frequency": opportunity.scan_frequency,
                "stats": opportunity.stats,
            }
            
            response = await self.client.post(
                f"{self.base_url}/api/v1/opportunities/multi-exchange",
                json=opportunity_data
            )
            response.raise_for_status()
            
            logger.info("Opportunity submitted successfully", 
                       symbol=opportunity.symbol,
                       total_opportunities=opportunity.total_opportunities)
            return True
            
        except Exception as e:
            logger.error("Failed to submit opportunity", 
                        symbol=opportunity.symbol, 
                        error=str(e))
            return False
    
    async def get_opportunity_stats(self) -> Dict[str, Any]:
        """Get opportunity statistics from wiggle-service"""
        try:
            response = await self.client.get(f"{self.base_url}/api/v1/opportunities/stats/summary")
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            logger.error("Failed to get opportunity stats", error=str(e))
            return {}
    
    async def submit_analysis_result(self, analysis_result: Dict[str, Any]) -> bool:
        """Submit analysis run results for tracking"""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/v1/analytics/analysis-results",
                json=analysis_result
            )
            response.raise_for_status()
            return True
            
        except Exception as e:
            logger.error("Failed to submit analysis result", error=str(e))
            return False