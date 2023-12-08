import datetime
from collections import namedtuple
import json
import urllib.request
from bs4 import BeautifulSoup
import logging
import random


MEALTIME_SWITCH = 14  # 14:00


def get_mensa(name):
    for mensa in available:
        if mensa.alias == name:
            return mensa


def meal_format(meal):
    ret = (
        f"{meal.label} "
        + f"<i>({meal.price_student}, "
        + f"{meal.price_intern}, "
        + f"{meal.price_extern})</i>\n"
        + f"<b>{meal.name}</b>\n"
        + f"{meal.description}"
    )
    return ret


def mensa_format(mensa, meals):
    times = (
        f" <i>{mensa.opening}-{mensa.closing}</i>"
        if isinstance(mensa, ETHMensa)
        else ""
    )
    return f"<b>{mensa.name}</b>{times}\n\n" + "\n\n".join(
        [meal_format(m) for m in meals]
    )


Meal = namedtuple(
    "Meal",
    [
        "label",
        "price_student",
        "price_intern",
        "price_extern",
        "name",
        "description",
    ],
)


class Mensa:
    name = "Not available."
    alias = ""

    def get_meals(self):
        return []


class ETHMensa(Mensa):
    def __init__(self, name, alias, facility_id):
        self.name = name
        self.alias = alias
        self.facility_id = facility_id
        self.opening = ""
        self.closing = ""

    def get_meals(self):
        menus = []
        try:
            now = datetime.datetime.now()
            date = now.strftime("%Y-%m-%d")
            language = "en"  # "de" or "en"
            URL = f"https://idapps.ethz.ch/cookpit-pub-services/v1/weeklyrotas?client-id=ethz-wcms&lang={language}&rs-first=0&rs-size=50&valid-after={date}"

            with urllib.request.urlopen(URL) as request:
                meals = json.loads(request.read().decode())

            logging.debug(f"Got {len(meals['weekly-rota-array'])} facilities")

            facility = None
            for facility in meals["weekly-rota-array"]:
                valid_from = datetime.datetime.strptime(
                    facility["valid-from"], "%Y-%m-%d"
                )
                if not 0 < (now - valid_from).days < 7:
                    continue
                if facility["facility-id"] != self.facility_id:
                    continue

                break
            else:
                return menus

            logging.debug(f"Found facility {facility['facility-id']}")

            day = None
            for day in facility["day-of-week-array"]:
                if "opening-hour-array" not in day.keys():
                    continue
                if len(day["opening-hour-array"][0]["meal-time-array"]) == 0:
                    continue
                if now.weekday() + 1 != day["day-of-week-code"]:
                    continue

                break
            else:
                return menus

            logging.debug(
                f"Found day {day['day-of-week-desc']} (code {day['day-of-week-code']}))"
            )

            meals = day["opening-hour-array"][0]["meal-time-array"]
            meal = meals[0]
            time_to = datetime.datetime.strptime(meal["time-to"], "%H:%M")
            if len(meals) > 1 and (
                now.hour == time_to.hour
                and now.minute > time_to.minute
                or now.hour > time_to.hour
            ):
                meal = meals[1]

            logging.debug(f"Found meal {meal['name']}")

            self.opening = meal["time-from"]
            self.closing = meal["time-to"]

            for m in meal["line-array"]:
                if len(m) == 1:
                    logging.debug(f"Found empty meal {m['name']}")

                    emoji_variants = ["🤷", "🤷‍♂️", "🤷‍♀️"]

                    menu = Meal(
                        label=m["name"],
                        price_student="$",
                        price_intern="$$",
                        price_extern="$$$",
                        name=random.choice(emoji_variants),
                        description="",
                    )

                    menus.append(menu)

                    continue

                logging.debug(f"Found meal {m['name']}")

                prices = [
                    (p["price"], p["customer-group-desc"])
                    for p in m["meal"]["meal-price-array"]
                ]
                student_price = next((p[0] for p in prices if "students" in p[1]), "$")
                intern_price = next((p[0] for p in prices if "internal" in p[1]), "$$")
                extern_price = next((p[0] for p in prices if "external" in p[1]), "$$$")

                menu = Meal(
                    label=m["name"],
                    price_student=student_price,
                    price_intern=intern_price,
                    price_extern=extern_price,
                    name=m["meal"]["name"],
                    description=m["meal"]["description"],
                )

                menus.append(menu)

            return menus
        except Exception as e:
            logging.error("Error while fetching ETH Mensa data")
            logging.error(e)
            return menus


class UniMensa(Mensa):
    def __init__(self, name, alias, api_name):
        self.name = name
        self.alias = alias
        self.tage = [
            "montag",
            "dienstag",
            "mittwoch",
            "donnerstag",
            "freitag",
            "samstag",
            "sonntag",
        ]
        self.api_name = api_name

    def get_meals(self):
        if self.alias == "uni":
            if datetime.datetime.now().hour < MEALTIME_SWITCH:
                self.api_name = "zentrum-mensa"
            else:
                self.api_name = "zentrum-mercato-abend"

        day = self.tage[datetime.datetime.today().weekday()]  # current day
        url = "https://www.mensa.uzh.ch/de/menueplaene/{}/{}.html".format(
            self.api_name, day
        )

        try:
            with urllib.request.urlopen(url) as request:
                raw_data = request.read().decode("utf8")

            soup = BeautifulSoup(raw_data, "html.parser")
            menu_holder = soup.find("div", {"class": "NewsListItem--content"})

            lines = menu_holder.text.split("\n")
        except Exception as e:
            logging.error("Error while fetching UZH Mensa data")
            logging.error(e)
            return []

        menus = []
        i = 0
        # Loop until there are no menus left
        while True:
            try:
                # find next menu
                while i < len(lines) and " | " not in lines[i]:
                    i += 1
                # check if we found menu or hit end
                if i < len(lines):
                    # very ugly html parsing for a very ugly html site :/
                    prices = lines[i].split(" | ")[1].split(" / ")
                    name_desc = lines[i + 1].split("  ")
                    name = ""
                    description = ""
                    if len(name_desc) > 0:
                        name = name_desc[0]
                    if len(name_desc) > 1:
                        description = " ".join(name_desc[1:])

                    menu = Meal(
                        label=lines[i].split(" | ")[0],
                        price_student=prices[0].replace("CHF", "").replace(" ", ""),
                        price_intern=prices[1].replace("CHF", "").replace(" ", ""),
                        price_extern=prices[2].replace("CHF", "").replace(" ", ""),
                        name=name,
                        description=description,
                    )
                    menus.append(menu)
                    i += 1
                # return what we've found when we hit the end
                else:
                    return menus
            except Exception as e:
                logging.error("Error while parsing UZH Mensa data")
                logging.error(e)
                return menus


with open("./WitiGrailleBotFiles/eth_mensas.json") as f:
    eth_mensas = json.load(f)

with open("./WitiGrailleBotFiles/uzh_mensas.json") as f:
    uzh_mensas = json.load(f)

available = []

for mensa in eth_mensas:
    available.append(ETHMensa(mensa["name"], mensa["alias"], mensa["facility-id"]))

for mensa in uzh_mensas:
    available.append(UniMensa(mensa["name"], mensa["alias"], mensa["api_name"]))
