import asyncio
import re
from datetime import datetime
from telethon import events

class TelegramNavigator:
    def __init__(self, client, bot, config, message_monitor):
        self.client = client
        self.bot = bot
        self.config = config
        self.message_monitor = message_monitor
        self.models = {
            '1': '🌙 SORA',
            '2': '➕ Hailuo MiniMax',
            '3': '📦 RunWay: Gen-3',
            '4': '🎬 Kling 1.6',
            '5': '🎯 Pika 2.0',
            '6': '👁 Act-One (Аватары 2.0)',
            '7': '🌫 Luma: DM',
            '8': '🦋 RW: Стилизатор'
        }
        self.wait_timeout = int(config.get('command_timeout', '30'))  # Ожидание реакции на команду
        self.retry_count = int(config.get('retry_count', '2'))  # Количество попыток при отправке промпта
        self.extended_wait_time = int(config.get('extended_wait_time', '60'))  # Увеличенное время ожидания
        
        # Добавляем шаблоны для проверки ответов бота
        self.model_ready_patterns = [
            r'отправьте.*текстовое задание',
            r'загрузите изображение',
            r'введите запрос',
            r'тариф:.*0\.00'
        ]

    async def wait_for_model_ready(self, timeout=10):
        """Ожидает сообщение от бота о готовности принять промпт"""
        ready_event = asyncio.Event()
        
        @self.client.on(events.NewMessage(from_users=self.bot))
        async def temp_handler(event):
            message_text = event.message.text or ''
            for pattern in self.model_ready_patterns:
                if re.search(pattern, message_text.lower()):
                    print(f"Обнаружено сообщение о готовности: '{message_text[:50]}...'")
                    ready_event.set()
                    # Удаляем временный обработчик
                    self.client.remove_event_handler(temp_handler)
                    return
        
        try:
            print(f"Ожидаем готовности модели принять промпт (таймаут {timeout} сек)...")
            await asyncio.wait_for(ready_event.wait(), timeout=timeout)
            print("Модель готова принять промпт")
            return True
        except asyncio.TimeoutError:
            print("Таймаут ожидания готовности модели")
            # Удаляем временный обработчик в случае таймаута
            self.client.remove_event_handler(temp_handler)
            return False
        except Exception as e:
            print(f"Ошибка при ожидании готовности модели: {str(e)}")
            import traceback
            print(f"Подробная информация об ошибке:\n{traceback.format_exc()}")
            # Удаляем временный обработчик в случае ошибки
            self.client.remove_event_handler(temp_handler)
            return False

    async def navigate_and_send_prompt(self, prompt_data, slot=None):
        """
        Отправляет промпт и ожидает ответа
        prompt_data: словарь с данными промпта
        slot: номер слота для параллельной обработки
        """
        try:
            print(f"\n=== Отправка промпта в слоте {slot} ===")
            
            model_number = self.config.get('model_number', '1')
            model = self.models.get(model_number, self.models['1'])
            
            # Устанавливаем текущий запрос в мониторе для конкретного слота
            if not self.message_monitor.set_current_task(prompt_data['id'], prompt_data['prompt'], model, slot):
                print(f"Не удалось установить задачу для слота {slot}")
                return False
            
            # Отправляем команду /video и ждем ответа
            print("Отправляем команду /video...")
            await self.client.send_message(self.bot, '/video')
            await asyncio.sleep(2.0)  # Увеличиваем паузу для получения ответа
            
            # Отправляем выбор модели и ждем ответа
            print(f"Выбираем модель: {model}...")
            await self.client.send_message(self.bot, model)
            
            # Ждем, пока бот будет готов принять промпт
            model_ready = await self.wait_for_model_ready(timeout=15)
            if not model_ready:
                print("Бот не готов принять промпт, возможно проблема с выбором модели")
                # Обновляем статус слота
                if slot in self.message_monitor.slot_status:
                    self.message_monitor.slot_status[slot].update({
                        'status': self.message_monitor.STATUS_ERROR,
                        'last_update_time': datetime.now(),
                        'last_status_message': 'Ошибка выбора модели'
                    })
                return False

            # Обновляем статус - промпт отправлен
            self.message_monitor.table_manager.mark_prompt_sent(prompt_data['id'], model)
            
            # Отправляем промпт
            print(f"Отправляем промпт (Слот {slot}): {prompt_data['prompt']}")
            try:
                await self.client.send_message(self.bot, prompt_data['prompt'])
                print(f"Промпт успешно отправлен в слоте {slot}")
            except Exception as e:
                print(f"Ошибка при отправке промпта в слоте {slot}: {str(e)}")
                import traceback
                print(f"Подробная информация об ошибке:\n{traceback.format_exc()}")
                # Обновляем статус слота
                if slot in self.message_monitor.slot_status:
                    self.message_monitor.slot_status[slot].update({
                        'status': self.message_monitor.STATUS_ERROR,
                        'last_update_time': datetime.now(),
                        'last_status_message': f'Ошибка отправки промпта: {str(e)}'
                    })
                return False
            
            # Выводим текущие статусы слотов
            self.message_monitor.print_slot_statuses()
            
            # Ожидаем подтверждения начала генерации
            print(f"Ожидание подтверждения начала генерации (Слот {slot})...")
            generation_confirmed = await self.message_monitor.wait_for_generation_start(slot, timeout=self.wait_timeout)
            
            if not generation_confirmed:
                print(f"Не получено подтверждение начала генерации в слоте {slot}")
                
                # Проверяем, не был ли обнаружен лимит запросов
                if self.message_monitor.check_limit_detected(slot):
                    print(f"Обнаружен лимит запросов в слоте {slot}")
                    return False
                
                # Вместо повторной отправки, увеличиваем время ожидания
                print(f"Увеличиваем время ожидания подтверждения генерации...")
                
                # Пробуем дождаться подтверждения с увеличенным таймаутом
                generation_confirmed = await self.message_monitor.wait_for_generation_start(slot, timeout=self.extended_wait_time)
                
                if not generation_confirmed:
                    print(f"Не получено подтверждение даже после увеличенного ожидания. Продолжаем ожидание видео.")
                    
                    # Проверяем еще раз лимит запросов
                    if self.message_monitor.check_limit_detected(slot):
                        print(f"Обнаружен лимит запросов в слоте {slot}")
                        return False
            else:
                print(f"Получено подтверждение начала генерации для слота {slot}")
            
            # Обновляем статус - ожидание видео
            self.message_monitor.table_manager.mark_waiting_video(prompt_data['id'], model)
            
            print(f"Ожидание получения видео (Слот {slot})...")
            result = await self.message_monitor.wait_for_video(slot)
            
            # Выводим текущие статусы слотов
            self.message_monitor.print_slot_statuses()
            
            # Возвращаем результат
            return result
                
        except Exception as e:
            print(f"Ошибка при навигации в слоте {slot}: {str(e)}")
            # Записываем подробную информацию об ошибке
            import traceback
            print(f"Подробная информация об ошибке:\n{traceback.format_exc()}")
            return False 