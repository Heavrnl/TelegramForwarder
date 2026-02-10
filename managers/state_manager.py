import logging
from typing import Dict, Tuple, Optional, Union
from telethon.tl.custom import Message

logger = logging.getLogger(__name__)

class StateManager:
    def __init__(self):
        self._states: Dict[Tuple[int, int], Tuple[str, Optional[Message], Optional[str]]] = {}
        logger.info("StateManager initialized")

    def set_state(self, user_id: int, chat_id: int, state: str, message: Optional[Message] = None, state_type: Optional[str] = None) -> None:
        """Set user state"""
        key = (user_id, chat_id)
        self._states[key] = (state, message, state_type)
        logger.info(f"Set state - key: {key}, state: {state}, type: {state_type}")
        logger.debug(f"All current states: {self._states}")  # Changed to debug level

    def get_state(self, user_id: int, chat_id: int) -> Union[Tuple[str, Optional[Message], Optional[str]], Tuple[None, None, None]]:
        """Get user state"""
        key = (user_id, chat_id)
        state_data = self._states.get(key)
        if state_data:  # Only log when state exists
            if len(state_data) == 3:  # Compatible with new format
                state, message, state_type = state_data
                logger.info(f"Get state - key: {key}, state: {state}, type: {state_type}")
            else:  # Compatible with old format
                state, message = state_data
                state_type = None
                logger.info(f"Get state - key: {key}, state: {state}, type: None (old format)")
            return state, message, state_type
        return None, None, None

    def clear_state(self, user_id: int, chat_id: int) -> None:
        """Clear user state"""
        key = (user_id, chat_id)
        if key in self._states:
            del self._states[key]
            logger.info(f"Clear state - key: {key}")
        logger.debug(f"All current states: {self._states}")  # Changed to debug level

    def check_state(self) -> bool:
        """Check if any state exists"""
        return bool(self._states)

# Create global instance
state_manager = StateManager()
logger.info("StateManager global instance created")