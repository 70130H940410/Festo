# =============================================================
# core/sse.py
# Server-Sent Events (SSE) 管理模組
# ----------------------------------------------------------
# SSE 是一種伺服器主動推播訊息給瀏覽器的技術（單向，Server → Client）。
# 本模組透過 Queue 實作：
#   - 每個連線的前端都有一個 Queue（監聽器）
#   - 當工廠狀態更新時，呼叫 announce() 把訊息推給所有監聽者
# =============================================================

import queue


class SSEManager:
    """
    管理所有 SSE 連線的 Queue 列表。
    每當有前端連上 /api/stream，就建立一個新 Queue 加入 listeners。
    """

    def __init__(self):
        self.listeners: list[queue.Queue] = []

    def listen(self) -> queue.Queue:
        """
        建立一個新的 Queue 並加入監聽列表，回傳給 event_stream generator 使用。
        maxsize=100：Queue 超過 100 則自動丟棄舊訊息（避免記憶體爆炸）。
        """
        q = queue.Queue(maxsize=100)
        self.listeners.append(q)
        return q

    def announce(self, msg: str) -> None:
        """
        把 msg 廣播給所有目前連線的前端。
        若某個 Queue 已滿（連線斷開但沒清掉），就從列表移除。
        使用反向遍歷，安全地在迴圈中刪除元素。
        """
        for i in reversed(range(len(self.listeners))):
            try:
                self.listeners[i].put_nowait(msg)
            except queue.Full:
                # Queue 滿 → 該連線已失效，移除
                del self.listeners[i]


# 全域單例：整個 App 共用同一個 SSEManager
sse_manager = SSEManager()
