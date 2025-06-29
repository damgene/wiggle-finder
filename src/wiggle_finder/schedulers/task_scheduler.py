"""
Task scheduler for Wiggle Finder.

Manages background task scheduling and execution.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional
import structlog

from wiggle_finder.core.config import get_settings
from wiggle_finder.services.discovery_service import DiscoveryService

logger = structlog.get_logger(__name__)


class TaskScheduler:
    """
    Simple async task scheduler for discovery cycles.
    
    Enhanced from EventScanner with:
    - Async scheduling
    - Configurable intervals
    - Health monitoring
    - Graceful shutdown
    """
    
    def __init__(self, discovery_service: DiscoveryService):
        self.discovery_service = discovery_service
        self.settings = get_settings()
        
        # Scheduler state
        self.running = False
        self.task: Optional[asyncio.Task] = None
        
        # Performance tracking
        self.cycles_completed = 0
        self.last_cycle_time: Optional[datetime] = None
        self.last_cycle_duration: Optional[float] = None
    
    async def initialize(self):
        """Initialize the scheduler"""
        logger.info("Task scheduler initialized",
                   fast_interval_minutes=self.settings.analysis.fast_scan_interval_minutes,
                   normal_interval_minutes=self.settings.analysis.normal_scan_interval_minutes)
    
    async def start(self):
        """Start the background task scheduler"""
        if self.running:
            logger.warning("Scheduler is already running")
            return
        
        self.running = True
        self.task = asyncio.create_task(self._scheduler_loop())
        logger.info("Task scheduler started")
    
    async def stop(self):
        """Stop the scheduler and cancel running tasks"""
        if not self.running:
            return
        
        self.running = False
        
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        
        logger.info("Task scheduler stopped")
    
    async def _scheduler_loop(self):
        """Main scheduler event loop"""
        logger.info("Starting scheduler loop")
        
        try:
            while self.running:
                # Run discovery cycle
                cycle_start = datetime.now()
                
                try:
                    result = await self.discovery_service.run_discovery_cycle()
                    
                    # Update metrics
                    cycle_duration = (datetime.now() - cycle_start).total_seconds()
                    self.cycles_completed += 1
                    self.last_cycle_time = cycle_start
                    self.last_cycle_duration = cycle_duration
                    
                    logger.info("Discovery cycle completed by scheduler",
                               cycle_number=self.cycles_completed,
                               duration_seconds=cycle_duration,
                               result_status=result.get("status"))
                    
                except Exception as e:
                    logger.error("Discovery cycle failed", error=str(e))
                
                # Wait for next cycle
                interval_minutes = self._get_next_interval()
                await asyncio.sleep(interval_minutes * 60)
                
        except asyncio.CancelledError:
            logger.info("Scheduler loop cancelled")
        except Exception as e:
            logger.error("Scheduler loop error", error=str(e))
    
    def _get_next_interval(self) -> int:
        """
        Get interval for next cycle based on current performance.
        
        Enhanced scheduling logic:
        - Fast cycles when opportunities are found
        - Normal cycles for regular scanning
        - Adaptive intervals based on success rate
        """
        # For now, use normal interval
        # TODO: Implement adaptive scheduling based on opportunity discovery
        return self.settings.analysis.normal_scan_interval_minutes
    
    def get_status(self) -> dict:
        """Get scheduler status and metrics"""
        return {
            "running": self.running,
            "cycles_completed": self.cycles_completed,
            "last_cycle_time": self.last_cycle_time.isoformat() if self.last_cycle_time else None,
            "last_cycle_duration": self.last_cycle_duration,
            "next_cycle_in_minutes": self._get_next_interval() if self.running else None,
        }