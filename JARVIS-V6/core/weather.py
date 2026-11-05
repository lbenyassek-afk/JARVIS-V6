from __future__ import annotations

import threading
import time

import requests

from .config import load_config
from .language import normalize_language


class WeatherError(RuntimeError):
    pass


_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, str]] = {}
_CODES = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers",
    81: "rain showers", 82: "heavy showers", 95: "thunderstorms",
}
_CONDITIONS = {
    "fr": {"clear": "dégagé", "mostly clear": "globalement dégagé", "partly cloudy": "partiellement nuageux",
           "overcast": "couvert", "foggy": "brumeux", "light rain": "pluie légère", "rain": "pluie",
           "heavy rain": "fortes pluies", "snow": "neige", "thunderstorms": "orages"},
    "ar": {"clear": "صافٍ", "mostly clear": "صافٍ غالباً", "partly cloudy": "غائم جزئياً",
           "overcast": "غائم", "foggy": "ضبابي", "light rain": "مطر خفيف", "rain": "ممطر",
           "heavy rain": "أمطار غزيرة", "snow": "ثلوج", "thunderstorms": "عواصف رعدية"},
    "es": {"clear": "despejado", "mostly clear": "mayormente despejado", "partly cloudy": "parcialmente nublado",
           "overcast": "cubierto", "foggy": "con niebla", "light rain": "lluvia ligera", "rain": "lluvia",
           "heavy rain": "lluvia intensa", "snow": "nieve", "thunderstorms": "tormentas"},
    "de": {"clear": "klar", "mostly clear": "überwiegend klar", "partly cloudy": "teilweise bewölkt",
           "overcast": "bedeckt", "foggy": "neblig", "light rain": "leichter Regen", "rain": "Regen",
           "heavy rain": "starker Regen", "snow": "Schnee", "thunderstorms": "Gewitter"},
    "it": {"clear": "sereno", "mostly clear": "prevalentemente sereno", "partly cloudy": "parzialmente nuvoloso",
           "overcast": "coperto", "foggy": "nebbioso", "light rain": "pioggia leggera", "rain": "pioggia",
           "heavy rain": "pioggia intensa", "snow": "neve", "thunderstorms": "temporali"},
    "pt": {"clear": "céu limpo", "mostly clear": "maioritariamente limpo", "partly cloudy": "parcialmente nublado",
           "overcast": "encoberto", "foggy": "com nevoeiro", "light rain": "chuva fraca", "rain": "chuva",
           "heavy rain": "chuva forte", "snow": "neve", "thunderstorms": "trovoadas"},
}


def _json(url: str, params: dict | None = None) -> dict:
    try:
        response = requests.get(url, params=params, timeout=(4, 9), headers={"User-Agent": "JARVIS-V6"})
        response.raise_for_status()
        value = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise WeatherError("Live weather is unavailable. Check the internet connection or set a city in Settings.") from exc
    if not isinstance(value, dict):
        raise WeatherError("The weather service returned an invalid response.")
    return value


def _coordinates(location: str, automatic: bool, language: str = "en") -> tuple[float, float, str]:
    if location:
        data = _json("https://geocoding-api.open-meteo.com/v1/search", {
            "name": location, "count": 1, "language": language, "format": "json",
        })
        rows = data.get("results") or []
        if not rows:
            raise WeatherError(f"I could not find the weather location ‘{location}’. Change it in Settings.")
        row = rows[0]
        label = ", ".join(part for part in (row.get("name"), row.get("country")) if part)
        return float(row["latitude"]), float(row["longitude"]), label
    if not automatic:
        raise WeatherError("Set your weather city in Settings first.")
    data = _json("https://ipapi.co/json/")
    try:
        label = ", ".join(part for part in (data.get("city"), data.get("country_name")) if part)
        return float(data["latitude"]), float(data["longitude"]), label or "your location"
    except (KeyError, TypeError, ValueError) as exc:
        raise WeatherError("Automatic location failed. Enter your city in Settings.") from exc


