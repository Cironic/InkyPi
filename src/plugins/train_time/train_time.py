from plugins.base_plugin.base_plugin import BasePlugin
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
import logging

logger = logging.getLogger(__name__)

class Train(BasePlugin):

    def generate_image(self, settings, device_config):
          
        
        api_key = device_config.load_env_key("DB_CLIENT_SECRET")
        if not api_key:
            raise RuntimeError("DB API Key not configured.")
        
        db_client_id = device_config.load_env_key("DB_CLIENT_ID")
        if not db_client_id:
            raise RuntimeError("DB Client ID not configured.")
        
        try: 
            departures=self.get_departures(api_key, db_client_id)

        except Exception as e:
            logger.error(f"Failed to Request DB API: {str(e)}")
            raise RuntimeError("DB API request failure, please check logs.")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        image = self.render_image(dimensions, html_file="train_time.html", template_params={"departures": departures})
        if not image:
            raise RuntimeError("Failed to take screenshot, please check logs.")
        return image

    
    def get_departures(self, api_key, db_client_id):
        DB_URL='https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1/plan/{evaNo}/{today}/{hour}'
        headers = {
            'DB-Client-Id': db_client_id,
            'DB-Api-Key': api_key,
            'accept': 'application/xml'
            }
        evaNo = '08011427'
        today = datetime.today().strftime("%y%m%d")
        hour = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%H")
        
        response = requests.get(DB_URL.format(evaNo=evaNo, today=today, hour=hour), headers=headers)
        parsed_departures = self.parse_departures(response.content)
        return parsed_departures
    
    def parse_departures(self, xml_bytes):
        xml_string = xml_bytes.decode("utf-8")
        root = ET.fromstring(xml_string)
        departures = []

        for s in root.findall('s'):
            dp = s.find('dp')
            tl = s.find('tl')
            if dp is None or tl is None:
                continue

            # Zeitstempel in lesbares Format umwandeln (YYMMDDHHMM → datetime)
            pt = dp.attrib.get('pt')
            if not pt or len(pt) != 10:
                continue
            dt = datetime.strptime(pt, "%y%m%d%H%M")

            zugnummer = f"{tl.attrib.get('c', '')}{tl.attrib.get('n', '')}"
            gleis = dp.attrib.get('pp', '?')
            ppth = dp.attrib.get('ppth', '')
            ziel = ppth.split('|')[-1] if ppth else 'Unbekannt'

            departures.append({
                'zug': zugnummer,
                'abfahrt': dt.strftime('%H:%M'),
                'gleis': gleis,
                'ziel': ziel,
                'verspaetung': 0  # Kein Delay in XML enthalten
            })
        return departures
