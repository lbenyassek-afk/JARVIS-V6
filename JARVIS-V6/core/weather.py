from __future__ import annotations

import threading
import time

import requests

from .config import load_config


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


def _coordinates(location: str, automatic: bool) -> tuple[float, float, str]:
    if location:
        data = _json("https://geocoding-api.open-meteo.com/v1/search", {
            "name": location, "count": 1, "language": "en", "format": "json",
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


def report(location_override: str = "") -> str:
    cfg = load_config().get("weather", {})
    location = str(location_override or cfg.get("location", "")).strip()
    units = "imperial" if cfg.get("units") == "imperial" else "metric"
    key = f"{location.casefold()}|{units}|{bool(cfg.get('automatic_location', True))}"
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached[0] < 600:
            return cached[1]
    latitude, longitude, label = _coordinates(location, bool(cfg.get("automatic_location", True)))
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
        condition = _CODES.get(int(current.get("weather_code", -1)), "mixed conditions")
        high = daily["temperature_2m_max"][0]
        low = daily["temperature_2m_min"][0]
        rain = daily.get("precipitation_probability_max", [0])[0] or 0
        answer = (
            f"In {label}, it is {round(float(current['temperature_2m']))}{symbol} and {condition}. "
            f"It feels like {round(float(current['apparent_temperature']))}{symbol}. "
            f"Today’s high is {round(float(high))}{symbol}, the low is {round(float(low))}{symbol}, "
            f"with a {round(float(rain))}% chance of precipitation and wind at "
            f"{round(float(current['wind_speed_10m']))} {speed}."
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise WeatherError("The live weather report was incomplete. Try again shortly.") from exc
    with _LOCK:
        _CACHE[key] = (now, answer)
    return answer


def prefetch() -> str:
    return report()
