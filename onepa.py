from scraper import *

class onepa(Scraper):
    def __init__(self):
        super().__init__()
        self.name = 'onePA'
        self.dateTimeStringFormat = '%d/%m/%Y %I:%M %p'
        # [todo] activites id below is wrong. it is actually facility id. look at how to fix this in future
        self.activities = [{'name': 'badminton', 'id': '4040ccmcpa-bm'}]
        self.urls = {
            'main': 'https://www.onepa.sg/facilities/4040ccmcpa-bm',
        }
    
    def _preScrape(self):
        # construct dates to scrape
        today = sgTimezone.localize(datetime.datetime.now()).replace(hour=0, minute=0, second=0)
        self.datesToScrape = [(today + datetime.timedelta(days=n)).strftime('%d/%m/%Y') for n in range (0, self.daysToScrape)]

        # set current scrape time
        self.currentScrapeStartDate = sgTimezone.localize(datetime.datetime.now())
        self.currentScrapeStartDateStr = self.currentScrapeStartDate.strftime("%d/%m/%Y, %H:%M:%S")
        

    def _keyFormatter(self, key_string):
        output = key_string.strip().upper().replace(' ', '_')
        return output
    
    @retry()
    def _getLocationData(self):
        """
        Get available locations
        """
        location_data = []
        response_courts = self.session.get(self.urls['main'])
        if response_courts.ok:
            bs = BeautifulSoup(response_courts.text, 'html.parser')
            location_list = bs.find('select', {'name':'content_0$ddlFacilityLocation'}).findAll('option')

            for loc in location_list:
                # create a dummy facility data with minimal info first
                facilityData = {
                    'source': self.name,
                    'source_id': '{}'.format(loc['value']),
                    'name': loc.text,
                    'address': '',
                    'postal_code': -1,
                    'loc' : {
                        'type' : "Point",
                        'coordinates' : [-1, -1]
                    },
                    'no_of_spaces': -1,
                    'weekdays_avail': [-1,-1,-1,-1,-1],
                    'weekends_avail': [-1,-1],          
                }

                location_data.append(facilityData)
        return location_data
    
    def _buildDateTemplatePayload(self, date):
        """
        This builds a payload containing a viewState with a specific date. 
        The output of this function has no "location" data.

        PRE-REQUISITE: This function requries "session" and "response_courts".
        """
        template_payload = False

        try:     
            # prepare an (almost) empty payload. most importantly, there is no viewState in the payload
            payload_bait = {}
            payload_bait['content_0$tbDatePicker'] = date
            payload_bait['content_0$ddlFacilityLocation'] = ''

            # send this (incomplete) payload to onePA, and trick onePA to send us back a response containing the complete payload
            response_specificDate = self.session.post(self.urls['main'], data=payload_bait)

            # after this, start building an acutal output payload
            if response_specificDate.ok:
                # define an empty payload
                payload = {}

                # pass the response data to BeautifulSoup
                bs = BeautifulSoup(response_specificDate.text, 'html.parser')
                l_inputs = bs.find(id="form1").findAll('input')

                # scrape the existing input values
                for inp in l_inputs:
                    # if matches any of the following input types, we will skip it
                    banned_types = ['checkbox', 'image', 'submit', 'button']
                    if inp['type'] in banned_types:
                        continue

                    key = inp['name']
                    if 'value' in inp.attrs.keys():
                        value = inp['value']
                    else:
                        # some input have no attribute "value". in this case, we will assign a blank value to it
                        value = ''

                    # add this key/pair to the payload
                    payload[key]=value

                # this payload will not have a date value, we will add this in manually
                payload['content_0$tbDatePicker'] = date

                # additional key/pair required by onePA website
                payload['hiddenInputToUpdateATBuffer_CommonToolkitScripts'] = '1'

                # set output as payload
                template_payload = payload
            else:
                print(response_specificDate.status_code)

        except Exception as e:
            #error handling
            print(e)
            traceback.print_exc()

        return template_payload
    
    def _buildCompletePayloadWithLocation(self, payload, location_id):
        """
        Using a response that contains a viewState with a specific date, this adds on location data to that payload.

        Please use this after using "buildDateTemplatePayload".

        PRE-REQUISITE: This function requries "location_data".
        """

        # set the desired location
        payload['content_0$ddlFacilityLocation'] = location_id

        return payload
    
    @retry()
    def _getSlots(self, payload):
        """
        Using a complete payload, we can request the avalability of the courts.

        Please use this after using "buildCompletePayloadWithLocation".

        PRE-REQUISITE: This function requries "courts".
        """
        try:
            output = {}

            response = self.session.post(self.urls['main'], data=payload)
            if response.ok:
                bs = BeautifulSoup(response.text, 'html.parser')

                # get facility information
                postal_long_lat = response.text.split("GetLatLongFromPostalCode(")[1].split(");")[0].replace("'","").replace(" ","").split(",");
                facility = bs.find("div", {"id":"oneMapContainer"})
                facilityData = {
                    'source': self.name,
                    'source_id': bs.find("select", {"name":"content_0$ddlFacilityLocation"}).find("option", {"selected":"selected"})['value'],
                    'name': facility['data-modal-title'],
                    'address': facility.find("p").find("span").text.strip(),
                    'postal_code': postal_long_lat[0],
                    'loc' : {
                        'type' : "Point",
                        'coordinates' : [float(postal_long_lat[1]), float(postal_long_lat[2])]
                    },
                }

                # get list of timeslots
                timeslots = bs.find("div", {"class":"timeslotsContainer"}).findAll("div", {"class": "slots"})

                # get list of availability
                #soup_slots.find("div", {"class":"facilitiesType"}).findAll("span", {"class": re.compile("^slots ")})
                location_courts = bs.find_all("div", {"class":"facilitiesType"})
                if location_courts == None:
                    return output

                else:
                    for n in range(len(location_courts)):
                        court = location_courts[n]

                        #court_n = str(n+1)
                        court_n = court.select('div[class="slotsTitle"] span')[0].text.lower().replace('court', '').strip()

                        print('Court_' + court_n)

                        # c_item = []
                        # c_item['court']=court_n
                        c_item = {}

                        availability = court.select('span[class^="slots"]')

                        # s_list = []
                        s_list = {}
                        if len(timeslots) == len(availability):
                            for i in range(len(timeslots)):
                                timeslot_data = timeslots[i].text
                                timeslot_start = timeslot_data.split('-')[0].strip()

                                # remove the item called "slots", then return the first item in the list
                                availability_data = availability[i]['class']
                                availability_data.remove('slots')
                                availability_data = availability_data[0]

                                # print(timeslot_data, availability_data)

                                s_item = {}

                                s_item['timeslot'] = timeslot_data
                                s_item['availability'] = availability_data

                                #s_list.append(s_item)
                                s_list[timeslot_start] = s_item
                        else:
                            print("data is weird")

                        #c_item['slots'] = s_list
                        c_item = s_list

                        #output.append(c_item)
                        #output['Court {:02d}'.format(int(court_n))] = c_item
                        output['Court {}'.format(court_n)] = c_item

                    return output, facilityData
            else:
                print(response.status_code)

            # if error has occured, then we will reach this line
            return response
        except Exception as e: 
            print(e)
            self.informTelegram('_getSlots', 'ERROR -', e)
    
    def _prepareSession(self):
        return True
        
    def _scrapeProcess(self):
        try:
            location_data = self._getLocationData()
            for location in location_data:
                source = location['source']
                source_id = location['source_id']
                name = location['name']

                countOfExisting = collection_facilities.count_documents({'source': source, 'source_id': source_id})

                if countOfExisting == 0:
                    insertId = collection_facilities.insert_one(location).inserted_id
                    print('New location detected, adding as a facility - {} - {} - {} '.format(name, source_id, insertId))
                else:
                    print('Location already exists as a facility - {} - {}'.format(name, source_id))
        except Exception as e: 
            print(e)
            self.informTelegram('_scrapeProcess', 'ERROR (getLocationData) -', e)

            
        for activity in self.activities:
            for date in self.datesToScrape:
                try:
                    self.delay()
                    slots_data_temp = {}
                    slots_data_temp['retrieved_dateTime'] = self.currentScrapeStartDate

                    date_arr = date.split('/')
                    slots_data_temp['date'] = '{}-{}-{}'.format(date_arr[2],date_arr[1], date_arr[0])

                    # define sport
                    slots_data_temp['sport'] = activity['name']
                    slots_data_temp['sport_source_id'] = activity['id']

                    date_templatePayload = self._buildDateTemplatePayload(date)
                    #print(date_templatePayload)

                    # loop through every badminton court
                    for loc in location_data:
                        try:
                            locationKey=loc['name']
                            location_id=loc['source_id']

                            slots_data = copy.deepcopy(slots_data_temp)
                            slots_data['facility']=locationKey 
                            #print(locationKey)
                            completePayload = self._buildCompletePayloadWithLocation(date_templatePayload, location_id)

                            timeslotsData, facilityData = self._getSlots(completePayload)

                            # availalbility mapping to integer
                            availabilityMapping = {
                                'notAvailable': -1,
                                'booked': 0,
                                'normal': 1,
                                'peak': 2,
                            }

                            # modify timeslotsData to include StartTime and EndTime
                            for court in timeslotsData.values():
                                for slotData in court.values():
                                    timings = slotData['timeslot'].split('-')

                                    slotData['startTime'] = self.string_to_dateTime('{} {}'.format(date, timings[0].strip()))
                                    slotData['endTime'] = self.string_to_dateTime('{} {}'.format(date, timings[1].strip()))
                                    slotData['duration'] = divmod((slotData['endTime'] - slotData['startTime']).total_seconds(), 3600)[0] 

                                    slotData['status'] = availabilityMapping[slotData['availability']]

                            # construct the data
                            slots_data['courts'] = timeslotsData
                            slots_data['facility'] = collection_facilities.find_one({'source': self.name, 'source_id': loc['source_id']})
                            #print(slots_data)

                            print(slots_data)

                            # save to mongodb
                            insertId = collection_timeslots.insert_one(slots_data).inserted_id
                            print('New timeslot data inserted for - {} - {} - {} '.format(facilityData['name'], slots_data['date'], insertId))     
                    
                        except Exception as e: 
                            print(e)
                            self.informTelegram('_scrapeProcess', 'ERROR {} {} -'.format(date, loc['name']), e)
                except Exception as e: 
                    print(e)
                    self.informTelegram('_scrapeProcess', 'ERROR {} -'.format(date), e)

        
        self.updateScrapeHistory(self.name, self.currentScrapeStartDate)

