import yaml


def read_config():
    # yaml 파일 내 한글 읽을 때 안 깨지게 utf-8 encoding
    with open('./config.yaml', encoding='utf-8') as f:
        config = yaml.load(f, Loader=yaml.FullLoader)

    return config

def read_config_okx():
    # yaml 파일 내 한글 읽을 때 안 깨지게 utf-8 encoding
    with open('./configs/config_okx.yaml', encoding='utf-8') as f:
        config = yaml.load(f, Loader=yaml.FullLoader)

    return config

from telegram import Bot

async def send_telegram_message(token, chat_id, text):
    bot = Bot(token=token)
    await bot.send_message(chat_id=chat_id, text=text)
