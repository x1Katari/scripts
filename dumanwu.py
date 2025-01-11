import os
import time
import requests
import shutil
import asyncio
import re
import ssl
import urllib3

from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
ssl._create_default_https_context = ssl._create_unverified_context

TOKEN = ''

bot = Bot(token=TOKEN)
dp = Dispatcher()

chrome_options = Options()
chrome_options.add_argument('--headless')
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')
chrome_options.add_argument('--ignore-ssl-errors=yes')
chrome_options.add_argument('--allow-insecure-localhost')
chrome_options.add_argument('--ignore-certificate-errors')

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()), 
    options=chrome_options
)

output_folder = 'images'
os.makedirs(output_folder, exist_ok=True)

allowed_users = []

def sanitize_folder_name(folder_name):
    return re.sub(r'[<>:"/\\|?*]', '', folder_name.replace(" ", "_"))

def scroll_to_bottom():
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

def download_image(chapter_folder, url, idx, progress_bar):
    try:
        response = requests.get(url, stream=True, verify=False)
        if response.status_code == 200:
            with open(os.path.join(chapter_folder, f'{idx}.jpg'), 'wb') as out_file:
                shutil.copyfileobj(response.raw, out_file)
            progress_bar.update(1)
        else:
            print(f"Ошибка загрузки {idx}: {response.status_code}")
    except Exception as e:
        print(f"Ошибка при загрузке изображения {idx}: {e}")
    finally:
        if 'response' in locals():
            del response

def download_images(link, custom_folder_name=None):
    try:
        driver.get(link)
        scroll_to_bottom()

        if custom_folder_name:
            title = custom_folder_name
        else:
            title = driver.title
            if title:
                title = title.split('漫画 - 读漫屋')[0].strip()
            if not title:
                title = 'БезНазвания'

        title = sanitize_folder_name(title)
        chapter_folder = os.path.join(output_folder, title)

        if not os.path.exists(chapter_folder):
            os.makedirs(chapter_folder)

        print(f"Создана папка: {chapter_folder}")

        container = driver.find_element(By.CLASS_NAME, 'main_img')
        
        images = container.find_elements(By.TAG_NAME, 'img')
        urls = []
        for idx, img in enumerate(images):
            src = img.get_attribute('src')
            if src == 'https://dumanwu.com/static/images/load.gif':
                src = img.get_attribute('data-src')
            img_url = urljoin(link, src)
            if img_url.endswith('.html') or img_url.endswith('.png'):
                continue
            else:
                urls.append(img_url)

        with tqdm(total=len(urls), desc="Скачивание изображений", unit="img") as progress_bar:
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [
                    executor.submit(download_image, chapter_folder, url, idx, progress_bar) 
                    for idx, url in enumerate(urls)
                ]
                
                for future in as_completed(futures):
                    future.result()

        return chapter_folder
    except Exception as e:
        print(f"Ошибка при скачивании изображений: {e}")
        return None

download_queue = asyncio.Queue()

async def process_download_queue():
    while True:
        link, custom_folder_name, message = await download_queue.get()

        try:
            await message.answer("Скачиваю изображения, это может занять немного времени...")
            chapter_folder = download_images(link, custom_folder_name)

            if chapter_folder and os.path.exists(chapter_folder):
                print("Создание архива...")
                archive_path = shutil.make_archive(chapter_folder, 'zip', chapter_folder)
                file = types.FSInputFile(archive_path)
                await message.answer_document(file)
                await message.answer("Загрузка завершена!")
            else:
                await message.answer("Не удалось скачать изображения. Проверьте ссылку.")
            print("Загрузка завершена.")
        except Exception as e:
            await message.answer(f"Произошла ошибка: {e}")
        finally:
            if chapter_folder and os.path.exists(chapter_folder):
                shutil.rmtree(chapter_folder)
            if chapter_folder and os.path.exists(f"{chapter_folder}.zip"):
                os.remove(f"{chapter_folder}.zip")
            download_queue.task_done()

@dp.message(Command('start'))
async def start(message: Message):
    await message.answer("Привет! Отправь мне ссылку на главу, и я скачаю изображения с неё в виде архива.")

@dp.message()
async def handle_message(message: Message):
    if message.from_user.id not in allowed_users:
        await message.answer("У вас нет доступа к этому боту.")
        return

    parts = message.text.strip().split(" ", 1)
    link = parts[0]
    custom_folder_name = parts[1] if len(parts) > 1 else None

    if link.startswith('http://') or link.startswith('https://'):
        await message.answer("Ссылка добавлена в очередь. Загрузка начнется автоматически.")
        await download_queue.put((link, custom_folder_name, message))
    else:
        await message.answer("Неверная ссылка.")

async def main():
    asyncio.create_task(process_download_queue())
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
