"""This module provides enumerations for various site locations and language codes."""

from enum import Enum


class Site(str, Enum):
    """Enumeration representing various site locations.

    Attributes:
        SWEDEN_STERILE (str): Sweden sterile site.
        SWEDEN_SBC (str): Sweden SBC site.
        SWEDEN_OSD (str): Sweden OSD site.
        US_MOUNT_VERMONT (str): Mount Vernon site in the United States.
        CHINA_TAIZHOU (str): Taizhou site in China.
        CHINA_WUXI (str): Wuxi site in China.
        EMPTY (str): Represents an empty site value.
    """

    SWEDEN_STERILE = "sweden_sterile"
    SWEDEN_SBC = "sweden_sbc"
    SWEDEN_OSD = "sweden_osd"
    US_MOUNT_VERMONT = "us_mount_vermont"
    CHINA_TAIZHOU = "china_thaizou"
    CHINA_WUXI = "china_wuxi"
    EMPTY = ""


class Language(str, Enum):
    """Enumeration representing various language codes.

    Attributes:
        ENGLISH (str): English language, code 'en'.
        SWEDISH (str): Swedish language, code 'sv'.
        FRENCH (str): French language, code 'fr'.
        ARABIC (str): Arabic language, code 'ar'.
        JAPANESE (str): Japanese language, code 'ja'.
        CHINESE (str): Chinese language, code 'zh'.
    """

    ENGLISH = "en"
    SWEDISH = "sv"
    FRENCH = "fr"
    ARABIC = "ar"
    JAPANESE = "ja"
    CHINESE = "zh"
