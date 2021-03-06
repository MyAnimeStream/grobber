import logging
import re
from typing import AsyncIterator, Dict, List, Optional, Pattern, Tuple

from grobber.decorators import cached_property
from grobber.languages import Language
from grobber.request import DefaultUrlFormatter, Request
from grobber.url_pool import UrlPool
from grobber.utils import add_http_scheme, get_certainty
from . import register_source
from ..models import SearchResult, SourceAnime, SourceEpisode

log = logging.getLogger(__name__)

RE_TITLE_EXTRACTOR: Pattern = re.compile(r"\s*(.+?)( \(Dub\))? Episode ([\d.]+)\s*$")
RE_HEADER_EXTRACTOR: Pattern = re.compile(r"\s*(.+?)( \(Dub\))? Episode ([\d.]+)(?: English Subbed)?\s*$")
RE_URL_SLUG_EXTRACTOR: Pattern = re.compile(r"([^/]+-episode-)(.+)$")

vidstreaming_pool = UrlPool("Vidstreaming", ["https://vidstreaming.io"])
DefaultUrlFormatter.add_field("VIDSTREAMING_URL", lambda: vidstreaming_pool.url)
DefaultUrlFormatter.use_proxy("VIDSTREAMING_URL")

BASE_URL = "{VIDSTREAMING_URL}"


async def is_not_found(req: Request) -> bool:
    text = await req.text
    return text.strip() == "404"


def parse_raw_title(raw_title: str) -> Tuple[str, bool, int]:
    match = RE_TITLE_EXTRACTOR.search(raw_title)
    if not match:
        return "UNKNOWN", False, 0

    title, dubbed_str, episode_number_str = match.groups()
    dubbed: bool = dubbed_str is not None

    try:
        episode_index = int(episode_number_str) - 1
    except ValueError:
        episode_index = 0

    return title, dubbed, episode_index


class VidstreamingEpisode(SourceEpisode):
    @cached_property
    async def streams_page(self) -> Request:
        bs = await self._req.bs
        frame = bs.select_one("div.play-video iframe")
        return Request(add_http_scheme(frame["src"]))

    @cached_property
    async def raw_streams(self) -> List[str]:
        streams_page = await self.streams_page
        bs = await streams_page.bs

        stream_urls = [await streams_page.url]
        streams = bs.select("""li.linkserver[data-status="1"]""")

        for stream in streams:
            href = stream["data-video"]
            url = add_http_scheme(href)
            stream_urls.append(url)

        return stream_urls


class VidstreamingAnime(SourceAnime):
    ATTRS = ("url_slug",)
    EPISODE_CLS = VidstreamingEpisode

    @cached_property
    async def is_dub(self) -> False:
        await self.parse_header()
        return self._is_dub

    @cached_property
    async def language(self) -> Language:
        return Language.ENGLISH

    @cached_property
    async def title(self) -> str:
        await self.parse_header()
        return self._title

    @cached_property
    async def thumbnail(self) -> Optional[str]:
        return None

    async def get_episodes(self) -> Dict[int, EPISODE_CLS]:
        bs = await self._req.bs
        links = bs.select("div.video-info-left ul.items li.video-block a")
        episodes: Dict[int, VidstreamingEpisode] = {}

        for link in reversed(links):
            href = link["href"]
            match = RE_URL_SLUG_EXTRACTOR.search(href)
            if not match:
                log.info(f"Couldn't extract episode number from url: \"{href}\", moving on")
                continue

            episode_number_str = match.group(2)
            try:
                episode_number = int(episode_number_str)
            except ValueError:
                log.info(f"{self!r} Couldn't parse episode number {episode_number_str}. Ignoring episode \"{href}\"")
                continue

            req = Request(f"{BASE_URL}{href}")
            episode = self.EPISODE_CLS(req)
            episodes[episode_number - 1] = episode

        return episodes

    @cached_property
    async def url_slug(self) -> str:
        url = await self._req.url
        match = RE_URL_SLUG_EXTRACTOR.search(url)
        return match.group(1)

    async def get_episode(self, index: int) -> EPISODE_CLS:
        url_slug = await self.url_slug
        url = f"{BASE_URL}/videos/{url_slug}{index + 1}"
        episode_req = Request(url)
        if await is_not_found(episode_req):
            raise KeyError(f"Episode index {index} doesn't exist in {self!r}")

        return self.EPISODE_CLS(episode_req)

    @classmethod
    async def search(cls, query: str, *, dubbed: bool = False, language: Language = Language.ENGLISH) -> AsyncIterator[SearchResult]:
        if language != Language.ENGLISH:
            return

        bs = await Request(f"{BASE_URL}/search.html", dict(keyword=query)).bs
        links = bs.select("ul.items li.video-block a")

        for link in links:
            url = BASE_URL + link["href"]
            title_container = link.select_one("div.name").text
            title, is_dub, ep_count = parse_raw_title(title_container)
            thumbnail = link.select_one("div.picture img")["src"]

            anime = cls(Request(url), data=dict(title=title, thumbnail=thumbnail, is_dub=is_dub, episode_count=ep_count))

            similarity = get_certainty(query, title)
            yield SearchResult(anime, similarity)

    # noinspection PyPropertyAccess
    async def parse_header(self) -> None:
        header = (await self._req.bs).select_one(".video-info h1").text
        match = RE_HEADER_EXTRACTOR.match(header)
        self.title = match.group(1)
        self.is_dub = bool(match.group(2))

        try:
            self.episode_count = int(match.group(3))
        except ValueError as e:
            log.info(f"{self} Couldn't parse episode count, using 0: {e}")
            self.episode_count = 0


register_source(VidstreamingAnime)
