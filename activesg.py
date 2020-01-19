from scraper import *
from config import config

# active sg specific
import base64
from Crypto.Cipher import PKCS1_v1_5 as Cipher_pkcs1_v1_5
from Crypto.PublicKey import RSA

class activesg(Scraper):
    def __init__(self):
        super().__init__()
        self.name = 'ActiveSG'
        self.dateTimeStringFormat = '%Y-%m-%d %I:%M %p'
        self.login = config['activesg']['login']
        self.password = config['activesg']['password']
        self.activities = [{'name': 'badminton', 'id': 18}]
        self.urls = {
            'landing': 'https://members.myactivesg.com/auth',
            'login': 'https://members.myactivesg.com/auth/signin',
            'facilityInfo': 'https://www.myactivesg.com/Facilities/{}',
            'venuesForActivity': 'https://members.myactivesg.com/ajax/getVenues/{}',
            'slots': 'https://members.myactivesg.com/facilities/ajax/getTimeslots?activity_id={}&venue_id={}&date={}&time_from={}',
        }
    
    def _preScrape(self):
        # construct dates to scrape
        today = sgTimezone.localize(datetime.datetime.now()).replace(hour=0, minute=0, second=0)
        self.datesToScrape = [(today + datetime.timedelta(days=n)).strftime('%Y-%m-%d') for n in range (0, self.daysToScrape)]

        # set current scrape time
        self.currentScrapeStartDate = sgTimezone.localize(datetime.datetime.now())
        self.currentScrapeStartDateStr = self.currentScrapeStartDate.strftime("%d/%m/%Y, %H:%M:%S")
    
    def _encryptStr(self, toEncryptStr, public_key):
        rsakey = RSA.importKey((public_key))
        cipher = Cipher_pkcs1_v1_5.new(rsakey)
        encrypted_PASS = str(base64.b64encode(cipher.encrypt(toEncryptStr)), 'utf-8')
        
        return encrypted_PASS
        
    def _getSgUnixTime(self, year, month, day, hour=0, minute=0):
        """
        Returns a string and unix time (in Singapore timezone) for a specified date (and time if needed).
        """
        targetDate = datetime.datetime.now(pytz.timezone('Asia/Singapore')).replace(second=0, microsecond=0)

        if year != None and month != None and hour != None:
            targetDate = targetDate.replace(
                year=int(year), 
                month=int(month), 
                day=int(day), 
                hour=int(hour), 
                minute=int(minute), 
            )


        date_string = '{0:04d}-{1:02d}-{2:02d}'.format(targetDate.year, targetDate.month, targetDate.day)
        date_unixSeconds = int(targetDate.timestamp())

        return [date_string, date_unixSeconds]
    
    @retry()
    def _prepareSession(self):
        try:
            # send request to login page
            res_preLogin = self.session.get(self.urls['landing'])

            # get CSRF token
            csrf = res_preLogin.text.split('name="_csrf" value="')[1].split('"')[0].strip()

            # get encrypted pass
            public_key = res_preLogin.text.split('name="rsapublickey" value="')[1].split('"')[0].strip()        
            encrypted_PASS = self._encryptStr(self.password, public_key)

            # sign in
            auth_payload = {
                'email': self.login,
                'ecpassword': encrypted_PASS,
                '_csrf': csrf,
            }
            res_signin = self.session.post(self.urls['login'], data=auth_payload)
            
            return res_signin.ok
        
        except Exception as e: 
            print(e)
            self.informTelegram('_prepareSession', 'ERROR -', e)

    def _getFacilitiesData(self, facilityName):
        try:
            facility_slug = facilityName.lower().replace(' ', '-')

            facilities_response = self.session.get(self.urls['facilityInfo'].format(facility_slug))
            bs = BeautifulSoup(facilities_response.text, 'html.parser')

            address_dataArray = bs.find("div", {"class":"facility-address"}).find("p").text.split("Singapore")
            address = address_dataArray[0].strip()
            postal = address_dataArray[1].strip()

            latlng_dataArray = bs.find("i", {"class":"icon icon-location"}).parent['href'].split('q=')[1].split(',')
            lat = float(latlng_dataArray[0].strip())
            lng = float(latlng_dataArray[1].strip())

            image = 'https://www.myactivesg.com' + bs.find("div", {"class":"gallery-image background"}).find('img')['src']

            return {
                "address":address, 
                "postal":postal, 
                "lat":lat, 
                "lng":lng, 
                "image":image, 
            }

        except Exception as e: 
            print(e)
            #self.informTelegram('_getFacilitiesData', 'ERROR - {}'.format(facilityName), e)

            return {
                "address":"", 
                "postal":"", 
                "lat":-1, 
                "lng":-1, 
                "image":"", 
            }
        
    def _getSlots(self, activityId, locationId, date_data):
        try:
            TARGET_URL = self.urls['slots'].format(activityId, locationId, date_data[0], date_data[1])
            #print(TARGET_URL)

            response_timeslots = self.session.get(TARGET_URL, headers=self.headers_ajax)

            if (response_timeslots.ok):
                #print(response_timeslots.text)
                bs = BeautifulSoup(response_timeslots.text.replace('\\',''), 'html.parser')
                location_courts = bs.findAll("div", {"class": "subvenue-slot"})

                output = {'status': 'success', 'locationId':locationId, 'activityId':activityId, 'date_data': date_data, "data":{}}
                for i in range(len(location_courts)):
                    court = location_courts[i];

                    courtName = court.find("h4",{"class":"fac-court-name"}).text

                    output['data'][courtName] = {}

                    timeslots = court.findAll("div", {"class": "chkbox-grid"});
                    for j in range(len(timeslots)):
                        slot = timeslots[j]

                        time = slot.find('label').text
                        available = (slot.find('input', {"type": 'checkbox'}).has_attr('disabled') == False)
                        output['data'][courtName][time] = int(available)
                #print(output)
                return output
            else:
                return {'status':'error', "data": response_timeslots.status_code}

        except Exception as e: 
            print(e)
            self.informTelegram('_getSlots', 'ERROR -', e)
    
    def _scrapeProcess(self):        
        for activity in self.activities:
            # get venues
            facilityIds = {}
            
            try:
                response_facilityIds = self.session.get(self.urls['venuesForActivity'].format(activity['id']), headers=self.headers_ajax)
                if (response_facilityIds.ok):
                    dict_data = json.loads(response_facilityIds.text)
                    print(dict_data.keys())

                    for venueDict in dict_data['venues']:
                        key = venueDict['name']
                        value = venueDict['venue_id']

                        facilityIds[key] = value

            except Exception as e: 
                self.informTelegram('_scrapeProcess', 'ERROR facilityIds -', e)

            for facility in list(facilityIds.items()):
                try:
                    print('Scraping: {}'.format(facility))
                    # ('Admiralty Primary School Hall', '968')
                    facility_name = facility[0]
                    source_id = facility[1]

                    # create a dummy facility data with minimal info first
                    facility_info_from_activesg = self._getFacilitiesData(facility_name)
                    facilityData = {
                        'source': self.name,
                        'source_id': '{}'.format(source_id),
                        'name': facility_name,
                        'address': facility_info_from_activesg['address'],
                        'postal_code': facility_info_from_activesg['postal'],
                        'loc' : {
                            'type' : "Point",
                            'coordinates' : [facility_info_from_activesg['lng'], facility_info_from_activesg['lat']]
                        },
                        'no_of_spaces': -1,
                        'weekdays_avail': [-1,-1,-1,-1,-1],
                        'weekends_avail': [-1,-1],          
                    }


                    countOfExisting = collection_facilities.count_documents({'source': self.name, 'source_id': source_id})

                    if countOfExisting == 0:
                        insertId = collection_facilities.insert_one(facilityData).inserted_id
                        print('New facility detected, adding - {} - {} - {} '.format(facility_name, source_id, insertId))
                    else:
                        print('Facility already exists - {} - {}'.format(facility_name, source_id))
                
                except Exception as e: 
                    self.informTelegram('_scrapeProcess', 'ERROR getFacilityData {} -'.format(facility_name), e)


                # scrape timeslots
                for date in self.datesToScrape:
                    try:
                        date_arr = date.split('-')
                        date_data = self._getSgUnixTime(date_arr[0],date_arr[1], date_arr[2])
                        # ("2019-12-25", 1231232313)
                        date_str = date_data[0]

                        slots_data_template = {}
                        slots_data_template['retrieved_dateTime'] = self.currentScrapeStartDate
                        slots_data_template['date'] = date
                        slots_data_template['sport'] = activity['name']
                        slots_data_template['sport_source_id'] = activity['id']

                        getSlots_result = self._getSlots(activity['id'], source_id, date_data)

                        if getSlots_result['status'] != 'success':
                            #print('error', getSlots_result['data'])
                            continue
                        else:
                            self.delay()
                            getSlots_data = getSlots_result['data']
                            print('Scraping: {} {}'.format(facility, date))
                            #print(getSlots_data)

                            slots_data = copy.deepcopy(slots_data_template)
                            slots_data['facility'] = collection_facilities.find_one({'source': self.name, 'source_id': source_id})
                            slots_data['courts'] = {};

                            # modify timeslotsData to include StartTime and EndTime
                            for courtName, slotsObj in getSlots_data.items():
                                slots_data['courts'][courtName] = {}
                                duration_in_hours = 1

                                for slotName, slotAvailability in slotsObj.items():
                                    startTime = self.string_to_dateTime('{} {}'.format(date_str, slotName));
                                    slots_data['courts'][courtName][slotName] = {
                                        'startTime': startTime,
                                        'endTime': startTime + datetime.timedelta(hours=duration_in_hours),
                                        'duration': duration_in_hours,
                                        'status': slotAvailability
                                    }

                            print(slots_data)

                            # save to mongodb
                            insertId = collection_timeslots.insert_one(slots_data).inserted_id
                            print('New timeslot data inserted for - {} - {} - {} '.format(facility_name, slots_data['date'], insertId))
                    
                    except Exception as e: 
                        self.informTelegram('_scrapeProcess', 'ERROR getSlots {} {} -'.format(facility_name, date), e)
                        
        
        self.updateScrapeHistory(self.name, self.currentScrapeStartDate)