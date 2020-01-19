from config import config
import requests
import json
import copy
import time, datetime
import pytz
from bs4 import BeautifulSoup
sgTimezone = pytz.timezone('Asia/Singapore')

import pymongo
from pymongo import MongoClient
client = MongoClient('mongodb://{}:{}/'.format(config['mongodb_host'], config['mongodb_port']))

# https://codereview.stackexchange.com/questions/188539/python-code-to-retry-function
import functools
def retry(retry_count=3, delay=5, allowed_exceptions=()):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            for _ in range(retry_count):
                #print(_)
                try:
                    result = f(*args, **kwargs)
                    if result: return result
                except allowed_exceptions as e:
                    pass

        return wrapper
    return decorator

# define database to use
db = client['fitnest']

# define collections
collection_facilities = db['facilities']
collection_timeslots = db['timeslots']
collection_scrapeHistory = db['scrapeHistory']

class Scraper:
    def __init__(self):
        self.name = ""
        self.headers = {
            'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/73.0.3683.75 Safari/537.36"
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.headers_ajax = {
            'X-Requested-With': 'XMLHttpRequest',
        }
        self.dateTimeStringFormat = '%Y-%m-%d %I:%M %p'
        self.daysToScrape = 14
        self.datesToScrape = []
        self.currentScrapeStartDate = None
        self.currentScrapeStartDateStr = ""
        self.scrapeLoopDelay = 60*(60+30)      #1.5 hours

    def change_name(self, new_name):
        self.name = new_name
    
    def delay(self, seconds=1.5):
        time.sleep(seconds)
    
    def string_to_dateTime(self, date_time_str):
        date_time_obj = datetime.datetime.strptime(date_time_str, self.dateTimeStringFormat)
        timezone_date_time_obj = sgTimezone.localize(date_time_obj)

        return timezone_date_time_obj
    
    def updateScrapeHistory(self, source, scrapeStart):
        check_count = collection_timeslots.count_documents({'facility.source': source, 'retrieved_dateTime': scrapeStart})

        if check_count > 25:  # arbitiary number, just to prevent incomplete data
            post = {
                "source": source,
                "scrapeStart": scrapeStart,
                "scrapeEnd": sgTimezone.localize(datetime.datetime.now())
            }

            collection_scrapeHistory.insert_one(post)
    
    @retry()
    def _sendUpdateToBot(self, message):
        BOT_TOKEN = config['telegram_bot_token']
        CHAT_ID = config['telegram_chat_id']

        send = requests.get("https://api.telegram.org/bot{}/sendMessage?chat_id={}&text={}".format(BOT_TOKEN, CHAT_ID, message))
        return send.ok

    def informTelegram(self, source, state, message = ''):
        result = self._sendUpdateToBot('{} {}: {} {}'.format(self.name, source, state, message))
        return result
                
    def _preScrape(self):
        return
    
    def _postScrape(self):
        return
    
    def scrapeAll(self):
        self._prepareSession()
        self._preScrape()
        self._scrapeProcess()
        self._postScrape()
        self.informTelegram(self.name, 'Success', '- started from {}'.format(self.currentScrapeStartDateStr))
  
    def scrapeLoop(self):
        while True:
            try:
                today = sgTimezone.localize(datetime.datetime.now())

                if today.hour > 5 or today.hour < 1:
                    self.scrapeAll()
            except Exception as e:
                print(e)
                statusUpdate('scrapeLoop', 'ERROR', '{}'.format(e))

            self.delay(self.scrapeLoopDelay)