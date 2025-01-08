import asyncio
import datetime
import os

import aiofiles
import aiohttp
import requests

from PIL import Image
from sqlmodel import Field, Session, SQLModel, create_engine, select
from aiogram import Bot, types
from fake_useragent import UserAgent
from bs4 import BeautifulSoup


class Site(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    name: str
    url: str


class Comic(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    site_id: int = Field(foreign_key="site.id")
    comic_id_on_site: str
    name: str
    description: str
    url: str
    cover: str


class Settings(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    site_id: int = Field(foreign_key="site.id")
    buvid3: str
    user_agent: str
    created_at: datetime.datetime


db_url = "sqlite:///comics.db"
engine = create_engine(db_url)
SQLModel.metadata.create_all(engine)


API_TOKEN = "..."
USER_IDS = [...]
ADMIN_ID = 370247555
bot = Bot(token=API_TOKEN)


def fetch_buvid3():
    headers = {
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    }
    response = requests.get('https://manga.bilibili.com/ductape/buvid', headers=headers)
    response.raise_for_status()
    return response.json()["data"]["buvid3"]


def fetch_comics_bilibili(settings):
    headers = {
        'cookie': f'buvid3={settings.buvid3};',
        'user-agent': settings.user_agent,
    }
    json_data = {
        'style_id': -1,
        'area_id': -1,
        'is_finish': -1,
        'order': 3,
        'special_tag': 0,
        'page_num': 1,
        'page_size': 30,
        'is_free': -1,
    }
    response = requests.post('https://manga.bilibili.com/twirp/comic.v1.Comic/ClassPage', headers=headers, json=json_data)
    response.raise_for_status()
    return response.json().get("data", [])


def fetch_comics_kuaikan():
    response = requests.get(
        'https://www.kuaikanmanhua.com/search/mini/topic/multi_filter?page=1&size=48&tag_id=0&update_status=1&pay_status=0&label_dimension_origin=1&sort=3'
    )
    response.raise_for_status()
    return response.json().get("hits", {}).get("topicMessageList", [])

def fetch_kuaikan_description(comic_id):
    response = requests.get(f'https://www.kuaikanmanhua.com/web/topic/{comic_id}/')
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    details_box = soup.find('div', class_="detailsBox")
    description = details_box.find('p').text if details_box else "No description."
    return description

def save_comic(session, site_id, comic_data):
    comic = Comic(
        site_id=site_id,
        comic_id_on_site=comic_data["comic_id_on_site"],
        name=comic_data["name"],
        description=comic_data["description"],
        url=comic_data["url"],
        cover=comic_data["cover"]
    )
    session.add(comic)
    session.commit()
    return comic


async def send_comic_to_telegram(comic):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(comic.cover) as response:
                if response.status == 200:
                    if comic.site_id == 1:
                        cover_path = f'{comic.comic_id_on_site}.{comic.cover.split(".")[-1]}'
                    if comic.site_id == 2:
                        cover_path = f'{comic.comic_id_on_site}.jpg'
                    async with aiofiles.open(f'{cover_path}', 'wb') as out_file:
                        await out_file.write(await response.read())

                    image = Image.open(cover_path)
                    if image.mode == 'RGBA':
                        image = image.convert('RGB')
                    image.save(cover_path, 'JPEG', quality=60)

                    file = types.FSInputFile(cover_path)
                    caption = f"{comic.name}\n{comic.url}\n{comic.description}"
                    for USER_ID in USER_IDS:
                        await bot.send_document(chat_id=USER_ID, document=file, caption=caption[:1024])
                    os.remove(cover_path)
                else:
                    print(f"Не удалось скачать изображение: {comic.cover}")
                    message = f"Без обложки\n{comic.name}\n{comic.url}\n{comic.description}"
                    for USER_ID in USER_IDS:
                        await bot.send_message(USER_ID, message)
    except Exception as e:
        if os.path.exists(cover_path):
            os.remove(cover_path)
        print(f"Ошибка при отправке комикса в Telegram: {e}")


def initialize_database():
    with Session(engine) as session:
        if not session.exec(select(Site)).first():
            bilibili = Site(name="Bilibili", url="https://manga.bilibili.com")
            kuaikan = Site(name="Kuaikan", url="https://www.kuaikanmanhua.com")
            session.add_all([bilibili, kuaikan])
            session.commit()

            user_agent = str(UserAgent().chrome)
            buvid3 = fetch_buvid3()
            bilibili_settings = Settings(site_id=bilibili.id, buvid3=buvid3, user_agent=user_agent, created_at=datetime.datetime.now())
            session.add(bilibili_settings)
            session.commit()

async def process_comics():
    with Session(engine) as session:
        bilibili_site = session.exec(select(Site).where(Site.name == "Bilibili")).first()
        kuaikan_site = session.exec(select(Site).where(Site.name == "Kuaikan")).first()
        settings = session.exec(select(Settings).where(Settings.site_id == bilibili_site.id)).first()
        if (datetime.datetime.now() - settings.created_at).days >= 20:
            settings.buvid3 = fetch_buvid3()
            settings.created_at = datetime.datetime.now()
            session.commit()

        while True:
            try:
                bilibili_comics = fetch_comics_bilibili(settings)
                for data in bilibili_comics:
                    if not session.exec(select(Comic).where(Comic.comic_id_on_site == str(data["season_id"]))).first():
                        comic_data = {
                            "comic_id_on_site": str(data["season_id"]),
                            "name": data["title"].strip(),
                            "description": data["evaluate"].strip(),
                            "url": f'https://manga.bilibili.com/detail/mc{data["season_id"]}',
                            "cover": data["vertical_cover"]
                        }
                        comic = save_comic(session, bilibili_site.id, comic_data)
                        await send_comic_to_telegram(comic)

                kuaikan_comics = fetch_comics_kuaikan()
                for data in kuaikan_comics:
                    if not session.exec(select(Comic).where(Comic.comic_id_on_site == str(data["topic_id"]))).first():
                        description = fetch_kuaikan_description(data["topic_id"])
                        comic_data = {
                            "comic_id_on_site": str(data["topic_id"]),
                            "name": data["title"].strip(),
                            "description": description.strip(),
                            "url": f'https://www.kuaikanmanhua.com/web/topic/{data["topic_id"]}/',
                            "cover": data["vertical_image_url"]
                        }
                        comic = save_comic(session, kuaikan_site.id, comic_data)
                        await send_comic_to_telegram(comic)

                print('Ухожу поспать 5 минут. Сейчас:', f'{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
                await asyncio.sleep(300)

            except Exception as e:
                print(f"Error: {str(e)}")
                try:
                    await bot.send_message(ADMIN_ID, f"Error: {str(e)}")
                except Exception as send_error:
                    print(f"Failed to send error message: {str(send_error)}")
            finally:
                for img in os.listdir():
                    if img.endswith(".jpg") or img.endswith(".jpeg") or img.endswith(".png"):
                        os.remove(img)


def main():
    initialize_database()
    asyncio.run(process_comics())


if __name__ == "__main__":
    main()
