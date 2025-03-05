from telethon import events
from datetime import datetime
import asyncio
import os
from message_filter import MessageFilter
from message_logger import MessageLogger
from prompt_matcher import PromptMatcher
import re

class MessageMonitor:
    def __init__(self, client, bot, video_downloader, config, logger=None):
        self.client = client
        self.bot = bot
        self.video_downloader = video_downloader
        self.table_manager = video_downloader.table_manager
        self.config = config
        self.logger = logger  # Сохраняем переданный логгер
        self.max_slots = int(config.get('parallel_requests', '1'))
        self.active_requests = {}  # slot: {prompt_id, model, event}
        self.message_filter = MessageFilter()
        self.message_logger = MessageLogger()
        self.wait_time = int(config.get('wait_time_minutes', '20')) * 60
        self.current_prompt = {}  # slot: prompt_id
        self.current_model = {}   # slot: model
        self.video_received = {}  # slot: asyncio.Event()
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
        self.last_video_info = None
        
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

        if self.logger:
            self.logger.log_app_event("MONITOR_INIT", "Инициализирован монитор сообщений")

    def increase_model_counter(self, model):
        """Увеличивает счетчик использования модели"""
        if model not in self.model_limits:
            self.model_limits[model] = 0
        self.model_limits[model] += 1
        print(f"Увеличен счетчик модели {model}: {self.model_limits[model]}/{self.max_model_limit}")
        
        if self.logger:
            self.logger.log_app_event("MODEL_COUNTER", f"Увеличен счетчик модели {model}", 
                                    extra_info={"value": self.model_limits[model]})
        
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
        """Устанавливает флаг лимита для модели"""
        self.model_limits[model] = self.model_limits.get(model, 0) + 1
        print(f"Установлен максимальный лимит для модели {model}: {self.model_limits[model]}/{self.max_model_limit}")
        
        if self.logger:
            self.logger.log_model_limit(model, self.model_limits[model])

    def is_model_limited(self, model):
        """Проверяет, достигла ли модель лимита запросов"""
        return self.model_limits.get(model, 0) >= self.max_model_limit

    def set_current_task(self, prompt_id, prompt, model, slot):
        """Устанавливает текущий обрабатываемый промпт и модель"""
        # Проверяем, не находится ли модель в состоянии лимита
        if self.is_model_limited(model):
            if self.logger:
                self.logger.log_app_event("MODEL_LIMITED", 
                                        f"Модель {model} находится в состоянии лимита (значение: {self.model_limits.get(model, 0)})",
                                        "WARNING")
            return False
        
        # Сбрасываем статус получения видео для слота
        if slot in self.video_received:
            self.video_received[slot].clear()
        
        # Сохраняем информацию о текущем задании
        self.current_prompt[slot] = prompt_id
        self.current_model[slot] = model
        self.active_requests[slot] = {
            'prompt_id': prompt_id,
            'prompt': prompt,
            'model': model,
            'event': asyncio.Event(),
            'limit_detected': False  # Добавляем флаг для отслеживания лимита
        }
        print(f"Ожидается обработка промпта {prompt_id} в слоте {slot}")
        
        # Увеличиваем счетчик использования модели
        self.increase_model_counter(model)
        
        if self.logger:
            self.logger.log_app_event("TASK_SET", 
                                    f"Установлена задача в слоте {slot}: промпт {prompt_id}, модель {model}",
                                    extra_info={"prompt_preview": prompt[:50]+"..." if len(prompt) > 50 else prompt})
        
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
            # Получаем текст сообщения и флаг наличия видео
            message_text = event.message.text or ""
            has_video = bool(event.message.media and hasattr(event.message.media, 'document') and 
                             event.message.media.document.mime_type.startswith('video/'))
            
            # Проверяем, нужно ли логировать/обрабатывать сообщение
            if not self.message_filter.should_print_message(message_text, has_video) and not has_video:
                return  # Пропускаем неинтересные сообщения
            
            # Форматируем сообщение для вывода
            formatted_message = self.message_filter.format_message(message_text, has_video)
            
            # Логируем полученное сообщение
            if self.logger:
                media_type = "VIDEO" if has_video else None
                self.logger.log_incoming(
                    message=message_text,
                    sender=self.config.get('bot_name', 'Unknown'),
                    has_media=has_video,
                    media_type=media_type
                )
            
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
                print("\nПолучено видео!")
                
                # Извлекаем модель из текста сообщения
                model = self.video_downloader.extract_model_from_text(message_text)
                
                # Пытаемся загрузить видео
                success = await self.video_downloader.download_any_video(event.message, model)
                
                if success:
                    # Получаем информацию о загруженном видео
                    file_path = self.video_downloader.last_saved_filepath
                    file_name = file_path.split('\\')[-1] if '\\' in file_path else file_path.split('/')[-1]
                    
                    if self.logger:
                        # Попытка получить prompt_id из имени файла
                        prompt_id = None
                        if "_" in file_name:
                            parts = file_name.split('_')
                            if len(parts) > 1 and len(parts[1]) == 8:  # Обычно ID промпта имеет 8 символов
                                prompt_id = parts[1]
                        
                        self.logger.log_video_downloaded(
                            prompt_id=prompt_id or "unknown",
                            filename=file_name,
                            model=model or "unknown",
                            success=True
                        )
                        
                    # Для любого слота, который ожидает видео, уведомляем о получении
                    for slot in list(self.active_requests.keys()):
                        request = self.active_requests[slot]  # Добавляем определение переменной request
                        # Если модель запроса совпадает с моделью видео, считаем это успешной обработкой
                        if model and model in self.model_limits:
                            print(f"Отмечаем обработку промпта {request['prompt_id']} для модели {model}")
                        request['event'].set()
                    
                    # Устанавливаем событие получения видео
                    self.any_video_received.set()
                    
                    # Сохраняем информацию о последнем видео
                    self.last_video_info = {
                        "file_path": file_path,
                        "model": model,
                        "message_text": message_text
                    }
                    
                    # Проверяем, был ли сброшен лимит для модели после получения видео
                    if model and model in self.model_limits:
                        del self.model_limits[model]
                        if self.logger:
                            self.logger.log_app_event("LIMIT_RESET", 
                                                   f"Сброшен лимит для модели {model} после получения видео")
                else:
                    print("Ошибка при загрузке видео")
                    if self.logger:
                        self.logger.log_video_downloaded(
                            prompt_id="unknown",
                            filename="failed_download",
                            model=model or "unknown",
                            success=False,
                            error="Не удалось загрузить видео"
                        )
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
        self.current_prompt = {}
        self.current_model = {}
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