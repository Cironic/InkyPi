from plugins.base_plugin.base_plugin import BasePlugin
from PIL import Image
import os
import requests
import logging
from datetime import datetime, timezone
import pytz
from io import BytesIO
import math
import re 


logger = logging.getLogger(__name__)

UNITS = {
    "standard": {
        "temperature": "K",
        "speed": "m/s"
    },
    "metric": {
        "temperature": "°C",
        "speed": "m/s"

    },
    "imperial": {
        "temperature": "°F",
        "speed": "mph"
    }
}

WEATHER_URL = "https://api.openweathermap.org/data/3.0/onecall?lat={lat}&lon={long}&units={units}&exclude=minutely&appid={api_key}"
AIR_QUALITY_URL = "http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={long}&appid={api_key}"
GEOCODING_URL = "http://api.openweathermap.org/geo/1.0/reverse?lat={lat}&lon={long}&limit=1&appid={api_key}"

VVO_URL='https://webapi.vvo-online.de/dm'

class Weather(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['api_key'] = {
            "required": True,
            "service": "OpenWeatherMap",
            "expected_key": "OPEN_WEATHER_MAP_SECRET"
        }
        template_params['style_settings'] = True

        return template_params

    def generate_image(self, settings, device_config):
        api_key = device_config.load_env_key("OPEN_WEATHER_MAP_SECRET")
        if not api_key:
            raise RuntimeError("Open Weather Map API Key not configured.")

        lat = settings.get('latitude')
        long = settings.get('longitude')
        if not lat or not long:
            raise RuntimeError("Latitude and Longitude are required.")

        units = settings.get('units')
        if not units or units not in ['metric', 'imperial', 'standard']:
            raise RuntimeError("Units are required.")

        try:
            weather_data = self.get_weather_data(api_key, units, lat, long)
            aqi_data = self.get_air_quality(api_key, lat, long)
            location_data = self.get_location(api_key, lat, long)
            departures = self.get_departures()
        except Exception as e:
            logger.error(f"Failed to make OpenWeatherMap request: {str(e)}")
            raise RuntimeError("OpenWeatherMap request failure, please check logs.")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        timezone = device_config.get_config("timezone", default="America/New_York")
        time_format = device_config.get_config("time_format", default="12h")
        tz = pytz.timezone(timezone)
        template_params = self.parse_weather_data(weather_data, aqi_data, location_data, tz, units, time_format)
        template_params["plugin_settings"] = settings

        # Add last refresh time
        now = datetime.now(tz)
        if time_format == "24h":
            last_refresh_time = now.strftime("%Y-%m-%d %H:%M")
        else:
            last_refresh_time = now.strftime("%Y-%m-%d %I:%M %p")
        template_params["last_refresh_time"] = last_refresh_time
        template_params["departures"] = departures[:2]

        image = self.render_image(dimensions, "weather.html", "weather.css", template_params)

        if not image:
            raise RuntimeError("Failed to take screenshot, please check logs.")
        return image

    def parse_weather_data(self, weather_data, aqi_data, location_data, tz, units, time_format):
        current = weather_data.get("current")
        dt = datetime.fromtimestamp(current.get('dt'), tz=timezone.utc).astimezone(tz)
        current_icon = current.get("weather")[0].get("icon").replace("n", "d")
        location_str = f"{location_data.get('name')}, {location_data.get('state', location_data.get('country'))}"
        data = {
            "current_date": dt.strftime("%A, %B %d"),
            "location": location_str,
            "current_day_icon": self.get_plugin_dir(f'icons/{current_icon}.png'),
            "current_temperature": str(round(current.get("temp"))),
            "feels_like": str(round(current.get("feels_like"))),
            "temperature_unit": UNITS[units]["temperature"],
            "units": units,
            "time_format": time_format
        }
        data['forecast'] = self.parse_forecast(weather_data.get('daily'), tz)
        data['data_points'] = self.parse_data_points(weather_data, aqi_data, tz, units, time_format)

        data['hourly_forecast'] = self.parse_hourly(weather_data.get('hourly'), tz, time_format)
        return data

    def parse_forecast(self, daily_forecast, tz):
        """
        - daily_forecast: list of daily entries from One‑Call v3 (each has 'dt', 'weather', 'temp', 'moon_phase')
        - tz: your target tzinfo (e.g. from zoneinfo or pytz)
        """
        PHASES = [
            (0.0, "newmoon"),
            (0.25, "firstquarter"),
            (0.5, "fullmoon"),
            (0.75, "lastquarter"),
            (1.0, "newmoon"),  # API treats 1.0 same as 0.0
        ]

        def choose_phase_name(phase: float) -> str:
            # exact matches
            for target, name in PHASES:
                if math.isclose(phase, target, abs_tol=1e-3):
                    return name

            # intermediate phases
            if 0.0 < phase < 0.25:
                return "waxingcrescent"
            elif 0.25 < phase < 0.5:
                return "waxinggibbous"
            elif 0.5 < phase < 0.75:
                return "waninggibbous"
            else:  # 0.75 < phase < 1.0
                return "waningcrescent"

        forecast = []
        # skip today (i=0)
        for day in daily_forecast[1:]:
            # --- weather icon ---
            weather_icon = day["weather"][0]["icon"]  # e.g. "10d", "01n"
            # always show day‑style icon
            weather_icon = weather_icon.replace("n", "d")
            weather_icon_path = self.get_plugin_dir(f"icons/{weather_icon}.png")

            # --- moon phase & icon ---
            moon_phase = float(day["moon_phase"])  # [0.0–1.0]
            phase_name = choose_phase_name(moon_phase)
            moon_icon_path = self.get_plugin_dir(f"icons/{phase_name}.png")
            # --- true illumination percent, no decimals ---
            illum_fraction = (1 - math.cos(2 * math.pi * moon_phase)) / 2
            moon_pct = f"{illum_fraction * 100:.0f}"

            # --- date & temps ---
            dt = datetime.fromtimestamp(day["dt"], tz=timezone.utc).astimezone(tz)
            day_label = dt.strftime("%a")

            forecast.append(
                {
                    "day": day_label,
                    "high": int(day["temp"]["max"]),
                    "low": int(day["temp"]["min"]),
                    "icon": weather_icon_path,
                    "moon_phase_pct": moon_pct,
                    "moon_phase_icon": moon_icon_path,
                }
            )

        return forecast

    def parse_hourly(self, hourly_forecast, tz, time_format):
        hourly = []
        for hour in hourly_forecast[:24]:
            dt = datetime.fromtimestamp(hour.get('dt'), tz=timezone.utc).astimezone(tz)
            hour_forecast = {
                "time": self.format_time(dt, time_format),
                "temperature": int(hour.get("temp")),
                "precipitiation": hour.get("pop")
            }
            hourly.append(hour_forecast)
        return hourly

    def parse_data_points(self, weather, air_quality, tz, units, time_format):
        data_points = []
        sunrise_epoch = weather.get('current', {}).get("sunrise")

        if sunrise_epoch:
            sunrise_dt = datetime.fromtimestamp(sunrise_epoch, tz=timezone.utc).astimezone(tz)
            if time_format == "24h":
                sunrise_time = sunrise_dt.strftime('%H:%M')
                sunrise_unit = ""
            else:
                sunrise_time = sunrise_dt.strftime('%I:%M').lstrip("0")
                sunrise_unit = sunrise_dt.strftime('%p')
            data_points.append({
                "label": "Sunrise",
                "measurement": sunrise_time,
                "unit": sunrise_unit,
                "icon": self.get_plugin_dir('icons/sunrise.png')
            })
        else:
            logging.error(f"Sunrise not found in OpenWeatherMap response, this is expected for polar areas in midnight sun and polar night periods.")

        sunset_epoch = weather.get('current', {}).get("sunset")
        if sunset_epoch:
            sunset_dt = datetime.fromtimestamp(sunset_epoch, tz=timezone.utc).astimezone(tz)
            if time_format == "24h":
                sunset_time = sunset_dt.strftime('%H:%M')
                sunset_unit = ""
            else:
                sunset_time = sunset_dt.strftime('%I:%M').lstrip("0")
                sunset_unit = sunset_dt.strftime('%p')
            data_points.append({
                "label": "Sunset",
                "measurement": sunset_time,
                "unit": sunset_unit,
                "icon": self.get_plugin_dir('icons/sunset.png')
            })
        else:
            logging.error(f"Sunset not found in OpenWeatherMap response, this is expected for polar areas in midnight sun and polar night periods.")

        data_points.append({
            "label": "Wind",
            "measurement": weather.get('current', {}).get("wind_speed"),
            "unit": UNITS[units]["speed"],
            "icon": self.get_plugin_dir('icons/wind.png')
        })

        data_points.append({
            "label": "Humidity",
            "measurement": weather.get('current', {}).get("humidity"),
            "unit": '%',
            "icon": self.get_plugin_dir('icons/humidity.png')
        })

        data_points.append({
            "label": "Pressure",
            "measurement": weather.get('current', {}).get("pressure"),
            "unit": 'hPa',
            "icon": self.get_plugin_dir('icons/pressure.png')
        })

        data_points.append({
            "label": "UV Index",
            "measurement": weather.get('current', {}).get("uvi"),
            "unit": '',
            "icon": self.get_plugin_dir('icons/uvi.png')
        })

        visibility = weather.get('current', {}).get("visibility")/1000
        visibility_str = f">{visibility}" if visibility >= 10 else visibility
        data_points.append({
            "label": "Visibility",
            "measurement": visibility_str,
            "unit": 'km',
            "icon": self.get_plugin_dir('icons/visibility.png')
        })

        aqi = air_quality.get('list', [])[0].get("main", {}).get("aqi")
        data_points.append({
            "label": "Air Quality",
            "measurement": aqi,
            "unit": ["Good", "Fair", "Moderate", "Poor", "Very Poor"][int(aqi)-1],
            "icon": self.get_plugin_dir('icons/aqi.png')
        })

        return data_points

    def get_weather_data(self, api_key, units, lat, long):
        url = WEATHER_URL.format(lat=lat, long=long, units=units, api_key=api_key)
        response = requests.get(url)
        if not 200 <= response.status_code < 300:
            logging.error(f"Failed to retrieve weather data: {response.content}")
            raise RuntimeError("Failed to retrieve weather data.")

        return response.json()

    def get_air_quality(self, api_key, lat, long):
        url = AIR_QUALITY_URL.format(lat=lat, long=long, api_key=api_key)
        response = requests.get(url)

        if not 200 <= response.status_code < 300:
            logging.error(f"Failed to get air quality data: {response.content}")
            raise RuntimeError("Failed to retrieve air quality data.")

        return response.json()

    def get_location(self, api_key, lat, long):
        url = GEOCODING_URL.format(lat=lat, long=long, api_key=api_key)
        response = requests.get(url)

        if not 200 <= response.status_code < 300:
            logging.error(f"Failed to get location: {response.content}")
            raise RuntimeError("Failed to retrieve location.")

        return response.json()[0]

    def format_time(self, dt, time_format, include_am_pm=True):
        """Format datetime based on 12h or 24h preference"""
        if time_format == "24h":
            return dt.strftime("%H:%M")
        else:  # 12h format
            if include_am_pm:
                return dt.strftime("%-I:%M %p")
            else:
                return dt.strftime("%-I:%M")

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
                'plan': scheduled.strftime('%H:%M'),
                'abfahrt': real.strftime('%H:%M'),
                'gleis': dep['Platform']['Name'],
                'ziel': dep['Direction'],
                'verspaetung': delay
            })
            departures.sort(key=lambda x: datetime.strptime(x['abfahrt'], '%H:%M'))
        return departures