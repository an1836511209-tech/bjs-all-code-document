"""任务取消订阅器"""
import asyncio
from loguru import logger
from src.services.redis.client import get_redis_client


class TaskCancelSubscriber:
    """监听任务取消通知"""
    
    def __init__(self):
        self.redis_client = get_redis_client()
        self.pubsub = self.redis_client.get_pubsub()
        self.cancelled_tasks = set()  # 本地缓存已取消的任务ID
        self._running = False
    
    async def start(self):
        """启动订阅"""
        self._running = True
        self.pubsub.subscribe("cancel:task")
        logger.info("任务取消订阅器已启动")
        
        # 在后台任务中监听
        asyncio.create_task(self._listen())
    
    async def _listen(self):
        """监听取消消息（在单独线程中运行以避免阻塞）"""
        import threading
        
        def blocking_listen():
            """在单独线程中执行阻塞的Redis监听"""
            while self._running:
                try:
                    message = self.pubsub.get_message(timeout=1.0)
                    if message and message['type'] == 'message':
                        task_info = message['data']
                        task_id = task_info.split(':')[0]
                        self.cancelled_tasks.add(task_id)
                        logger.info(f"收到任务取消通知: {task_id}")
                except Exception as e:
                    logger.error(f"监听取消消息异常: {e}")
        
        # 在独立线程中运行阻塞操作
        listener_thread = threading.Thread(target=blocking_listen, daemon=True)
        listener_thread.start()
        logger.debug("任务取消监听线程已启动")
        
        # 保持异步任务活跃
        while self._running:
            await asyncio.sleep(1)
    
    def is_cancelled(self, task_id: str) -> bool:
        """检查任务是否已取消"""
        return task_id in self.cancelled_tasks
    
    async def stop(self):
        """停止订阅"""
        self._running = False
        self.pubsub.unsubscribe()
        logger.info("任务取消订阅器已停止")


# 全局单例
_subscriber = None

def get_task_cancel_subscriber() -> TaskCancelSubscriber:
    global _subscriber
    if _subscriber is None:
        _subscriber = TaskCancelSubscriber()
    return _subscriber

