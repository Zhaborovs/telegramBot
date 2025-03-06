import os
import sys
import subprocess
import platform
import shutil
from pathlib import Path

# Цвета для консоли Windows
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    """Выводит заголовок в консоль"""
    print(f"{Colors.HEADER}{Colors.BOLD}=== {text} ==={Colors.ENDC}")

def print_step(text):
    """Выводит шаг установки в консоль"""
    print(f"{Colors.BLUE}>> {text}{Colors.ENDC}")

def print_success(text):
    """Выводит сообщение об успехе в консоль"""
    print(f"{Colors.GREEN}✓ {text}{Colors.ENDC}")

def print_warning(text):
    """Выводит предупреждение в консоль"""
    print(f"{Colors.WARNING}⚠ {text}{Colors.ENDC}")

def print_error(text):
    """Выводит сообщение об ошибке в консоль"""
    print(f"{Colors.FAIL}✗ {text}{Colors.ENDC}")

def run_command(command, check=True):
    """Выполняет команду и возвращает результат"""
    try:
        result = subprocess.run(command, shell=True, check=check, capture_output=True, text=True)
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.CalledProcessError as e:
        return False, "", str(e)

def check_python():
    """Проверяет установку Python и выводит версию"""
    print_step("Проверка версии Python...")
    
    try:
        version = sys.version.split()[0]
        if version.startswith('3.'):
            major, minor = map(int, version.split('.')[:2])
            if major == 3 and minor >= 10:
                print_success(f"Найден Python версии {version}")
                return True
            else:
                print_warning(f"Версия Python {version} может быть несовместима с приложением")
                print_warning("Рекомендуется Python 3.10 или выше")
                return True
        else:
            print_error(f"Неподдерживаемая версия Python: {version}")
            return False
    except Exception as e:
        print_error(f"Не удалось определить версию Python: {e}")
        return False

def setup_virtual_env():
    """Создает виртуальное окружение"""
    print_step("Настройка виртуального окружения...")
    
    venv_dir = Path(".venv")
    
    # Проверяем, существует ли виртуальное окружение
    if venv_dir.exists():
        print_warning("Виртуальное окружение уже существует")
        recreate = input("Пересоздать виртуальное окружение? (д/н): ").lower()
        if recreate == 'д' or recreate == 'y':
            print_step("Удаление существующего виртуального окружения...")
            shutil.rmtree(venv_dir, ignore_errors=True)
        else:
            print_step("Используем существующее виртуальное окружение")
            return True
    
    # Создаем новое виртуальное окружение
    success, _, error = run_command(f"{sys.executable} -m venv .venv")
    if success:
        print_success("Виртуальное окружение создано успешно")
        return True
    else:
        print_error(f"Ошибка при создании виртуального окружения: {error}")
        return False

def get_pip_path():
    """Возвращает путь к pip внутри виртуального окружения"""
    if platform.system() == "Windows":
        return ".venv\\Scripts\\pip"
    else:
        return ".venv/bin/pip"

def install_dependencies():
    """Устанавливает зависимости из requirements.txt"""
    print_step("Установка зависимостей...")
    
    if not os.path.exists("requirements.txt"):
        print_error("Файл requirements.txt не найден")
        return False
    
    pip_path = get_pip_path()
    
    # Обновляем pip
    print_step("Обновление pip...")
    update_cmd = f"{pip_path} install --upgrade pip"
    run_command(update_cmd, check=False)
    
    # Устанавливаем зависимости
    print_step("Установка пакетов из requirements.txt...")
    success, output, error = run_command(f"{pip_path} install -r requirements.txt")
    
    if success:
        print_success("Зависимости установлены успешно")
        return True
    else:
        print_error(f"Ошибка при установке зависимостей: {error}")
        return False

def create_directories():
    """Создает необходимые директории"""
    print_step("Создание необходимых директорий...")
    
    directories = ["logs", "downloaded_videos"]
    
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print_success(f"Создана директория: {directory}")
        else:
            print_warning(f"Директория {directory} уже существует")
    
    return True

def create_desktop_shortcut():
    """Создает ярлык на рабочем столе (только для Windows)"""
    if platform.system() != "Windows":
        print_warning("Создание ярлыка на рабочем столе поддерживается только для Windows")
        return False
    
    print_step("Создание ярлыка на рабочем столе...")
    
    try:
        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.exists(desktop_path):
            print_warning("Путь к рабочему столу не найден")
            return False
        
        # Создаем ярлык с помощью PowerShell
        current_dir = os.path.abspath(os.path.dirname(__file__))
        run_bat_path = os.path.join(current_dir, "run.bat")
        shortcut_path = os.path.join(desktop_path, "TelegramBot.lnk")
        
        # PowerShell скрипт для создания ярлыка
        ps_script = f"""
        $WshShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut("{shortcut_path}")
        $Shortcut.TargetPath = "{run_bat_path}"
        $Shortcut.WorkingDirectory = "{current_dir}"
        $Shortcut.Description = "Telegram Bot"
        $Shortcut.Save()
        """
        
        with open("create_shortcut.ps1", "w") as f:
            f.write(ps_script)
        
        # Запускаем PowerShell скрипт
        success, _, error = run_command("powershell -ExecutionPolicy Bypass -File create_shortcut.ps1")
        os.remove("create_shortcut.ps1")
        
        if success:
            print_success(f"Ярлык создан на рабочем столе: {shortcut_path}")
            return True
        else:
            print_error(f"Ошибка при создании ярлыка: {error}")
            return False
    
    except Exception as e:
        print_error(f"Ошибка при создании ярлыка: {e}")
        return False

