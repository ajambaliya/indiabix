import asyncio
import os
import logging
from aiohttp import web, ClientSession
from bs4 import BeautifulSoup
from datetime import datetime
import pytz
from motor.motor_asyncio import AsyncIOMotorClient
from telegram import Bot
from telegram.constants import PollType
from telegram.error import TelegramError
from deep_translator import GoogleTranslator
from deep_translator.exceptions import RequestError

# Configuration
MONGO_CONNECTION_STRING = os.environ.get('MONGO_CONNECTION_STRING')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_USERNAME = os.environ.get('TELEGRAM_CHANNEL_USERNAME')

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GoogleTranslatorWrapper:
    def __init__(self):
        self.translator = GoogleTranslator(source="auto", target="gu")

    async def translate(self, text):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return await asyncio.to_thread(self.translator.translate, text)
            except RequestError as e:
                logger.error(f"Translation error (attempt {attempt + 1}): {e}")
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Unexpected error in translation (attempt {attempt + 1}): {e}")
                await asyncio.sleep(2)
        return text

class MongoDBManager:
    def __init__(self):
        self.client = AsyncIOMotorClient(MONGO_CONNECTION_STRING)
        self.db = self.client["current_affairs"]

    async def get_or_create_collection(self, year, month):
        return self.db[str(year)][str(month)]

    async def insert_question(self, collection, question_doc):
        await collection.insert_one(question_doc)

    async def close_connection(self):
        self.client.close()

class TelegramQuizBot:
    def __init__(self, token, channel_username):
        self.bot = Bot(token=token)
        self.channel_username = channel_username

    def truncate_text(self, text, max_length):
        return text[:max_length-3] + '...' if len(text) > max_length else text

    async def send_poll(self, question_doc):
        question = self.truncate_text(question_doc["question"], 300)
        options = [self.truncate_text(opt, 100) for opt in question_doc["options"]]
        correct_option = question_doc["value_in_braces"]
        explanation = self.truncate_text(question_doc["explanation"], 200)

        option_mapping = {chr(65+i): i for i in range(len(options))}

        try:
            correct_option_id = option_mapping.get(correct_option)
            if correct_option_id is None:
                logger.error(f"Correct option '{correct_option}' not found in options: {options}")
                return

            await self.bot.send_poll(
                chat_id=self.channel_username,
                question=question,
                options=options,
                is_anonymous=True,
                type=PollType.QUIZ,
                correct_option_id=correct_option_id,
                explanation=explanation
            )
            logger.info(f"Sent poll: {question}")
        except TelegramError as e:
            logger.error(f"Failed to send poll: {e.message}")

async def scrape_questions():
    url = "https://www.indiabix.com/current-affairs/questions-and-answers/"
    month_digit = get_current_month()

    async with ClientSession() as session:
        try:
            async with session.get(url) as response:
                text = await response.text()
                soup = BeautifulSoup(text, 'html.parser')
                link_elements = soup.find_all("a", class_="text-link me-3")

                valid_links = [
                    f"https://www.indiabix.com{link_element.get('href')}"
                    for link_element in link_elements
                    if f"/current-affairs/2024-{month_digit}-" in link_element.get("href", "")
                ]

                translator = GoogleTranslatorWrapper()
                mongo_manager = MongoDBManager()

                new_questions = []

                for full_url in valid_links:
                    _, year, month, day = full_url.split("/")[-4:]
                    day = day.rstrip('/')

                    collection = await mongo_manager.get_or_create_collection(year, month)
                    
                    async with session.get(full_url) as response:
                        text = await response.text()
                        soup = BeautifulSoup(text, 'html.parser')

                        question_divs = soup.find_all("div", class_="bix-div-container")

                        for question_div in question_divs:
                            try:
                                qtxt = question_div.find("div", class_="bix-td-qtxt").text.strip()
                                options_div = question_div.find("div", class_="bix-tbl-options")
                                option_rows = options_div.find_all("div", class_="bix-opt-row")
                                options = [option_row.find("div", class_="bix-td-option-val").text.strip() for option_row in option_rows]

                                hidden_input = question_div.find("input", class_="jq-hdnakq")
                                value_in_braces = hidden_input['value'].split('{', 1)[-1].rsplit('}', 1)[0] if hidden_input and 'value' in hidden_input.attrs else ""

                                answer_div = question_div.find("div", class_="bix-div-answer")
                                explanation = answer_div.find("div", class_="bix-ans-description").text.strip()

                                translated_qtxt = await translator.translate(qtxt)
                                translated_options = [await translator.translate(option) for option in options]
                                translated_explanation = await translator.translate(explanation)

                                question_doc = {
                                    "question": translated_qtxt,
                                    "options": translated_options,
                                    "value_in_braces": value_in_braces,
                                    "explanation": translated_explanation,
                                    "day": day
                                }

                                await mongo_manager.insert_question(collection, question_doc)
                                new_questions.append(question_doc)

                            except Exception as e:
                                logger.error(f"Error scraping content: {e}")

                await mongo_manager.close_connection()
                return new_questions

        except Exception as e:
            logger.error(f"Error scraping questions: {str(e)}")
            return []

def get_current_month():
    ist = pytz.timezone('Asia/Kolkata')
    current_date = datetime.now(ist)
    return f"{current_date.month:02d}"

async def send_new_questions_to_telegram(new_questions):
    bot = TelegramQuizBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_USERNAME)
    for question in new_questions:
        await bot.send_poll(question)
        await asyncio.sleep(3)

async def main():
    new_questions = await scrape_questions()
    if new_questions:
        await send_new_questions_to_telegram(new_questions)
    else:
        logger.info("No new questions found.")

async def hello(request):
    return web.Response(text="Hello, World! Telegram Quiz Bot is running.")

async def run_task(app):
    while True:
        await main()
        await asyncio.sleep(300)  # Sleep for 5 minutes (300 seconds)

app = web.Application()
app.router.add_get('/', hello)
app.on_startup.append(lambda app: asyncio.create_task(run_task(app)))

if __name__ == '__main__':
    web.run_app(app, port=8080)
