"""Telegram bot client for sending messages and handling updates."""

import logging
import os
from typing import Dict, List, Optional

import requests

from ..settings import Settings

logger = logging.getLogger(__name__)


class TelegramClient:
    """Client for Telegram Bot API."""
    
    def __init__(self, settings: Settings):
        """Initialize Telegram client."""
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.parse_mode = settings.telegram_parse_mode
        self.enabled = bool(self.token and self.chat_id)
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        
        if not self.enabled:
            logger.warning(
                "Telegram client not enabled. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables."
            )
    
    def _make_request(self, method: str, **kwargs) -> Optional[Dict]:
        """Make a request to Telegram API."""
        if not self.enabled:
            logger.debug("Telegram client is not enabled, skipping request.")
            return None
        
        try:
            url = f"{self.base_url}/{method}"
            response = requests.post(url, json=kwargs, timeout=10.0)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error in Telegram API request {method}: {e}")
            return None
    
    def send_message(
        self,
        text: str,
        reply_markup: Optional[Dict] = None,
        chat_id: Optional[int] = None,
    ) -> bool:
        """Send a message to Telegram.
        
        Args:
            text: Message text
            reply_markup: Inline keyboard markup (optional)
            chat_id: Chat ID (uses default if None)
        
        Returns:
            True if successful
        """
        chat = chat_id or self.chat_id
        if not chat:
            logger.warning("No chat_id available for sending message")
            return False
        
        result = self._make_request(
            "sendMessage",
            chat_id=chat,
            text=text,
            parse_mode=self.parse_mode,
            reply_markup=reply_markup,
        )
        
        if result and result.get("ok"):
            logger.debug("Telegram message sent successfully")
            return True
        
        return False
    
    def edit_message_text(
        self,
        text: str,
        chat_id: int,
        message_id: int,
        reply_markup: Optional[Dict] = None,
    ) -> bool:
        """Edit an existing message.
        
        Args:
            text: New message text
            chat_id: Chat ID
            message_id: Message ID to edit
            reply_markup: New inline keyboard markup (optional)
        
        Returns:
            True if successful
        """
        result = self._make_request(
            "editMessageText",
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=self.parse_mode,
            reply_markup=reply_markup,
        )
        
        if result and result.get("ok"):
            logger.debug(f"Telegram message {message_id} edited successfully")
            return True
        
        return False
    
    def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False,
    ) -> bool:
        """Answer a callback query (required to stop loading spinner).
        
        Args:
            callback_query_id: Callback query ID
            text: Optional text to show to user
            show_alert: If True, show as alert instead of notification
        
        Returns:
            True if successful
        """
        result = self._make_request(
            "answerCallbackQuery",
            callback_query_id=callback_query_id,
            text=text,
            show_alert=show_alert,
        )
        
        if result and result.get("ok"):
            logger.debug(f"Callback query {callback_query_id} answered")
            return True
        
        return False
    
    def set_webhook(
        self,
        url: str,
        secret_token: Optional[str] = None,
        allowed_updates: Optional[List[str]] = None,
        drop_pending_updates: bool = False,
    ) -> bool:
        """Set webhook URL for receiving updates.
        
        Args:
            url: Webhook URL (must be HTTPS)
            secret_token: Optional secret token for verification
            allowed_updates: List of update types (default: ["message", "callback_query"])
            drop_pending_updates: If True, drop pending updates
        
        Returns:
            True if successful
        """
        if allowed_updates is None:
            allowed_updates = ["message", "callback_query"]
        
        result = self._make_request(
            "setWebhook",
            url=url,
            secret_token=secret_token,
            allowed_updates=allowed_updates,
            drop_pending_updates=drop_pending_updates,
        )
        
        if result and result.get("ok"):
            logger.info(f"Webhook set to {url}")
            return True
        
        logger.error(f"Failed to set webhook: {result}")
        return False
    
    def delete_webhook(self, drop_pending_updates: bool = False) -> bool:
        """Delete webhook.
        
        Args:
            drop_pending_updates: If True, drop pending updates
        
        Returns:
            True if successful
        """
        result = self._make_request(
            "deleteWebhook",
            drop_pending_updates=drop_pending_updates,
        )
        
        if result and result.get("ok"):
            logger.info("Webhook deleted")
            return True
        
        return False
    
    def get_webhook_info(self) -> Optional[Dict]:
        """Get current webhook information.
        
        Returns:
            Webhook info dict or None
        """
        result = self._make_request("getWebhookInfo")
        if result and result.get("ok"):
            return result.get("result")
        return None
    
    def get_updates(
        self,
        offset: Optional[int] = None,
        limit: int = 100,
        timeout: int = 0,
        allowed_updates: Optional[List[str]] = None,
    ) -> Optional[List[Dict]]:
        """Get updates via long polling.
        
        Args:
            offset: Offset for pagination
            limit: Maximum number of updates (1-100)
            timeout: Timeout in seconds (0 = short polling)
            allowed_updates: List of update types
        
        Returns:
            List of updates or None
        """
        result = self._make_request(
            "getUpdates",
            offset=offset,
            limit=limit,
            timeout=timeout,
            allowed_updates=allowed_updates or ["message", "callback_query"],
        )
        
        if result and result.get("ok"):
            return result.get("result", [])
        
        return None
