from telethon import events
from datetime import datetime
import asyncio
import os
from message_filter import MessageFilter
from message_logger import MessageLogger
from prompt_matcher import PromptMatcher
import re
import time

class MessageMonitor:
    def __init__(self, client, bot, video_downloader, config, logger=None):
        """
        Инициализирует монитор сообщений
        
        Args:
            client: Телеграм-клиент
            bot: Бот для отправки сообщений
            video_downloader: Загрузчик видео, содержащий table_manager
            config: Конфигурация
            logger: Логгер для записи событий
        """
        self.client = client
        self.bot = bot
        self.video_downloader = video_downloader
        self.table_manager = video_downloader.table_manager if hasattr(video_downloader, 'table_manager') else None
        
        # Передаем client в video_downloader
        if hasattr(self.video_downloader, 'set_client'):
            self.video_downloader.set_client(client)
            self.video_downloader.message_monitor = self
            if logger:
                logger.log_app_event("INIT", "Client установлен для video_downloader")
        
        self.config = config
        self.logger = logger  # Сохраняем переданный логгер
        self.max_slots = int(config.get('parallel_requests', '1'))
        self.active_requests = {}  # slot: {prompt_id, model, event}
        self.message_filter = MessageFilter()
        self.message_logger = MessageLogger()
        
        # Время ожидания видео в секундах (из конфига)
        wait_minutes = int(config.get('wait_time_minutes', '20'))
        self.wait_time = wait_minutes * 60  # Конвертируем минуты в секунды
        
        self.current_prompt = {}  # slot: prompt_id
        self.current_model = {}   # slot: model
        self.video_received = {}  # slot: filename
        self.expected_filepath = None
        self.generation_in_progress = False
        self.error_received = False
        self.prompt_history = []  # История промптов только для текущей сессии
        self.current_video_prompt = None  # Промпт из сообщения с видео
        
        # Флаг активности мониторинга
        self.monitoring_active = False
        
        # Регулярное выражение для поиска промптов
        self.prompt_pattern = re.compile(r'\*\*📍 Ваш запрос:\*\* `(.+?)`', re.DOTALL)
        
        # Инициализация словарей
        self.current_prompt = {}  # Текущие промпты по слотам
        self.current_model = {}   # Текущие модели по слотам
        self.video_received = {}  # Флаги получения видео по слотам
        
        # Активные запросы со всей информацией
        self.active_requests = {}
        
        self.max_model_limit = 2  # Максимум 2 одновременно обрабатываемых промпта для модели
        self.waiting_for_any_video = False  # Флаг ожидания любого видео при лимите
        self.any_video_received = asyncio.Event()  # Событие для отслеживания получения любого видео
        self.last_video_info = None
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
        self.generation_in_progress = False
        self.error_received = False
        self.prompt_history = []  # История промптов только для текущей сессии
        self.current_video_prompt = None  # Промпт из сообщения с видео
        self.expected_prompt = None  # Промпт, который мы ожидаем
        self.received_video_prompt = None  # Промпт из полученного видео
        
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
        """Уменьшает счетчик использования модели на 1"""
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
        """
        Устанавливает текущую задачу
        
        Args:
            prompt_id: ID промпта
            prompt: Текст промпта
            model: Модель для генерации
            slot: Номер слота
            
        Returns:
            bool: True если успешно, False в случае ошибки
        """
        # Проверяем, не находится ли модель в состоянии лимита
        if self.is_model_limited(model):
            print(f"❌ Модель {model} достигла лимита запросов. Промпт {prompt_id} будет возвращен в очередь.")
            
            # Отмечаем промпт как ожидающий
            table_manager = self.get_table_manager()
            if table_manager:
                table_manager.mark_pending(prompt_id)
                
                if self.logger:
                    self.logger.log_app_event("MODEL_LIMITED", 
                                            f"Модель {model} достигла лимита. Промпт {prompt_id} возвращен в очередь",
                                            extra_info={"model": model, "prompt_id": prompt_id})
                
            return False
            
        # Инкрементируем счетчик для модели
        self.increase_model_counter(model)
        
        # Сохраняем информацию о текущей задаче
        prompt_short = prompt[:30] + "..." if len(prompt) > 30 else prompt
        
        self.active_requests[slot] = {
            'prompt_id': prompt_id,
            'prompt': prompt,
            'model': model,
            'start_time': time.time(),
            'sent_message_id': None,
            'status': 'sending'
        }
        
        # Отмечаем промпт как находящийся в обработке
        table_manager = self.get_table_manager()
        if table_manager:
            table_manager.mark_in_progress(prompt_id, model)
            
            if self.logger:
                self.logger.log_app_event("TASK_SET", 
                                        f"Установлена задача для промпта {prompt_id} в слоте {slot}",
                                        extra_info={"model": model, "slot": slot, "prompt": prompt_short})
        
        print(f"Увеличен счетчик модели {model}: {self.model_limits[model]}/{self.max_model_limit}")
        return True

    async def wait_for_video(self, slot):
        """
        Ожидает получения видео для конкретного слота
        
        Args:
            slot: Номер слота
            
        Returns:
            bool: True если видео получено, False если истек таймаут
        """
        if slot not in self.active_requests:
            print(f"Ошибка: слот {slot} не активен")
            return False
            
        request = self.active_requests[slot]
        prompt_id = request['prompt_id']
        model = request['model']
        
        print(f"Ожидаем видео для слота {slot}. Таймаут установлен на {self.wait_time} секунд ({self.wait_time/60} минут)")
        
        # Ожидаем получения видео
        start_time = time.time()
        
        while time.time() - start_time < self.wait_time:
            # Видео получено
            if slot in self.video_received and self.video_received[slot]:
                print(f"✅ Видео для слота {slot} получено!")
                
                # Отмечаем, что видео получено
                self.video_received[slot] = False
                
                # Уменьшаем счетчик для модели
                self.decrease_model_counter(model)
                print(f"Уменьшен счетчик модели {model} после успешного получения видео: {self.model_limits[model]}/{self.max_model_limit}")
                
                # Освобождаем слот
                if slot in self.active_requests:
                    del self.active_requests[slot]
                
                return True
                
            # Получена ошибка
            if self.error_received:
                print(f"❌ Получена ошибка при генерации видео для слота {slot}")
                self.error_received = False
                
                # Отмечаем промпт как завершившийся с ошибкой
                table_manager = self.get_table_manager()
                if table_manager:
                    table_manager.mark_error(prompt_id, model, "Ошибка при генерации видео")
                    
                # Уменьшаем счетчик для модели
                self.decrease_model_counter(model)
                print(f"Уменьшен счетчик модели {model} после ошибки: {self.model_limits[model]}/{self.max_model_limit}")
                
                # Освобождаем слот
                if slot in self.active_requests:
                    del self.active_requests[slot]
                
                return False
            
            # Проверяем, не был ли слот освобожден извне
            if slot not in self.active_requests:
                print(f"Слот {slot} был освобожден во время ожидания")
                return False
                
            # Небольшая пауза, чтобы не нагружать процессор
            await asyncio.sleep(0.5)
            
        # Время ожидания истекло
        print(f"⏰ Истекло время ожидания видео для слота {slot}")
        
        # Отмечаем промпт как таймаут
        table_manager = self.get_table_manager()
        if table_manager:
            table_manager.mark_timeout(prompt_id, model)
            
        # Уменьшаем счетчик для модели
        self.decrease_model_counter(model)
        print(f"Уменьшен счетчик модели {model} из-за таймаута: {self.model_limits[model]}/{self.max_model_limit}")
        
        # Освобождаем слот
        if slot in self.active_requests:
            del self.active_requests[slot]
            
        return False

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
        # Устанавливаем флаг активности мониторинга
        self.monitoring_active = True
        
        # Обработчик исходящих сообщений (от нас боту)
        @self.client.on(events.NewMessage(outgoing=True, chats=self.bot))
        async def outgoing_handler(event):
            """Обработчик исходящих сообщений от нас боту"""
            try:
                message_text = event.message.text or ""
                
                # Логируем исходящее сообщение
                if self.logger:
                    self.logger.log_outgoing(message_text, self.bot.username, "TEXT")
                
                # Проверяем, является ли сообщение промптом
                if len(message_text) > 20 and not message_text.startswith('/'):
                    print(f"\nОтправлен промпт: {message_text[:30]}...")
                    
                    # Ищем активный слот для этого промпта
                    for slot, request in self.active_requests.items():
                        if request['prompt'] == message_text:
                            # Сохраняем ID отправленного сообщения
                            request['sent_message_id'] = event.message.id
                            print(f"Промпт связан со слотом {slot}, ID сообщения: {event.message.id}")
                            
                            if self.logger:
                                self.logger.log_app_event("PROMPT_SENT", 
                                                      f"Отправлено сообщение с промптом {request['prompt_id']} (ID: {event.message.id})",
                                                      extra_info={"message_id": event.message.id, "slot": slot})
                            break
            except Exception as e:
                if self.logger:
                    self.logger.log_exception(e, context="При обработке исходящего сообщения")
        
        @self.client.on(events.NewMessage(chats=self.bot))
        async def handler(event):
            # Обработка входящих сообщений от бота
            try:
                message = event.message
                message_text = message.text or message.message or ""
                has_video = False
                
                # Проверяем, содержит ли сообщение видео
                if message.media and hasattr(message.media, 'document') and \
                   message.media.document.mime_type and message.media.document.mime_type.startswith('video/'):
                    has_video = True
                
                if self.logger:
                    extra_info = {"has_video": has_video}
                    self.logger.log_incoming(message_text, "Bot", has_video, "VIDEO" if has_video else None, extra_info)
                
                # Если сообщение содержит видео, обрабатываем его
                if has_video:
                    print(f"\n🎬 ПОЛУЧЕНО ВИДЕО В СООБЩЕНИИ!")
                    print(f"Содержимое сообщения: {message_text[:50]}...")
                    
                    # Находим слот по тексту сообщения (в нем содержится промпт)
                    prompt_slot = self.find_slot_by_last_prompt(message_text)
                    print(f"Найден слот по промпту: {prompt_slot}")
                    
                    if prompt_slot and prompt_slot in self.active_requests:
                        prompt_id = self.active_requests[prompt_slot]['prompt_id']
                        model = self.active_requests[prompt_slot]['model']
                        
                        print(f"Скачиваем видео для промпта {prompt_id}, модель {model}")
                        
                        if self.logger:
                            self.logger.log_app_event("VIDEO_RECEIVED", 
                                                     f"Получено видео для промпта {prompt_id} в слоте {prompt_slot}",
                                                     extra_info={"model": model})
                        
                        # Скачиваем видео
                        await self.video_downloader.download_video(message, prompt_id, model)
                        
                        # Уменьшаем счетчик использования модели после успешного скачивания
                        self.decrease_model_counter(model)
                        print(f"Уменьшен счетчик модели {model} после успешного получения видео: {self.model_limits[model]}/{self.max_model_limit}")
                        
                        # Уведомляем о получении видео для слота
                        self.video_received[prompt_slot] = True
                        
                        # Сигнализируем о том, что видео получено и загружено
                        if prompt_slot in self.active_requests and 'event' in self.active_requests[prompt_slot]:
                            event_obj = self.active_requests[prompt_slot]['event']
                            event_obj.set()
                    else:
                        # Если не смогли определить слот по промпту, пробуем по ID ответа
                        for slot, request in self.active_requests.items():
                            if 'status_message_id' in request and request['status_message_id'] == message.id:
                                prompt_id = request['prompt_id']
                                model = request['model']
                                
                                if self.logger:
                                    self.logger.log_app_event("VIDEO_RECEIVED_BY_STATUS", 
                                                            f"Получено видео для промпта {prompt_id} в слоте {slot}",
                                                            extra_info={"model": model})
                                
                                # Скачиваем видео
                                await self.video_downloader.download_video(message, prompt_id, model)
                                
                                # Уведомляем о получении видео для слота
                                self.video_received[slot] = True
                                
                                # Сигнализируем о том, что видео получено и загружено
                                if 'event' in request:
                                    request['event'].set()
                                break
                        else:
                            # Если не смогли определить слот ни по промпту, ни по ID, скачиваем видео со стандартным названием
                            if self.logger:
                                self.logger.log_app_event("VIDEO_RECEIVED_UNKNOWN", 
                                                        "Получено видео, но не удалось определить промпт",
                                                        "WARNING")
                            
                            # Скачиваем видео с неизвестным промптом
                            await self.video_downloader.download_any_video(message)
                
                # Остальной код обработки сообщений...
                print("\nПОЛУЧЕНО НОВОЕ СООБЩЕНИЕ")  # Отладочное сообщение
                # Получаем текст сообщения и флаг наличия видео
                message_text = event.message.text or ""
                has_video = (event.message.media and hasattr(event.message.media, 'document') and 
                            event.message.media.document.mime_type.startswith('video/'))
                
                print(f"Текст: {message_text[:50]}{'...' if len(message_text) > 50 else ''}")
                print(f"Содержит видео: {has_video}")
                
                # Логируем входящее сообщение
                if self.logger:
                    media_type = None
                    if has_video:
                        media_type = "VIDEO"
                    self.logger.log_incoming(message_text, "Bot", has_video, media_type)
                
                # Записываем сообщение в лог
                self.message_logger.log_message(message_text, has_video)
                
                # Проверяем, нужно ли логировать/обрабатывать сообщение
                if not self.message_filter.should_print_message(message_text, has_video) and not has_video:
                    return  # Пропускаем неинтересные сообщения
                
                # Проверяем, является ли сообщение статусным (содержит "📍 Ваш запрос:" или "📍 Запрос:")
                is_status_message = "📍 Ваш запрос:" in message_text or "📍 Запрос:" in message_text

                # Если это статусное сообщение, пытаемся найти соответствующий слот/промпт
                if is_status_message:
                    # Извлекаем текст промпта из сообщения
                    prompt_match = re.search(r'📍 (?:Ваш )?запрос:\s*(.+)', message_text, re.IGNORECASE | re.DOTALL)
                    if prompt_match:
                        prompt_text = prompt_match.group(1).strip()
                        
                        # Ищем соответствующий слот
                        for slot, request in self.active_requests.items():
                            if request['prompt'].startswith(prompt_text[:30]) or prompt_text.startswith(request['prompt'][:30]):
                                # Нашли соответствующий слот
                                request['status_message_id'] = event.message.id
                                
                                if self.logger:
                                    self.logger.log_app_event("STATUS_MESSAGE", 
                                                            f"Найдено статусное сообщение для промпта {request['prompt_id']} в слоте {slot}",
                                                            extra_info={"message_id": event.message.id})
                                print(f"\n📊 Отслеживается статус для промпта {request['prompt_id']} (слот {slot})")
                                break

                # Проверяем на наличие ошибки в сообщении - используем patterns из MessageFilter
                if any(error_pattern in message_text.lower() for error_pattern in self.message_filter.error_patterns):
                    print("\n⚠️ Обнаружена ошибка в сообщении!")
                    
                    # Пытаемся определить слот по реплаю или содержимому
                    slot = self.find_slot_by_reply(event.message) or self.find_slot_by_last_prompt(message_text)
                    
                    if slot:
                        # Если нашли слот, отмечаем ошибку для этого промпта
                        request = self.active_requests[slot]
                        prompt_id = request['prompt_id']
                        
                        if self.logger:
                            self.logger.log_app_event("VIDEO_ERROR", 
                                                    f"Обнаружена ошибка генерации для промпта {prompt_id} в слоте {slot}",
                                                    "ERROR", 
                                                    {"error_text": message_text[:200]})
                        
                        # Отмечаем промпт как пропущенный из-за ошибки
                        self.table_manager.mark_error(request['prompt_id'], request['model'], message_text[:100])
                        print(f"❌ Промпт {prompt_id} помечен как завершившийся с ошибкой")
                        
                        # Уменьшаем счетчик использования модели
                        self.decrease_model_counter(request['model'])
                        
                        # Устанавливаем событие для разблокировки ожидающего потока
                        request['event'].set()
                        return
                    else:
                        # Если не смогли определить слот, ищем по контексту сообщения
                        # Проверяем все активные запросы
                        for active_slot, request in self.active_requests.items():
                            # Если нашли упоминание промпта в сообщении об ошибке
                            prompt_preview = request['prompt'][:30].lower()
                            if prompt_preview in message_text.lower():
                                prompt_id = request['prompt_id']
                                
                                if self.logger:
                                    self.logger.log_app_event("VIDEO_ERROR_MATCHED", 
                                                            f"Сопоставлена ошибка для промпта {prompt_id} в слоте {active_slot}",
                                                            "ERROR", 
                                                            {"error_text": message_text[:200]})
                                
                                # Отмечаем промпт как завершившийся с ошибкой
                                self.table_manager.mark_error(request['prompt_id'], request['model'], message_text[:100])
                                print(f"❌ Промпт {prompt_id} помечен как завершившийся с ошибкой (по содержимому)")
                                
                                # Уменьшаем счетчик использования модели
                                self.decrease_model_counter(request['model'])
                                
                                # Устанавливаем событие
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

            except Exception as e:
                if self.logger:
                    self.logger.log_exception(e, context="При обработке входящего сообщения")

        # Добавляем обработчик для отредактированных сообщений
        @self.client.on(events.MessageEdited(chats=self.bot))
        async def edited_handler(event):
            # Обработка отредактированных сообщений
            try:
                message_text = event.message.text or ""
                has_video = (hasattr(event.message, 'media') and 
                            event.message.media and 
                            hasattr(event.message.media, 'document') and 
                            event.message.media.document.mime_type.startswith('video/'))
                
                # Проверяем, соответствует ли отредактированное сообщение какому-либо статусному сообщению
                matching_slot = None
                for slot, request in self.active_requests.items():
                    if 'status_message_id' in request and request['status_message_id'] == event.message.id:
                        matching_slot = slot
                        break
                
                # Если нашли соответствующий слот для статусного сообщения
                if matching_slot:
                    if self.logger:
                        self.logger.log_app_event("STATUS_UPDATE", 
                                                f"Обновлен статус для промпта {self.active_requests[matching_slot]['prompt_id']} в слоте {matching_slot}")
                    
                    # Проверяем на наличие ошибки в обновленном статусе
                    if any(error_pattern in message_text.lower() for error_pattern in self.message_filter.error_patterns):
                        request = self.active_requests[matching_slot]
                        prompt_id = request['prompt_id']
                        
                        if self.logger:
                            self.logger.log_app_event("VIDEO_ERROR_IN_STATUS", 
                                                    f"Обнаружена ошибка в статусном сообщении для промпта {prompt_id} в слоте {matching_slot}",
                                                    "ERROR", 
                                                    {"error_text": message_text[:200]})
                        
                        # Отмечаем промпт как завершившийся с ошибкой
                        self.table_manager.mark_error(request['prompt_id'], request['model'], message_text[:100])
                        print(f"❌ Промпт {prompt_id} помечен как завершившийся с ошибкой (из статусного сообщения)")
                        
                        # Уменьшаем счетчик использования модели
                        self.decrease_model_counter(request['model'])
                        
                        # Устанавливаем событие
                        request['event'].set()
                        return
                
                # Используем новый метод для проверки, нужно ли обрабатывать отредактированное сообщение
                if not self.message_filter.should_process_edited_message(message_text, has_video):
                    # Добавляем логирование игнорируемых сообщений
                    if self.logger and message_text:
                        self.logger.log_app_event("IGNORED_EDIT", 
                                               f"Игнорируется отредактированное сообщение: {message_text[:30]}...", 
                                               "DEBUG")
                    return

                # Продолжаем только если сообщение нужно обрабатывать
                if self.logger:
                    self.logger.log_incoming(f"[EDIT] {message_text}", "Bot", has_video, 
                                          "VIDEO" if has_video else None)
                
                # Проверяем наличие ошибки в отредактированном сообщении
                if any(error_pattern in message_text.lower() for error_pattern in self.message_filter.error_patterns):
                    # Пытаемся определить слот по реплаю или содержимому
                    slot = self.find_slot_by_reply(event.message) or self.find_slot_by_last_prompt(message_text)
                    
                    if slot:
                        # Если нашли слот, отмечаем ошибку для этого промпта
                        request = self.active_requests[slot]
                        prompt_id = request['prompt_id']
                        
                        if self.logger:
                            self.logger.log_app_event("VIDEO_ERROR", 
                                                    f"Обнаружена ошибка генерации в отредактированном сообщении для промпта {prompt_id} в слоте {slot}",
                                                    "ERROR", 
                                                    {"error_text": message_text[:200]})
                        
                        # Отмечаем промпт как завершившийся с ошибкой
                        self.table_manager.mark_error(request['prompt_id'], request['model'], message_text[:100])
                        print(f"❌ Промпт {prompt_id} помечен как завершившийся с ошибкой (в отредактированном сообщении)")
                        
                        # Уменьшаем счетчик использования модели
                        self.decrease_model_counter(request['model'])
                        
                        # Устанавливаем событие, чтобы разблокировать ожидающий поток
                        request['event'].set()
                        return
                    else:
                        # Если не смогли определить слот, ищем по контексту сообщения
                        for active_slot, request in self.active_requests.items():
                            prompt_preview = request['prompt'][:30].lower()
                            if prompt_preview in message_text.lower():
                                prompt_id = request['prompt_id']
                                
                                if self.logger:
                                    self.logger.log_app_event("VIDEO_ERROR_MATCHED", 
                                                           f"Сопоставлена ошибка для промпта {prompt_id} в слоте {active_slot}",
                                                           "ERROR", 
                                                           {"error_text": message_text[:200]})
                                
                                # Отмечаем промпт как завершившийся с ошибкой
                                self.table_manager.mark_error(request['prompt_id'], request['model'], message_text[:100])
                                print(f"❌ Промпт {prompt_id} помечен как завершившийся с ошибкой (по содержимому)")
                                
                                # Уменьшаем счетчик использования модели
                                self.decrease_model_counter(request['model'])
                                
                                # Устанавливаем событие
                                request['event'].set()
                                return
                
                # Проверяем, содержит ли сообщение промпт
                if "📍 Ваш запрос:" in message_text or "📍 Запрос:" in message_text:
                    try:
                        prompt_match = re.search(r'(?:📍 Ваш запрос:|📍 Запрос:)\s*(.+)', message_text)
                        if prompt_match:
                            self.received_video_prompt = prompt_match.group(1).strip()
                            
                            # Пытаемся найти слот по тексту промпта
                            slot = self.find_slot_by_last_prompt(self.received_video_prompt)
                            if slot and self.logger:
                                self.logger.log_app_event("PROMPT_MATCHED", 
                                                       f"Найден слот {slot} для промпта: {self.received_video_prompt[:30]}...")
                    except Exception as e:
                        if self.logger:
                            self.logger.log_exception(e, context="При обработке промпта из отредактированного сообщения")
                
                # Обрабатываем видео, если оно есть в сообщении
                if has_video:
                    # Здесь код для обработки видео в отредактированном сообщении
                    # Пытаемся найти слот по видео
                    slot = None
                    if self.received_video_prompt:
                        slot = self.find_slot_by_last_prompt(self.received_video_prompt)
                    
                    if slot:
                        # Обрабатываем видео для найденного слота
                        request = self.active_requests[slot]
                        video_path = await self.download_video(event.message)
                        
                        if video_path:
                            # Проверяем соответствие видео промпту
                            if self.check_video_matches_prompt(video_path, request['prompt']):
                                # Обновляем статус и уведомляем ожидающий поток
                                self.table_manager.mark_success(request['prompt_id'], request['model'])
                                request['event'].set()
                            else:
                                # Видео не соответствует промпту
                                if self.logger:
                                    self.logger.log_app_event("VIDEO_MISMATCH",
                                                           f"Видео не соответствует промпту для слота {slot}")
                                self.table_manager.mark_error(request['prompt_id'], request['model'])
                                request['event'].set()

            except Exception as e:
                if self.logger:
                    self.logger.log_exception(e, context="При обработке отредактированного сообщения")

    def find_slot_by_reply(self, message):
        """Находит слот по реплаю на сообщение"""
        if message.reply_to is None:
            return None
        
        # Получаем ID сообщения, на которое отвечают
        reply_to_msg_id = message.reply_to.reply_to_msg_id
        
        # Проверяем все активные запросы
        for slot, request in self.active_requests.items():
            if 'sent_message_id' in request and request['sent_message_id'] == reply_to_msg_id:
                return slot
            
        return None

    def find_slot_by_last_prompt(self, message_text):
        """Находит слот по последнему промпту в сообщении"""
        # Проверяем новый формат с маркдауном (жирный текст и обратные кавычки)
        prompt_match = re.search(r'\*\*📍 (?:Ваш )?запрос:\*\* `([^`]+)`', message_text, re.IGNORECASE | re.DOTALL)
        
        # Если не нашли по новому формату, пробуем старый формат
        if not prompt_match:
            prompt_match = re.search(r'📍 (?:Ваш )?запрос:\s*(.+)', message_text, re.IGNORECASE | re.DOTALL)
            
        if prompt_match:
            prompt_text = prompt_match.group(1).strip()
            print(f"Извлечен текст промпта из сообщения: {prompt_text[:50]}...")
            
            # Ищем соответствующий слот
            for slot, request in self.active_requests.items():
                print(f"Сравниваем с промптом в слоте {slot}: {request['prompt'][:50]}...")
                if request['prompt'].startswith(prompt_text[:30]) or prompt_text.startswith(request['prompt'][:30]):
                    print(f"Найдено соответствие промпта в слоте {slot}!")
                    return slot
                
                # Добавляем более гибкое сравнение с использованием частичного совпадения
                similarity_threshold = 0.7  # Порог сходства (можно настроить)
                prompt_words = set(request['prompt'].lower().split()[:20])  # Берем первые 20 слов
                text_words = set(prompt_text.lower().split()[:20])
                
                common_words = prompt_words.intersection(text_words)
                if len(common_words) >= min(len(prompt_words), len(text_words)) * similarity_threshold:
                    print(f"Найдено частичное соответствие промпта в слоте {slot}!")
                    return slot
            
        return None

    async def wait_for_any_video(self):
        """Ожидает получение любого видео для очистки слотов"""
        video_received = asyncio.Event()
        
        @self.client.on(events.NewMessage(chats=self.bot))
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
        """Очищает активные слоты из прошлой сессии"""
        try:
            print("Очистка активных слотов из прошлой сессии...")
            
            # Получаем активные промпты
            if self.table_manager:
                active_prompts = self.table_manager.get_active_prompts()
                if active_prompts:
                    for prompt in active_prompts:
                        prompt_id = prompt.get('id')
                        slot = prompt.get('slot')
                        if prompt_id and slot:
                            print(f"Обнаружен активный слот {slot} для промпта {prompt_id} из прошлой сессии")
                            if self.logger:
                                self.logger.log_app_event("CLEANUP", 
                                                        f"Очистка слота {slot} (промпт {prompt_id}) из прошлой сессии")
                            
                            self.table_manager.mark_error(prompt_id, "", "Прервано при перезапуске бота")
                            print(f"Слот {slot} очищен и промпт {prompt_id} помечен как завершенный с ошибкой")
            elif hasattr(self.video_downloader, 'table_manager'):
                # Если table_manager не был установлен напрямую, но есть в video_downloader
                table_manager = self.video_downloader.table_manager
                active_prompts = table_manager.get_active_prompts()
                if active_prompts:
                    for prompt in active_prompts:
                        prompt_id = prompt.get('id')
                        slot = prompt.get('slot')
                        if prompt_id and slot:
                            print(f"Обнаружен активный слот {slot} для промпта {prompt_id} из прошлой сессии")
                            if self.logger:
                                self.logger.log_app_event("CLEANUP", 
                                                        f"Очистка слота {slot} (промпт {prompt_id}) из прошлой сессии")
                            
                            table_manager.mark_error(prompt_id, "", "Прервано при перезапуске бота")
                            print(f"Слот {slot} очищен и промпт {prompt_id} помечен как завершенный с ошибкой")
            else:
                print("Внимание: table_manager не доступен, очистка активных слотов не выполнена")
                if self.logger:
                    self.logger.log_app_event("WARNING", 
                                            "table_manager не доступен, очистка активных слотов не выполнена",
                                            "WARNING")
                                            
            # Очищаем активные слоты
            self.active_requests = {}
            if self.logger:
                self.logger.log_app_event("CLEANUP_COMPLETE", "Очистка активных слотов завершена")
                
        except Exception as e:
            print(f"Ошибка при очистке активных слотов: {e}")
            if self.logger:
                self.logger.log_exception(e, context="При очистке активных слотов")

    def get_table_manager(self):
        """
        Безопасно получает доступ к table_manager
        
        Returns:
            TableManager или None, если недоступен
        """
        if hasattr(self, 'table_manager') and self.table_manager:
            return self.table_manager
        elif hasattr(self.video_downloader, 'table_manager'):
            return self.video_downloader.table_manager
        return None