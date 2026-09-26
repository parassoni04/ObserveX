"""
ObserveX Server — WebSocket Package.

manager: Connection tracking and message routing
agent_handler: Agent WebSocket endpoint
dashboard_handler: Dashboard WebSocket endpoint
"""
from server.websockets.manager import ConnectionManager, connection_manager
