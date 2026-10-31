#!/usr/bin/env python3

import json
import random
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

# noinspection PyPackageRequirements
from luma.core.interface.serial import spi, noop
# noinspection PyPackageRequirements
from luma.led_matrix.device import max7219
from PIL import Image, ImageDraw

CONFIG_PATH = Path(__file__).resolve().with_name("config.json")
with CONFIG_PATH.open(encoding="utf-8") as config_file:
    CONFIG = json.load(config_file)

DISPLAY_CONFIG = CONFIG["display"]
LOCATION_CONFIG = CONFIG["location"]
TIMING_CONFIG = CONFIG["timing"]
BRIGHTNESS_CONFIG = CONFIG["brightness"]
API_CONFIG = CONFIG["api"]

serial = spi(port=0, device=0, gpio=noop())
device = max7219(
    serial,
    cascaded=DISPLAY_CONFIG["cascaded_modules"],
    block_orientation=DISPLAY_CONFIG["block_orientation"],
    rotate=DISPLAY_CONFIG["rotate"],
)
device.contrast(DISPLAY_CONFIG["initial_contrast"])

WIDTH, HEIGHT = 8 * DISPLAY_CONFIG["cascaded_modules"], 8
GRAZ_LAT = LOCATION_CONFIG["latitude"]
GRAZ_LON = LOCATION_CONFIG["longitude"]
WEATHER_REFRESH_SECONDS = TIMING_CONFIG["weather_refresh_seconds"]
WEATHER_TIMEOUT_SECONDS = TIMING_CONFIG["weather_timeout_seconds"]
METALS_TIMEOUT_SECONDS = TIMING_CONFIG["metals_timeout_seconds"]
SCREEN_SLOT_SECONDS = TIMING_CONFIG["screen_slot_seconds"]
WEATHER_WINDOW_SECONDS = SCREEN_SLOT_SECONDS * 3
MINUTE_ANIMATION_SECONDS = TIMING_CONFIG["transition_seconds"]
NIGHT_CONTRAST = BRIGHTNESS_CONFIG["night_contrast"]
OVERCAST_DAY_CONTRAST = BRIGHTNESS_CONFIG["overcast_day_contrast"]
CLEAR_DAY_CONTRAST = BRIGHTNESS_CONFIG["clear_day_contrast"]
TWILIGHT_RAMP_MINUTES = BRIGHTNESS_CONFIG["twilight_ramp_minutes"]

# Bold 5x7 pixel-block digits, centered in each 8x8 matrix.
DIGITS = {
    "0": ("11111", "10001", "10011", "10101", "11001", "10001", "11111"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("11110", "00001", "00001", "11110", "10000", "10000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("10010", "10010", "10010", "11111", "00010", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01111", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "11110"),
}
METAL_LABEL_GLYPHS = {
    "silver": ("01111", "11000", "11100", "01110", "00011", "11011", "11110"),
}

# Compact 3x5 glyphs used for temperature on the 32x8 weather screen.
SMALL = {
    "0": ("111", "101", "101", "101", "111"), "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"), "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"), "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"), "9": ("111", "101", "111", "001", "111"),
    "-": ("000", "000", "111", "000", "000"), "C": ("111", "100", "100", "100", "111"),
}

# Minus-sign glyphs for weather values and sun-time labels.
SUN_TIME_GLYPHS = {
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
}

