from .arknights import ArknightsProcessor as ArknightsProcessor
from .genshin import GenshinProcessor as GenshinProcessor
from .pgr import PGRProcessor as PGRProcessor
from .starrail import StarrailProcessor as StarrailProcessor
from .umamusume import UmaMusumeProcessor as UmaMusumeProcessor
from .wutheringwaves import WutheringWavesProcessor as WutheringWavesProcessor
from .zenless import ZenlessProcessor as ZenlessProcessor

__all__ = [
    "ArknightsProcessor",
    "GenshinProcessor",
    "StarrailProcessor",
    "ZenlessProcessor",
    "WutheringWavesProcessor",
    "PGRProcessor",
    "UmaMusumeProcessor",
]
