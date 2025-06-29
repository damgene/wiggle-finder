"""
Main application for Wiggle Finder.

Opportunity discovery and analysis service with async architecture and background task support.
"""

import asyncio
import signal
import sys
from contextlib import asynccontextmanager
from typing import List, Optional
import structlog
import argparse

from wiggle_finder.core.config import get_settings
from wiggle_finder.services.discovery_service import DiscoveryService
from wiggle_finder.services.wiggle_api_client import WiggleAPIClient
from wiggle_finder.schedulers.task_scheduler import TaskScheduler
from wiggle_finder.exchanges.exchange_factory import ExchangeFactory

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(30),  # INFO level
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


class WiggleFinderApp:
    """
    Main application class for Wiggle Finder.
    
    Coordinates discovery service, API client, and background tasks.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.running = False
        
        # Core services
        self.wiggle_client: Optional[WiggleAPIClient] = None
        self.discovery_service: Optional[DiscoveryService] = None
        self.task_scheduler: Optional[TaskScheduler] = None
        
        # Exchange connections
        self.exchanges = []
    
    async def initialize(self):
        """Initialize all application components"""
        logger.info("Initializing Wiggle Finder", version="0.1.0")
        
        try:
            # Initialize Wiggle API client
            self.wiggle_client = WiggleAPIClient(
                base_url=self.settings.wiggle_service.base_url,
                api_key=self.settings.wiggle_service.api_key,
                timeout=self.settings.wiggle_service.timeout_seconds
            )
            
            # Test connection to wiggle-service
            await self.wiggle_client.health_check()
            logger.info("Connected to wiggle-service", 
                       url=self.settings.wiggle_service.base_url)
            
            # Initialize exchanges
            exchange_factory = ExchangeFactory()
            self.exchanges = await exchange_factory.create_all_exchanges()
            logger.info("Initialized exchanges", 
                       count=len(self.exchanges),
                       exchanges=[ex.name for ex in self.exchanges])
            
            # Initialize discovery service
            self.discovery_service = DiscoveryService(
                exchanges=self.exchanges,
                wiggle_client=self.wiggle_client
            )
            
            # Initialize task scheduler
            if self.settings.scheduler.enable_scheduler:
                self.task_scheduler = TaskScheduler(
                    discovery_service=self.discovery_service
                )
                await self.task_scheduler.initialize()
                logger.info("Task scheduler initialized")
            
            logger.info("Wiggle Finder initialization completed")
            
        except Exception as e:
            logger.error("Failed to initialize Wiggle Finder", error=str(e))
            raise
    
    async def start(self):
        """Start the application and all background services"""
        if self.running:
            logger.warning("Application is already running")
            return
        
        logger.info("Starting Wiggle Finder")
        self.running = True
        
        try:
            # Start task scheduler if enabled
            if self.task_scheduler:
                await self.task_scheduler.start()
                logger.info("Task scheduler started")
            
            # Start main application loop
            await self._run_main_loop()
            
        except Exception as e:
            logger.error("Error during application startup", error=str(e))
            raise
    
    async def stop(self):
        """Stop the application and cleanup resources"""
        if not self.running:
            return
        
        logger.info("Stopping Wiggle Finder")
        self.running = False
        
        try:
            # Stop task scheduler
            if self.task_scheduler:
                await self.task_scheduler.stop()
                logger.info("Task scheduler stopped")
            
            # Close exchange connections
            for exchange in self.exchanges:
                await exchange.close()
            logger.info("Exchange connections closed")
            
            # Close API client
            if self.wiggle_client:
                await self.wiggle_client.close()
                logger.info("API client closed")
            
            logger.info("Wiggle Finder stopped successfully")
            
        except Exception as e:
            logger.error("Error during shutdown", error=str(e))
    
    async def _run_main_loop(self):
        """Main application event loop"""
        logger.info("Starting main event loop")
        
        try:
            while self.running:
                # Application health monitoring
                await self._perform_health_checks()
                
                # Wait before next iteration
                await asyncio.sleep(30)  # Check every 30 seconds
                
        except asyncio.CancelledError:
            logger.info("Main loop cancelled")
        except Exception as e:
            logger.error("Error in main loop", error=str(e))
            raise
    
    async def _perform_health_checks(self):
        """Perform periodic health checks"""
        try:
            # Check wiggle-service connection
            if self.wiggle_client:
                health_ok = await self.wiggle_client.health_check()
                if not health_ok:
                    logger.warning("Wiggle service health check failed")
            
            # Check exchange health
            unhealthy_exchanges = []
            for exchange in self.exchanges:
                health_data = await exchange.health_check()
                if not health_data.get("healthy", False):
                    unhealthy_exchanges.append(exchange.name)
            
            if unhealthy_exchanges:
                logger.warning("Unhealthy exchanges detected", 
                             exchanges=unhealthy_exchanges)
            
        except Exception as e:
            logger.error("Health check failed", error=str(e))
    
    async def run_single_analysis(self, token_symbols: List[str]):
        """Run a single analysis for specified tokens (for CLI usage)"""
        logger.info("Running single analysis", tokens=token_symbols)
        
        if not self.discovery_service:
            raise RuntimeError("Discovery service not initialized")
        
        results = await self.discovery_service.analyze_tokens(token_symbols)
        
        # Log results summary
        total_opportunities = sum(
            result.total_opportunities for result in results.values()
            if result is not None
        )
        
        logger.info("Single analysis completed",
                   tokens_analyzed=len(token_symbols),
                   tokens_with_opportunities=len([r for r in results.values() if r]),
                   total_opportunities=total_opportunities)
        
        return results


# Signal handlers for graceful shutdown
app_instance: Optional[WiggleFinderApp] = None

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info("Received shutdown signal", signal=signum)
    if app_instance:
        asyncio.create_task(app_instance.stop())


async def main():
    """Main application entry point"""
    global app_instance
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    app_instance = WiggleFinderApp()
    
    try:
        await app_instance.initialize()
        await app_instance.start()
        
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error("Application error", error=str(e))
        sys.exit(1)
    finally:
        if app_instance:
            await app_instance.stop()


def cli():
    """Command-line interface for Wiggle Finder"""
    parser = argparse.ArgumentParser(description="Wiggle Finder - Opportunity Discovery Service")
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Run command (default)
    run_parser = subparsers.add_parser("run", help="Run the service")
    run_parser.add_argument("--scheduler", action="store_true", 
                           help="Enable background task scheduler")
    
    # Analyze command (one-time analysis)
    analyze_parser = subparsers.add_parser("analyze", help="Run one-time analysis")
    analyze_parser.add_argument("tokens", nargs="+", 
                               help="Token symbols to analyze (e.g., ETH BTC)")
    
    # Health command
    health_parser = subparsers.add_parser("health", help="Check system health")
    
    args = parser.parse_args()
    
    if args.command == "analyze":
        # One-time analysis mode
        async def run_analysis():
            app = WiggleFinderApp()
            await app.initialize()
            try:
                results = await app.run_single_analysis(args.tokens)
                
                # Print results
                print(f"\\nAnalysis Results for {len(args.tokens)} tokens:")
                print("=" * 50)
                
                for token, result in results.items():
                    if result:
                        print(f"{token}: {result.total_opportunities} opportunities, "
                              f"best return: {result.best_overall_return:.2f}%")
                    else:
                        print(f"{token}: No opportunities found")
                        
            finally:
                await app.stop()
        
        asyncio.run(run_analysis())
        
    elif args.command == "health":
        # Health check mode
        async def check_health():
            app = WiggleFinderApp()
            await app.initialize()
            try:
                await app._perform_health_checks()
                print("Health check completed - see logs for details")
            finally:
                await app.stop()
        
        asyncio.run(check_health())
        
    else:
        # Default: run service
        asyncio.run(main())


if __name__ == "__main__":
    cli()