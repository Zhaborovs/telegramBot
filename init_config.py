import os

class ConfigInitializer:
    @staticmethod
    def create_default_config():
        """Создает конфиг с настройками по умолчанию"""
        config_template = '''# Telegram API credentials
api_id=YOUR_API_ID
api_hash=YOUR_API_HASH
bot_name=@syntxaibot

# Пути к файлам и папкам
downloads_path=downloaded_videos
prompts_file=prompt.txt
table_file=prompts_table.csv

# Настройки генерации
model_number=1
parallel_requests=1
wait_time_minutes=20
retry_attempts=3

# Настройки логирования
log_level=INFO
log_file=bot.log

# Доступные модели:
# 1 = 🌙 SORA
# 2 = ➕ Hailuo MiniMax
# 3 = 📦 RunWay: Gen-3
# 4 = 🎬 Kling 1.6
# 5 = 🎯 Pika 2.0
# 6 = 👁 Act-One (Аватары 2.0)
# 7 = 🌫 Luma: DM
# 8 = 🦋 RW: Стилизатор'''

        return config_template

    @staticmethod
    def ensure_config_exists():
        """Проверяет наличие конфига и создает его при отсутствии"""
        config_path = 'config.txt'
        config_created = False

        if not os.path.exists(config_path):
            config_template = ConfigInitializer.create_default_config()
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(config_template)
            print(f"\nСоздан файл конфигурации {config_path}")
            print("Пожалуйста, заполните настройки в файле config.txt и перезапустите программу")
            config_created = True

        return config_created

    @staticmethod
    def load_config():
        """Загружает и проверяет конфигурацию"""
        # Проверяем/создаем конфиг
        if ConfigInitializer.ensure_config_exists():
            return None

        # Загружаем настройки
        config = {}
        with open('config.txt', 'r', encoding='utf-8') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, value = line.strip().split('=')
                    config[key.strip()] = value.strip()

        # Проверяем обязательные поля
        required_fields = ['api_id', 'api_hash']
        default_values = ['YOUR_API_ID', 'YOUR_API_HASH']
        
        for field in required_fields:
            if field not in config or config[field] in default_values:
                print(f"\nПожалуйста, заполните поле {field} в config.txt")
                return None

        return config

    @staticmethod
    def check_config():
        """Проверяет обязательные поля конфига"""
        config = ConfigInitializer.load_config()
        if not config:
            return None

        required_fields = ['api_id', 'api_hash']
        default_values = ['YOUR_API_ID', 'YOUR_API_HASH']
        
        for field in required_fields:
            if field not in config or config[field] in default_values:
                print(f"\nПожалуйста, заполните поле {field} в config.txt")
                return None

        return config 