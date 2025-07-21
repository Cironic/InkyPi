from plugins.base_plugin.base_plugin import BasePlugin
from plugins.weather.weather import Weather
from datetime import datetime
import pytz
import requests
import logging
import re 

logger = logging.getLogger(__name__)

VVO_URL='https://webapi.vvo-online.de/dm'

weather_plugin = Weather(BasePlugin)

class Train(BasePlugin):
    def generate_image(self, settings, device_config):
        
        try:
            departures = self.get_departures()
            weather_json, aqi_json, location_json, tz, units, time_format = self.get_weather_components(settings, device_config)
            weather_data = weather_plugin.parse_weather_data(
                weather_data=weather_json,
                aqi_data=aqi_json,
                location_data=location_json,
                tz=tz,
                units=units,
                time_format=time_format
            )
        except Exception as e:
            logger.error(f"Failed to request VVO API: {str(e)}")
            raise RuntimeError("VVO API request failure, please check logs.")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        image = self.render_image(
            dimensions,
            html_file="train_time.html",
            template_params = {
                "departures": departures[:2],
                "last_refresh_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "current_temperature": weather_data["current_temperature"],
                "current_day_icon": weather_data["current_day_icon"],
                "temperature_unit": weather_data["temperature_unit"],
                "data_points": weather_data["data_points"],
            }
        )

        if not image:
            raise RuntimeError("Failed to take screenshot, please check logs.")
        return image
    
    def get_weather_components(settings, device_config):
        weather_plugin.get_location("")
        lat = "51.08500382549591"
        lon = "13.71067464351654"
        timezone = pytz.timezone(device_config.get_config("timezone", default="Europe/Berlin"))
        units = "metric"
        time_format = "24h"
        api_key = device_config.load_env_key("OPEN_WEATHER_MAP_SECRET")

        weather_json = weather_plugin.get_weather_data(api_key, units, lat, lon)
        aqi_json = weather_plugin.get_air_quality(api_key, lat, lon)
        location_json = weather_plugin.get_location(api_key, lat, lon)

        return weather_json, aqi_json, location_json, timezone, units, time_format


    @staticmethod
    def parse_date(date_str):
        timestamp = int(re.search(r'\d+', date_str).group(0)) / 1000
        return datetime.fromtimestamp(timestamp)
    
    def get_departures(self):
        VVO_URL='https://webapi.vvo-online.de/dm'
        stopId=33000622
        time=datetime.now().isoformat()
        response = requests.post(VVO_URL,json={'stopId':stopId, 'time':time, "Mot":"SuburbanRailway"})
        return self.parse_departures(response.json())
    
    def parse_departures(self, response):
        departures = []
        for dep in response['Departures']:
            scheduled = self.parse_date(dep['ScheduledTime'])
            real = self.parse_date(dep['RealTime'])
            delay = int((real - scheduled).total_seconds() / 60)

            departures.append({
                'zug': dep['LineName'],
                'plan': scheduled.strftime('%H:%M'),  # NEU
                'abfahrt': real.strftime('%H:%M'),
                'gleis': dep['Platform']['Name'],
                'ziel': dep['Direction'],
                'verspaetung': delay
            })
            departures.sort(key=lambda x: datetime.strptime(x['abfahrt'], '%H:%M'))
        return departures


    
