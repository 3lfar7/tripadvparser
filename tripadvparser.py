import os
import os.path
import re
import shutil
import argparse
import sqlite3
import logging
import urllib.request
import urllib.parse
import urllib.error
import http.client
import http.cookiejar
import socket
import hashlib
import time
import datetime
import collections
import json
import yaml
from htmlparser import *
from htmlparser.jsinterpreter import JSInterpreter, JSInterpreterError


class ServicesHTMLParser(HTMLParser):
    services = Collector("div[id=\"jfy_filter_bar_amenities_lb\"] label.label", DataHandler(), min_pass_count=1)


class HotelsHTMLParser(HTMLParser):
    paths = Collector("div.listing:not([id=\"sponsoredCouponListing\"]) div.listing_title a.property_title", AttrHandler("href"), min_pass_count=1)
    page_count = Collector("div.standard_pagination", IntHandler(AttrHandler("data-numpages")), limit=1, default_value=0)


class PhoneHandler(DataHandler):
    def __init__(self):
        super().__init__()

    def __call__(self, name, element):
        code = super().__call__(name, element)
        js_interpreter = JSInterpreter()
        try:
            return js_interpreter(code)
        except JSInterpreterError as e:
            raise ValueHandlerError(name, str(e))


class WebsiteHandler(AttrHandler):
    def __init__(self):
        super().__init__("data-ahref")

    def __call__(self, name, element):
        return self.decode(super().__call__(name, element))

    def decode(self, encoded_url):
        table = {
            "": ["&", "=", "p", "6", "?", "H", "%", "B", ".com", "k", "9", ".html", "n", "M", "r", "www.", "h", "b", "t", "a", "0", "/", "d", "O", "j", "http://", "_", "L", "i", "f", "1", "e", "-", "2", ".", "N", "m", "A", "l", "4", "R", "C", "y", "S", "o", "+", "7", "I", "3", "c", "5", "u", 0, "T", "v", "s", "w", "8", "P", 0, "g", 0],
            "q": [0, "__3F__", 0, "Photos", 0, "https://", ".edu", "*", "Y", ">", 0, 0, 0, 0, 0, 0, "`", "__2D__", "X", "<", "slot", 0, "ShowUrl", "Owners", 0, "[", "q", 0, "MemberProfile", 0, "ShowUserReviews", '"', "Hotel", 0, 0, "Expedia", "Vacation", "Discount", 0, "UserReview", "Thumbnail", 0, "__2F__", "Inspiration", "V", "Map", ":", "@", 0, "F", "help", 0, 0, "Rental", 0, "Picture", 0, 0, 0, "hotels", 0, "ftp://"],
            "x": [0, 0, "J", 0, 0, "Z", 0, 0, 0, ";", 0, "Text", 0, "(", "x", "GenericAds", "U", 0, "careers", 0, 0, 0, "D", 0, "members", "Search", 0, 0, 0, "Post", 0, 0, 0, "Q", 0, "$", 0, "K", 0, "W", 0, "Reviews", 0, ",", "__2E__", 0, 0, 0, 0, 0, 0, 0, "{", "}", 0, "Cheap", ")", 0, 0, 0, "#", ".org"],
            "z": [0, "Hotels", 0, 0, "Icon", 0, 0, 0, 0, ".net", 0, 0, "z", 0, 0, "pages", 0, "geo", 0, 0, 0, "cnt", "~", 0, 0, "]", "|", 0, "tripadvisor", "Images", "BookingBuddy", 0, "Commerce", 0, 0, "partnerKey", 0, "area", 0, "Deals", "from", "\\", 0, "urlKey", 0, "'", 0, "WeatherUnderground", 0, "MemberSign", "Maps", 0, "matchID", "Packages", "E", "Amenities", "Travel", ".htm", 0, "!", "^", "G"]
        }
        arr = []
        jump = False
        for i, ch1 in enumerate(encoded_url):
            if jump:
                jump = False
                continue
            ch2 = ch1
            if ch1 in table and i + 1 < len(encoded_url):
                i += 1
                ch2 += encoded_url[i]
                jump = True
            else:
                ch1 = ""
            offset = -1
            ch_code = ord(encoded_url[i])
            if ch_code >= 97 and ch_code <= 122:
                offset = ch_code - 61
            elif ch_code >= 65 and ch_code <= 90:
                offset = ch_code - 55
            elif ch_code >= 48 and ch_code <= 71:
                offset = ch_code - 48
            if offset < 0:
                arr.append(ch2)
            else:
                arr.append(table[ch1][offset])
        return "".join(arr)


class StarCountHandler:
    PATTERN = re.compile("star_(\d\d)")

    def __call__(self, name, element):
        for class_ in element.classes:
            match = self.PATTERN.fullmatch(class_)
            if match:
                return match.group(1)
        raise ValueHandlerError(name, "element does not contain class that match pattern")


