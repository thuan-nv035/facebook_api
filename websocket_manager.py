from datetime import datetime
class ConnectionManager:
    def __init__(self):
        self.active_connections = {}
        self.last_seen = {} 

    async def connect(self, user_id: int, websocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        # await self.broadcast_status(user_id, "online")
        if user_id in self.last_seen:
            del self.last_seen[user_id]

    async def disconnect(self, user_id: int):
        self.active_connections.pop(user_id, None)
        self.last_seen[user_id] = datetime.now()
        await self.broadcast_status(user_id, "offline")

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
        
    def get_last_seen_info(self, user_id: int):
        if user_id in self.active_connections:
            return "Đang trực tuyến"
        
        last_time = self.last_seen.get(user_id)
        if not last_time:
            return "Không có dữ liệu"

        # Tính khoảng thời gian chênh lệch
        diff = datetime.now() - last_time
        hours = diff.total_seconds() // 3600
        minutes = (diff.total_seconds() % 3600) // 60
        
        return f"Ngoại tuyến {int(hours)} giờ {int(minutes)} phút trước"

manager = ConnectionManager()