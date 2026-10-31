# Raspberry Pi LED Matrix Clock

A clock and information display for a Raspberry Pi connected to cascaded MAX7219 8×8 LED matrix modules. The default setup uses four modules for a 32×8 display showing the time, weather, date, sunrise and sunset, and the silver spot price.

## Features

- 24-hour `HHMM` clock with pixel transition animations
- Current temperature, feels-like temperature, humidity, and precipitation chance
- Weather condition icon and temperature trend
- Day and date, sunrise and sunset times, and silver price in euros per troy ounce
- Automatic brightness adjustment using local time and available weather data
- Cached weather and metal values remain available when a refresh fails

Weather is retrieved from Open-Meteo using the configured location. Silver prices are retrieved from GoldAPI and converted from USD to EUR using the ExchangeRate-API. Internet access is needed to refresh these values; the clock display itself runs locally.

## Hardware

- Raspberry Pi with SPI enabled
- MAX7219 8×8 LED matrix modules, connected in a chain (four modules by default)
- Suitable power supply for the Pi and display modules

Connect the display's `DIN`, `CLK`, and `CS`/`LOAD` pins to the Pi's SPI0 `MOSI`, `SCLK`, and `CE0` pins. On standard Raspberry Pi SPI0 pin assignments, these are GPIO 10 (physical pin 19), GPIO 11 (physical pin 23), and GPIO 8 (physical pin 24). Connect ground to ground and provide the display with the supply voltage specified by its module. Check the module and Pi documentation before wiring; do not connect a 5 V signal to a Pi GPIO pin.

The program uses SPI bus 0 and chip-select device 0. Its default configuration uses four cascaded MAX7219 modules. If your module count or physical orientation differs, edit the `display` settings in `config.json`.

## Configuration

The script loads [`config.json`](config.json) from the same directory as `led_matrix_clock.py`. Edit it to change these settings:

| Section | Settings |
| --- | --- |
| `display` | Number of cascaded modules, block orientation, rotation, and initial brightness. |
| `location` | Latitude and longitude used in the weather request. Defaults to Graz, Austria. |
| `api` | Weather, currency conversion, and metal price endpoint URLs. The weather URL supports `{latitude}` and `{longitude}` placeholders; the metal URL supports `{symbol}`. |
| `timing` | API timeouts and refresh interval, screen slot duration, and transition duration. |
| `brightness` | Contrast levels for night, overcast daylight, and clear daylight, plus the twilight ramp duration. |

The weather URL includes the requested fields and timezone. If you change the location to a different timezone, update the `timezone` parameter in that URL as well. Display width is calculated from the configured number of cascaded 8×8 modules.

## Python dependencies

`requirements.txt` lists the third-party Python packages this project needs. A virtual environment (`venv`) is a project-local Python environment: installing the requirements there keeps them separate from the operating system's Python packages and other projects.

Create and activate a virtual environment, then install the listed packages:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Activate the environment again in a new terminal before running the clock. To leave it, run `deactivate`. The `.venv` directory is local to your machine and does not need to be committed.

## Run

From the project directory:

```sh
python led_matrix_clock.py
```

Stop it with `Ctrl+C`. The display starts with a pixel reveal, then cycles through screens using the configured timing. Weather and metal data refresh in a background thread at the configured interval.

## Troubleshooting

- **Display stays blank:** Confirm power and ground, enable SPI, and check `DIN`/`CLK`/`CS` wiring and the module's required supply voltage.
- **Permission error opening SPI:** Check that SPI is enabled and that your user has access to the SPI device (commonly `/dev/spidev0.0`). Log out and back in after changing group membership.
- **Pixels or module order look wrong:** Check the chain order and adjust `block_orientation` / `rotate` for your physical arrangement.
- **Weather or silver screens are missing:** Check internet connectivity and the terminal output. The application keeps the last successful values; screens without data are skipped.

## Dependencies and data sources

- Python 3
- [`luma.led_matrix`](https://pypi.org/project/luma.led-matrix/) and [`luma.core`](https://pypi.org/project/luma.core/)
- [Pillow](https://python-pillow.org/)
- [Open-Meteo forecast API](https://open-meteo.com/)
- [ExchangeRate-API](https://www.exchangerate-api.com/) and [GoldAPI](https://www.gold-api.com/)