class AddressHandler(DataHandler):
    def __init__(self):
        super().__init__()

    def __call__(self, name, element):
        text = super().__call__(name, element)
        try:
            info = json.loads(text)
        except json.JSONDecodeError:
            raise ValueHandlerError(name, "json is not valid")
        else:
            address = info.get("address", {})
            return {
                "street": address.get("streetAddress"),
                "postal_code": address.get("postalCode")
            }


class HotelHTMLParser(HTMLParser):
    name = Collector("h1[id=\"HEADING\"]", DataHandler(), min_pass_count=1, limit=1)
    location = Collector(
        "li.breadcrumb[itemscope] span[itemprop=\"title\"]",
        DataHandler(),
        min_pass_count=4
    )
    address = Collector("head script[type=\"application/ld+json\"]", AddressHandler(), limit=1)
    phone = Collector("div.phone span script", PhoneHandler(), limit=1)
    website = Collector("div.website", WebsiteHandler(), limit=1)
    services = Collector("div.ui_columns.section_content li.item:not(.title)", DataHandler())
    description = Collector("div.description div.section_content", DataHandler(), limit=1)
    star_count = Collector("ul.list.stars div.ui_star_rating", IntHandler(StarCountHandler()), limit=1)
    room_count = Collector("ul.list.number_of_rooms li.item:not(.title)", IntHandler(DataHandler()), limit=1)

    def is_translation(self, name):
        return name in ["name", "location", "street", "phone", "services", "description"]

    def clean(self):
        self.data["location"] = self.data["location"][:-1]
        address = self.data["address"]
        self.data["street"] = address["street"]
        self.data["postal_code"] = address["postal_code"]
        del self.data["address"]
        services = []
        for service in self.data["services"]:
            if service not in services:
                services.append(service)
        self.data["services"] = services


class HotelEmailHTMLParser(HTMLParser):
    email = Collector("input[id=\"receiver\"]", AttrHandler("value"), min_pass_count=1, limit=1)


class PhotoUrlHandler(AttrHandler):
    def __init__(self, name):
        super().__init__(name)

    def __call__(self, name, element):
        url = super().__call__(name, element)
        if not url.endswith(".jpg"):
            raise ValueHandlerError(name, "url '{}' does not endswith '.jpg'".format(url))
        return url.replace("photo-s", "photo-o", 1)


class HotelGalleryHTMLParser(HTMLParser):
    photo_urls = Collector("a.photoGridImg img, div.tinyThumb", (PhotoUrlHandler("src"), PhotoUrlHandler("data-bigurl")))


class PriceHandler:
    def __init__(self):
        self.price_handler = IntHandler(AttrHandler("data-pernight"))
        self.vendor_handler = AttrHandler("data-offerclient")

    def __call__(self, name, element):
        price = self.price_handler(name, element)
        vendor_name = self.vendor_handler(name, element)
        return vendor_name, price


class HotelPriceHTMLParser(HTMLParser):
    price = Collector("div[data-pernight]", PriceHandler())
    offer = Collector("div[data-offerclient]")

    def clean(self):
        if self.data["offer"]:
            self.data = dict(self.data["price"])
        else:
            self.data = None


class TripAdvisorParserError(Exception):
    pass


class IncorrectConfig(Exception):
    pass


