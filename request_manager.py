import asyncio
from datetime import datetime

class RequestManager:
    def __init__(self, max_slots, table_manager):
        self.max_slots = max_slots
        self.table_manager = table_manager
        self.active_slots = {}  # slot_number: prompt_id
        
    async def get_available_slot(self):
        """Возвращает номер доступного слота или None"""
        active_prompts = self.table_manager.get_active_prompts()
        used_slots = set(int(p.get('slot', 0)) for p in active_prompts)
        
        for slot in range(1, self.max_slots + 1):
            if slot not in used_slots:
                return slot
        return None

    async def acquire_slot(self, prompt_id):
        """Получает слот для промпта"""
        slot = await self.get_available_slot()
        if slot:
            self.table_manager.mark_queued(prompt_id, slot)
            self.active_slots[slot] = prompt_id
            print(f"Промпт {prompt_id} добавлен в слот {slot}")
            return slot
        return None

    async def release_slot(self, slot_number):
        """Освобождает слот"""
        if slot_number in self.active_slots:
            del self.active_slots[slot_number]
            print(f"Слот {slot_number} освобожден")

    def get_active_slots_count(self):
        """Возвращает количество активных слотов"""
        return len(self.active_slots) 