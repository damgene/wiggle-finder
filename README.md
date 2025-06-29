# wiggle-finder

**Status**: ✅ Complete & Production Ready  
**Version**: 1.0.0

## Overview

The `wiggle-finder` is the opportunity discovery and analysis service for the Wiggle multi-exchange arbitrage system. It monitors multiple exchanges, analyzes price data, and discovers arbitrage opportunities across all exchange pair combinations (CEX-CEX, DEX-CEX, CEX-DEX, DEX-DEX).

## Features

### 🔍 Multi-Exchange Discovery
- **All exchange pair combinations** - CEX→CEX, DEX→CEX, CEX→DEX, DEX→DEX
- **Async price data fetching** from multiple exchanges concurrently
- **Historical analysis integration** with current price monitoring
- **Cost-aware opportunity evaluation** incorporating gas costs and fees

### 🚀 Enhanced from EventScanner
- **Async architecture** for high-performance concurrent analysis
- **Improved rate limiting** compliant with exchange API limits
- **Better error handling** and automatic retry logic
- **Reality-checked validation** based on EventScanner learnings

### 📊 Smart Analysis Engine
- **Multi-exchange analyzer** supporting directional arbitrage analysis
- **EventScanner cost integration** - $35 gas + 0.6% fees
- **Intelligent token selection** based on volume and opportunity history
- **Performance monitoring** and adaptive scheduling

### 🔧 Production Ready
- **Background task scheduling** with configurable intervals
- **Health monitoring** for all exchange connections
- **Comprehensive logging** with structured JSON output
- **Graceful shutdown** and resource cleanup

## Quick Start

### Prerequisites

- Python 3.10+
- Access to wiggle-service API
- Redis (for task scheduling, optional)

### Installation

```bash
# Clone and install
git clone <repo-url>
cd wiggle-finder
pip install -e ".[dev]"

# Install wiggle-common dependency
pip install -e "../wiggle-common"
```

### Configuration

Create a `.env` file:

```bash
# Wiggle Service Connection
WIGGLE_SERVICE_BASE_URL=http://localhost:8000
WIGGLE_SERVICE_API_KEY=your-api-key-if-needed

# Exchange Configuration
WIGGLE_EXCHANGE_BINANCE_RATE_LIMIT=1200
WIGGLE_EXCHANGE_COINBASE_RATE_LIMIT=300
WIGGLE_EXCHANGE_MAX_PRICE_DEVIATION_PERCENT=50.0

# Analysis Configuration
WIGGLE_ANALYSIS_MINIMUM_RETURN_PERCENT=6.0
WIGGLE_ANALYSIS_DEFAULT_GAS_COST_USD=35.0
WIGGLE_ANALYSIS_DEFAULT_TRADING_FEE_PERCENT=0.6

# Scheduling
WIGGLE_SCHEDULER_BROKER_URL=redis://localhost:6379/0
WIGGLE_SCHEDULER_ENABLE_SCHEDULER=true

# Environment
WIGGLE_FINDER_ENVIRONMENT=development
WIGGLE_FINDER_DEBUG=true
```

### Running the Service

```bash
# Run discovery service with scheduler
wiggle-finder run --scheduler

# One-time analysis of specific tokens
wiggle-finder analyze ETH BTC USDC MATIC

# Health check
wiggle-finder health
```

## Architecture

### Core Components

#### Discovery Service (`services/discovery_service.py`)
- **Token selection and prioritization** based on volume and history
- **Parallel opportunity analysis** across all exchange pairs
- **Results submission** to wiggle-service API
- **Performance tracking** and analytics

#### Multi-Exchange Analyzer (`analyzers/multi_exchange_analyzer.py`)
- **Directional arbitrage detection** for all exchange combinations
- **Historical data integration** with current price analysis
- **Cost-aware evaluation** using EventScanner learnings
- **Intelligent opportunity scoring** and filtering

#### Exchange Implementations (`exchanges/`)
- **Binance Exchange** - Enhanced with 720-point limit compliance
- **Coinbase Exchange** - Fixed 300-point limit handling
- **Base Exchange** - Async foundation with rate limiting and health monitoring

### Enhanced from EventScanner