WEATHER_GLYPHS = {
    "-": ("000", "000", "000", "111", "000", "000", "000"),
    "°": ("11", "11"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "%": ("11000", "11001", "00010", "00100", "01000", "10011", "00011"),
}

# WMO code groups: the small display icon communicates the main condition.
# Includes the WMO codes returned for Graz by the weather service.
CODE_DESCRIPTION = {
    0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog", 51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle",
    56: "Freezing drizzle", 57: "Freezing drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Freezing rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow",
    77: "Snow grains", 80: "Showers", 81: "Showers", 82: "Heavy showers",
    85: "Snow showers", 86: "Heavy snow showers", 95: "Thunderstorm", 96: "Thunderstorm/hail",
    97: "Heavy thunderstorm", 99: "Thunderstorm/hail",
}

# Direct 5x7 weather icons sized for the display.
ICONS = {
    "sun": ("00100", "10101", "01110", "11111", "01110", "10101", "00100"),
    "cloud": ("00100", "01110", "11111", "11111", "01111", "00000", "00000"),
    "partly": ("00100", "10101", "01110", "00111", "01111", "11111", "00000"),
    "rain": ("00100", "01110", "11111", "11111", "01110", "10101", "01010"),
    "snow": ("00100", "01110", "11111", "01110", "10101", "01110", "10101"),
    "storm": ("00100", "01110", "11111", "01110", "00100", "01100", "01000"),
    "fog": ("00000", "11111", "00000", "01110", "00000", "11111", "00000"),
    "unknown": ("01110", "10001", "00001", "00110", "00100", "00000", "00100"),
}
RAIN_CHANCE_ICON = ("00100", "01110", "11111", "10101", "00100", "00100", "00110")

SUNRISE_ARROW = ("00100", "01110", "11111", "00100", "00100", "00100", "00100")
SUNSET_ARROW = ("00100", "00100", "00100", "00100", "11111", "01110", "00100")
TEMPERATURE_TREND_GLYPHS = {
    "up": SUNRISE_ARROW,
    "down": SUNSET_ARROW,
    "steady": ("00000", "00100", "00010", "11111", "00010", "00100", "00000"),
}

weather_lock = threading.Lock()
DisplayData = Dict[str, Any]
Glyph = Tuple[str, ...]

weather_data: Optional[DisplayData] = None
last_fetch_ok = False
metals_lock = threading.Lock()
metal_data: Optional[DisplayData] = None

# Uppercase 3x5 alphabet for compact labels and the scrolling message.
LETTERS = {
    "A": ("010", "101", "111", "101", "101"), "B": ("110", "101", "110", "101", "110"),
    "C": ("011", "100", "100", "100", "011"), "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"), "F": ("111", "100", "110", "100", "100"),
    "G": ("011", "100", "101", "101", "011"), "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"), "J": ("001", "001", "001", "101", "010"),
    "K": ("101", "101", "110", "101", "101"), "L": ("100", "100", "100", "100", "111"),
    "M": ("101", "111", "111", "101", "101"), "N": ("101", "101", "111", "101", "101"),
    "O": ("010", "101", "101", "101", "010"), "P": ("110", "101", "110", "100", "100"),
    "Q": ("010", "101", "101", "111", "011"), "R": ("110", "101", "110", "101", "101"),
    "S": ("111", "100", "111", "001", "111"), "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "111"), "V": ("101", "101", "101", "101", "010"),
    "W": ("101", "101", "101", "111", "101"), "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"), "Z": ("111", "001", "010", "100", "111"),
    ":": ("000", "010", "000", "010", "000"), ".": ("000", "000", "000", "000", "010"),
    "/": ("001", "001", "010", "100", "100"), "%": ("101", "001", "010", "100", "101"),
}

# A small 2x3 alphabet keeps the date, network state, and sun times on two lines.
TINY = {
    "A": ("11", "11", "11"), "B": ("10", "11", "10"), "C": ("11", "10", "11"),
    "D": ("10", "11", "10"), "E": ("11", "10", "11"), "F": ("11", "10", "10"),
    "G": ("11", "10", "11"), "H": ("10", "11", "10"), "I": ("11", "01", "11"),
    "J": ("01", "01", "11"), "K": ("10", "11", "10"), "L": ("10", "10", "11"),
    "M": ("11", "11", "10"), "N": ("10", "11", "11"), "O": ("11", "10", "11"),
    "P": ("11", "11", "10"), "Q": ("11", "11", "01"), "R": ("11", "11", "10"),
    "S": ("11", "01", "11"), "T": ("11", "01", "01"), "U": ("10", "10", "11"),
    "V": ("10", "10", "01"), "W": ("10", "11", "11"), "X": ("10", "01", "10"),
    "Y": ("10", "01", "01"), "Z": ("11", "01", "11"),
    "0": ("11", "10", "11"), "1": ("01", "01", "01"), "2": ("11", "01", "10"),
    "3": ("11", "01", "11"), "4": ("10", "11", "01"), "5": ("11", "10", "11"),
    "6": ("11", "10", "11"), "7": ("11", "01", "01"), "8": ("11", "11", "11"),
    "9": ("11", "11", "01"), ":": ("00", "01", "00"), "-": ("00", "11", "00"),
}

