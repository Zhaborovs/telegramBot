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
        
        # События для каждого слота
        self.generation_start_events = {}  # slot: event для отслеживания начала генерации
        
        # Добавляем детальные статусы
        self.slot_status = {}  # slot: {status, last_update_time, message_count}
        
        # Сообщения о генерации
        self.generation_start_messages = [
            "⚡ ULTRA ELITE",
            "Генерирую видео",
            "⏳ Генерация видео",
            "⚡ Задача ожидает выполнения",
            "⏳ Одну секунду"  # Добавляем сообщение "Одну секунду" как подтверждение начала генерации
        ]
        
        # Добавляем статусы для более детального отслеживания
        self.STATUS_IDLE = 'idle'  # Слот свободен
        self.STATUS_SENDING_PROMPT = 'sending_prompt'  # Отправка промпта
        self.STATUS_WAITING_CONFIRMATION = 'waiting_confirmation'  # Ожидание подтверждения
        self.STATUS_GENERATING = 'generating'  # Идет генерация
        self.STATUS_WAITING_VIDEO = 'waiting_video'  # Ожидание видео
        self.STATUS_ERROR = 'error'  # Ошибка
        self.STATUS_LIMIT_REACHED = 'limit_reached'  # Достигнут лимит
        
        # Сообщения о лимите
        self.limit_messages = [
            "Максимальное количество одновременных генераций",
            "ULTRA ELITE: 1 (временно/temporary)"
        ]
        
        # Сообщения об ошибках
        self.error_messages = [
            "Ошибка генерации",
            "Error",
            "Failed"
        ]

    def set_current_task(self, prompt_id, prompt, model, slot):
        """Устанавливает текущую задачу для слота"""
        if slot is None:
            print("Ошибка: не указан слот для задачи")
            return False
            
        # Создаем событие для отслеживания начала генерации
        if slot not in self.generation_start_events:
            self.generation_start_events[slot] = asyncio.Event()
            
        # Инициализируем статус слота, если его еще нет
        if slot not in self.slot_status:
            self.slot_status[slot] = {
                'status': self.STATUS_IDLE,
                'last_update_time': datetime.now(),
                'message_count': 0,
                'last_status_message': 'Инициализация'
            }
            
        # Обновляем статус слота
        self.slot_status[slot].update({
            'status': self.STATUS_SENDING_PROMPT,
            'last_update_time': datetime.now(),
            'last_status_message': f'Отправка промпта {prompt_id}'
        })
        
        # Сохраняем информацию о текущем запросе
        self.active_requests[slot] = {
            'prompt_id': prompt_id,
            'prompt': prompt,
            'model': model,
            'start_time': datetime.now(),
            'event': asyncio.Event(),
            'video_received': False,
            'generation_started': False,
            'limit_detected': False,
            'error_detected': False,
            'status_changes': [],  # История изменений статуса
            'attempt_count': 0     # Счетчик попыток
        }
        
        # Добавляем первую запись в историю изменений
        self.active_requests[slot]['status_changes'].append({
            'time': datetime.now(), 
            'status': self.STATUS_SENDING_PROMPT
        })
        
        print(f"Ожидается обработка промпта {prompt_id} в слоте {slot}")
        return True

    async def wait_for_video(self, slot):
        """Ожидает получение видео для конкретного слота"""
        if slot not in self.active_requests:
            return False

        request = self.active_requests[slot]
        try:
            # Обновляем статус
            current_time = datetime.now()
            if slot in self.slot_status:
                self.slot_status[slot].update({
                    'status': self.STATUS_WAITING_VIDEO,
                    'last_update_time': current_time,
                    'last_status_message': f'Ожидание видео для промпта {request["prompt_id"]}'
                })
                
            # Обновляем историю изменений
            request['status_changes'].append({
                'time': current_time, 
                'status': self.STATUS_WAITING_VIDEO
            })
            
            # Ждем получения видео
            await asyncio.wait_for(request['event'].wait(), timeout=self.wait_time)
            return True
        except asyncio.TimeoutError:
            print(f"Таймаут ожидания видео в слоте {slot}")
            self.table_manager.mark_timeout(request['prompt_id'])
            
            # Обновляем статус при таймауте
            if slot in self.slot_status:
                self.slot_status[slot].update({
                    'status': self.STATUS_ERROR,
                    'last_update_time': datetime.now(),
                    'last_status_message': f'Таймаут ожидания видео для промпта {request["prompt_id"]}'
                })
            
            return False
        finally:
            # Очищаем слот
            if slot in self.active_requests:
                del self.active_requests[slot]
                
            # Сбрасываем статус слота
            if slot in self.slot_status:
                self.slot_status[slot].update({
                    'status': self.STATUS_IDLE,
                    'last_update_time': datetime.now(),
                    'last_status_message': 'Слот освобожден'
                })

    async def wait_for_slot_release(self):
        """Ожидает освобождения слота при достижении лимита"""
        print("\nОжидаем освобождения слота...")
        self.waiting_for_slot = True
        self.slot_freed.clear()  # Сбрасываем событие перед ожиданием
        
        try:
            await asyncio.wait_for(self.slot_freed.wait(), timeout=self.wait_time)
            print("Слот освободился")
            self.waiting_for_slot = False
            return True
        except asyncio.TimeoutError:
            print("Таймаут ожидания освобождения слота")
            self.waiting_for_slot = False
            return False

    async def start_monitoring(self):
        @self.client.on(events.NewMessage(from_users=self.bot))
        async def handler(event):
            message_text = event.message.text or ''
            
            # Логируем все сообщения с тайм-штампом
            timestamp = datetime.now().strftime('%H:%M:%S')
            log_message = f"[{timestamp}] Сообщение от бота: {message_text[:100]}" + ("..." if len(message_text) > 100 else "")
            print(log_message)
            
            # Записываем сообщение в лог
            has_video = bool(event.message.media and 
                           hasattr(event.message.media, 'document') and 
                           event.message.media.document.mime_type.startswith('video/'))
            self.message_logger.log_message(message_text, has_video)
            
            # Проверяем сообщение о готовности модели принять промпт
            model_ready_patterns = [
                r'отправьте.*текстовое задание',
                r'загрузите изображение',
                r'введите запрос',
                r'тариф:.*0\.00'
            ]
            
            is_model_ready = any(re.search(pattern, message_text.lower()) for pattern in model_ready_patterns)
            if is_model_ready:
                print("Обнаружено сообщение о готовности модели принять промпт")
                # Это информационное сообщение, не требующее действий
                # Просто обновляем статусы слотов
                self.print_slot_statuses()
                return

            # Проверяем сообщение о лимите
            if any(msg in message_text for msg in self.limit_messages):
                print("Обнаружено сообщение о лимите запросов")
                # Возвращаем все активные промпты в очередь
                for slot, request in list(self.active_requests.items()):
                    if not request.get('limit_detected'):
                        print(f"Лимит запросов в слоте {slot}")
                        request['limit_detected'] = True
                        
                        # Обновляем статус слота
                        if slot in self.slot_status:
                            self.slot_status[slot].update({
                                'status': self.STATUS_LIMIT_REACHED,
                                'last_update_time': datetime.now(),
                                'last_status_message': f'Лимит запросов: {message_text[:50]}...'
                            })
                        
                        # Обновляем историю изменений
                        request['status_changes'].append({
                            'time': datetime.now(), 
                            'status': self.STATUS_LIMIT_REACHED
                        })
                        
                        # Обновляем статус промпта
                        self.table_manager.mark_limit_reached(request['prompt_id'], message_text)
                        
                        # Сигнализируем о лимите событиям
                        if slot in self.generation_start_events:
                            self.generation_start_events[slot].set()
                        request['event'].set()
                        
                        # Сообщаем об освобождении слота
                        if self.waiting_for_slot:
                            self.slot_freed.set()
                            
                # Печатаем статусы всех слотов после обнаружения лимита
                self.print_slot_statuses()
                return

            # Проверяем сообщения о начале генерации
            if any(msg in message_text for msg in self.generation_start_messages):
                print("Обнаружено сообщение о начале генерации видео")
                
                # Определяем, к какому слоту относится сообщение (на основе содержания)
                matched_slot = None
                matched_similarity = 0
                
                for slot, request in list(self.active_requests.items()):
                    # Используем более точное сопоставление промптов
                    similarity = self.prompt_matcher.calculate_similarity(request['prompt'], message_text)
                    
                    if similarity > 0.5 and similarity > matched_similarity:  # Порог сходства
                        matched_slot = slot
                        matched_similarity = similarity
                        
                # Если нашли подходящий слот
                if matched_slot:
                    slot = matched_slot
                    request = self.active_requests[slot]
                    
                    if not request.get('generation_started'):
                        print(f"Началась генерация видео в слоте {slot} (сходство: {matched_similarity:.2f})")
                        
                        # Обновляем статус слота
                        if slot in self.slot_status:
                            self.slot_status[slot].update({
                                'status': self.STATUS_GENERATING,
                                'last_update_time': datetime.now(),
                                'last_status_message': f'Генерация видео для промпта {request["prompt_id"]}'
                            })
                        
                        # Обновляем историю изменений
                        request['status_changes'].append({
                            'time': datetime.now(), 
                            'status': self.STATUS_GENERATING
                        })
                        
                        # Устанавливаем флаг и событие
                        request['generation_started'] = True
                        if slot in self.generation_start_events:
                            self.generation_start_events[slot].set()
                            
                    # Печатаем статусы всех слотов
                    self.print_slot_statuses()
                    return
                    
                # Если не смогли определить слот, но получили сообщение о начале генерации
                # возможно, оно относится к единственному активному запросу
                if len(self.active_requests) == 1:
                    slot, request = next(iter(self.active_requests.items()))
                    if not request.get('generation_started'):
                        print(f"Началась генерация видео в единственном активном слоте {slot}")
                        
                        # Обновляем статус слота
                        if slot in self.slot_status:
                            self.slot_status[slot].update({
                                'status': self.STATUS_GENERATING,
                                'last_update_time': datetime.now(),
                                'last_status_message': f'Генерация видео для промпта {request["prompt_id"]}'
                            })
                        
                        # Обновляем историю изменений
                        request['status_changes'].append({
                            'time': datetime.now(), 
                            'status': self.STATUS_GENERATING
                        })
                        
                        request['generation_started'] = True
                        if slot in self.generation_start_events:
                            self.generation_start_events[slot].set()
                
                self.generation_in_progress = True
                # Печатаем статусы всех слотов
                self.print_slot_statuses()
                return

            # Обрабатываем видео
            if has_video:
                print("Получено видео - слот должен освободиться")
                
                # Логируем параметры видео для отладки
                video_info = ""
                if hasattr(event.message.media, 'document'):
                    video_info = f"Размер: {event.message.media.document.size} байт, "
                    video_info += f"Название: {getattr(event.message.media.document, 'attributes', [])}"
                print(f"Информация о видео: {video_info}")
                
                if self.waiting_for_slot:
                    print("Сигнализируем об освобождении слота")
                    self.slot_freed.set()
                
                # Проверяем, к какому запросу относится видео
                matched_slot = None
                best_similarity = 0
                
                for slot, request in list(self.active_requests.items()):
                    # Пытаемся сопоставить видео с запросом
                    similarity = self.prompt_matcher.calculate_similarity(request['prompt'], message_text)
                    
                    if similarity > 0.4 and similarity > best_similarity:  # Порог сходства для видео
                        matched_slot = slot
                        best_similarity = similarity
                
                # Если нашли соответствующий слот
                if matched_slot:
                    slot = matched_slot
                    request = self.active_requests[slot]
                    print(f"Видео соответствует запросу в слоте {slot} (сходство: {best_similarity:.2f})")
                    
                    # Обновляем статус слота
                    if slot in self.slot_status:
                        self.slot_status[slot].update({
                            'status': self.STATUS_IDLE,
                            'last_update_time': datetime.now(),
                            'last_status_message': f'Получено видео для промпта {request["prompt_id"]}'
                        })
                    
                    success = await self.video_downloader.download_video(
                        event.message, 
                        request['prompt_id'],
                        request['model']
                    )
                    if success:
                        print(f"Видео успешно загружено для промпта {request['prompt_id']}")
                        request['event'].set()
                        # Печатаем статусы всех слотов
                        self.print_slot_statuses()
                        return
                
                # Если не смогли определить слот, но есть только один запрос
                elif len(self.active_requests) == 1:
                    slot, request = next(iter(self.active_requests.items()))
                    print(f"Предполагаем, что видео соответствует единственному активному запросу в слоте {slot}")
                    
                    # Обновляем статус слота
                    if slot in self.slot_status:
                        self.slot_status[slot].update({
                            'status': self.STATUS_IDLE,
                            'last_update_time': datetime.now(),
                            'last_status_message': f'Получено видео для промпта {request["prompt_id"]}'
                        })
                    
                    success = await self.video_downloader.download_video(
                        event.message, 
                        request['prompt_id'],
                        request['model']
                    )
                    if success:
                        print(f"Видео успешно загружено для промпта {request['prompt_id']}")
                        request['event'].set()
                        # Печатаем статусы всех слотов
                        self.print_slot_statuses()
                        return
                
                # Если не смогли определить, для какого запроса это видео
                print("Не удалось определить, к какому запросу относится видео")
                # Пытаемся загрузить видео с общим идентификатором
                success = await self.video_downloader.download_video(
                    event.message, 
                    f"unknown_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "unknown"
                )
                if success:
                    print("Видео загружено с общим идентификатором")
                
                # Печатаем статусы всех слотов
                self.print_slot_statuses()
                return

            # Проверяем сообщения об ошибках
            if any(msg in message_text for msg in self.error_messages):
                print("Обнаружено сообщение об ошибке")
                error_slot = None
                
                # Пытаемся определить, к какому запросу относится ошибка
                for slot, request in list(self.active_requests.items()):
                    # Используем эвристику для сопоставления
                    similarity = self.prompt_matcher.calculate_similarity(request['prompt'], message_text)
                    
                    if similarity > 0.3:  # Низкий порог для ошибок
                        error_slot = slot
                        break
                
                # Если определили слот
                if error_slot:
                    slot = error_slot
                    request = self.active_requests[slot]
                    print(f"Получена ошибка от бота для слота {slot}")
                    
                    # Обновляем статус слота
                    if slot in self.slot_status:
                        self.slot_status[slot].update({
                            'status': self.STATUS_ERROR,
                            'last_update_time': datetime.now(),
                            'last_status_message': f'Ошибка: {message_text[:50]}...'
                        })
                    
                    # Обновляем историю изменений
                    request['status_changes'].append({
                        'time': datetime.now(), 
                        'status': self.STATUS_ERROR
                    })
                    
                    self.table_manager.mark_error(request['prompt_id'], request['model'], message_text)
                    request['event'].set()
                    
                    # Если ожидаем освобождения слота
                    if self.waiting_for_slot:
                        self.slot_freed.set()
                        
                # Если не смогли определить, но есть только один активный запрос
                elif len(self.active_requests) == 1:
                    slot, request = next(iter(self.active_requests.items()))
                    print(f"Предполагаем, что ошибка относится к единственному активному запросу в слоте {slot}")
                    
                    # Обновляем статус слота
                    if slot in self.slot_status:
                        self.slot_status[slot].update({
                            'status': self.STATUS_ERROR,
                            'last_update_time': datetime.now(),
                            'last_status_message': f'Ошибка: {message_text[:50]}...'
                        })
                    
                    # Обновляем историю изменений
                    request['status_changes'].append({
                        'time': datetime.now(), 
                        'status': self.STATUS_ERROR
                    })
                    
                    self.table_manager.mark_error(request['prompt_id'], request['model'], message_text)
                    request['event'].set()
                    
                    # Если ожидаем освобождения слота
                    if self.waiting_for_slot:
                        self.slot_freed.set()
                
                # Печатаем статусы всех слотов
                self.print_slot_statuses()
                return

            # Печатаем статусы всех слотов после каждого сообщения
            self.print_slot_statuses()

        # Запускаем обработчик сообщений
        print("Мониторинг сообщений запущен")

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

    async def wait_for_generation_start(self, slot, timeout=30):
        """Ожидает сообщение о начале генерации видео"""
        if slot not in self.active_requests or slot not in self.generation_start_events:
            return False
        
        # Обновляем статус
        if slot in self.slot_status:
            self.slot_status[slot].update({
                'status': self.STATUS_WAITING_CONFIRMATION,
                'last_update_time': datetime.now(),
                'last_status_message': f'Ожидание подтверждения начала генерации'
            })
        
        # Обновляем историю изменений
        request = self.active_requests[slot]
        request['status_changes'].append({
            'time': datetime.now(), 
            'status': self.STATUS_WAITING_CONFIRMATION
        })
        
        # Проверяем, не было ли уже получено подтверждение
        if request.get('generation_started', False):
            print(f"Генерация уже была подтверждена ранее для слота {slot}")
            return True
        
        try:
            # Сбрасываем событие перед ожиданием
            self.generation_start_events[slot].clear()
            
            # Ждем сообщение о начале генерации
            print(f"Ожидаем подтверждения генерации в течение {timeout} секунд...")
            await asyncio.wait_for(self.generation_start_events[slot].wait(), timeout=timeout)
            
            # Если дождались, обновляем статус
            if slot in self.active_requests:
                request = self.active_requests[slot]
                self.table_manager.mark_generation_started(request['prompt_id'], request['model'])
                request['generation_started'] = True
                
                # Обновляем историю изменений
                request['status_changes'].append({
                    'time': datetime.now(), 
                    'status': self.STATUS_GENERATING
                })
                
                # Обновляем статус слота
                if slot in self.slot_status:
                    self.slot_status[slot].update({
                        'status': self.STATUS_GENERATING,
                        'last_update_time': datetime.now(),
                        'last_status_message': f'Генерация видео для промпта {request["prompt_id"]}'
                    })
                
                return True
        except asyncio.TimeoutError:
            # Проверяем наличие лимита
            if slot in self.active_requests and self.active_requests[slot].get('limit_detected', False):
                # Обновляем статус слота
                if slot in self.slot_status:
                    self.slot_status[slot].update({
                        'status': self.STATUS_LIMIT_REACHED,
                        'last_update_time': datetime.now(),
                        'last_status_message': f'Достигнут лимит запросов'
                    })
                return False
                
            print(f"Таймаут ожидания начала генерации в слоте {slot}")
            
            # Проверяем, не появилось ли видео, несмотря на отсутствие подтверждения
            # Это может произойти, если сообщение о начале генерации было пропущено
            if slot in self.active_requests:
                # Обновляем статус слота на "ожидание видео" вместо ошибки
                if slot in self.slot_status:
                    self.slot_status[slot].update({
                        'status': self.STATUS_WAITING_VIDEO,
                        'last_update_time': datetime.now(),
                        'last_status_message': f'Ожидание видео без подтверждения генерации'
                    })
                
                # Обновляем историю изменений
                request = self.active_requests[slot]
                request['status_changes'].append({
                    'time': datetime.now(), 
                    'status': self.STATUS_WAITING_VIDEO
                })
                
                print(f"Переходим к ожиданию видео без подтверждения генерации для слота {slot}")
                return False
            
            # Обновляем статус слота
            if slot in self.slot_status:
                self.slot_status[slot].update({
                    'status': self.STATUS_ERROR,
                    'last_update_time': datetime.now(),
                    'last_status_message': f'Таймаут ожидания подтверждения'
                })
            
            return False
    
    def check_limit_detected(self, slot):
        """Проверяет, был ли обнаружен лимит запросов для слота"""
        return slot in self.active_requests and self.active_requests[slot].get('limit_detected', False)
        
    def get_slot_status(self, slot):
        """Возвращает текущий статус слота"""
        if slot in self.slot_status:
            return self.slot_status[slot]
        return None

    def print_slot_statuses(self):
        """Выводит статусы всех слотов"""
        print("\nСтатусы слотов:")
        for slot, status in self.slot_status.items():
            status_message = f"Слот {slot}: {status['status']} - {status['last_status_message']} " \
                            f"(обновлен {status['last_update_time'].strftime('%H:%M:%S')})"
            print(status_message)
            # Логируем статус слота
            self.message_logger.log_slot_status(slot, status['status'], status['last_status_message'])

    async def start_monitoring(self):
        @self.client.on(events.NewMessage(from_users=self.bot))
        async def handler(event):
            message_text = event.message.text or ''
            
            # Логируем все сообщения с тайм-штампом
            timestamp = datetime.now().strftime('%H:%M:%S')
            log_message = f"[{timestamp}] Сообщение от бота: {message_text[:100]}" + ("..." if len(message_text) > 100 else "")
            print(log_message)
            
            # Записываем сообщение в лог
            has_video = bool(event.message.media and 
                           hasattr(event.message.media, 'document') and 
                           event.message.media.document.mime_type.startswith('video/'))
            self.message_logger.log_message(message_text, has_video)
            
            # Проверяем сообщение о готовности модели принять промпт
            model_ready_patterns = [
                r'отправьте.*текстовое задание',
                r'загрузите изображение',
                r'введите запрос',
                r'тариф:.*0\.00'
            ]
            
            is_model_ready = any(re.search(pattern, message_text.lower()) for pattern in model_ready_patterns)
            if is_model_ready:
                print("Обнаружено сообщение о готовности модели принять промпт")
                # Это информационное сообщение, не требующее действий
                # Просто обновляем статусы слотов
                self.print_slot_statuses()
                return

            # Проверяем сообщение о лимите
            if any(msg in message_text for msg in self.limit_messages):
                print("Обнаружено сообщение о лимите запросов")
                # Возвращаем все активные промпты в очередь
                for slot, request in list(self.active_requests.items()):
                    if not request.get('limit_detected'):
                        print(f"Лимит запросов в слоте {slot}")
                        request['limit_detected'] = True
                        
                        # Обновляем статус слота
                        if slot in self.slot_status:
                            self.slot_status[slot].update({
                                'status': self.STATUS_LIMIT_REACHED,
                                'last_update_time': datetime.now(),
                                'last_status_message': f'Лимит запросов: {message_text[:50]}...'
                            })
                        
                        # Обновляем историю изменений
                        request['status_changes'].append({
                            'time': datetime.now(), 
                            'status': self.STATUS_LIMIT_REACHED
                        })
                        
                        # Обновляем статус промпта
                        self.table_manager.mark_limit_reached(request['prompt_id'], message_text)
                        
                        # Сигнализируем о лимите событиям
                        if slot in self.generation_start_events:
                            self.generation_start_events[slot].set()
                        request['event'].set()
                        
                        # Сообщаем об освобождении слота
                        if self.waiting_for_slot:
                            self.slot_freed.set()
                            
                # Печатаем статусы всех слотов после обнаружения лимита
                self.print_slot_statuses()
                return

            # Проверяем сообщения о начале генерации
            if any(msg in message_text for msg in self.generation_start_messages):
                print("Обнаружено сообщение о начале генерации видео")
                
                # Определяем, к какому слоту относится сообщение (на основе содержания)
                matched_slot = None
                matched_similarity = 0
                
                for slot, request in list(self.active_requests.items()):
                    # Используем более точное сопоставление промптов
                    similarity = self.prompt_matcher.calculate_similarity(request['prompt'], message_text)
                    
                    if similarity > 0.5 and similarity > matched_similarity:  # Порог сходства
                        matched_slot = slot
                        matched_similarity = similarity
                        
                # Если нашли подходящий слот
                if matched_slot:
                    slot = matched_slot
                    request = self.active_requests[slot]
                    
                    if not request.get('generation_started'):
                        print(f"Началась генерация видео в слоте {slot} (сходство: {matched_similarity:.2f})")
                        
                        # Обновляем статус слота
                        if slot in self.slot_status:
                            self.slot_status[slot].update({
                                'status': self.STATUS_GENERATING,
                                'last_update_time': datetime.now(),
                                'last_status_message': f'Генерация видео для промпта {request["prompt_id"]}'
                            })
                        
                        # Обновляем историю изменений
                        request['status_changes'].append({
                            'time': datetime.now(), 
                            'status': self.STATUS_GENERATING
                        })
                        
                        # Устанавливаем флаг и событие
                        request['generation_started'] = True
                        if slot in self.generation_start_events:
                            self.generation_start_events[slot].set()
                            
                    # Печатаем статусы всех слотов
                    self.print_slot_statuses()
                    return
                    
                # Если не смогли определить слот, но получили сообщение о начале генерации
                # возможно, оно относится к единственному активному запросу
                if len(self.active_requests) == 1:
                    slot, request = next(iter(self.active_requests.items()))
                    if not request.get('generation_started'):
                        print(f"Началась генерация видео в единственном активном слоте {slot}")
                        
                        # Обновляем статус слота
                        if slot in self.slot_status:
                            self.slot_status[slot].update({
                                'status': self.STATUS_GENERATING,
                                'last_update_time': datetime.now(),
                                'last_status_message': f'Генерация видео для промпта {request["prompt_id"]}'
                            })
                        
                        # Обновляем историю изменений
                        request['status_changes'].append({
                            'time': datetime.now(), 
                            'status': self.STATUS_GENERATING
                        })
                        
                        request['generation_started'] = True
                        if slot in self.generation_start_events:
                            self.generation_start_events[slot].set()
                
                self.generation_in_progress = True
                # Печатаем статусы всех слотов
                self.print_slot_statuses()
                return

            # Обрабатываем видео
            if has_video:
                print("Получено видео - слот должен освободиться")
                
                # Логируем параметры видео для отладки
                video_info = ""
                if hasattr(event.message.media, 'document'):
                    video_info = f"Размер: {event.message.media.document.size} байт, "
                    video_info += f"Название: {getattr(event.message.media.document, 'attributes', [])}"
                print(f"Информация о видео: {video_info}")
                
                if self.waiting_for_slot:
                    print("Сигнализируем об освобождении слота")
                    self.slot_freed.set()
                
                # Проверяем, к какому запросу относится видео
                matched_slot = None
                best_similarity = 0
                
                for slot, request in list(self.active_requests.items()):
                    # Пытаемся сопоставить видео с запросом
                    similarity = self.prompt_matcher.calculate_similarity(request['prompt'], message_text)
                    
                    if similarity > 0.4 and similarity > best_similarity:  # Порог сходства для видео
                        matched_slot = slot
                        best_similarity = similarity
                
                # Если нашли соответствующий слот
                if matched_slot:
                    slot = matched_slot
                    request = self.active_requests[slot]
                    print(f"Видео соответствует запросу в слоте {slot} (сходство: {best_similarity:.2f})")
                    
                    # Обновляем статус слота
                    if slot in self.slot_status:
                        self.slot_status[slot].update({
                            'status': self.STATUS_IDLE,
                            'last_update_time': datetime.now(),
                            'last_status_message': f'Получено видео для промпта {request["prompt_id"]}'
                        })
                    
                    success = await self.video_downloader.download_video(
                        event.message, 
                        request['prompt_id'],
                        request['model']
                    )
                    if success:
                        print(f"Видео успешно загружено для промпта {request['prompt_id']}")
                        request['event'].set()
                        # Печатаем статусы всех слотов
                        self.print_slot_statuses()
                        return
                
                # Если не смогли определить слот, но есть только один запрос
                elif len(self.active_requests) == 1:
                    slot, request = next(iter(self.active_requests.items()))
                    print(f"Предполагаем, что видео соответствует единственному активному запросу в слоте {slot}")
                    
                    # Обновляем статус слота
                    if slot in self.slot_status:
                        self.slot_status[slot].update({
                            'status': self.STATUS_IDLE,
                            'last_update_time': datetime.now(),
                            'last_status_message': f'Получено видео для промпта {request["prompt_id"]}'
                        })
                    
                    success = await self.video_downloader.download_video(
                        event.message, 
                        request['prompt_id'],
                        request['model']
                    )
                    if success:
                        print(f"Видео успешно загружено для промпта {request['prompt_id']}")
                        request['event'].set()
                        # Печатаем статусы всех слотов
                        self.print_slot_statuses()
                        return
                
                # Если не смогли определить, для какого запроса это видео
                print("Не удалось определить, к какому запросу относится видео")
                # Пытаемся загрузить видео с общим идентификатором
                success = await self.video_downloader.download_video(
                    event.message, 
                    f"unknown_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "unknown"
                )
                if success:
                    print("Видео загружено с общим идентификатором")
                
                # Печатаем статусы всех слотов
                self.print_slot_statuses()
                return

            # Проверяем сообщения об ошибках
            if any(msg in message_text for msg in self.error_messages):
                print("Обнаружено сообщение об ошибке")
                error_slot = None
                
                # Пытаемся определить, к какому запросу относится ошибка
                for slot, request in list(self.active_requests.items()):
                    # Используем эвристику для сопоставления
                    similarity = self.prompt_matcher.calculate_similarity(request['prompt'], message_text)
                    
                    if similarity > 0.3:  # Низкий порог для ошибок
                        error_slot = slot
                        break
                
                # Если определили слот
                if error_slot:
                    slot = error_slot
                    request = self.active_requests[slot]
                    print(f"Получена ошибка от бота для слота {slot}")
                    
                    # Обновляем статус слота
                    if slot in self.slot_status:
                        self.slot_status[slot].update({
                            'status': self.STATUS_ERROR,
                            'last_update_time': datetime.now(),
                            'last_status_message': f'Ошибка: {message_text[:50]}...'
                        })
                    
                    # Обновляем историю изменений
                    request['status_changes'].append({
                        'time': datetime.now(), 
                        'status': self.STATUS_ERROR
                    })
                    
                    self.table_manager.mark_error(request['prompt_id'], request['model'], message_text)
                    request['event'].set()
                    
                    # Если ожидаем освобождения слота
                    if self.waiting_for_slot:
                        self.slot_freed.set()
                        
                # Если не смогли определить, но есть только один активный запрос
                elif len(self.active_requests) == 1:
                    slot, request = next(iter(self.active_requests.items()))
                    print(f"Предполагаем, что ошибка относится к единственному активному запросу в слоте {slot}")
                    
                    # Обновляем статус слота
                    if slot in self.slot_status:
                        self.slot_status[slot].update({
                            'status': self.STATUS_ERROR,
                            'last_update_time': datetime.now(),
                            'last_status_message': f'Ошибка: {message_text[:50]}...'
                        })
                    
                    # Обновляем историю изменений
                    request['status_changes'].append({
                        'time': datetime.now(), 
                        'status': self.STATUS_ERROR
                    })
                    
                    self.table_manager.mark_error(request['prompt_id'], request['model'], message_text)
                    request['event'].set()
                    
                    # Если ожидаем освобождения слота
                    if self.waiting_for_slot:
                        self.slot_freed.set()
                
                # Печатаем статусы всех слотов
                self.print_slot_statuses()
                return

            # Печатаем статусы всех слотов после каждого сообщения
            self.print_slot_statuses()

        # Запускаем обработчик сообщений
        print("Мониторинг сообщений запущен")

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

    async def wait_for_generation_start(self, slot, timeout=30):
        """Ожидает сообщение о начале генерации видео"""
        if slot not in self.active_requests or slot not in self.generation_start_events:
            return False
        
        # Обновляем статус
        if slot in self.slot_status:
            self.slot_status[slot].update({
                'status': self.STATUS_WAITING_CONFIRMATION,
                'last_update_time': datetime.now(),
                'last_status_message': f'Ожидание подтверждения начала генерации'
            })
        
        # Обновляем историю изменений
        request = self.active_requests[slot]
        request['status_changes'].append({
            'time': datetime.now(), 
            'status': self.STATUS_WAITING_CONFIRMATION
        })
        
        # Проверяем, не было ли уже получено подтверждение
        if request.get('generation_started', False):
            print(f"Генерация уже была подтверждена ранее для слота {slot}")
            return True
        
        try:
            # Сбрасываем событие перед ожиданием
            self.generation_start_events[slot].clear()
            
            # Ждем сообщение о начале генерации
            print(f"Ожидаем подтверждения генерации в течение {timeout} секунд...")
            await asyncio.wait_for(self.generation_start_events[slot].wait(), timeout=timeout)
            
            # Если дождались, обновляем статус
            if slot in self.active_requests:
                request = self.active_requests[slot]
                self.table_manager.mark_generation_started(request['prompt_id'], request['model'])
                request['generation_started'] = True
                
                # Обновляем историю изменений
                request['status_changes'].append({
                    'time': datetime.now(), 
                    'status': self.STATUS_GENERATING
                })
                
                # Обновляем статус слота
                if slot in self.slot_status:
                    self.slot_status[slot].update({
                        'status': self.STATUS_GENERATING,
                        'last_update_time': datetime.now(),
                        'last_status_message': f'Генерация видео для промпта {request["prompt_id"]}'
                    })
                
                return True
        except asyncio.TimeoutError:
            # Проверяем наличие лимита
            if slot in self.active_requests and self.active_requests[slot].get('limit_detected', False):
                # Обновляем статус слота
                if slot in self.slot_status:
                    self.slot_status[slot].update({
                        'status': self.STATUS_LIMIT_REACHED,
                        'last_update_time': datetime.now(),
                        'last_status_message': f'Достигнут лимит запросов'
                    })
                return False
                
            print(f"Таймаут ожидания начала генерации в слоте {slot}")
            
            # Проверяем, не появилось ли видео, несмотря на отсутствие подтверждения
            # Это может произойти, если сообщение о начале генерации было пропущено
            if slot in self.active_requests:
                # Обновляем статус слота на "ожидание видео" вместо ошибки
                if slot in self.slot_status:
                    self.slot_status[slot].update({
                        'status': self.STATUS_WAITING_VIDEO,
                        'last_update_time': datetime.now(),
                        'last_status_message': f'Ожидание видео без подтверждения генерации'
                    })
                
                # Обновляем историю изменений
                request = self.active_requests[slot]
                request['status_changes'].append({
                    'time': datetime.now(), 
                    'status': self.STATUS_WAITING_VIDEO
                })
                
                print(f"Переходим к ожиданию видео без подтверждения генерации для слота {slot}")
                return False
            
            # Обновляем статус слота
            if slot in self.slot_status:
                self.slot_status[slot].update({
                    'status': self.STATUS_ERROR,
                    'last_update_time': datetime.now(),
                    'last_status_message': f'Таймаут ожидания подтверждения'
                })
            
            return False
    
    def check_limit_detected(self, slot):
        """Проверяет, был ли обнаружен лимит запросов для слота"""
        return slot in self.active_requests and self.active_requests[slot].get('limit_detected', False)
        
    def get_slot_status(self, slot):
        """Возвращает текущий статус слота"""
        if slot in self.slot_status:
            return self.slot_status[slot]
        return None

    def print_slot_statuses(self):
        """Выводит статусы всех слотов"""
        print("\nСтатусы слотов:")
        for slot, status in self.slot_status.items():
            status_message = f"Слот {slot}: {status['status']} - {status['last_status_message']} " \
                            f"(обновлен {status['last_update_time'].strftime('%H:%M:%S')})"
            print(status_message)
            # Логируем статус слота
            self.message_logger.log_slot_status(slot, status['status'], status['last_status_message']) 