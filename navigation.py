import asyncio

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

    def set_model(self, model_number):
        """
        Устанавливает модель для использования в запросах
        model_number: номер модели (строка от '1' до '8')
        """
        if model_number in self.models:
            self.config['model_number'] = model_number
            print(f"Установлена модель: {self.models[model_number]}")
            return True
        else:
            print(f"Ошибка: неверный номер модели {model_number}. Допустимые значения: от 1 до 8.")
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
            
            # Проверяем, находится ли модель в состоянии лимита
            if self.message_monitor.is_model_limited(model):
                print(f"\nМодель {model} достигла лимита запросов (текущее значение: {self.message_monitor.model_limits.get(model, 0)})")
                print(f"Автоматическое ожидание снятия лимита для модели {model}...")
                
                # Ждем снятия лимита
                await self.wait_for_limit_release(model)
                print(f"Лимит для модели {model} снят, продолжаем отправку промпта")
                
                # Проверяем лимит еще раз после ожидания
                if self.message_monitor.is_model_limited(model):
                    print(f"Лимит для модели {model} все еще активен после ожидания")
                    # Отмечаем промпт как ожидающий и возвращаем False для повторного добавления в очередь 
                    self.message_monitor.table_manager.mark_pending(prompt_data['id'])
                    return False
            
            # Устанавливаем текущий запрос в мониторе для конкретного слота
            if not self.message_monitor.set_current_task(prompt_data['id'], prompt_data['prompt'], model, slot):
                # Если не удалось установить запрос (возможно, лимит), отмечаем промпт как ожидающий
                self.message_monitor.table_manager.mark_pending(prompt_data['id'])
                return False

            # Отправляем команду /video и сразу модель
            await self.client.send_message(self.bot, '/video')
            await self.client.send_message(self.bot, model)
            await asyncio.sleep(0.5)

            # Отправляем промпт
            print(f"Отправлен промпт (Слот {slot}): {prompt_data['prompt']}")
            await self.client.send_message(self.bot, prompt_data['prompt'])

            print(f"Ожидание получения видео (Слот {slot})...")
            return await self.message_monitor.wait_for_video(slot)

        except Exception as e:
            print(f"Ошибка при навигации в слоте {slot}: {e}")
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