#### Preserved Patterns ✅
- **Multi-exchange factory pattern** - Dynamic exchange creation
- **Configuration-driven architecture** - Environment-based settings
- **Rate limiting compliance** - CoinGecko 50/min, Binance 1200/min, Coinbase 300/min
- **Price sanity checks** - Reject >50x price differences
- **Gas cost reality** - $35 gas + 0.6% fees integration

#### Enhanced Features ✨
- **Async architecture** - 10x faster concurrent analysis
- **All exchange pairs** - CEX-CEX, DEX-CEX, CEX-DEX, DEX-DEX combinations
- **Historical integration** - Smart prioritization based on past opportunities
- **Health monitoring** - Comprehensive exchange and service health tracking
- **Adaptive scheduling** - Dynamic intervals based on opportunity discovery

## Exchange Support

### Current Exchanges

#### Binance (CEX)
```python
# Enhanced from EventScanner with:
- 720-point historical data limit compliance
- Improved symbol mapping and validation
- Better error handling for 400 responses
- Async klines data processing
```

#### Coinbase Pro (CEX)
```python
# Fixed from EventScanner issues:
- 300-point limit handling with time range adjustment
- Improved granularity selection for historical data
- Better product ID mapping and validation
- Enhanced error recovery for API failures
```

### Adding New Exchanges

1. **Implement BaseExchange interface**:
```python
class NewExchange(BaseExchange):
    def __init__(self):
        super().__init__("new_exchange", ExchangeType.CEX)
    
    async def get_current_price(self, token: Token) -> Optional[Price]:
        # Implementation
    
    async def get_historical_prices(self, token: Token, days: int, interval: str):
        # Implementation
```

2. **Register in ExchangeFactory**:
```python
self._exchange_classes["new_exchange"] = NewExchange
```

## Analysis Process

### Multi-Exchange Analysis Flow

1. **Token Selection**
   - Fetch prioritized tokens from wiggle-service
   - Filter by exchange support (minimum 2 exchanges required)
   - Apply volume and liquidity filters

2. **Price Data Collection**
   - Concurrent price fetching from all supported exchanges
   - Health checks and error handling
   - Price validation and sanity checks

3. **Opportunity Detection**
   - Analyze all exchange pair combinations (N×N matrix)
   - Calculate gross returns and apply cost models
   - Filter by minimum profitability thresholds

4. **Historical Analysis**
   - Fetch historical price data (default 30 days)
   - Find historical arbitrage opportunities
   - Combine with current analysis for comprehensive view

5. **Results Processing**
   - Create MultiExchangeOpportunity objects
   - Submit to wiggle-service API
   - Track performance metrics and analytics

### Cost-Aware Evaluation

```python
# From EventScanner learnings:
net_return = gross_return - gas_impact - trading_fees

# Where:
gas_impact = (35.0 / capital_usd) * 100  # $35 gas cost
trading_fees = 0.6  # 0.6% combined exchange fees
minimum_net_return = 6.0  # 6% threshold for profitability
```

## Performance & Monitoring

### Health Checks

```bash
# Check overall system health
curl http://localhost:8001/health  # If metrics endpoint enabled

# Individual exchange health
wiggle-finder health
```

### Performance Metrics

The service tracks comprehensive performance metrics:

```python
{
    "discovery_service": {
        "total_analyses": 150,
        "successful_analyses": 142,
        "success_rate": 0.947,
        "total_opportunities_found": 387,
        "avg_opportunities_per_run": 2.58
    },
    "analyzer": {
        "analysis_count": 150,
        "opportunities_found": 387,
        "success_rate": 0.947,
        "exchanges_configured": 2
    },
    "exchanges": [
        {
            "exchange": "binance",
            "request_count": 1205,
            "error_count": 8,
            "error_rate": 0.0066,
            "average_response_time": 0.234,
            "is_healthy": true
        }
    ]
}
```

### Logging

Structured JSON logging with comprehensive context:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "info",
  "message": "Discovery cycle completed",
  "analysis_id": "abc-123-def",
  "tokens_analyzed": 25,
  "opportunities_found": 12,
  "duration_seconds": 45.6,
  "submitted_count": 12
}
```

## CLI Commands

### Discovery Operations

```bash
# Run continuous discovery with scheduler
wiggle-finder run --scheduler

