"""Telegram update queue for async processing."""

import asyncio
import logging
from collections import deque
from typing import Deque, Dict

logger = logging.getLogger(__name__)


class TelegramUpdateQueue:
    """Queue for processing Telegram updates asynchronously."""
    
    def __init__(self, maxsize: int = 100):
        """Initialize queue.
        
        Args:
            maxsize: Maximum queue size
        """
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self.metrics = {
            "updates_received": 0,
            "updates_processed": 0,
            "processing_errors": 0,
            "queue_drops": 0,
        }
        self._worker_task: asyncio.Task = None
        self._processor = None
    
    def enqueue(self, update: Dict) -> bool:
        """Enqueue an update for processing.
        
        Args:
            update: Telegram update dict
        
        Returns:
            True if enqueued, False if queue full
        """
        try:
            self.queue.put_nowait(update)
            self.metrics["updates_received"] += 1
            return True
        except asyncio.QueueFull:
            self.metrics["queue_drops"] += 1
            logger.warning("Telegram update queue full, dropping update")
            return False
    
    def set_processor(self, processor):
        """Set the processor function for updates.
        
        Args:
            processor: Function that takes (update, ...) and processes it
        """
        self._processor = processor
    
    async def _worker(self, *args, **kwargs):
        """Background worker that processes updates."""
        logger.info("Telegram update queue worker started")
        while True:
            try:
                update = await self.queue.get()
                if self._processor:
                    try:
                        await asyncio.to_thread(self._processor, update, *args, **kwargs)
                        self.metrics["updates_processed"] += 1
                    except Exception as e:
                        self.metrics["processing_errors"] += 1
                        logger.error(f"Error processing Telegram update: {e}", exc_info=True)
                self.queue.task_done()
            except asyncio.CancelledError:
                logger.info("Telegram update queue worker cancelled")
                break
            except Exception as e:
                logger.error(f"Error in queue worker: {e}", exc_info=True)
                await asyncio.sleep(1)
    
    def start_worker(self, *args, **kwargs):
        """Start the background worker.
        
        Args:
            *args, **kwargs: Arguments to pass to processor
        """
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker(*args, **kwargs))
            logger.info("Telegram update queue worker started")
    
    def stop_worker(self):
        """Stop the background worker."""
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            logger.info("Telegram update queue worker stopped")
    
    def get_metrics(self) -> Dict:
        """Get queue metrics.
        
        Returns:
            Dict with metrics
        """
        return {
            **self.metrics,
            "queue_depth": self.queue.qsize(),
        }

