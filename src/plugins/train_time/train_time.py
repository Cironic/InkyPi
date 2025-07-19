from plugins.base_plugin.base_plugin import BasePlugin
from datetime import datetime
import requests
import logging
import re 

logger = logging.getLogger(__name__)

VVO_URL='https://webapi.vvo-online.de/dm'

class Train(BasePlugin):
    def generate_image(self, settings, device_config):
        api_key = 'e66ed4c930cffd68921f09b9d16496ff'
        if not api_key:
            raise RuntimeError("DB API Key not configured.")
        
        try:
            departures = self.get_departures()
        except Exception as e:
            logger.error(f"Failed to request VVO API: {str(e)}")
            raise RuntimeError("VVO API request failure, please check logs.")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        image = self.render_image(
            dimensions,
            html_file="train_time.html",
            template_params={"departures": departures}
        )

        if not image:
            raise RuntimeError("Failed to take screenshot, please check logs.")
        return image
        
    @staticmethod
    def parse_date(date_str):
        timestamp = int(re.search(r'\d+', date_str).group(0)) / 1000
        return datetime.fromtimestamp(timestamp)
    
    def get_departures(self):
        VVO_URL='https://webapi.vvo-online.de/dm'
        stopId=33000622
        time=datetime.now().isoformat()
        response = requests.post(VVO_URL,json={'stopId':stopId, 'time':time, "Mot":"SuburbanRailway"})
        parsed_departures = self.parse_departures(response.json())
        return parsed_departures
    
    def parse_departures(self, response):
        departures = []
        for dep in response['Departures']:
            scheduled = self.parse_date(dep['ScheduledTime'])
            real = self.parse_date(dep['RealTime'])
            delay = int((real - scheduled).total_seconds() / 60)

            departures.append({
                'zug': dep['LineName'],
                'abfahrt': real.strftime('%H:%M'),
                'gleis': dep['Platform']['Name'],
                'ziel': dep['Direction'],
                'verspaetung': delay
            })
            departures.sort(key=lambda x: datetime.strptime(x['abfahrt'], '%H:%M'))
        return departures


    