# Compact combined mark used when the full 3x5 FL label and a three-digit
# temperature would exceed the 32-pixel display width.
COMPACT_FEELS_LIKE_LABEL = ("11010", "10010", "10011")


def fetch_weather():
    """Fetch current weather; failures leave the last successful cache intact."""
    global weather_data, last_fetch_ok
    url = API_CONFIG["weather_forecast_url"].format(
        latitude=GRAZ_LAT, longitude=GRAZ_LON)
    request = Request(url, headers={"User-Agent": "PiMatrixClock/1.0"})
    try:
        with urlopen(request, timeout=WEATHER_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        current = payload["current"]
        temperature = float(current["temperature_2m"])
        feels_like = float(current["apparent_temperature"])
        humidity = int(current["relative_humidity_2m"])
        code = int(current["weather_code"])
        cloud_cover_value = current.get("cloud_cover")
        is_day_value = current.get("is_day")
        cloud_cover = int(cloud_cover_value) if cloud_cover_value is not None else 50
        is_day = int(is_day_value) if is_day_value is not None else 0
        hourly = payload.get("hourly", {})
        rain_chance = None
        try:
            current_hour = datetime.fromisoformat(current["time"]).replace(
                minute=0, second=0, microsecond=0)
            rain_samples = [
                (datetime.fromisoformat(sample_time), probability)
                for sample_time, probability in zip(
                    hourly.get("time", []), hourly.get("precipitation_probability", []))
                if probability is not None
            ]
            if rain_samples:
                _, probability = min(
                    rain_samples, key=lambda item: abs((item[0] - current_hour).total_seconds()))
                rain_chance = int(probability)
        except (KeyError, TypeError, ValueError):
            rain_chance = None
        if (not (-80 <= temperature <= 65) or not (-100 <= feels_like <= 100)
                or not (0 <= humidity <= 100)
                or not (0 <= cloud_cover <= 100) or is_day not in (0, 1)
                or (rain_chance is not None and not (0 <= rain_chance <= 100))
                or code not in CODE_DESCRIPTION):
            raise ValueError("Unexpected weather response values")
        daily = payload.get("daily", {})
        rounded_temperature = round(temperature)
        with weather_lock:
            previous_temperature_value = numeric_value(weather_data, "temperature")
        previous_temperature = (round(previous_temperature_value)
                                if previous_temperature_value is not None else None)
        if previous_temperature is None:
            try:
                current_time = datetime.fromisoformat(current["time"])
                previous_samples = [
                    (datetime.fromisoformat(sample_time), float(sample_temperature))
                    for sample_time, sample_temperature in zip(
                        hourly.get("time", []), hourly.get("temperature_2m", []))
                    if isinstance(sample_time, str)
                    and isinstance(sample_temperature, (int, float))
                    and datetime.fromisoformat(sample_time) < current_time
                ]
                if previous_samples:
                    previous_temperature = round(max(previous_samples, key=lambda item: item[0])[1])
            except (KeyError, TypeError, ValueError):
                previous_temperature = None
        if previous_temperature is None:
            temperature_trend = None
        elif rounded_temperature > previous_temperature:
            temperature_trend = "up"
        elif rounded_temperature < previous_temperature:
            temperature_trend = "down"
        else:
            temperature_trend = "steady"
        result = {
            "temperature": rounded_temperature, "temperature_trend": temperature_trend,
            "feels_like": round(feels_like),
            "rain_chance": rain_chance,
            "humidity": humidity, "cloud_cover": cloud_cover, "is_day": is_day,
            "code": code, "fetched": time.time(),
            "sunrise": daily.get("sunrise", [None])[0],
            "sunset": daily.get("sunset", [None])[0],
        }
        with weather_lock:
            weather_data = result
            last_fetch_ok = True
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        with weather_lock:
            last_fetch_ok = False
        print("Weather update failed; continuing with cached data:", exc)


def fetch_metal_prices():
    """Cache the silver spot price in euros per troy ounce."""
    global metal_data

    def read_json(url):
        request = Request(url, headers={"User-Agent": "PiMatrixClock/1.0"})
        with urlopen(request, timeout=METALS_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        exchange = read_json(API_CONFIG["exchange_rates_url"])
        usd_to_eur = float(exchange["rates"]["EUR"])
        if not (0 < usd_to_eur < 2):
            raise ValueError("Unexpected USD/EUR exchange rate")

        prices = {}
        for metal, symbol in (("silver", "XAG"),):
            quote = read_json(API_CONFIG["metal_price_url"].format(symbol=symbol))
            usd_per_troy_ounce = float(quote["price"])
            if not (0 < usd_per_troy_ounce < 1_000_000):
                raise ValueError("Unexpected {} spot price".format(metal))
            prices[metal] = usd_per_troy_ounce * usd_to_eur
        prices["fetched"] = time.time()
        with metals_lock:
            metal_data = prices
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError,
            TypeError, json.JSONDecodeError) as exc:
        print("Metal price update failed; continuing with cached prices:", exc)


def brightness_for(now, data):
    """Set a soft day/night brightness curve, adjusted for daytime cloud cover."""
    cloud_cover_value = numeric_value(data, "cloud_cover")
    cloud_cover = cloud_cover_value if cloud_cover_value is not None else 50
    day_contrast = round(OVERCAST_DAY_CONTRAST
                         + (CLEAR_DAY_CONTRAST - OVERCAST_DAY_CONTRAST)
                         * (100 - cloud_cover) / 100)

    daylight = None
    if data is not None and data.get("sunrise") and data.get("sunset"):
        try:
            sunrise_value = data.get("sunrise")
            sunset_value = data.get("sunset")
            if not isinstance(sunrise_value, str) or not isinstance(sunset_value, str):
                raise ValueError("Sun times must be strings")
            sunrise = datetime.fromisoformat(sunrise_value).time().replace(tzinfo=None)
            sunset = datetime.fromisoformat(sunset_value).time().replace(tzinfo=None)
            current_minutes = now.hour * 60 + now.minute + now.second / 60
            sunrise_minutes = sunrise.hour * 60 + sunrise.minute + sunrise.second / 60
            sunset_minutes = sunset.hour * 60 + sunset.minute + sunset.second / 60
            ramp = TWILIGHT_RAMP_MINUTES
            if current_minutes < sunrise_minutes - ramp or current_minutes > sunset_minutes + ramp:
                daylight = 0.0
            elif current_minutes < sunrise_minutes:
                daylight = 0.5 * (current_minutes - (sunrise_minutes - ramp)) / ramp
            elif current_minutes < sunrise_minutes + ramp:
                daylight = 0.5 + 0.5 * (current_minutes - sunrise_minutes) / ramp
            elif current_minutes < sunset_minutes - ramp:
                daylight = 1.0
            else:
                daylight = max(0.0, 1.0 - 0.5 * (current_minutes - (sunset_minutes - ramp)) / ramp)
        except (TypeError, ValueError):
            daylight = None

    if daylight is None:
        is_day_value = numeric_value(data, "is_day")
        if is_day_value is not None:
            daylight = 1.0 if is_day_value else 0.0
        else:
            daylight = 1.0 if 7 <= now.hour < 19 else 0.0
    return round(NIGHT_CONTRAST + (day_contrast - NIGHT_CONTRAST) * daylight)


def apply_auto_brightness(now, data, current_contrast):
    contrast = brightness_for(now, data)
    if contrast != current_contrast:
        device.contrast(contrast)
    return contrast


def weather_worker():
    while True:
        fetch_weather()
        fetch_metal_prices()
        time.sleep(WEATHER_REFRESH_SECONDS)


def icon_for_code(code):
    if code in (0, 1):
        return "sun"
    if code == 2:
        return "partly"
    if code in (3,):
        return "cloud"
    if code in (45, 48):
        return "fog"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 97, 99):
        return "storm"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "rain"
    return "unknown"