class TripAdvisorParser:
    LOCATION_PATH_PATTERN = re.compile(r"/Hotels-g(\d+)-[a-zA-Z_]+-Hotels\.html")
    HOTEL_PATH_PATTERN = re.compile(r"/Hotel_Review-g\d+-d(\d+)-Reviews-\w+-\w+\.html")
    HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"}

    def __init__(self):
        if not os.path.exists("config.yaml"):
            shutil.copyfile("config.default.yaml", "config.yaml")
        with open("config.yaml") as f:
            config = yaml.load(f)
        self.config = {}
        self.config["out_dir_path"] = config.get("out_dir_path", "output")
        self.config["skip_errors"] = config.get("skip_errors", False)
        self.config["languages"] = collections.OrderedDict([("en", "www.tripadvisor.com")])
        self.config["languages"].update(config.get("extra_languages", {}))
        try:
            self.config["services_path"] = config["services_path"]
        except KeyError:
            raise IncorrectConfig("'service_path' is missing")
        self.config["exclude_services"] = config.get("exclude_services", {})
        self.config["max_photo_count"] = config.get("max_photo_count")
        self.config["price_interval"] = config.get("price_interval", 15)
        location_paths = {}
        hotel_paths = {}
        for path in config.get("paths", []):
            for pattern in [self.LOCATION_PATH_PATTERN, self.HOTEL_PATH_PATTERN]:
                match = pattern.fullmatch(path)
                if match:
                    if pattern == self.LOCATION_PATH_PATTERN:
                        location_paths[path] = match.group(1)
                    else:
                        hotel_paths[path] = match.group(1)
                    break
            if not match:
                raise IncorrectConfig("path '{}' is incorrect".format(path))
        self.config["location_paths"] = location_paths
        self.config["hotel_paths"] = hotel_paths
        if not os.path.exists(self.config["out_dir_path"]):
            os.makedirs(self.config["out_dir_path"])
        logging.basicConfig(format="%(levelname)s: %(message)s",
            filename=os.path.join(self.config["out_dir_path"], "errors.log"),
            filemode="w", level=logging.ERROR
        )
        self.failure_count = 0

    def init_db(self):
        db_path = os.path.join(self.config["out_dir_path"], "tripadvisor.db")
        images_path = os.path.join(self.config["out_dir_path"], "images")
        has_db = os.path.exists(db_path)
        if not has_db and os.path.exists(images_path):
            shutil.rmtree(images_path)
        self.connection = sqlite3.connect(db_path)
        self.connection.cursor().execute("""PRAGMA foreign_keys = ON""")
        if not has_db:
            print("creating tables")
            self.create_tables()
            self.create_languages()

    def parse_services(self):
        services = {}
        prev_lang = None
        for lang, domain in self.config["languages"].items():
            request = urllib.request.Request("https://" + domain + self.config["services_path"], headers=self.HEADERS)
            response = urllib.request.urlopen(request)
            if response.getcode() != 200:
                raise TripAdvisorParserError
            parser = ServicesHTMLParser()
            html = response.read().decode("utf-8")
            parser(html)
            if prev_lang and len(services[prev_lang]) != len(parser.data["services"]):
                raise TripAdvisorParserError(
                    "services have different length in translations ('{}', '{}'): {} and {}".format(
                        prev_lang, lang, len(services[prev_lang]), len(parser.data["services"]))
                    )
            services[lang] = parser.data["services"]
            prev_lang = lang
        return services

    def proc_hotel_paths(self, paths):
        hotel_paths = {}
        for path in paths:
            match = self.HOTEL_PATH_PATTERN.fullmatch(path)
            if not match:
                raise TripAdvisorParserError("hotel path '{}' is incorrect".format(path))
            hotel_paths[path] = match.group(1)
        return hotel_paths

    def parse_hotels(self, geo):
        headers = self.HEADERS.copy()
        headers["X-Requested-With"] = "XMLHttpRequest"
        domain = self.config["languages"]["en"]
        data = {
            "geo": geo,
            "o": "a0",
            "adults": 1,
            "rooms": 1,
            "seen": 0,
            "sortOrder": "distLow",
            "displayedSortOrder": "recommended",
            "requestingServlet": "Hotels",
            # "sequence": 1,
            # "refineForm": "true",
            # "dateBumped": "NONE",
            # "rad": 0,
            # "hs": "",
            # "pageSize": "",
        }
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        url = "https://" + domain + "/Hotels"
        request = urllib.request.Request(url, urllib.parse.urlencode(data).encode("ascii"), headers)
        response = opener.open(request)
        parser = HotelsHTMLParser()
        parser(response.read().decode("utf-8"))
        parser.disable("page_count")
        hotel_paths = self.proc_hotel_paths(parser.data["paths"])
        for i in range(30, parser.data["page_count"] * 30, 30):
            data["o"] = "a" + str(i)
            request = urllib.request.Request(url, urllib.parse.urlencode(data).encode("ascii"), headers)
            response = opener.open(request)
            parser(response.read().decode("utf-8"))
            hotel_paths.update(self.proc_hotel_paths(parser.data["paths"]))
        return hotel_paths

    @staticmethod
    def zip_translation(translation):
        for texts in zip(*translation.values()):
            text = {}
            for i, lang in enumerate(translation.keys()):
                text[lang] = texts[i]
            yield text

    # def get_website(self, path):
    #     ignored_keys = ("utm_", "cm_mmc", "wt.mc_id", "source", "pmf", "pid", "scid", "cid", "iata", "facilitator", "csref", "xts", "xtor", "em", "fbtrack")
    #     ignored_values = ("tripadvisor", "trip_advisor", "trip-advisor", "trip+advisor", "trip advisor")
    #     domain = self.config["languages"]["en"]
    #     connection = http.client.HTTPSConnection(domain)
    #     connection.request("GET", path, headers=self.HEADERS)
    #     response = connection.getresponse()
    #     if response.status == 302:
    #         url_parts = urllib.parse.urlsplit(response.getheader("Location"))
    #         if url_parts[3].lower().startswith(("http://", "https://")):
    #             url_parts = urllib.parse.urlsplit(url_parts[3])
    #         url_parts = list(url_parts)
    #         query = urllib.parse.parse_qs(url_parts[3])
    #         for key, values in list(query.items()):
    #             if (key.lower().startswith(ignored_keys) or
    #                     any(ignored_value in value for ignored_value in ignored_values for value in (value.lower() for value in values))):
    #                 del query[key]
    #         url_parts[3] = urllib.parse.urlencode(query, doseq=True)
    #         return urllib.parse.urlunsplit(url_parts)

    def get_website(self, path):
        website = {}
        for lang, domain in self.config["languages"].items():
            connection = http.client.HTTPSConnection(domain)
            connection.request("GET", path, headers=self.HEADERS)
            response = connection.getresponse()
            if response.status == 302:
                website[lang] = response.getheader("Location")
            connection.close()
        if website:
            return website

    def get_email(self, hotel_id):
        domain = self.config["languages"]["en"]
        query = urllib.parse.urlencode({
            "detail": hotel_id,
            "quests": 1,
            "isOfferEmail": "false",
            "rooms": 1
        })
        url = "https://" + domain + "/EmailHotel?" + query
        opener = urllib.request.OpenerDirector()
        opener.add_handler(urllib.request.HTTPSHandler())
        opener.add_handler(urllib.request.HTTPDefaultErrorHandler())
        opener.add_handler(urllib.request.HTTPErrorProcessor())
        request = urllib.request.Request(url, headers=self.HEADERS)
        try:
            response = opener.open(request)
        except urllib.error.HTTPError:
            return None
        else:
            parser = HotelEmailHTMLParser()
            parser(response.read().decode("utf-8"))
            return parser.data["email"]

    def parse_photo_urls(self, hotel_id):
        domain = self.config["languages"]["en"]
        query = urllib.parse.urlencode({
            "detail": hotel_id,
            "filter": 1
        })
        url = "https://" + domain + "/LocationPhotoAlbum?detail=" + query
        request = urllib.request.Request(url, headers=self.HEADERS)
        response = urllib.request.urlopen(request)
        parser = HotelGalleryHTMLParser()
        parser(response.read().decode("utf-8"))
        raw_urls = parser.data["photo_urls"]
        urls = []
        for url in raw_urls:
            if url not in urls:
                urls.append(url)
        return urls

    def parse_hotel(self, path, hotel_id):
        hotel = {}
        parser = HotelHTMLParser()
        query = urllib.parse.urlencode({
            "detail": hotel_id,
            "placementName": "hr_btf_north_star_about",
            "servletClass": "com.TripResearch.servlet.accommodation.AccommodationDetail",
            "servletName": "Hotel_Review",
            "more_content_request": "true"
        })
        prev_lang = None
        for lang, domain in self.config["languages"].items():
            html_pages = []
            urls = [
                "https://" + domain + path,
                "https://" + domain + "/MetaPlacementAjax?" + query
            ]
            for url in urls:
                request = urllib.request.Request(url, headers=self.HEADERS)
                response = urllib.request.urlopen(request)
                html_pages.append(response.read().decode("utf-8"))
            for i, html in enumerate(html_pages, start=1):
                parser(html, i == len(html_pages))
            for name, val in parser.data.items():
                if not parser.is_translation(name):
                    if prev_lang and hotel[name] != val:
                        raise TripAdvisorParserError(
                            "field '{}' has different value in translations ('{}', '{}'): '{}'  and '{}'".format(
                                name, prev_lang, lang, hotel[name], val
                            )
                        )
                    hotel[name] = val
                else:
                    if not prev_lang:
                        hotel[name] = translation = {} if val else None
                    else:
                        translation = hotel[name]
                    if translation is not None:
                        if name == "services":
                            exclude_services = self.config["exclude_services"].get(lang)
                            if exclude_services is not None:
                                services = []
                                for service in val:
                                    if service not in exclude_services:
                                        services.append(service)
                                val = services
                        if prev_lang and name in ("location", "services") and len(translation[prev_lang]) != len(val):
                            raise TripAdvisorParserError(
                                "field '{}' has different length in translations ('{}', '{}'): {} and {}".format(
                                    name, prev_lang, lang, len(translation[prev_lang]), len(val)
                                )
                            )
                        translation[lang] = val
            prev_lang = lang
        if hotel["website"]:
            hotel["website"] = self.get_website(hotel["website"])
        hotel["email"] = self.get_email(hotel_id)
        return hotel

    def create_tables(self):
        cursor = self.connection.cursor()
        cursor.execute("""CREATE TABLE `hotels` (
            `id` INTEGER,
            `name_translation_id` INTEGER NOT NULL,
            `address_id` INTEGER NOT NULL,
            `phone_translation_id` INTEGER,
            `website_translation_id` INTEGER,
            `email` TEXT,
            `description_translation_id` INTEGER,
            `star_count` INTEGER,
            `room_count` INTEGER,
            `path` TEXT NOT NULL UNIQUE,
            PRIMARY KEY(`id`),
            FOREIGN KEY(`address_id`) REFERENCES `addresses`(`id`),
            FOREIGN KEY(`name_translation_id`) REFERENCES `translations`(`id`),
            FOREIGN KEY(`phone_translation_id`) REFERENCES `translations`(`id`),
            FOREIGN KEY(`website_translation_id`) REFERENCES `translations`(`id`),
            FOREIGN KEY(`description_translation_id`) REFERENCES `translations`(`id`)
        )""")
        cursor.execute("""CREATE TABLE `hotel_price_updates` (
            `hotel_id` INTEGER,
            `updated` TEXT NOT NULL,
            `interval` INTEGER NOT NULL,
            PRIMARY KEY (`hotel_id`),
            FOREIGN KEY (`hotel_id`) REFERENCES `hotels`(`id`)
        )""")
        cursor.execute("""CREATE TABLE `images` (
            `id` INTEGER,
            `hash` TEXT UNIQUE NOT NULL,
            `path` TEXT NOT NULL,
            PRIMARY KEY(`id`)
        )""")
        cursor.execute("""CREATE TABLE `hotel_photos` (
            `hotel_id` INTEGER NOT NULL,
            `image_id` INTEGER NOT NULL,
            `url` TEXT NOT NULL,
            FOREIGN KEY(`hotel_id`) REFERENCES `hotels`(`id`),
            FOREIGN KEY(`image_id`) REFERENCES `images`(`id`)
        )""")
        cursor.execute("""CREATE TABLE `locations` (
            `id` INTEGER,
            `parent_id` INTEGER,
            `name_translation_id` INTEGER NOT NULL,
            PRIMARY KEY(`id`),
            FOREIGN KEY(`parent_id`) REFERENCES `locations`(`id`),
            FOREIGN KEY(`name_translation_id`) REFERENCES `translations`(`id`)
        )""")
        cursor.execute("""CREATE TABLE `addresses` (
            `id` INTEGER,
            `location_id` INTEGER NOT NULL,
            `street_translation_id` INTEGER,
            `postal_code` TEXT,
            PRIMARY KEY(`id`),
            FOREIGN KEY(`location_id`) REFERENCES `locations`(`id`),
            FOREIGN KEY(`street_translation_id`) REFERENCES `translations`(`id`)
        )""")
        cursor.execute("""CREATE TABLE `services` (
            `id` INTEGER,
            `name_translation_id` INTEGER NOT NULL,
            `is_extra` NUMERIC,
            PRIMARY KEY(`id`),
            FOREIGN KEY(`name_translation_id`) REFERENCES `translations`(`id`)
        )""")
        cursor.execute("""CREATE TABLE `hotel_services` (
            `hotel_id` INTEGER NOT NULL,
            `service_id` INTEGER NOT NULL,
            FOREIGN KEY(`hotel_id`) REFERENCES `hotels`(`id`),
            FOREIGN KEY(`service_id`) REFERENCES `services`(`id`)
        )""")
        cursor.execute("""CREATE TABLE `hotel_prices` (
            `id` INTEGER,
            `hotel_id` INTEGER NOT NULL,
            `date` TEXT NOT NULL,
            PRIMARY KEY(`id`),
            FOREIGN KEY(`hotel_id`) REFERENCES `hotels`(`id`)
        )""")
        cursor.execute("""CREATE TABLE `vendors` (
            `id` INTEGER,
            `name` TEXT NOT NULL UNIQUE,
            PRIMARY KEY(`id`)
        )""")
        cursor.execute("""CREATE TABLE `vendor_prices` (
            `id` INTEGER,
            `hotel_price_id` INTEGER NOT NULL,
            `vendor_id` INTEGER NOT NULL,
            `price` INTEGER NOT NULL,
            PRIMARY KEY(`id`),
            FOREIGN KEY(`hotel_price_id`) REFERENCES `hotel_prices`(`id`) ON DELETE CASCADE,
            FOREIGN KEY(`vendor_id`) REFERENCES `vendors`(`id`)
        )""")
        # TODO
        # cursor.execute("""CREATE TABLE `rooms` (
        #     `id` INTEGER,
        #     `hotel_id` INTEGER NOT NULL,
        #     `name_translation_id` INTEGER NOT NULL,
        #     `adult_occupancy` INTEGER,
        #     `child_occupancy` INTEGER,
        #     `description_translation_id` INTEGER NOT NULL,
        #     `other_translation_id` INTEGER NOT NULL,
        #     `count` INTEGER,
        #     PRIMARY KEY(`id`),
        #     FOREIGN KEY(`hotel_id`) REFERENCES `hotels`(`id`),
        #     FOREIGN KEY(`name_translation_id`) REFERENCES `translations`(`id`),
        #     FOREIGN KEY(`description_translation_id`) REFERENCES `translations`(`id`),
        #     FOREIGN KEY(`other_translation_id`) REFERENCES `translations`(`id`)
        # )""")
        # cursor.execute("""CREATE TABLE `room_prices` (
        #     `id` INTEGER,
        #     `room_id` INTEGER NOT NULL,
        #     `start_date` NUMERIC,
        #     `worth` REAL,
        #     PRIMARY KEY(`id`),
        #     FOREIGN KEY(`room_id`) REFERENCES `rooms`(`id`)
        # )""")
        # cursor.execute("""CREATE TABLE `room_services` (
        #     `room_id` INTEGER NOT NULL,
        #     `service_id` INTEGER NOT NULL,
        #     FOREIGN KEY(`room_id`) REFERENCES `rooms`(`id`),
        #     FOREIGN KEY(`service_id`) REFERENCES `services`(`id`)
        # )""")
        # cursor.execute("""CREATE TABLE `room_reservations` (
        #     `id` INTEGER,
        #     `room_id` INTEGER NOT NULL,
        #     `checkin` NUMERIC,
        #     `checkout` NUMERIC,
        #     PRIMARY KEY(`id`),
        #     FOREIGN KEY(`room_id`) REFERENCES `rooms`(`id`)
        # )""")
        cursor.execute("""CREATE TABLE `translations` (
            `id` INTEGER,
            PRIMARY KEY(`id`)
        )""")
        cursor.execute("""CREATE TABLE `translation_entries` (
            `id` INTEGER,
            `translation_id` INTEGER NOT NULL,
            `language_id` INTEGER NOT NULL,
            `text` TEXT NOT NULL,
            PRIMARY KEY(`id`),
            FOREIGN KEY(`translation_id`) REFERENCES `translations`(`id`),
            FOREIGN KEY(`language_id`) REFERENCES `translation_languages`(`id`)
        )""")
        cursor.execute("""CREATE TABLE `translation_languages` (
            `id` INTEGER,
            `char_code` TEXT NOT NULL,
            PRIMARY KEY(`id`)
        )""")

    def create_languages(self):
        cursor = self.connection.cursor()
        for char_code in self.config["languages"]:
            cursor.execute("""INSERT INTO `translation_languages` (`char_code`) VALUES (?)""", (char_code,))
        self.connection.commit()

    def get_language(self, char_code):
        cursor = self.connection.cursor()
        cursor.execute("""SELECT `id` FROM `translation_languages` WHERE `char_code` = ?""", (char_code,))
        result = cursor.fetchone()
        if result:
            return result[0]

    def create_service(self, name, is_extra=True):
        cursor = self.connection.cursor()
        cursor.execute("""SELECT `services`.`id`, `services`.`is_extra` FROM `services`, `translation_entries`
            WHERE `services`.`name_translation_id` = `translation_entries`.`translation_id`
            AND `translation_entries`.`language_id` = ?
            AND `translation_entries`.`text` = ?
        """, (self.get_language("en"), name["en"]))
        result = cursor.fetchone()
        if not result:
            cursor.execute("""INSERT INTO `services` (`name_translation_id`, `is_extra`) VALUES (?, ?)""", (self.create_translation(name), is_extra))
            return cursor.lastrowid
        # if result[1] != is_extra:
        #     cursor.execute("""UPDATE `services` SET `is_extra` = ? WHERE `id` = ?""", (is_extra, result[0]))
        return result[0]

    def create_translation(self, translation):
        cursor = self.connection.cursor()
        cursor.execute("""INSERT INTO `translations` DEFAULT VALUES""")
        translation_id = cursor.lastrowid
        texts = set()
        for char_code, text in translation.items():
            if text and text not in texts:
                cursor.execute("""INSERT INTO `translation_entries` (`translation_id`, `language_id`, `text`)
                    VALUES (?, (SELECT `id` FROM `translation_languages` WHERE `char_code` = ?), ?)
                """, (translation_id, char_code, text))
                texts.add(text)
        return translation_id

    def create_address(self, location, street, postal_code):
        cursor = self.connection.cursor()
        location_id = None
        is_new_location = False
        for location_item in self.zip_translation(location):
            if not is_new_location:
                cursor.execute("""SELECT `locations`.`id` FROM `locations`, `translation_entries`
                    WHERE `locations`.`parent_id` IS ?
                    AND `locations`.`name_translation_id` = `translation_entries`.`translation_id`
                    AND `translation_entries`.`language_id` = ?
                    AND `translation_entries`.`text` = ?
                """, (location_id, self.get_language("en"), location_item["en"]))
                result = cursor.fetchone()
            else:
                result = None
            if result:
                location_id = result[0]
            else:
                cursor.execute("""INSERT INTO `locations` (`parent_id`, `name_translation_id`)
                    VALUES (?, ?)
                """, (location_id, self.create_translation(location_item)))
                location_id = cursor.lastrowid
                is_new_location = True
        if street:
            street_translation_id = self.create_translation(street)
        else:
            street_translation_id = None
        cursor.execute("""INSERT INTO `addresses` (`location_id`, `street_translation_id`, `postal_code`)
            VALUES (?, ?, ?)
        """, (location_id, street_translation_id, postal_code))
        return cursor.lastrowid

    def create_hotel(self, hotel):
        cursor = self.connection.cursor()
        translation = {}
        translation["name"] = self.create_translation(hotel["name"])
        for key in ("phone", "website", "description"):
            if hotel[key]:
                translation[key] = self.create_translation(hotel[key])
            else:
                translation[key] = None
        address_id = self.create_address(hotel["location"], hotel["street"], hotel["postal_code"])
        cursor.execute("""INSERT INTO `hotels`
            (`name_translation_id`, `address_id`, `phone_translation_id`, `website_translation_id`, `email`,
            `description_translation_id`, `star_count`, `room_count`, `path`)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (translation["name"], address_id, translation["phone"], translation["website"], hotel["email"],
            translation["description"], hotel["star_count"], hotel["room_count"], hotel["path"])
        )
        hotel_id = cursor.lastrowid
        if hotel["services"]:
            for name in self.zip_translation(hotel["services"]):
                cursor.execute("""INSERT INTO `hotel_services` VALUES (?, ?)""", (hotel_id, self.create_service(name)))
        self.connection.commit()

    def fetch_hotel(self, path, hotel_id):
        hotel = self.parse_hotel(path, hotel_id)
        hotel["path"] = path
        self.create_hotel(hotel)

    def handle_error(self, func, path):
        status = "passed"
        try:
            func()
        except (TripAdvisorParserError, ValueHandlerError, CollectorError):
            if not self.config["skip_errors"]:
                raise
            logging.exception(path)
            self.failure_count += 1
            status = "failed"
        return status

    def fetch_main_services(self):
        for name in self.zip_translation(self.parse_services()):
            self.create_service(name, False)
        self.connection.commit()

    def fetch_hotels(self):
        self.init_db()
        print("fetching main services: {}".format(self.config["services_path"]))
        self.fetch_main_services()
        location_paths = self.config["location_paths"]
        hotel_paths = self.config["hotel_paths"]
        if location_paths:
            print("collecting hotel paths:")
            for i, values in enumerate(location_paths.items(), start=1):
                path, geo = values
                print("{} of {}: {}".format(i, len(location_paths), path))
                status = self.handle_error(lambda: hotel_paths.update(self.parse_hotels(geo)), path)
                print("{}, {} failures".format(status, self.failure_count))
        print("removing duplicates in hotel paths")
        cursor = self.connection.cursor()
        cursor.execute("""SELECT `path` FROM `hotels`""")
        for (path,) in cursor:
            if path in hotel_paths:
                del hotel_paths[path]
        if hotel_paths:
            print("fetching hotels:")
            for i, values in enumerate(hotel_paths.items(), start=1):
                path, hotel_id = values
                print("{} of {}: {}".format(i, len(hotel_paths), path))
                status = self.handle_error(lambda: self.fetch_hotel(path, hotel_id), path)
                print("{}, {} failures".format(status, self.failure_count))

    def update_hotels(self): # TODO
        pass

    def create_image(self, data):
        cursor = self.connection.cursor()
        m = hashlib.md5()
        m.update(data)
        hash_ = m.hexdigest()
        cursor.execute("""SELECT `id` FROM `images` WHERE `hash` = ?""", (hash_,))
        result = cursor.fetchone()
        if not result:
            path = os.path.join("images", "/".join(hash_[i - 1] + hash_[i] for i in range(1, 8, 2)))
            dir_path = os.path.join(self.config["out_dir_path"], path)
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)
            path = os.path.join(path, hash_[8:] + ".jpg")
            with open(os.path.join(self.config["out_dir_path"], path), "wb") as f:
                f.write(data)
            cursor.execute("""INSERT INTO `images` (`hash`, `path`) VALUES (?, ?)""", (hash_, path))
            return cursor.lastrowid
        return result[0]

    def load_image(self, url):
        request = urllib.request.Request(url, headers=self.HEADERS)
        try:
            response = urllib.request.urlopen(request)
        except urllib.error.HTTPError:
            return None
        else:
            return response.read()

    def fetch_hotel_photos(self, hotel_id, path):
        cursor = self.connection.cursor()
        match = self.HOTEL_PATH_PATTERN.fullmatch(path)
        max_photo_count = self.config["max_photo_count"]
        for i, url in enumerate(self.parse_photo_urls(match.group(1))):
            is_loaded_image = True
            if i == max_photo_count:
                break
            cursor.execute("""SELECT * FROM `hotel_photos` WHERE `hotel_id` = ? AND `url` = ?""", (hotel_id, url))
            result = cursor.fetchone()
            if not result:
                data = self.load_image(url)
                if data:
                    cursor.execute("""INSERT INTO `hotel_photos` VALUES (?, ?, ?)""", (hotel_id, self.create_image(data), url))
                    self.connection.commit()
                else:
                    max_photo_count += 1
                    is_loaded_image = False
            if is_loaded_image:
                print("  {}".format(url))

    def fetch_photos(self):
        self.init_db()
        cursor = self.connection.cursor()
        cursor.execute("""SELECT COUNT(*) FROM `hotels`""")
        hotel_count = cursor.fetchone()[0]
        if hotel_count:
            print("fetching photos:")
            cursor.execute("""SELECT `id`, `path` FROM `hotels`""")
            for i, values in enumerate(cursor, start=1):
                hotel_id, path = values
                print("{} of {}: {}".format(i, hotel_count, path))
                status = self.handle_error(lambda: self.fetch_hotel_photos(hotel_id, path), path)
                print("{}, {} failures".format(status, self.failure_count))

    def parse_hotel_price(self, path, date):
        req_1_headers = self.HEADERS.copy()
        req_1_headers.update({
            "X-Requested-With": "XMLHttpRequest",
            "Cookie": "SetCurrency=USD"
        })
        req_2_headers = self.HEADERS.copy()
        req_2_headers.update({
            "X-Requested-With": "XMLHttpRequest"
        })
        req_1_data = urllib.parse.urlencode({
            "rooms": 1,
            "adults": 1,
            "child_rm_ages": "",
            "reqNum": 1,
            "staydates": "{}_{}".format(date.strftime("%Y_%m_%d"), (date + datetime.timedelta(1)).strftime("%Y_%m_%d")),
            "changeSet": "TRAVEL_INFO"
        })
        req_2_data = urllib.parse.urlencode({
            "reqNum": 2
        })
        domain = self.config["languages"]["en"]
        url = "https://" + domain + path + "?"
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        request = urllib.request.Request(url, req_1_data.encode("ascii"), headers=req_1_headers)
        opener.open(request)
        request = urllib.request.Request(url, req_2_data.encode("ascii"), headers=req_2_headers)
        response = opener.open(request)
        parser = HotelPriceHTMLParser()
        parser(response.read().decode("utf-8"))
        return parser.data

    def create_hotel_price(self, hotel_id, date, price):
        cursor = self.connection.cursor()
        cursor.execute("""INSERT INTO `hotel_prices` (`hotel_id`, `date`) VALUES (?, ?)""", (hotel_id, date.strftime("%Y_%m_%d")))
        hotel_price_id = cursor.lastrowid
        for vendor_name, vendor_price in price.items():
            cursor.execute("""SELECT `id` FROM `vendors` WHERE `name` = ?""", (vendor_name,))
            result = cursor.fetchone()
            if result:
                vendor_id = result[0]
            else:
                cursor.execute("""INSERT INTO `vendors` (`name`) VALUES (?)""", (vendor_name,))
                vendor_id = cursor.lastrowid
            cursor.execute("""INSERT INTO `vendor_prices` (`hotel_price_id`, `vendor_id`, `price`)
                VALUES (?, ?, ?)
            """, (hotel_price_id, vendor_id, vendor_price))
        self.connection.commit()

    def fetch_hotel_price(self, hotel_id, path, today):
        cursor = self.connection.cursor()
        cursor.execute("""SELECT `updated`, `interval` FROM `hotel_price_updates` WHERE `hotel_id` = ?""", (hotel_id,))
        result = cursor.fetchone()
        if result:
            updated, interval = result
        today_str = today.strftime("%Y_%m_%d")
        if not result:
            start = 0
        elif today_str != updated:
            cursor.execute("""DELETE FROM `hotel_prices` WHERE `hotel_id` = ? AND `date` >= ?""", (hotel_id, today_str))
            self.connection.commit()
            start = 0
        elif self.config["price_interval"] > interval:
            start = interval
        else:
            start = None
        if start is not None:
            error = None
            count = start
            for i in range(start, self.config["price_interval"]):
                date = today + datetime.timedelta(i)
                try:
                    price = self.parse_hotel_price(path, date)
                except (ValueHandlerError, CollectorError) as e:
                    error = e
                    break
                else:
                    if price is None:
                        break
                    print("  {}: {}".format(date, price))
                    self.create_hotel_price(hotel_id, date, price)
                    count += 1
            if result:
                cursor.execute("""UPDATE `hotel_price_updates` SET `updated` = ?, `interval` = ?
                    WHERE `hotel_id` = ?
                """, (today_str, count, hotel_id))
            else:
                cursor.execute("""INSERT INTO `hotel_price_updates` (`hotel_id`, `updated`, `interval`)
                    VALUES (?, ?, ?)
                """, (hotel_id, today_str, count))
            self.connection.commit()
            if error:
                raise error

    def fetch_prices(self):
        self.init_db()
        cursor = self.connection.cursor()
        cursor.execute("""SELECT COUNT(*) FROM `hotels`""")
        hotel_count = cursor.fetchone()[0]
        if hotel_count:
            cursor.execute("""SELECT `id`, `path` FROM `hotels`""")
            today = datetime.date.today()
            print("fetching prices:")
            for i, (hotel_id, path) in enumerate(cursor, start=1):
                print("{} of {}: {}".format(i, hotel_count, path))
                status = self.handle_error(lambda: self.fetch_hotel_price(hotel_id, path, today), path)
                print("{}, {} failures".format(status, self.failure_count))

    def clean(self):
        db_path = os.path.join(self.config["out_dir_path"], "tripadvisor.db")
        images_path = os.path.join(self.config["out_dir_path"], "images")
        if os.path.exists(db_path):
            os.remove(db_path)
        if os.path.exists(images_path):
            shutil.rmtree(images_path)


if __name__ == "__main__":
    start_time = time.time()
    parser = argparse.ArgumentParser()
    parser.add_argument("task", choices=["fetch_hotels", "fetch_photos", "fetch_prices", "clean"], help="execute task")
    args = parser.parse_args()
    ta_parser = TripAdvisorParser()
    if args.task == "fetch_hotels":
        ta_parser.fetch_hotels()
    elif args.task == "fetch_photos":
        ta_parser.fetch_photos()
    elif args.task == "fetch_prices":
        ta_parser.fetch_prices()
    else:
        ta_parser.clean()
    elapsed_time = int(time.time() - start_time)
    print("elapsed: {}m {}s, {} failures".format(elapsed_time // 60, elapsed_time % 60, ta_parser.failure_count))