def setup_config():
    """Проверяет и создает конфигурационный файл при необходимости"""
    print_step("Настройка конфигурации...")
    
    # Проверяем наличие config.txt
    if os.path.exists("config.txt"):
        print_warning("Файл конфигурации уже существует")
        return True
    
    # Используем функцию из init_config.py
    try:
        import init_config
        initializer = init_config.ConfigInitializer()
        initializer.ensure_config_exists()
        print_success("Создан файл конфигурации config.txt")
        print_warning("Не забудьте заполнить API ID и API Hash в файле config.txt")
        return True
    except Exception as e:
        print_error(f"Ошибка при создании конфигурации: {e}")
        
        # Создаем конфигурацию вручную
        config_template = """# Telegram API credentials
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
log_dir=logs
enable_console_logs=true
detailed_logging=true

# Доступные модели:
# 1 = 🌙 SORA
# 2 = ➕ Hailuo MiniMax
# 3 = 📦 RunWay: Gen-3
# 4 = 🎬 Kling 1.6
# 5 = 🎯 Pika 2.0
# 6 = 👁 Act-One (Аватары 2.0)
# 7 = 🌫 Luma: DM"""
        
        with open("config.txt", "w", encoding="utf-8") as f:
            f.write(config_template)
        
        print_success("Создан файл конфигурации config.txt")
        print_warning("Не забудьте заполнить API ID и API Hash в файле config.txt")
        return True

def create_run_scripts():
    """Создает скрипты для запуска приложения"""
    print_step("Создание скриптов запуска...")
    
    # Создаем run.bat для Windows
    if not os.path.exists("run.bat"):
        with open("run.bat", "w") as f:
            f.write('@echo off\n')
            f.write('cls\n')
            f.write('title Telegram Bot\n')
            f.write('color 0A\n')
            f.write('echo Запуск Telegram бота...\n')
            f.write('echo.\n')
            f.write('cd "%~dp0"\n')
            f.write('if exist .venv (\n')
            f.write('    call .venv\\Scripts\\activate\n')
            f.write('    python main.py\n')
            f.write(') else (\n')
            f.write('    echo Виртуальное окружение не найдено. Запустите установку.\n')
            f.write('    pause\n')
            f.write(')\n')
            f.write('pause\n')
        print_success("Создан файл run.bat")
    else:
        print_warning("Файл run.bat уже существует")
    
    # Создаем run.sh для Linux/macOS
    if platform.system() != "Windows":
        if not os.path.exists("run.sh"):
            with open("run.sh", "w") as f:
                f.write('#!/bin/bash\n')
                f.write('echo "Запуск Telegram бота..."\n')
                f.write('echo ""\n')
                f.write('if [ -d ".venv" ]; then\n')
                f.write('    source .venv/bin/activate\n')
                f.write('    python main.py\n')
                f.write('else\n')
                f.write('    echo "Виртуальное окружение не найдено. Запустите установку."\n')
                f.write('    read -p "Нажмите Enter для выхода..."\n')
                f.write('fi\n')
            os.chmod("run.sh", 0o755)
            print_success("Создан файл run.sh")
        else:
            print_warning("Файл run.sh уже существует")
    
    return True

def main():
    """Основная функция установки"""
    os.system('color' if platform.system() == 'Windows' else 'tput init')
    
    print("\n")
    print_header("УСТАНОВКА TELEGRAM БОТА")
    print("\n")
    
    # Проверяем Python
    if not check_python():
        print_error("Установка не может быть продолжена без подходящей версии Python")
        return False
    
    # Настраиваем виртуальное окружение
    if not setup_virtual_env():
        print_error("Ошибка при настройке виртуального окружения")
        return False
    
    # Устанавливаем зависимости
    if not install_dependencies():
        print_error("Ошибка при установке зависимостей")
        return False
    
    # Создаем необходимые директории
    create_directories()
    
    # Настраиваем конфигурацию
    setup_config()
    
    # Создаем скрипты запуска
    create_run_scripts()
    
    # Создаем ярлык на рабочем столе (только для Windows)
    if platform.system() == "Windows":
        create_desktop_shortcut()
    
    print("\n")
    print_header("УСТАНОВКА ЗАВЕРШЕНА УСПЕШНО")
    print("\n")
    print_success("Теперь вы можете запустить бота, используя:")
    if platform.system() == "Windows":
        print("  - Ярлык на рабочем столе")
        print("  - Файл run.bat в папке с программой")
    else:
        print("  - Файл run.sh в папке с программой")
    
    print("\n")
    print_warning("Не забудьте заполнить API ID и API Hash в файле config.txt")
    print("\n")
    
    input("Нажмите Enter для выхода...")
    return True

if __name__ == "__main__":
    main() 