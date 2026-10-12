import asyncio
import importlib
import json
import os
import sys
import time
from pathlib import Path
import websockets
from typing import Optional, Dict, Any, Callable
import logging

logger = logging.getLogger(__name__)

async def get_main_module():
    """Get the main module"""
    try:
        return sys.modules['__main__']
    except KeyError:
        # If the main module is not found, try importing it manually
        spec = importlib.util.spec_from_file_location(
            "main",
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py")
        )
        main = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(main)
        return main

async def get_db_ops():
    """Get the db_ops instance from main.py"""
    main = await get_main_module()
    if main.db_ops is None:
        main.db_ops = await main.init_db_ops()
    return main.db_ops

class UFBClient:
    def __init__(self, config_dir: str = "./ufb/config"):
        # Get the directory containing this file (the ufb directory)
        current_file_dir = Path(__file__).parent
        # Get the project root (parent of the current file's directory)
        project_root = current_file_dir.parent

        self.server_url: Optional[str] = None
        self.token: Optional[str] = None

        # Use the project root as the reference point
        self.config_dir = (project_root / config_dir).resolve()
        # logger.info(f"Config directory: {self.config_dir}")

        self.config_path = self.config_dir / "config.json"
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.is_connected = False
        self.on_config_update_callbacks: list[Callable[[Dict[str, Any]], None]] = []
        self.reconnect_task = None  # Stores the reconnection task

        # Ensure the config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)

    async def ensure_config_dir(self):
        """Ensure the config directory exists"""
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def load_config(self) -> Dict[str, Any]:
        """Load local configuration"""
        if self.config_path.exists():
            try:
                return json.loads(self.config_path.read_text(encoding='utf-8'))
            except json.JSONDecodeError:
                logger.error("Config file is corrupted")
                return {}
        return {}

    async def save_config(self, config: Dict[str, Any], to_client: bool = False):
        """Save configuration to local disk"""
        logger.info(f"Saving config to local disk: {self.config_path.absolute()}")
        self.config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
        if to_client:
            db_ops = await get_db_ops()
            await db_ops.sync_from_json(config)


    def merge_configs(self, local_config: Dict[str, Any], cloud_config: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge local and cloud configurations.
        Strategy:
        1. If local config is empty, use the cloud config.
        2. If the value is a dict, merge recursively.
        3. If the value is a list, merge and deduplicate.
        4. For all other types, overwrite the local value with the cloud value.
        """
        # If local config is empty, use cloud config directly
        if not local_config:
            return cloud_config.copy()

        # If cloud config is empty, use local config
        if not cloud_config:
            return local_config.copy()

        # Begin recursive merge
        merged = local_config.copy()

        for key, cloud_value in cloud_config.items():
            # If the value is a dict, merge recursively
            if isinstance(cloud_value, dict):
                if key not in merged:
                    merged[key] = {}
                if isinstance(merged[key], dict):
                    merged[key] = self.merge_configs(merged[key], cloud_value)
                else:
                    # Local value is not a dict but cloud value is; use cloud value
                    merged[key] = cloud_value.copy()
            # If the value is a list, merge and deduplicate
            elif isinstance(cloud_value, list):
                if key not in merged or not isinstance(merged[key], list):
                    merged[key] = cloud_value.copy()
                else:
                    # Merge lists, removing duplicates
                    merged_list = merged[key].copy()
                    for item in cloud_value:
                        if item not in merged_list:
                            merged_list.append(item)
                    merged[key] = merged_list
            else:
                # Non-dict, non-list: use cloud value
                merged[key] = cloud_value

        return merged

    def on_config_update(self, callback: Callable[[Dict[str, Any]], None]):
        """Register a config update callback"""
        self.on_config_update_callbacks.append(callback)

    def notify_config_update(self, config: Dict[str, Any]):
        """Notify all listeners that the config has been updated"""
        for callback in self.on_config_update_callbacks:
            try:
                callback(config)
            except Exception as e:
                logger.error(f"Config update callback failed: {e}")

    async def handle_config_conflict(self, conflict_data: Dict[str, Any], local_config: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a configuration conflict.
        Returns the final configuration to use.
        """
        logger.info(f"Config conflict: \nCloud time: {conflict_data['cloudTime']}\nLocal time: {conflict_data['localTime']}")

        # Always choose to use the cloud configuration
        await self.websocket.send(json.dumps({
            "type": "resolveConflict",
            "choice": "useCloud"
        }))

        # Wait for the server response
        cloud_config = json.loads(await self.websocket.recv())
        logger.info(f"Received cloud config: {json.dumps(cloud_config, ensure_ascii=False, indent=2)}")

        # Merge cloud and local configurations
        merged_config = self.merge_configs(local_config, cloud_config)
        logger.info(f"Merged config: {json.dumps(merged_config, ensure_ascii=False, indent=2)}")

        return merged_config

    async def connect(self, server_url: str, token: str):
        """Establish a WebSocket connection"""
        if self.is_connected:
            await self.close()

        self.server_url = server_url
        self.token = token

        try:
            self.websocket = await websockets.connect(f"{server_url}/ws/config/{token}")
            self.is_connected = True
            logger.info("WebSocket connection established")

            # Cancel reconnection task on successful connection
            if self.reconnect_task:
                self.reconnect_task.cancel()
                self.reconnect_task = None

        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            # Start reconnection
            await self.start_reconnect()
            raise

    async def reconnect(self):
        """Reconnection loop"""
        while True:
            try:
                if not self.is_connected and self.server_url and self.token:
                    logger.info("Attempting to reconnect...")
                    self.websocket = await websockets.connect(f"{self.server_url}/ws/config/{self.token}")
                    self.is_connected = True
                    logger.info("Reconnection successful")

                    # Restart message handling
                    asyncio.create_task(self._handle_messages())

                    # Re-send the config update
                    local_config = self.load_config()
                    await self.websocket.send(json.dumps({
                        "type": "update",
                        **local_config
                    }))

                    # Exit the loop on successful reconnection
                    break
            except Exception as e:
                logger.error(f"Reconnection failed: {e}")
                await asyncio.sleep(10)  # Wait 10 seconds before retrying

    async def start_reconnect(self):
        """Start the reconnection task"""
        if not self.reconnect_task or self.reconnect_task.done():
            self.reconnect_task = asyncio.create_task(self.reconnect())

    async def start(self, server_url: Optional[str] = None, token: Optional[str] = None):
        """Start the client"""
        logger.info("Starting client")
        await self.ensure_config_dir()

        if server_url and token:
            await self.connect(server_url, token)
        elif self.server_url and self.token:
            await self.connect(self.server_url, self.token)
        else:
            logger.info("Waiting for connection parameters...")
            return

        # Check local configuration
        local_config = self.load_config()
        current_timestamp = int(time.time() * 1000)

        # Ensure the config structure is complete
        if not local_config:
            local_config = {
                "globalConfig": {
                    "SYNC_CONFIG": {
                        "lastSyncTime": current_timestamp
                    }
                }
            }
        else:
            if "globalConfig" not in local_config:
                local_config["globalConfig"] = {}
            if "SYNC_CONFIG" not in local_config["globalConfig"]:
                local_config["globalConfig"]["SYNC_CONFIG"] = {}
            if "lastSyncTime" not in local_config["globalConfig"]["SYNC_CONFIG"]:
                local_config["globalConfig"]["SYNC_CONFIG"]["lastSyncTime"] = current_timestamp

        # Check whether this is the first sync (config file missing or empty)
        if not self.config_path.exists() or not local_config:
            # Send a first-sync request
            await self.websocket.send(json.dumps({
                "type": "firstSync",
                **local_config
            }))
        else:
            # Not the first sync; check whether the config needs updating
            await self.websocket.send(json.dumps({
                "type": "update",
                **local_config
            }))

        # Create a background task to handle messages
        asyncio.create_task(self._handle_messages())

    async def _handle_messages(self):
        """Handle WebSocket messages in the background"""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    logger.info(f"Received server message")

                    msg_type = data.get("type")
                    if msg_type == "firstSync":
                        if data.get("message") == "firstSync_success":
                            logger.info("First sync successful")
                            await self.save_config(data)
                            self.notify_config_update(data)

                    elif msg_type == "update":
                        if data:
                            if data.get('additional_info') != "to_server" or data.get('additional_info') is None:
                                await self.save_config(data, to_client=True)
                            else:
                                await self.save_config(data)
                            self.notify_config_update(data)

                            if data.get("message") == "config_updated":
                                logger.info("Config updated")

                    elif msg_type == "configConflict":
                        # Extract timestamps
                        cloud_time = data.get("cloudTime")
                        local_time = data.get("localTime")
                        newer_config = data.get("newerConfig")

                        logger.info(f"Config conflict:\nCloud time: {cloud_time}\nLocal time: {local_time}\nNewer config: {newer_config}")

                        # Load local config
                        local_config = self.load_config()

                        # Always use cloud config
                        await self.websocket.send(json.dumps({
                            "type": "resolveConflict",
                            "choice": "useCloud"
                        }))

                        # Wait for server response
                        response = json.loads(await self.websocket.recv())
                        # Merge configurations
                        merged_config = self.merge_configs(local_config, response)
                        await self.save_config(merged_config)
                        self.notify_config_update(merged_config)

                    elif msg_type == "delete":
                        if data.get("success"):
                            logger.info("Config deleted successfully")
                        else:
                            logger.error(f"Config deletion failed: {data.get('message', '')}")

                except json.JSONDecodeError:
                    logger.error("Received invalid JSON message")
                except Exception as e:
                    logger.error(f"Error processing message: {e}")

        except websockets.ConnectionClosed:
            logger.info("WebSocket connection closed")
            self.is_connected = False
            # Start reconnection
            await self.start_reconnect()
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            self.is_connected = False
            # Start reconnection
            await self.start_reconnect()

    async def close(self):
        """Close the client"""
        if self.websocket:
            await self.websocket.close()
            self.is_connected = False
            logger.info("WebSocket connection closed")
            # Cancel reconnection task
            if self.reconnect_task:
                self.reconnect_task.cancel()
                self.reconnect_task = None
