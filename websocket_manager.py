class ConnectionManager:
    def __init__(self):
        self.active_connections = {}

    async def connect(self, user_id: int, websocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: int):
        self.active_connections.pop(user_id, None)

    def is_online(self, user_id: int):
        return user_id in self.active_connections
    
    def get_online_users(self):
        return list(self.active_connections.keys())
    
    def get_online_count(self):
        return len(self.active_connections)

    async def send_to_user(self, user_id: int, message: dict):
        websocket = self.active_connections.get(user_id)
        if websocket:
            await websocket.send_json(message)

    async def send_to_many(self, user_ids: list[int], message: dict):
        for user_id in user_ids:
            await self.send_to_user(user_id, message)

    async def send_notification(self, user_id: int, notification: dict):
        await self.send_to_user(user_id, {
            "type": "notification",
            "data": notification
        })

manager = ConnectionManager()