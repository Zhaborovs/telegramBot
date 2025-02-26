from telethon import events
from datetime import datetime
import asyncio
import os
from message_filter import MessageFilter
from message_logger import MessageLogger
from prompt_matcher import PromptMatcher
import re

class MessageMonitor:
    def __init__(self, client, bot, video_downloader, config):
        self.client = client
        self.bot = bot
        self.video_downloader = video_downloader
        self.table_manager = video_downloader.table_manager
        self.max_slots = int(config.get('parallel_requests', '1'))
        self.active_requests = {}  # slot: {prompt_id, model, event}
        self.message_filter = MessageFilter()
        self.message_logger = MessageLogger()
        self.wait_time = int(config.get('wait_time_minutes', '20')) * 60
        self.current_prompt = None
        self.current_model = None
        self.video_received = asyncio.Event()
        self.expected_filepath = None
        self.generation_in_progress = False
        self.error_received = False
        self.prompt_history = []  # История промптов только для текущей сессии
        self.current_video_prompt = None  # Промпт из сообщения с видео
        self.expected_prompt = None  # Промпт, который мы ожидаем
        self.received_video_prompt = None  # Промпт из полученного видео
        self.current_request_id = None  # ID текущего запроса
        self.current_request_time = None  # Время отправки текущего запроса
        self.last_sent_prompt = None  # Последний отправленный нами промпт
        self.waiting_for_response = False  # Флаг ожидания ответа на наш запрос
        self.expected_filename = None  # Ожидаемое имя файла для текущего запроса
        self.prompt_matcher = PromptMatcher()  # Добавляем matcher
        self.current_prompt_id = None  # Добавляем ID текущего промпта
        self.startup_cleanup = False  # Флаг для очистки слотов при старте
        self.waiting_for_slot = False  # Флаг ожидания освобождения слота
        self.slot_freed = asyncio.Event()  # Событие для отслеживания освобождения слота
        self.model_limits = {}  # Словарь для отслеживания счетчиков лимитов моделей
        self.max_model_limit = 2  # Максимум 2 одновременно обрабатываемых промпта для модели
        self.waiting_for_any_video = False  # Флаг ожидания любого видео при лимите
        self.any_video_received = asyncio.Event()  # Событие для отслеживания получения любого видео
        
        # Сообщения о генерации
        self.generation_start_messages = [
            "⚡ ULTRA ELITE",
            "Генерирую видео",
            "⏳ Генерация видео",
            "⚡ Задача ожидает выполнения",
            "⏳ Одну секунду"  # Добавляем сообщение ожидания
        ]
        
        # Только критические ошибки, требующие повторной отправки
        self.error_messages = [
            "Ошибка генерации"
        ]

        # Обновляем сообщения о лимите
        self.limit_messages = [
            "⚠️ Достигнут лимит одновременных запросов",
            "Максимальное количество одновременных генераций"
        ]

    def increase_model_counter(self, model):
        """Увеличивает счетчик активных запросов для модели"""
        if model not in self.model_limits:
            self.model_limits[model] = 0
        self.model_limits[model] += 1
        print(f"Увеличен счетчик модели {model}: {self.model_limits[model]}/{self.max_model_limit}")
        
    def decrease_model_counter(self, model):
        """Уменьшает счетчик активных запросов для модели"""
        if model in self.model_limits and self.model_limits[model] > 0:
            self.model_limits[model] -= 1
            print(f"Уменьшен счетчик модели {model}: {self.model_limits[model]}/{self.max_model_limit}")
            
            # Если счетчик был на максимуме и теперь уменьшился, сигнализируем об освобождении слота
            if self.model_limits[model] == self.max_model_limit - 1:
                print(f"Лимит для модели {model} снят (счетчик уменьшен с {self.max_model_limit} до {self.model_limits[model]})")
                # Если кто-то ждет освобождения слота
                if self.waiting_for_slot:
                    print("Сигнализируем об освобождении слота для модели")
                    self.slot_freed.set()
                    
                # Если ожидаем любое видео для снятия лимита
                if self.waiting_for_any_video:
                    print("Сигнализируем о снятии лимита для модели")
                    self.any_video_received.set()

    def set_model_limit(self, model):
        """Устанавливает максимальный лимит для модели"""
        self.model_limits[model] = self.max_model_limit
        print(f"Установлен максимальный лимит для модели {model}: {self.model_limits[model]}/{self.max_model_limit}")

    def is_model_limited(self, model):
        """Проверяет, достигла ли модель лимита запросов"""
        return self.model_limits.get(model, 0) >= self.max_model_limit

    def set_current_task(self, prompt_id, prompt, model, slot):
        """Устанавливает текущий запрос для слота"""
        # Проверяем, есть ли лимит для данной модели
        if self.is_model_limited(model):
            print(f"Модель {model} достигла лимита запросов ({self.model_limits[model]}/{self.max_model_limit})")
            return False
            
        # Увеличиваем счетчик активных запросов для модели
        self.increase_model_counter(model)
        
        self.active_requests[slot] = {
            'prompt_id': prompt_id,
            'prompt': prompt,
            'model': model,
            'event': asyncio.Event(),
            'limit_detected': False  # Добавляем флаг для отслеживания лимита
        }
        print(f"Ожидается обработка промпта {prompt_id} в слоте {slot}")
        return True

    async def wait_for_video(self, slot):
        """Ожидает получение видео для конкретного слота"""
        if slot not in self.active_requests:
            return False

        request = self.active_requests[slot]
        model = request['model']
        
        try:
            # Ждем получения видео
            await asyncio.wait_for(request['event'].wait(), timeout=self.wait_time)
            # Если получен лимит для этой модели, считаем промпт не отправленным
            if request.get('limit_detected', False):
                print(f"Лимит запросов для модели {model}, промпт не отправлен")
                # Отмечаем промпт как ожидающий для повторной отправки
                self.table_manager.mark_pending(request['prompt_id'])
                # Уменьшаем счетчик модели при неудаче
                self.decrease_model_counter(model)
                return False
            return True
        except asyncio.TimeoutError:
            print(f"Таймаут ожидания видео в слоте {slot}")
            self.table_manager.mark_timeout(request['prompt_id'])
            # Уменьшаем счетчик модели при таймауте
            self.decrease_model_counter(model)
            return False
        finally:
            # Очищаем слот
            if slot in self.active_requests:
                del self.active_requests[slot]

    async def wait_for_any_video_received(self):
        """Ожидает получение любого видео (для снятия лимита)"""
        print("\nОжидаем получение любого видео для снятия лимита...")
        self.waiting_for_any_video = True
        self.any_video_received.clear()
        try:
            await asyncio.wait_for(self.any_video_received.wait(), timeout=self.wait_time)
            print("Получено видео, лимиты для моделей уменьшены")
            return True
        except asyncio.TimeoutError:
            print("Таймаут ожидания видео для снятия лимита")
            return False
        finally:
            self.waiting_for_any_video = False

    async def start_monitoring(self):
        @self.client.on(events.NewMessage(from_users=self.bot))
        async def handler(event):
            message_text = event.message.text or ''
            print(f"Получено сообщение: {message_text}")
            
            has_video = bool(event.message.media and 
                           hasattr(event.message.media, 'document') and 
                           event.message.media.document.mime_type.startswith('video/'))

            # Проверяем сообщение о лимите
            if any(msg in message_text for msg in self.limit_messages):
                print("Обнаружено сообщение о лимите запросов")
                
                # Ищем модель, для которой превышен лимит
                for slot, request in list(self.active_requests.items()):
                    if not request.get('limit_detected'):
                        model = request['model']
                        print(f"Лимит запросов в слоте {slot} для модели {model}")
                        # Устанавливаем лимит для этой модели
                        self.set_model_limit(model)
                        # Отмечаем запрос как неудачный из-за лимита
                        request['limit_detected'] = True
                        request['event'].set()  # Сигнализируем о завершении (с ошибкой)
                        print(f"Промпт {request['prompt_id']} не был отправлен из-за лимита")
                return

            # Обрабатываем видео - всегда скачиваем, независимо от промпта
            if has_video:
                # Определяем модель из текста сообщения или предыдущего контекста
                model_name = None
                
                # Ищем модель в формате "🧮 Модель: #Sora" или "Модель: #Sora"
                model_patterns = [
                    r'(?:\*\*)?🧮\s+Модель:(?:\*\*)?\s+`?#?([^`\n]+)`?',
                    r'Модель:\s+`?#?([^`\n]+)`?'
                ]
                
                for pattern in model_patterns:
                    model_match = re.search(pattern, message_text, re.IGNORECASE)
                    if model_match:
                        model_text = model_match.group(1).strip()
                        if model_text.lower() == 'sora':
                            model_name = '🌙 SORA'
                        elif any(m in model_text.lower() for m in ['hailuo', 'minimax']):
                            model_name = '➕ Hailuo MiniMax'
                        elif any(m in model_text.lower() for m in ['runway', 'gen-3']):
                            model_name = '📦 RunWay: Gen-3'
                        elif 'kling' in model_text.lower():
                            model_name = '🎬 Kling 1.6'
                        elif 'pika' in model_text.lower():
                            model_name = '🎯 Pika 2.0'
                        elif any(m in model_text.lower() for m in ['act-one', 'аватары']):
                            model_name = '👁 Act-One (Аватары 2.0)'
                        elif 'luma' in model_text.lower():
                            model_name = '🌫 Luma: DM'
                        elif 'стилизатор' in model_text.lower():
                            model_name = '🦋 RW: Стилизатор'
                        print(f"Извлечена модель из сообщения: {model_name}")
                        break
                
                # Если модель не найдена в формате "Модель:", ищем её по ключевым словам
                if not model_name:
                    # Поиск названий моделей в тексте сообщения
                    message_lower = message_text.lower()
                    models_map = {
                        'sora': '🌙 SORA',
                        'hailuo': '➕ Hailuo MiniMax',
                        'minimax': '➕ Hailuo MiniMax',
                        'runway': '📦 RunWay: Gen-3',
                        'gen-3': '📦 RunWay: Gen-3',
                        'kling': '🎬 Kling 1.6',
                        'pika': '🎯 Pika 2.0',
                        'act-one': '👁 Act-One (Аватары 2.0)',
                        'аватары': '👁 Act-One (Аватары 2.0)',
                        'luma': '🌫 Luma: DM',
                        'стилизатор': '🦋 RW: Стилизатор'
                    }
                    
                    # Ищем упоминания моделей в тексте сообщения
                    for key, model in models_map.items():
                        if key in message_lower:
                            model_name = model
                            break
                        
                # Если модель не найдена в тексте, берем из активных запросов
                if not model_name and self.active_requests:
                    # Берем модель из первого активного запроса
                    first_request = next(iter(self.active_requests.values()))
                    model_name = first_request['model']
                    
                print(f"Получено видео для модели: {model_name if model_name else 'неизвестно'}")
                
                # Уменьшаем счетчик только для определенной модели
                if model_name and model_name in self.model_limits:
                    print(f"Уменьшаем счетчик для модели {model_name}")
                    self.decrease_model_counter(model_name)
                else:
                    # Если модель не определена, уменьшаем для всех активных моделей
                    print("Модель не определена, уменьшаем счетчики для всех моделей")
                    for model in list(self.model_limits.keys()):
                        self.decrease_model_counter(model)
                
                # Сигнализируем о получении видео для ожидающих слотов
                if self.waiting_for_any_video:
                    self.any_video_received.set()
                
                # Если кто-то ждет освобождения слота
                if self.waiting_for_slot:
                    print("Сигнализируем об освобождении слота")
                    self.slot_freed.set()
                
                # Скачиваем видео и передаем определенную модель
                await self.video_downloader.download_any_video(event.message, model_name)
                
                # Отмечаем события для всех активных запросов, так как видео пришло
                for slot, request in list(self.active_requests.items()):
                    # Если модель запроса совпадает с моделью видео, считаем это успешной обработкой
                    if model_name and request['model'] == model_name:
                        print(f"Отмечаем обработку промпта {request['prompt_id']} для модели {model_name}")
                    request['event'].set()
                    
                return

            # Проверяем сообщения об ожидании (как положительный признак начала генерации)
            if any(msg in message_text for msg in self.generation_start_messages):
                self.generation_in_progress = True
                print("Началась генерация видео...")
                return
                
            # Проверяем сообщения об ошибках
            if any(msg in message_text for msg in self.error_messages):
                for slot, request in list(self.active_requests.items()):
                    print(f"Получена ошибка от бота для слота {slot}")
                    self.table_manager.mark_error(request['prompt_id'], request['model'])
                    # Уменьшаем счетчик при ошибке
                    self.decrease_model_counter(request['model'])
                    request['event'].set()
                return

    def clear_history(self):
        """Очистка истории промптов при новом запуске"""
        self.prompt_history = []
        self.reset_current_task()

    def get_expected_filename(self, prompt, model):
        """Генерирует шаблон имени файла для текущего запроса"""
        # Получаем первые 5 слов из промпта
        words = prompt.split()[:5]
        prompt_start = '_'.join(words)
        # Очищаем от спецсимволов
        prompt_start = ''.join(c if c.isalnum() or c in ['_', '-'] else '_' for c in prompt_start)
        
        # Возвращаем только часть с промптом для сравнения
        return prompt_start

    def check_video_matches_prompt(self, filename, expected_prompt):
        """Проверяет соответствие видео ожидаемому промпту"""
        return self.prompt_matcher.is_matching(filename, expected_prompt)

    def reset_current_task(self):
        self.waiting_for_response = False
        self.last_sent_prompt = None
        self.current_prompt = None
        self.expected_prompt = None
        self.received_video_prompt = None
        self.generation_in_progress = False
        self.error_received = False
        self.expected_filename = None 

    def find_slot_by_last_prompt(self, message_text):
        """Находит слот по промпту в сообщении об ошибке"""
        for slot, request in self.active_requests.items():
            if request['prompt'] in message_text:
                return slot
        return None 

    async def wait_for_any_video(self):
        """Ожидает получение любого видео для очистки слотов"""
        video_received = asyncio.Event()
        
        @self.client.on(events.NewMessage(from_users=self.bot))
        async def temp_handler(event):
            if event.message.media and hasattr(event.message.media, 'document'):
                if event.message.media.document.mime_type.startswith('video/'):
                    video_received.set()
                    # Удаляем временный обработчик
                    self.client.remove_event_handler(temp_handler)

        try:
            await asyncio.wait_for(video_received.wait(), timeout=self.wait_time)
            return True
        except asyncio.TimeoutError:
            print("Таймаут ожидания видео при очистке слотов")
            return False

    async def cleanup_active_slots(self):
        """Очищает занятые слоты при старте программы"""
        if self.startup_cleanup:
            return True
            
        active_prompts = self.table_manager.get_active_prompts()
        if not active_prompts:
            self.startup_cleanup = True
            return True

        print("\nОбнаружены активные слоты с прошлого запуска")
        print("Ожидаем получение видео для очистки слотов...")
        
        success = await self.wait_for_any_video()
        if success:
            # Очищаем все активные промпты
            for prompt in active_prompts:
                self.table_manager.mark_pending(prompt['id'])
            print("Слоты очищены")
        else:
            print("Не удалось дождаться видео, очищаем слоты принудительно")
            for prompt in active_prompts:
                self.table_manager.mark_timeout(prompt['id'])

        self.startup_cleanup = True
        return True 