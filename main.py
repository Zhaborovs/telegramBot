import os
import asyncio
import logging
import datetime
import sys
import io
from logging.handlers import RotatingFileHandler
from telethon.tl.types import InputPeerUser
from navigation import TelegramNavigator
from video_downloader import VideoDownloader
from message_monitor import MessageMonitor
from init_config import ConfigInitializer
from request_manager import RequestManager
from table_manager import TableManager
from telethon import TelegramClient, events, sync


# Настраиваем кодировку для корректного отображения Unicode в консоли Windows
if sys.platform == 'win32':
    # Устанавливаем кодировку UTF-8 для консоли
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Создаем папку для логов, если она не существует
logs_dir = 'logs'
os.makedirs(logs_dir, exist_ok=True)

# Настройка логирования
log_file = os.path.join(logs_dir, f'telegram_bot_{datetime.datetime.now().strftime("%Y-%m-%d")}.log')
file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
console_handler = logging.StreamHandler()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[file_handler, console_handler]
)
logger = logging.getLogger(__name__)

logger.info("Запуск приложения")

async def process_prompt(prompt_data, slot, navigator, request_manager, table_manager):
    """Обрабатывает один промпт"""
    try:
        while True:  # Добавляем цикл для повторных попыток
            try:
                success = await navigator.navigate_and_send_prompt(prompt_data, slot)
            except Exception as e:
                import traceback
                error_msg = f"Ошибка при отправке промпта {prompt_data['id']} в слоте {slot}: {str(e)}"
                logger.error(error_msg)
                logger.error(traceback.format_exc())
                print(f"\nОшибка при отправке промпта {prompt_data['id']} в слоте {slot}:")
                print(traceback.format_exc())
                success = False
            
            if not success:
                logger.info(f"Слот {slot} - Запрос действия пользователя")
                print(f"\nСлот {slot} - Выберите действие:")
                print("1. Подождать еще")
                print("2. Освободить слот и продолжить")
                print("3. Выйти")
                
                choice = input(f"Слот {slot} - Введите номер действия (1-3): ").strip()
                logger.info(f"Пользователь выбрал действие: {choice}")
                
                if choice == '1':
                    # Ждем освобождения слота при лимите
                    try:
                        logger.info(f"Ожидание освобождения слота {slot}")
                        if await navigator.message_monitor.wait_for_slot_release():
                            logger.info(f"Слот {slot} освобожден, повторяем попытку")
                            continue  # Повторяем попытку
                        else:
                            logger.warning("Не дождались освобождения слота")
                            print("Не дождались освобождения слота")
                            table_manager.mark_skipped(prompt_data['id'])
                            await request_manager.release_slot(slot)
                            return False
                    except Exception as e:
                        import traceback
                        error_msg = f"Ошибка при ожидании освобождения слота {slot}: {str(e)}"
                        logger.error(error_msg)
                        logger.error(traceback.format_exc())
                        print(f"\nОшибка при ожидании освобождения слота {slot}:")
                        print(traceback.format_exc())
                        table_manager.mark_error(prompt_data['id'])
                        await request_manager.release_slot(slot)
                        return False
                elif choice == '2':
                    logger.info(f"Пропуск промпта {prompt_data['id']} и освобождение слота {slot}")
                    table_manager.mark_skipped(prompt_data['id'])
                    await request_manager.release_slot(slot)
                    return False
                elif choice == '3':
                    logger.info("Пользователь выбрал выход")
                    await request_manager.release_slot(slot)
                    return None
            else:
                logger.info(f"Промпт {prompt_data['id']} успешно обработан в слоте {slot}")
                table_manager.mark_completed(prompt_data['id'])
                print(f"Промпт {prompt_data['id']} успешно обработан в слоте {slot}")
                await request_manager.release_slot(slot)
                return True

    except Exception as e:
        import traceback
        error_msg = f"Необработанная ошибка при обработке промпта {prompt_data['id']} в слоте {slot}: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        print(f"\nНеобработанная ошибка при обработке промпта {prompt_data['id']} в слоте {slot}:")
        print(traceback.format_exc())
        table_manager.mark_error(prompt_data['id'])
        await request_manager.release_slot(slot)
        return False

