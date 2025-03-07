import asyncio

class TelegramNavigator:
    def __init__(self, client, bot, config, message_monitor, logger=None):
        self.client = client
        self.bot = bot
        self.config = config
        self.message_monitor = message_monitor
        self.logger = logger
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

    def set_model(self, model_number):
        """
        Устанавливает модель для использования в запросах
        model_number: номер модели (строка от '1' до '8')
        """
        if model_number in self.models:
            self.config['model_number'] = model_number
            message = f"Установлена модель: {self.models[model_number]}"
            print(message)
            
            if self.logger:
                self.logger.log_app_event("MODEL_CHANGE", message, 
                                        extra_info={"model_number": model_number, "model_name": self.models[model_number]})
            return True
        else:
            message = f"Ошибка: неверный номер модели {model_number}. Допустимые значения: от 1 до 8."
            print(message)
            
            if self.logger:
                self.logger.log_app_event("MODEL_ERROR", message, "ERROR", 
                                        {"attempted_model": model_number})
            return False

    async def navigate_and_send_prompt(self, prompt_data, slot=None):
        """
        Отправляет промпт и ожидает ответа
        prompt_data: словарь с данными промпта
        slot: номер слота для параллельной обработки
        """
        try:
            # Используем модель из конфига или по умолчанию первую
            model_number = self.config.get('model_number', '1')
            model = self.models.get(model_number, self.models['1'])
            
            if self.logger:
                self.logger.log_app_event("NAVIGATION_START", 
                                        f"Начинаем навигацию для отправки промпта {prompt_data['id']} в слоте {slot}",
                                        extra_info={"model": model})
            
            # Проверяем, находится ли модель в состоянии лимита
            if self.message_monitor.is_model_limited(model):
                message = f"\nМодель {model} достигла лимита запросов (текущее значение: {self.message_monitor.model_limits.get(model, 0)})"
                print(message)
                print(f"Автоматическое ожидание снятия лимита для модели {model}...")
                
                if self.logger:
                    self.logger.log_model_limit(model, self.message_monitor.model_limits.get(model, 0), prompt_data['id'])
                
                # Ждем снятия лимита
                await self.wait_for_limit_release(model)
                print(f"Лимит для модели {model} снят, продолжаем отправку промпта")
                
                if self.logger:
                    self.logger.log_app_event("LIMIT_RELEASED", 
                                            f"Лимит для модели {model} снят, продолжаем отправку промпта {prompt_data['id']}")
                
                # Проверяем лимит еще раз после ожидания
                if self.message_monitor.is_model_limited(model):
                    message = f"Лимит для модели {model} все еще активен после ожидания"
                    print(message)
                    
                    if self.logger:
                        self.logger.log_app_event("LIMIT_PERSISTS", message, "WARNING", 
                                                {"prompt_id": prompt_data['id'], "model": model})
                        
                    # Отмечаем промпт как ожидающий и возвращаем False для повторного добавления в очередь 
                    self.message_monitor.table_manager.mark_pending(prompt_data['id'])
                    return False
            
            # Устанавливаем текущий запрос в мониторе для конкретного слота
            if not self.message_monitor.set_current_task(prompt_data['id'], prompt_data['prompt'], model, slot):
                # Если не удалось установить запрос (возможно, лимит), отмечаем промпт как ожидающий
                self.message_monitor.table_manager.mark_pending(prompt_data['id'])
                
                if self.logger:
                    self.logger.log_app_event("TASK_SET_FAILED", 
                                            f"Не удалось установить запрос для промпта {prompt_data['id']} в слоте {slot}",
                                            "ERROR")
                return False

            # Отправляем команду /video и сразу модель
            if self.logger:
                self.logger.log_outgoing("/video", self.config.get('bot_name', 'Unknown'), "COMMAND")
                
            await self.client.send_message(self.bot, '/video')
            
            if self.logger:
                self.logger.log_outgoing(model, self.config.get('bot_name', 'Unknown'), "MODEL",
                                      {"model_number": model_number})
                
            await self.client.send_message(self.bot, model)
            await asyncio.sleep(0.5)

            # Отправляем промпт
            print(f"Отправлен промпт (Слот {slot}): {prompt_data['prompt']}")
            
            if self.logger:
                self.logger.log_outgoing(prompt_data['prompt'], self.config.get('bot_name', 'Unknown'), "PROMPT",
                                      {"prompt_id": prompt_data['id'], "slot": slot})
                
            await self.client.send_message(self.bot, prompt_data['prompt'])

            print(f"Ожидание получения видео (Слот {slot})...")
            if self.logger:
                self.logger.log_app_event("WAITING_VIDEO", f"Ожидание получения видео в слоте {slot}")
                
            return await self.message_monitor.wait_for_video(slot)

        except Exception as e:
            error_message = f"Ошибка при навигации в слоте {slot}: {e}"
            print(error_message)
            
            if self.logger:
                self.logger.log_exception(e, context=f"При навигации для промпта {prompt_data['id']} в слоте {slot}")
                
            return False
            
    async def wait_for_limit_release(self, model=None):
        """
        Ожидает снятия лимита для указанной модели
        Если модель не указана, ожидает снятия лимита для любой модели
        """
        if model is None:
            # Если модель не указана, используем текущую модель из конфига
            model_number = self.config.get('model_number', '1')
            model = self.models.get(model_number, self.models['1'])
            
        if not self.message_monitor.is_model_limited(model):
            # Если лимита нет, возвращаем True
            return True
            
        print(f"Ожидаем снятия лимита для модели {model} (текущее значение: {self.message_monitor.model_limits.get(model, 0)})")
        
        # Максимальное количество попыток ожидания
        max_attempts = 3
        current_attempt = 0
        
        while current_attempt < max_attempts:
            current_attempt += 1
            print(f"Попытка {current_attempt}/{max_attempts} ожидания снятия лимита для модели {model}")
            
            # Пробуем ожидать получения любого видео, которое может снять лимит
            try:
                success = await self.message_monitor.wait_for_any_video_received()
                if success:
                    # Проверяем, был ли снят лимит для данной модели
                    if not self.message_monitor.is_model_limited(model):
                        print(f"Лимит для модели {model} успешно снят")
                        return True
                    else:
                        print(f"Получено видео, но лимит для модели {model} все еще активен")
                        # Продолжаем попытки, если лимит все еще активен
                else:
                    print(f"Не удалось дождаться видео для снятия лимита модели {model}")
                    # Если не получили видео, делаем паузу перед следующей попыткой
                    await asyncio.sleep(5)
            except Exception as e:
                print(f"Ошибка при ожидании снятия лимита: {e}")
                await asyncio.sleep(2)
        
        print(f"Все попытки ожидания снятия лимита для модели {model} исчерпаны")
        return False 