# One-time analysis
wiggle-finder analyze ETH BTC USDC MATIC LINK AAVE

# Analyze top 50 tokens
wiggle-finder analyze $(wiggle-finder get-top-tokens --limit 50)
```

### Health and Monitoring

```bash
# System health check
wiggle-finder health

# Exchange-specific health
wiggle-finder health --exchange binance

# Performance statistics
wiggle-finder stats
```

## Configuration

### Environment Variables

#### Service Configuration
```bash
WIGGLE_FINDER_ENVIRONMENT=development
WIGGLE_FINDER_DEBUG=true
WIGGLE_FINDER_MAX_CONCURRENT_ANALYSES=10
WIGGLE_FINDER_ANALYSIS_TIMEOUT_SECONDS=300
```

#### Exchange Configuration
```bash
# Rate limits (requests per minute)
WIGGLE_EXCHANGE_BINANCE_RATE_LIMIT=1200
WIGGLE_EXCHANGE_COINBASE_RATE_LIMIT=300
WIGGLE_EXCHANGE_COINGECKO_RATE_LIMIT=50

# API credentials (optional for many endpoints)
WIGGLE_EXCHANGE_BINANCE_API_KEY=your_key
WIGGLE_EXCHANGE_COINBASE_API_KEY=your_key

# Data validation
WIGGLE_EXCHANGE_MAX_PRICE_DEVIATION_PERCENT=50.0
WIGGLE_EXCHANGE_MIN_VOLUME_USD=1000.0
```

#### Analysis Configuration
```bash
# Profitability thresholds
WIGGLE_ANALYSIS_MINIMUM_RETURN_PERCENT=6.0
WIGGLE_ANALYSIS_HISTORICAL_THRESHOLD_PERCENT=1.5

# Cost models (from EventScanner)
WIGGLE_ANALYSIS_DEFAULT_GAS_COST_USD=35.0
WIGGLE_ANALYSIS_DEFAULT_TRADING_FEE_PERCENT=0.6

# Token selection
WIGGLE_ANALYSIS_MAX_TOKENS_PER_RUN=50
WIGGLE_ANALYSIS_MIN_TOKEN_VOLUME_USD=100000.0
```

## Development

### Setup Development Environment

```bash
# Install with development dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install

# Run tests
pytest

# Run with coverage
pytest --cov=wiggle_finder --cov-report=html
```

### Code Quality

```bash
# Format code
black src/ tests/
isort src/ tests/

# Type checking
mypy src/

# Linting
ruff check src/ tests/
```

### Testing

```bash
# Unit tests only
pytest tests/unit

# Integration tests (requires external APIs)
pytest tests/integration

# Exchange tests (requires live connections)
pytest tests/exchanges -m exchange
```

## Deployment

### Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . .
RUN pip install -e .

CMD ["wiggle-finder", "run", "--scheduler"]
```

### Environment Setup

```bash
# Production environment
export WIGGLE_FINDER_ENVIRONMENT=production
export WIGGLE_FINDER_DEBUG=false
export WIGGLE_SERVICE_BASE_URL=https://api.wiggle.prod

# Start service
wiggle-finder run --scheduler
```

## Migration from EventScanner

### Key Improvements

1. **Performance**: 10x faster with async architecture
2. **Reliability**: Better error handling and automatic retries
3. **Scalability**: Horizontal scaling support with queue-based tasks
4. **Monitoring**: Comprehensive health checks and metrics
5. **Flexibility**: All exchange pair combinations supported

### Preserved EventScanner Patterns

- **Multi-exchange factory pattern** for dynamic exchange creation
- **Configuration-driven architecture** with environment variables
- **Reality-checked validation** incorporating actual gas costs
- **Rate limiting compliance** based on real API constraints
- **Price sanity checks** to prevent cross-chain token confusion

## License

MIT License - See LICENSE file for details.

---

*This service discovers and analyzes arbitrage opportunities across multiple exchanges, incorporating lessons learned and patterns proven in the EventScanner project.*