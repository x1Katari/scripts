import os
import re
import time
import shutil
import asyncio
import aiohttp
import aiofiles

from tqdm import tqdm
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options

TOKEN = '...'

bot = Bot(token=TOKEN)
dp = Dispatcher()

output_folder = 'images'
os.makedirs(output_folder, exist_ok=True)

active_downloads = asyncio.Queue()
allowed_users = [
    370247555,
    ...
]


def sanitize_folder_name(folder_name):
    return re.sub(r'[<>:"/\\|?*]', '', folder_name)


def scroll_to_bottom(driver):
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height


def selenium_task(link):
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')

    driver = webdriver.Chrome(options=chrome_options)
    driver.get(link)
    scroll_to_bottom(driver)
    title = driver.find_element(By.TAG_NAME, 'h1').text or 'название_не_найдено'
    images = driver.find_elements(By.TAG_NAME, 'img')

    urls = []
    for img in images:
        src = img.get_attribute('src')

        if 'floatW' in src:
            continue

        if src in ['https://mh.iqtao.cn/images/loading_bak.png', '/images/loading_bak.png']:
            src = img.get_attribute('data-src')

        if src:
            urls.append(src)

    driver.quit()

    return title, urls


async def download_images(link, chapter_folder):
    title, urls = await asyncio.to_thread(selenium_task, link)

    os.makedirs(chapter_folder, exist_ok=True)

    total = len(urls)

    async with aiohttp.ClientSession() as session:
        async def download_image(session, chapter_folder, url, idx):
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        async with aiofiles.open(os.path.join(chapter_folder, f'{idx}.jpg'), 'wb') as out_file:
                            await out_file.write(await response.read())
                    else:
                        tqdm.write(f"Ошибка загрузки {idx + 1}: {response.status}")
            except Exception as e:
                tqdm.write(f"Ошибка загрузки {idx + 1}: {e}")

        tasks = []
        with tqdm(total=total, desc="Загрузка изображений", unit="изобр") as pbar:
            for idx, url in enumerate(urls):
                task = asyncio.create_task(download_image(session, chapter_folder, url, idx))
                task.add_done_callback(lambda _: pbar.update(1))
                tasks.append(task)
            await asyncio.gather(*tasks)

    return True


@dp.message(Command('start'))
async def start(message: Message):
    await message.answer("Привет! Отправь мне ссылку на главу, и я скачаю изображения с неё в виде архива.")


@dp.message(F.text)
async def handle_message(message: Message):
    if message.from_user.id not in allowed_users:
        await message.answer("У вас нет доступа к этому боту.")
        return

    parts = message.text.strip().split(" ", 1)
    link = parts[0]
    folder_name = ''.join(parts[1:]) if len(parts) > 1 else 'название_не_найдено'

    if 'iqtao.cn' not in link:
        await message.answer("Неверная ссылка. Убедитесь, что она ведёт на iqtao.cn.")
        return

    print(f"Получена ссылка: {link}")
    await active_downloads.put((link, folder_name, message))
    await message.answer("Ссылка добавлена в очередь.")


async def process_queue():
    while True:
        link, folder_name, message = await active_downloads.get()
        chapter_folder = os.path.join(output_folder, sanitize_folder_name(folder_name))
        try:
            await message.answer(f"Скачиваю главу: {link if folder_name == 'название_не_найдено' else folder_name}")

            await download_images(link, chapter_folder)

            archive_path = shutil.make_archive(chapter_folder, 'zip', chapter_folder)
            file = types.FSInputFile(archive_path)
            await message.answer_document(file, caption=f"Глава: {folder_name}")
            print(f"Глава {link} успешно загружена.")
        finally:
            if os.path.exists(chapter_folder):
                shutil.rmtree(chapter_folder)
            if os.path.exists(f"{chapter_folder}.zip"):
                os.remove(f"{chapter_folder}.zip")


async def main():
    asyncio.create_task(process_queue())
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