def draw_glyph(draw: ImageDraw.ImageDraw, glyph: Glyph, left: int, top: int = 0) -> None:
    """Draw a bitmap glyph at the given coordinates."""
    for y, row in enumerate(glyph):
        for x, bit in enumerate(row):
            if bit == "1":
                draw.point((left + x, top + y), fill=1)


def numeric_value(data: Optional[DisplayData], key: str) -> Optional[float]:
    """Return a numeric display value, excluding missing or malformed fields."""
    if data is None:
        return None
    value = data.get(key)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def make_clock_image(hhmm: str) -> Image.Image:
    image = Image.new("1", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(image)
    for digit_index, character in enumerate(hhmm):
        # Center each 5-pixel digit within its 8-pixel matrix.
        draw_glyph(draw, DIGITS[character], digit_index * 8 + 1)
    return image


def make_centered_lines(lines: List[str]) -> Image.Image:
    image = Image.new("1", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(image)
    for line_index, line in enumerate(lines[:2]):
        line = line.upper()
        width = len(line) * 3 - 1
        cursor = max(0, (WIDTH - width) // 2)
        top = 0 if line_index == 0 else 5
        for char in line:
            glyph = TINY.get(char)
            if glyph:
                draw_glyph(draw, glyph, cursor, top)
            cursor += 3
    return image


DATE_LETTERS = {
    "A": ("00100", "01010", "10001", "10001", "11111", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01110"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "01010", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
}


def make_date_text_image(text: str) -> Image.Image:
    """Center a date label using 5x7 digits and letters."""
    image = Image.new("1", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(image)
    text = text.upper()
    weekdays = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
    if text in weekdays:
        width = len(text) * 5 + (len(text) - 1) * 8
        cursor = max(0, (WIDTH - width) // 2)
        for index, character in enumerate(text):
            draw_glyph(draw, DATE_LETTERS[character], cursor)
            cursor += 5
            if index < len(text) - 1:
                cursor += 3  # Leave three blank pixels before the 2x2 dot.
                draw_glyph(draw, WEATHER_GLYPHS["°"], cursor, 3)
                cursor += 5  # Leave three blank pixels after the 2-pixel dot.
        return image

    width = sum(3 if character == " " else 6 for character in text) - 1
    cursor = max(0, (WIDTH - width) // 2)
    for index, character in enumerate(text):
        # Give the leading day number one extra pixel of room in the 25 OCT label.
        glyph_cursor = cursor + (1 if text == "25 OCT" and index < 2 else 0)
        glyph = DIGITS.get(character) or DATE_LETTERS.get(character)
        if glyph:
            draw_glyph(draw, glyph, glyph_cursor)
        cursor += 3 if character == " " else 6
    return image


def make_weather_image(data: Optional[DisplayData], page: str) -> Image.Image:
    image = Image.new("1", (WIDTH, HEIGHT), 0)
    draw = ImageDraw.Draw(image)

    def value_glyph(character: str) -> Glyph:
        if character == "-":
            return WEATHER_GLYPHS["-"]
        glyph = DIGITS.get(character)
        if glyph is None:
            raise ValueError("Unsupported weather value character: {}".format(character))
        return tuple(row[1:4] for row in glyph) if character == "1" else glyph

    def value_width(character):
        return 3 if character in ("-", "1") else 5

    def draw_weather_number(text, left):
        number_cursor = left
        for index, character in enumerate(text):
            draw_glyph(draw, value_glyph(character), number_cursor)
            number_cursor += value_width(character)
            if index < len(text) - 1:
                number_cursor += 1
        return number_cursor

    if page == "weather_temperature":
        temperature_value = numeric_value(data, "temperature")
        if temperature_value is None:
            return image
        temperature = str(round(temperature_value))
        number_width = sum(value_width(character) for character in temperature)
        number_width += max(0, len(temperature) - 1)
        width = number_width + 10  # Number, 2-pixel gap, degree mark, 1-pixel gap, and C.
        trend_value = data.get("temperature_trend") if data is not None else None
        trend_glyph = (TEMPERATURE_TREND_GLYPHS.get(trend_value)
                       if isinstance(trend_value, str) else None)
        trend_gap = 3
        trend_width = 5 + trend_gap
        show_trend = trend_glyph is not None and width + trend_width <= WIDTH
        cursor = (WIDTH - width - (trend_width if show_trend else 0)) // 2
        if show_trend and trend_glyph is not None:
            draw_glyph(draw, trend_glyph, cursor)
            cursor += trend_width  # Account for the 5-pixel arrow and 3-pixel gap.
        cursor = draw_weather_number(temperature, cursor)
        cursor += 2
        draw_glyph(draw, WEATHER_GLYPHS["°"], cursor)
        cursor += 3  # Account for the 2-pixel degree mark and 1-pixel gap before C.
        draw_glyph(draw, WEATHER_GLYPHS["C"], cursor)
    elif page == "weather_feels_like":
        feels_like_value = numeric_value(data, "feels_like")
        label_width = 3 + 1 + 3
        label_gap = 3
        label = None
        value_degree_gap = 2
        if feels_like_value is None:
            return image
        feels_like = str(round(feels_like_value))
        number_width = sum(value_width(character) for character in feels_like)
        number_width += max(0, len(feels_like) - 1)
        width = (label_width + label_gap + number_width
                 + value_degree_gap + 2 + 1 + 5)
        if width > WIDTH:
            label = COMPACT_FEELS_LIKE_LABEL
            label_width = len(label[0])
            width = (label_width + label_gap + number_width
                     + value_degree_gap + 2 + 1 + 5)
        if width > WIDTH:
            label_gap = 1
            value_degree_gap = 1
            width = (label_width + label_gap + number_width
                     + value_degree_gap + 2 + 1 + 5)
        cursor = (WIDTH - width) // 2
        if label is None:
            draw_glyph(draw, LETTERS["F"], cursor, top=1)
            draw_glyph(draw, LETTERS["L"], cursor + 4, top=1)
        else:
            draw_glyph(draw, label, cursor, top=2)
        cursor += label_width + label_gap
        cursor = draw_weather_number(feels_like, cursor)
        cursor += value_degree_gap
        draw_glyph(draw, WEATHER_GLYPHS["°"], cursor)
        cursor += 3
        draw_glyph(draw, WEATHER_GLYPHS["C"], cursor)
    elif page == "weather_rain_chance":
        chance_value = numeric_value(data, "rain_chance")
        if chance_value is None:
            return image
        chance = str(round(chance_value))
        number_width = sum(value_width(character) for character in chance)
        number_width += max(0, len(chance) - 1)
        width = 5 + 3 + number_width + 2 + 5
        cursor = (WIDTH - width) // 2
        draw_glyph(draw, RAIN_CHANCE_ICON, cursor)
        cursor += 8  # Account for the 5-pixel umbrella and 3-pixel gap.
        cursor = draw_weather_number(chance, cursor)
        cursor += 2
        draw_glyph(draw, WEATHER_GLYPHS["%"], cursor)
    else:
        weather_code = numeric_value(data, "code")
        icon = (ICONS[icon_for_code(int(weather_code))]
                if weather_code is not None else ICONS["unknown"])
        humidity_value = numeric_value(data, "humidity")
        if humidity_value is None:
            return image
        humidity = str(round(humidity_value))
        humidity_width = sum(value_width(character) for character in humidity)
        width = 5 + 3 + humidity_width + max(0, len(humidity) - 1) + 2 + 5
        cursor = (WIDTH - width) // 2
        draw_glyph(draw, icon, cursor)
        cursor += 8  # Account for the 5-pixel icon and 3-pixel gap.
        cursor = draw_weather_number(humidity, cursor)
        cursor += 2
        draw_glyph(draw, WEATHER_GLYPHS["%"], cursor)
    return image


def make_sun_event_image(event: str, value: Optional[str]) -> Image.Image:
    """Display a 5x7 sunrise/sunset arrow beside 5x7 time digits."""
    image = Image.new("1", (WIDTH, HEIGHT), 0)
    if not isinstance(value, str) or not has_display_value({event: value}, event):
        return image
    draw = ImageDraw.Draw(image)
    icon = SUNRISE_ARROW if event == "sunrise" else SUNSET_ARROW
    icon_image = Image.new("1", (5, 7), 0)
    icon_draw = ImageDraw.Draw(icon_image)
    draw_glyph(icon_draw, icon, 0)
    image.paste(icon_image, (1, 0))

    text_left = 9  # Leave one pixel between the icon and the time.
    spacing_width = len(value) * 6 - 1
    cursor = text_left + max(0, (WIDTH - text_left - spacing_width) // 2)
    for character in value:
        glyph = DIGITS.get(character) or SUN_TIME_GLYPHS.get(character)
        if glyph:
            draw_glyph(draw, glyph, cursor)
        cursor += 6
    return image


def has_display_value(data: Optional[DisplayData], key: str) -> bool:
    """Return whether a data page has a real value to show."""
    if data is None:
        return False
    value = data.get(key)
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() not in ("", "--", "----")
    return True


def make_metal_image(data: Optional[DisplayData], metal: str) -> Image.Image:
    """Show a bold 5x7 metal initial, a three-pixel gap, and its euro price."""
    image = Image.new("1", (WIDTH, HEIGHT), 0)
    if data is None:
        return image
    metal_value = numeric_value(data, metal)
    if metal_value is None:
        return image

    draw = ImageDraw.Draw(image)
    label = METAL_LABEL_GLYPHS[metal]
    price = str(int(round(metal_value)))
    label_width = len(label[0])
    price_width = len(price) * 5 + max(0, len(price) - 1)
    total_width = label_width + 3 + price_width
    cursor = (WIDTH - total_width) // 2

    draw_glyph(draw, label, cursor)
    cursor += label_width + 3
    for index, character in enumerate(price):
        glyph = DIGITS.get(character)
        if glyph:
            draw_glyph(draw, glyph, cursor)
        cursor += 5
        if index < len(price) - 1:
            cursor += 1
    return image


def sun_event_display_time(data: Optional[DisplayData], event: str) -> Optional[str]:
    """Return a formatted sun-event time, or None when the API value is absent or invalid."""
    if data is None:
        return None
    event_value = data.get(event)
    if not isinstance(event_value, str) or not has_display_value(data, event):
        return None
    try:
        return datetime.fromisoformat(event_value).strftime("%H%M")
    except (TypeError, ValueError):
        return None


def pixel_transition(old_image, new_image, duration=MINUTE_ANIMATION_SECONDS):
    """Randomize changed pixels over a fixed interval of about 1.5 seconds."""
    old_pixels = old_image.load()
    new_pixels = new_image.load()
    assert old_pixels is not None and new_pixels is not None
    changed = [(x, y) for y in range(HEIGHT) for x in range(WIDTH)
               if old_pixels[x, y] != new_pixels[x, y]]
    if not changed:
        device.display(new_image)
        return
    random.shuffle(changed)
    start = time.monotonic()
    # Each changed pixel is assigned a random moment in the animation interval.
    events = sorted((random.random() * duration, x, y) for x, y in changed)
    frame = old_image.copy()
    fp = frame.load()
    assert fp is not None
    next_event = 0
    while next_event < len(events):
        now = time.monotonic() - start
        while next_event < len(events) and events[next_event][0] <= now:
            _, x, y = events[next_event]
            fp[x, y] = new_pixels[x, y]
            next_event += 1
        device.display(frame)
        if next_event < len(events):
            delay = max(0.005, min(0.03, events[next_event][0] - (time.monotonic() - start)))
            time.sleep(delay)
    device.display(new_image)


def startup_reveal(image):
    """Show the pixels in random order, then display the complete time."""
    coords = [(x, y) for y in range(HEIGHT) for x in range(WIDTH)]
    random.shuffle(coords)
    frame = Image.new("1", (WIDTH, HEIGHT), 0)
    fp, target = frame.load(), image.load()
    assert fp is not None and target is not None
    total = len(coords)
    for index, (x, y) in enumerate(coords):
        fp[x, y] = target[x, y]
        device.display(frame)
        # Start with longer pauses, then shorten them for a quick final fill.
        pause = 0.055 * (1.0 - index / total) ** 2 + 0.0015
        time.sleep(pause)
    device.display(image)


def main():
    global weather_data
    threading.Thread(target=weather_worker, name="weather", daemon=True).start()
    startup_now = datetime.now()
    with weather_lock:
        startup_weather = dict(weather_data) if weather_data is not None else None
    current_contrast = apply_auto_brightness(startup_now, startup_weather, None)
    displayed_image = make_clock_image(startup_now.strftime("%H%M"))
    last_clock_key = startup_now.strftime("%Y%m%d%H%M")
    startup_reveal(displayed_image)

    startup_hold_started = time.monotonic()
    while True:
        now = datetime.now()
        with weather_lock:
            current_weather = dict(weather_data) if weather_data is not None else None
        current_contrast = apply_auto_brightness(now, current_weather, current_contrast)
        clock_key = now.strftime("%Y%m%d%H%M")
        if clock_key != last_clock_key:
            target = make_clock_image(now.strftime("%H%M"))
            pixel_transition(displayed_image, target)
            displayed_image = target
            last_clock_key = clock_key
            startup_hold_started = time.monotonic()
            continue
        steady_time = time.monotonic() - startup_hold_started
        at_slot_boundary = now.second % SCREEN_SLOT_SECONDS == 0 and now.microsecond < 400_000
        if steady_time >= SCREEN_SLOT_SECONDS - MINUTE_ANIMATION_SECONDS and at_slot_boundary:
            break
        time.sleep(0.05)

    # The first scheduled screen now starts near the beginning of its 12-second slot.
    last_page = "clock"

    while True:
        now = datetime.now()
        with weather_lock:
            current_weather = dict(weather_data) if weather_data is not None else None
        with metals_lock:
            current_metals = dict(metal_data) if metal_data is not None else None
        current_contrast = apply_auto_brightness(now, current_weather, current_contrast)
        clock_key = now.strftime("%Y%m%d%H%M")
        second = now.second
        if second < WEATHER_WINDOW_SECONDS:
            weather_slot = second // SCREEN_SLOT_SECONDS
            if weather_slot == 2 and now.minute % 2:
                page = "weather_rain_chance"
            else:
                page = ("weather_temperature", "weather_feels_like", "weather_humidity")[
                    weather_slot]
        elif second < SCREEN_SLOT_SECONDS * 4:
            info_pages = ("day", "date", "sunrise", "sunset", "silver")
            page = info_pages[now.minute % len(info_pages)]
        else:
            page = "clock"

        weather_page_fields = {
            "weather_temperature": "temperature",
            "weather_humidity": "humidity",
            "weather_feels_like": "feels_like",
            "weather_rain_chance": "rain_chance",
        }
        if page in weather_page_fields:
            if not has_display_value(current_weather, weather_page_fields[page]):
                page = None
        elif page in ("sunrise", "sunset"):
            if sun_event_display_time(current_weather, page) is None:
                page = None
        elif page == "silver":
            if not has_display_value(current_metals, page):
                page = None

        if page in ("weather_temperature", "weather_humidity", "weather_feels_like",
                    "weather_rain_chance"):
            target = make_weather_image(current_weather, page)
            if last_page != page or last_clock_key != clock_key:
                pixel_transition(displayed_image, target)
                displayed_image = target
                last_page = page
                last_clock_key = clock_key
        elif page == "clock":
            if last_page != page or last_clock_key != clock_key:
                target = make_clock_image(now.strftime("%H%M"))
                pixel_transition(displayed_image, target)
                displayed_image = target
                last_page = page
                last_clock_key = clock_key
        elif page in ("day", "date", "sunrise", "sunset", "silver"):
            # One information screen per minute; the five pages recur every five minutes.
            if page != last_page:
                target = None
                if page == "day":
                    target = make_date_text_image(now.strftime("%a")[:3])
                elif page == "date":
                    target = make_date_text_image(now.strftime("%d %b"))
                elif page in ("sunrise", "sunset"):
                    event_time = sun_event_display_time(current_weather, page)
                    target = make_sun_event_image(page, event_time)
                elif page == "silver":
                    target = make_metal_image(current_metals, page)
                if target is not None:
                    pixel_transition(displayed_image, target)
                    displayed_image = target
                    last_page = page
        time.sleep(0.08)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nClock stopped.")
