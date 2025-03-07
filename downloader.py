class VideoDownloader:
    def __init__(self, client=None):
        """Инициализирует загрузчик видео."""
        self.client = client
        
    def set_client(self, client):
        """Устанавливает клиент для загрузки видео."""
        self.client = client
        
    def download_video(self, message, file_path, client=None):
        """
        Скачивает видео из сообщения и сохраняет по указанному пути.
        
        Args:
            message: Сообщение с видео
            file_path: Путь для сохранения файла
            client: Клиент Telegram (опционально, если self.client не установлен)
        """
        # Используем переданный client, если self.client отсутствует
        active_client = client if (not self.client and client) else self.client
        
        if not active_client:
            raise AttributeError("Необходимо установить client через метод set_client или передать его параметром перед скачиванием видео")
            
        # Выполняем синхронную загрузку, если функция вызвана из синхронного контекста
        if not hasattr(message, 'download_media'):
            # Предполагаем, что это обычный объект сообщения Telethon
            import asyncio
            loop = asyncio.get_event_loop()
            try:
                loop.run_until_complete(active_client.download_media(message, file_path))
            except Exception as e:
                raise Exception(f"Ошибка при синхронном скачивании: {str(e)}")
        else:
            # Используем встроенный метод download_media, если он доступен
            message.download_media(file_path)
            
        return file_path