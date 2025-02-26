from telethon import TelegramClient, events, sync
import asyncio
import logging
from telethon.tl.types import InputPeerUser
from navigation import TelegramNavigator
from video_downloader import VideoDownloader
from message_monitor import MessageMonitor
from init_config import ConfigInitializer
from request_manager import RequestManager
from table_manager import TableManager
import os

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                   level=logging.INFO)
logger = logging.getLogger(__name__)

async def process_prompt(prompt_data, slot, navigator, request_manager, table_manager):
    """Обрабатывает один промпт"""
    try:
        while True:  # Добавляем цикл для повторных попыток
            # Модель будет выбрана внутри navigate_and_send_prompt
            # Отправляем промпт
            success = await navigator.navigate_and_send_prompt(prompt_data, slot)
            
            if not success:
                # Проверяем, не был ли промпт отмечен как pending из-за лимита
                prompt_status = table_manager.get_status(prompt_data['id'])
                if prompt_status['status'] == 'pending':
                    print(f"\nПромпт {prompt_data['id']} не был отправлен из-за лимита в слоте {slot}")
                    print(f"Автоматическое ожидание снятия лимита для данной модели...")
                    # Освобождаем слот и отмечаем промпт как ожидающий
                    await request_manager.release_slot(slot)
                    return False  # Вернет промпт обратно в очередь
                
                # Для других ошибок (не связанных с лимитом) показываем меню
                print(f"\nНе удалось отправить промпт {prompt_data['id']} в слоте {slot}")
                print(f"Слот {slot} - Выберите действие:")
                print("1. Повторить попытку")
                print("2. Освободить слот и продолжить")
                print("3. Выйти")
                
                choice = input(f"Слот {slot} - Введите номер действия (1-3): ").strip()
                
                if choice == '1':
                    continue  # Повторяем попытку
                elif choice == '2':
                    table_manager.mark_skipped(prompt_data['id'])
                    await request_manager.release_slot(slot)
                    return False
                elif choice == '3':
                    await request_manager.release_slot(slot)
                    return None
            else:
                table_manager.mark_completed(prompt_data['id'])
                print(f"Промпт {prompt_data['id']} успешно обработан в слоте {slot}")
                await request_manager.release_slot(slot)
                return True

    except Exception as e:
        print(f"Ошибка при обработке промпта {prompt_data['id']} в слоте {slot}: {e}")
        table_manager.mark_error(prompt_data['id'])
        await request_manager.release_slot(slot)
        return False

async def run_client():
    # Загружаем конфигурацию
    config = ConfigInitializer.load_config()
    if not config:
        return

    # Инициализация клиента с уникальным именем сессии
    session_name = f"bot_session_{config['api_id']}"
    client = TelegramClient(session_name,
                          int(config['api_id']),
                          config['api_hash'])

    try:
        # Подключение к Telegram с запросом номера телефона
        print("\nДля работы бота требуется войти в отдельный аккаунт Telegram.")
        print("Пожалуйста, введите номер телефона для входа:")
        
        # Запускаем клиент без автоматического входа
        await client.connect()
        
        if not await client.is_user_authorized():
            phone = input('Введите номер телефона: ')
            await client.send_code_request(phone)
            code = input('Введите код подтверждения: ')
            await client.sign_in(phone, code)
        
        # Получение информации о боте
        bot = await client.get_input_entity(config['bot_name'])
        
        print("\nПодключено к Telegram")
        
        # Создание компонентов с конфигом
        table_manager = TableManager(config)
        video_downloader = VideoDownloader(table_manager, config)
        message_monitor = MessageMonitor(client, bot, video_downloader, config)
        await message_monitor.start_monitoring()
        navigator = TelegramNavigator(client, bot, config, message_monitor)
        
        # Загружаем промпты
        prompts_file = config.get('prompts_file', 'prompt.txt')
        if not os.path.exists(prompts_file):
            print(f"\nФайл с промптами {prompts_file} не найден")
            return
            
        table_manager.load_prompts(prompts_file)
        
        # Инициализация менеджера запросов
        max_slots = int(config.get('parallel_requests', '1'))
        if max_slots not in [1, 2]:
            print("Ошибка: parallel_requests должно быть 1 или 2")
            return
        request_manager = RequestManager(max_slots, table_manager)

        # Очищаем занятые слоты при старте
        await message_monitor.cleanup_active_slots()

        # Обработка промптов
        pending_tasks = set()
        all_prompts = table_manager.get_pending_prompts()
        print(f"Загружено {len(all_prompts)} промптов")

        while all_prompts or pending_tasks:
            # Пытаемся заполнить все доступные слоты
            while all_prompts and len(pending_tasks) < max_slots:
                prompt_data = all_prompts.pop(0)
                slot = await request_manager.acquire_slot(prompt_data['id'])
                
                if slot:
                    task = asyncio.create_task(
                        process_prompt(prompt_data, slot, navigator, request_manager, table_manager)
                    )
                    task.prompt_id = prompt_data['id']
                    pending_tasks.add(task)
                    continue
                else:
                    # Если не получили слот, возвращаем промпт обратно
                    all_prompts.insert(0, prompt_data)
                    break

            if not pending_tasks:
                await asyncio.sleep(1)
                continue

            # Ждем завершения любой задачи
            done, pending_tasks = await asyncio.wait(
                pending_tasks,
                return_when=asyncio.FIRST_COMPLETED
            )

            # Обрабатываем завершенные задачи
            for task in done:
                try:
                    result = task.result()
                    if result is None:  # Пользователь выбрал выход
                        return
                    elif result is False:  # Ошибка обработки
                        # Проверяем, не был ли промпт возвращен в очередь из-за лимита
                        prompt_status = table_manager.get_status(task.prompt_id)
                        if prompt_status['status'] == 'pending':
                            all_prompts.append(prompt_status)
                except Exception as e:
                    print(f"Ошибка при выполнении задачи {task.prompt_id}: {e}")

    finally:
        await client.disconnect()

if __name__ == "__main__":
    # Запускаем асинхронный код
    asyncio.run(run_client())