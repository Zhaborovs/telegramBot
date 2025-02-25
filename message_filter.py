class MessageFilter:
    def __init__(self):
        # Сообщения, которые мы игнорируем
        self.ignored_messages = [
            "Выберите раздел для работы с видео 👇",
            "🎬 Видео будущего",
            "⚠️ Не выбран инструмент для работы с чат-ботом",
            "Пожалуйста, воспользуйтесь навигацией",
            "Меню",
            "Профиль",
            "База знаний",
            "В главное меню",
            "Назад",
            "Настройки модели",
            "Кубик удачи",
            "Встряхнем его хорошенько",
            "Пусть грани кубика",
            "играем в кубик"
        ]
        
        # Сообщения, которые указывают на прогресс генерации
        self.progress_messages = [
            "⏳ Ожидайте выполнения",
            "⚡ Задача ожидает выполнения",
            "🎬 Генерирую видео",
            "⏳ Одну секунду",
            "Ждите секунду"
        ]

        # Сообщения, которые мы точно хотим видеть
        self.important_messages = [
            "📍 Запрос:",
            "📍 Ваш запрос:",
            "Видео готово",
            "Генерирую видео"
        ]

    def should_print_message(self, message_text, has_video=False):
        # Всегда обрабатываем сообщения с видео
        if has_video:
            return True
            
        # Проверяем, не является ли сообщение пустым
        if not message_text:
            return False

        # Всегда показываем важные сообщения
        if any(important in message_text for important in self.important_messages):
            return True
            
        # Игнорируем сообщения из списка игнорируемых
        if any(ignored in message_text for ignored in self.ignored_messages):
            return False
            
        # Для сообщений о прогрессе выводим только первое
        if any(progress in message_text for progress in self.progress_messages):
            return True
            
        # Выводим сообщения об ошибках
        if "ошибка" in message_text.lower() or "error" in message_text.lower():
            return True
            
        # Выводим информацию о параметрах видео
        if any(param in message_text.lower() for param in ["качество:", "разрешение:", "длительность:", "модель:"]):
            return True
            
        return False  # По умолчанию не выводим сообщение

    def format_message(self, message_text, has_video=False):
        # Если есть видео, выводим полное сообщение
        if has_video:
            return f"Получено видео: {message_text}"
            
        # Форматируем сообщение о прогрессе
        if any(progress in message_text for progress in self.progress_messages):
            return "Генерация видео в процессе..."
            
        return message_text 