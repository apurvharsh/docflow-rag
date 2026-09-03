"""Lightweight backend telemetry for performance monitoring.

Tracks:
- Query execution latency
- Indexing performance
- API response times
- Search hit count and quality
"""

import time
import logging
from functools import wraps
from typing import Callable, Any

logger = logging.getLogger(__name__)


class PerformanceMetrics:
    """Simple telemetry tracker for backend operations."""
    
    @staticmethod
    def log_query_latency(query_text: str, latency_ms: float, hit_count: int):
        """Log search query performance."""
        logger.info(f"QUERY_LATENCY | query_len={len(query_text)} | latency_ms={latency_ms:.2f} | hits={hit_count}")
    
    @staticmethod
    def log_indexing_latency(document_id: str, chunk_count: int, latency_ms: float):
        """Log document indexing performance."""
        logger.info(f"INDEXING_LATENCY | doc_id={document_id} | chunks={chunk_count} | latency_ms={latency_ms:.2f}")
    
    @staticmethod
    def log_retrieval_latency(hit_count: int, dense_score: float, sparse_score: float, latency_ms: float):
        """Log hybrid retrieval performance."""
        logger.info(f"RETRIEVAL_LATENCY | hits={hit_count} | dense_score={dense_score:.2f} | sparse_score={sparse_score:.2f} | latency_ms={latency_ms:.2f}")
    
    @staticmethod
    def log_api_request(method: str, path: str, user_id: str, status_code: int, response_time_ms: float):
        """Log API request metrics."""
        logger.info(f"API_REQUEST | method={method} | path={path} | user={user_id} | status={status_code} | latency_ms={response_time_ms:.2f}")


def track_execution_time(operation_name: str) -> Callable:
    """Decorator to track execution time of a function."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            start = time.perf_counter()
            try:
                return await func(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                logger.debug(f"{operation_name} completed in {elapsed_ms:.2f}ms")
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                logger.debug(f"{operation_name} completed in {elapsed_ms:.2f}ms")
        
        # Return async or sync wrapper based on function
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator
