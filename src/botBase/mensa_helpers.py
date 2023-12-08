import datetime
from collections import namedtuple
import json
import urllib.request
from bs4 import BeautifulSoup
import logging


MEALTIME_SWITCH = 14  # 14:00


def get_meals(name):
    return get_mensa(name).get_meals()


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
    )
    if len(meal.description) > 0:
        ret += f"<b>{meal.description[0]}</b>\n{' '.join(meal.description[1:])}"
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


Meal = namedtuple("Meal", ["label", "price_student", "price_intern", "price_extern", "description"])

class Mensa:
    name = "Not available."
    alias = []

    def get_meals(self):
        """
        Returns list of menu objects of meuns that are available
        """
        return []


# ETH Mensa
class ETHMensa(Mensa):
    def __init__(self, api_name):
        self.api_name = api_name

        with open("./WitiGrailleBotFiles/mensas.json") as f:
            mensas = json.load(f)
        
        for mensa in mensas:
            if mensa["alias"] != self.api_name: continue

            self.name = mensa["name"]
            self.alias = mensa["alias"]
            self.facility_id = mensa["facility-id"]
            self.opening = ""
            self.closing = ""


    def get_meals(self):
        menus = []
        try:
            now = datetime.datetime.now()
            date = now.strftime("%Y-%m-%d")
            language = "en" # "de" or "en"
            URL = f"https://idapps.ethz.ch/cookpit-pub-services/v1/weeklyrotas?client-id=ethz-wcms&lang={language}&rs-first=0&rs-size=50&valid-after={date}"

            with urllib.request.urlopen(URL) as request:
                meals = json.loads(request.read().decode())

            logging.debug(f"Got {len(meals['weekly-rota-array'])} facilities")
            facility = None
            for facility in meals['weekly-rota-array']:
                valid_from = datetime.datetime.strptime(facility['valid-from'], '%Y-%m-%d')
                if not 0 < (now - valid_from).days < 7: continue
                if facility["facility-id"] != self.facility_id: continue

                break
            else:
                return menus
            
            logging.debug(f"Found facility {facility['facility-id']}")

            day = None
            for day in facility['day-of-week-array']:
                if 'opening-hour-array' not in day.keys(): continue
                if len(day['opening-hour-array'][0]['meal-time-array']) == 0: continue
                if now.weekday() + 1 != day['day-of-week-code']: continue

                break
            else:
                return menus

            logging.debug(f"Found day {day['day-of-week-code']}")

            meals = day['opening-hour-array'][0]['meal-time-array']
            meal = meals[0]
            time_to = datetime.datetime.strptime(meal['time-to'], "%H:%M")
            if len(meals) > 1 and (
                now.hour == time_to.hour and now.minute > time_to.minute or 
                now.hour > time_to.hour
            ):
                meal = meals[1]

            self.opening = meal['time-from']
            self.closing = meal['time-to']

            for m in meal['line-array']:
                prices = [(p['price'], p['customer-group-desc']) for p in m['meal']['meal-price-array']]
                student_price = next((p[0] for p in prices if 'students' in p[1]), "N/A")
                intern_price = next((p[0] for p in prices if 'internal' in p[1]), "N/A")
                extern_price = next((p[0] for p in prices if 'external' in p[1]), "N/A")

                menu = Meal(
                    label = m['name'],
                    price_student = student_price,
                    price_intern = intern_price,
                    price_extern = extern_price,
                    description = [m['meal']['name']] + (m['meal']['description']).split(" ")
                )

                menus.append(menu)

            return menus
        except Exception as e: 
            print(e)
            return menus  # we failed, but let's pretend nothing ever happened


class UniMensa(Mensa):
    api_name = ""  # the name used on the UNI website (has to be defined by the inheriting class)

    tage = [
        "montag",
        "dienstag",
        "mittwoch",
        "donnerstag",
        "freitag",
        "samstag",
        "sonntag",
    ]

    def get_meals(self):
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
            print(e)
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

                    menu = Meal(
                        label = lines[i].split(" | ")[0],
                        price_student = prices[0].replace("CHF", "").replace(" ", ""),
                        price_intern = prices[1].replace("CHF", "").replace(" ", ""),
                        price_extern = prices[2].replace("CHF", "").replace(" ", ""),
                        description = lines[i + 1].split("  ")
                    )
                    menus.append(menu)
                    i += 1
                # return what we've found when we hit the end
                else:
                    return menus
            except Exception as e:
                print(e)
                # If anything bad happens just ignore it. Just like we do in real life.
                return menus

    @property
    def alias(self):
        return self.aliases[0]

class Platte(UniMensa):
    aliases = ["platte", "plattestross", "plattenstrasse", "plattestrass"]
    name = "Plattenstrasse"
    api_name = "cafeteria-uzh-plattenstrasse"


class Raemi59(UniMensa):
    aliases = [
        "raemi",
        "rämi",
        "rämi59",
        "raemi59",
        "rämi 59",
        "raemi 59",
        "raemistrasse",
        "rämistrasse",
        "rämistross",
    ]
    name = "Rämi 59"
    api_name = "raemi59"


class UZHMercato(UniMensa):
    aliases = ["uniunten", "mercato", "uni-unten", "uni unten"]
    name = "UZH Mercato"
    api_name = "zentrum-mercato"


class UZHMercatoAbend(UniMensa):
    aliases = ["uniuntenabend", "mercato abend", "uni-unten-abend", "uni unten abend"]
    name = "UZH Mercato"
    api_name = "zentrum-mercato-abend"


class UZHZentrum(UniMensa):
    aliases = ["unioben", "zentrum", "uni", "uzh zentrum", "uzhzentrum"]
    name = "UZH Zentrum"
    api_name = "zentrum-mensa"


class UZHZentrumAllgemein(UniMensa):
    aliases = ["uni"]
    name = "UZH Zentrum"

    def get_meals(self):
        if datetime.datetime.now().hour < MEALTIME_SWITCH:
            self.api_name = "zentrum-mensa"
        else:
            self.api_name = "zentrum-mercato-abend"
        return super().get_meals()
    

class UZHLichthof(UniMensa):
    aliases = ["lichthof", "rondell"]
    name = "UZH Lichthof"
    api_name = "lichthof-rondell"


class Irchel(UniMensa):
    aliases = ["irchel", "irchel mensa", "irchelmensa"]
    name = "UZH Irchel"
    api_name = "mensa-uzh-irchel"


class IrchelAtrium(UniMensa):
    aliases = ["atrium", "irchel atrium"]
    name = "UZH Irchel Atrium"
    api_name = "irchel-cafeteria-atrium"


class Binzmühle(UniMensa):
    aliases = ["binzmuehle", "binzmühle"]
    name = "UZH Binzmühle"
    api_name = "mensa-uzh-binzmuehle"


class Cityport(UniMensa):
    aliases = ["cityport"]
    name = "UZH Cityport"
    api_name = "mensa-uzh-cityport"


class Zahnmedizin(UniMensa):
    aliases = ["zahnmedizin", "zzm"]
    name = "UZH Zahnmedizin"
    api_name = "cafeteria-zzm"


class Tierspital(UniMensa):
    aliases = ["tierspital"]
    name = "UZH Tierspital"
    api_name = "cafeteria-uzh-tierspital"


class BotanischerGarten(UniMensa):
    aliases = ["botanischergarten", "botanischer garten", "garten", "botgarten"]
    name = "UZH Botanischer Garten"
    api_name = "cafeteria-uzh-botgarten"

available = [
    ETHMensa("poly"),
    ETHMensa("foodlab"),
    ETHMensa("clausius"),
    ETHMensa("polysnack"),
    ETHMensa("alumni"),
    ETHMensa("fusion"),
    ETHMensa("dozentenfoyer"),
    Platte(),
    Raemi59(),
    UZHMercato(),
    UZHZentrum(),
    UZHLichthof(),
    Irchel(),
    IrchelAtrium(),
    Binzmühle(),
    Cityport(),
    Zahnmedizin(),
    Tierspital(),
    BotanischerGarten(),
    UZHZentrumAllgemein(),
]