async def run_client():
    # Загружаем конфигурацию
    logger.info("Загрузка конфигурации")
    config = ConfigInitializer.load_config()
    if not config:
        logger.error("Не удалось загрузить конфигурацию")
        return

    # Инициализация клиента с уникальным именем сессии
    session_name = f"bot_session_{config['api_id']}"
    logger.info(f"Инициализация клиента с сессией {session_name}")
    client = TelegramClient(session_name,
                          int(config['api_id']),
                          config['api_hash'])

    try:
        # Подключение к Telegram с запросом номера телефона
        logger.info("Подключение к Telegram")
        print("\nДля работы бота требуется войти в отдельный аккаунт Telegram.")
        print("Пожалуйста, введите номер телефона для входа:")
        
        # Запускаем клиент без автоматического входа
        await client.connect()
        
        if not await client.is_user_authorized():
            logger.info("Требуется авторизация пользователя")
            phone = input('Введите номер телефона: ')
            await client.send_code_request(phone)
            code = input('Введите код подтверждения: ')
            await client.sign_in(phone, code)
            logger.info("Пользователь успешно авторизован")
        else:
            logger.info("Пользователь уже авторизован")
        
        # Получение информации о боте
        logger.info(f"Получение информации о боте {config['bot_name']}")
        bot = await client.get_input_entity(config['bot_name'])
        
        print("\nПодключено к Telegram")
        logger.info("Успешное подключение к Telegram")
        
        # Создание компонентов с конфигом
        logger.info("Инициализация компонентов")
        table_manager = TableManager(config)
        video_downloader = VideoDownloader(table_manager, config)
        message_monitor = MessageMonitor(client, bot, video_downloader, config)
        await message_monitor.start_monitoring()
        navigator = TelegramNavigator(client, bot, config, message_monitor)
        
        # Загружаем промпты
        prompts_file = config.get('prompts_file', 'prompt.txt')
        logger.info(f"Загрузка промптов из файла {prompts_file}")
        if not os.path.exists(prompts_file):
            logger.error(f"Файл с промптами {prompts_file} не найден")
            print(f"\nФайл с промптами {prompts_file} не найден")
            return
            
        table_manager.load_prompts(prompts_file)
        
        # Инициализация менеджера запросов
        max_slots = int(config.get('parallel_requests', '1'))
        if max_slots not in [1, 2]:
            logger.error(f"Неверное значение parallel_requests: {max_slots}")
            print("Ошибка: parallel_requests должно быть 1 или 2")
            return
        logger.info(f"Инициализация менеджера запросов с {max_slots} слотами")
        request_manager = RequestManager(max_slots, table_manager)

        # Очищаем занятые слоты при старте
        logger.info("Очистка активных слотов")
        await message_monitor.cleanup_active_slots()

        # Обработка промптов
        pending_tasks = set()
        all_prompts = table_manager.get_pending_prompts()
        logger.info(f"Загружено {len(all_prompts)} промптов")
        print(f"Загружено {len(all_prompts)} промптов")

        while all_prompts or pending_tasks:
            # Пытаемся заполнить все доступные слоты
            while all_prompts and len(pending_tasks) < max_slots:
                prompt_data = all_prompts.pop(0)
                logger.info(f"Попытка получить слот для промпта {prompt_data['id']}")
                slot = await request_manager.acquire_slot(prompt_data['id'])
                
                if slot:
                    logger.info(f"Получен слот {slot} для промпта {prompt_data['id']}")
                    task = asyncio.create_task(
                        process_prompt(prompt_data, slot, navigator, request_manager, table_manager)
                    )
                    task.prompt_id = prompt_data['id']
                    pending_tasks.add(task)
                    continue
                else:
                    # Если не получили слот, возвращаем промпт обратно
                    logger.info(f"Не удалось получить слот для промпта {prompt_data['id']}")
                    all_prompts.insert(0, prompt_data)
                    break

            if not pending_tasks:
                await asyncio.sleep(1)
                continue

            # Ждем завершения любой задачи
            logger.debug(f"Ожидание завершения задач, активных задач: {len(pending_tasks)}")
            done, pending_tasks = await asyncio.wait(
                pending_tasks,
                return_when=asyncio.FIRST_COMPLETED
            )

            # Обрабатываем завершенные задачи
            for task in done:
                try:
                    result = task.result()
                    logger.info(f"Задача для промпта {task.prompt_id} завершена с результатом: {result}")
                    if result is None:  # Пользователь выбрал выход
                        logger.info("Завершение работы по запросу пользователя")
                        return
                    elif result is False:  # Ошибка обработки
                        # Проверяем, не был ли промпт возвращен в очередь из-за лимита
                        prompt_status = table_manager.get_status(task.prompt_id)
                        if prompt_status['status'] == 'pending':
                            logger.info(f"Возврат промпта {task.prompt_id} в очередь")
                            all_prompts.append(prompt_status)
                except Exception as e:
                    logger.error(f"Ошибка при выполнении задачи {task.prompt_id}: {str(e)}")
                    print(f"Ошибка при выполнении задачи {task.prompt_id}: {e}")

    finally:
        logger.info("Отключение от Telegram")
        await client.disconnect()
        logger.info("Работа приложения завершена")

if __name__ == "__main__":
    # Запускаем асинхронный код
    try:
        logger.info("Запуск основного цикла приложения")
        asyncio.run(run_client())
    except KeyboardInterrupt:
        logger.info("Приложение остановлено пользователем (KeyboardInterrupt)")
    except Exception as e:
        logger.critical(f"Критическая ошибка: {str(e)}", exc_info=True)