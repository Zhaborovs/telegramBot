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

    async def navigate_and_send_prompt(self, prompt_data, slot=None):
        """
        Отправляет промпт и ожидает ответа
        prompt_data: словарь с данными промпта
        slot: номер слота для параллельной обработки
        """
        try:
            model_number = self.config.get('model_number', '1')
            model = self.models.get(model_number, self.models['1'])
            
            # Проверяем, находится ли модель в состоянии лимита
            if self.message_monitor.is_model_limited(model):
                print(f"Модель {model} достигла лимита запросов")
                return False
            
            # Устанавливаем текущий запрос в мониторе для конкретного слота
            if not self.message_monitor.set_current_task(prompt_data['id'], prompt_data['prompt'], model, slot):
                return False

            # Отправляем команду /video и сразу модель
            await self.client.send_message(self.bot, '/video')
            await self.client.send_message(self.bot, model)
            await asyncio.sleep(0.5)  # Минимальная пауза

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
        # Ожидаем получения любого видео
        return await self.message_monitor.wait_for_any_video_received() 