def report(location_override: str = "", language_override: str = "") -> str:
    full = load_config(); cfg = full.get("weather", {})
    language = normalize_language(language_override or full.get("assistant", {}).get("language", "en"))
    language = "en" if language == "auto" else language
    location = str(location_override or cfg.get("location", "")).strip()
    units = "imperial" if cfg.get("units") == "imperial" else "metric"
    key = f"{location.casefold()}|{units}|{language}|{bool(cfg.get('automatic_location', True))}"
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached[0] < 600:
            return cached[1]
    latitude, longitude, label = _coordinates(location, bool(cfg.get("automatic_location", True)), language)
    imperial = units == "imperial"
    data = _json("https://api.open-meteo.com/v1/forecast", {
        "latitude": latitude, "longitude": longitude,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "temperature_unit": "fahrenheit" if imperial else "celsius",
        "wind_speed_unit": "mph" if imperial else "kmh",
        "forecast_days": 1, "timezone": "auto",
    })
    current, daily = data.get("current", {}), data.get("daily", {})
    try:
        symbol = "°F" if imperial else "°C"
        speed = "mph" if imperial else "km/h"
        base_condition = _CODES.get(int(current.get("weather_code", -1)), "mixed conditions")
        translations = _CONDITIONS.get(language, {})
        condition = translations.get(base_condition)
        if not condition:
            family = ("snow" if "snow" in base_condition else
                      "rain" if any(word in base_condition for word in ("rain", "drizzle", "showers")) else
                      "overcast" if base_condition == "mixed conditions" else base_condition)
            condition = translations.get(family, base_condition)
        high = daily["temperature_2m_max"][0]
        low = daily["temperature_2m_min"][0]
        rain = daily.get("precipitation_probability_max", [0])[0] or 0
        values = (label, round(float(current['temperature_2m'])), symbol, condition,
                  round(float(current['apparent_temperature'])), round(float(high)), round(float(low)),
                  round(float(rain)), round(float(current['wind_speed_10m'])), speed)
        templates = {
            "fr": "À {label}, il fait {temp}{symbol} avec un temps {condition}. Ressenti : {feels}{symbol}. Maximum {high}{symbol}, minimum {low}{symbol}, {rain} % de précipitations et vent à {wind} {speed}.",
            "ar": "في {label}، الحرارة {temp}{symbol} والجو {condition}. المحسوسة {feels}{symbol}. العظمى {high}{symbol}، الصغرى {low}{symbol}، احتمال الهطول {rain}٪ والرياح {wind} {speed}.",
            "es": "En {label}, hay {temp}{symbol} y está {condition}. Sensación de {feels}{symbol}. Máxima {high}{symbol}, mínima {low}{symbol}, {rain} % de precipitación y viento a {wind} {speed}.",
            "de": "In {label} sind es {temp}{symbol} bei {condition}. Gefühlt {feels}{symbol}. Höchstwert {high}{symbol}, Tiefstwert {low}{symbol}, {rain} % Niederschlag und Wind mit {wind} {speed}.",
            "it": "A {label} ci sono {temp}{symbol} e il tempo è {condition}. Percepiti {feels}{symbol}. Massima {high}{symbol}, minima {low}{symbol}, {rain}% di precipitazioni e vento a {wind} {speed}.",
            "pt": "Em {label}, estão {temp}{symbol} e o tempo está {condition}. Sensação de {feels}{symbol}. Máxima {high}{symbol}, mínima {low}{symbol}, {rain}% de precipitação e vento a {wind} {speed}.",
        }
        if language in templates:
            answer = templates[language].format(
                label=label, temp=values[1], symbol=symbol, condition=condition, feels=values[4],
                high=values[5], low=values[6], rain=values[7], wind=values[8], speed=speed)
        else:
            answer = (
                f"In {label}, it is {values[1]}{symbol} and {condition}. It feels like {values[4]}{symbol}. "
                f"Today’s high is {values[5]}{symbol}, the low is {values[6]}{symbol}, with a {values[7]}% "
                f"chance of precipitation and wind at {values[8]} {speed}."
            )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise WeatherError("The live weather report was incomplete. Try again shortly.") from exc
    with _LOCK:
        _CACHE[key] = (now, answer)
    return answer


def prefetch() -> str:
    return report()
