import logging
import re
from typing import Dict, Iterator, List, Optional, Tuple, cast

import yarl
from bs4 import Tag
from pyppeteer.page import Page

from grobber.decorators import cached_property
from grobber.languages import Language
from grobber.request import DefaultUrlFormatter, Request
from grobber.url_pool import UrlPool
from grobber.utils import get_certainty
from . import register_source
from ..models import SearchResult, SourceAnime, SourceEpisode

log = logging.getLogger(__name__)

BASE_URL = "{9ANIME_URL}"
SEARCH_URL = BASE_URL + "/search"

RE_DUB_STRIPPER = re.compile(r"\s\(Dub\)$")

JS_EXTRACT_EPISODES = """
Array.from(document.querySelectorAll("div.server:not(.hidden) ul.episodes a"))
.map(epLink => ({
    episode: epLink.dataset.comment, 
    href: epLink.href,
}));
"""


def parse_raw_title(raw_title: str) -> Tuple[str, bool]:
    title = RE_DUB_STRIPPER.sub("", raw_title, 1)
    dubbed = raw_title.endswith("(Dub)")
    return title, dubbed


def extract_episode_count(ep_text_container: Optional[Tag]) -> Optional[int]:
    if ep_text_container:
        try:
            ep_text = ep_text_container.text.split("/", 1)[0].strip()[3:].lower()
        except Exception:
            log.exception(f"couldn't extract episode text from {ep_text_container}")
            return None

        if ep_text.endswith("-preview"):
            ep_text = ep_text[:-len("-preview")]
            preview = True
        else:
            preview = False

        try:
            ep = int(ep_text)
        except ValueError:
            # movie
            if ep_text == "full":
                return 1

            log.warning(f"Couldn't tell episode count from \"{ep_text}\": {ep_text_container}")
            return None
        else:
            if preview:
                ep -= 1

            return ep
    else:
        # this is a movie
        return 1


class NineEpisode(SourceEpisode):
    @cached_property
    async def raw_streams(self) -> List[str]:
        raw_streams = []
        async with self._req.page as page:
            page = cast(Page, page)
            await page.waitFor("div#player .cover")
            await page.evaluate("""document.querySelector("div#player .cover").click();""")

            episode_base = await page.evaluate("""document.querySelector("ul.episodes a.active").getAttribute("data-base");""")
            servers = await page.querySelectorAll(f"ul.episodes a[data-base=\"{episode_base}\"]")

            for server in servers:
                try:
                    await page.evaluate("""(el) => el.click()""", server)
                    await page.bringToFront()
                    await page.waitFor("div#player iframe")
                    src = await page.evaluate("""document.querySelector("div#player iframe").src;""", force_expr=True)
                    raw_streams.append(src)
                except Exception as e:
                    log.exception("Couldn't get src of server")
                finally:
                    await server.dispose()

        log.debug(f"extracted {len(raw_streams)} raw streams from page")
        return raw_streams


class NineAnime(SourceAnime):
    EPISODE_CLS = NineEpisode

    @cached_property
    async def raw_title(self) -> str:
        return (await self._req.bs).select_one("h2.title").text.strip()

    @cached_property
    async def title(self) -> str:
        return parse_raw_title(await self.raw_title)[0]

    @cached_property
    async def thumbnail(self) -> Optional[str]:
        return (await self._req.bs).select_one("div.thumb img")["src"]

    @cached_property
    async def is_dub(self) -> bool:
        return parse_raw_title(await self.raw_title)[1]

    @cached_property
    async def language(self) -> Language:
        return Language.ENGLISH

    @classmethod
    async def search(cls, query: str, *, language=Language.ENGLISH, dubbed=False) -> Iterator[SearchResult]:
        if language != Language.ENGLISH:
            return

        for _ in range(5):
            req = Request(SEARCH_URL, {"keyword": query}, use_proxy=True)
            bs = await req.bs
            container = bs.select_one("div.film-list")

            if container:
                break

            log.debug(f"trying again {req._text}")
            req.reload()
        else:
            log.warning(f"{cls} Couldn't get search results, retries exceeded!")
            return

        search_results = container.select("div.item")

        for result in search_results:
            raw_title = result.select_one("a.name").text
            title, is_dub = parse_raw_title(raw_title)

            if dubbed != is_dub:
                continue

            data = dict(title=title, is_dub=is_dub)

            ep_text_container = result.select_one("div.ep")
            ep_count = extract_episode_count(ep_text_container)
            if ep_count is not None:
                data["episode_count"] = ep_count

            link = yarl.URL(result.select_one("a.poster")["href"])
            data["thumbnail"] = result.select_one("a.poster img")["src"]
            similarity = get_certainty(query, title)

            anime = cls(Request(BASE_URL + link.path), data=data)
            yield SearchResult(anime, similarity)

    @cached_property
    async def raw_eps(self) -> Dict[int, EPISODE_CLS]:
        async with self._req.page as page:
            page = cast(Page, page)
            episode_infos: List[dict] = await page.evaluate(
                JS_EXTRACT_EPISODES,
                force_expr=True
            )

            episodes: Dict[int, NineEpisode] = {}

            for ep_data in episode_infos:
                episode_number_str = ep_data["episode"]
                try:
                    episode_number = int(episode_number_str)
                except ValueError:
                    # check if we're dealing with a movie
                    if episode_number_str == "full":
                        if episodes:
                            log.warning(f"{self!r} found \"full\" episode (assuming movie) "
                                        f"but there already are episodes: {episodes} (returning full anyway)")
                        episode_number = 1
                    else:
                        log.info(f"{self!r} Couldn't parse episode number for episode {ep_data}, moving on")
                        continue

                url = yarl.URL(ep_data["href"])
                req = Request(BASE_URL + url.path)
                episodes[episode_number - 1] = self.EPISODE_CLS(req)

            return episodes

    async def get_episodes(self) -> Dict[int, EPISODE_CLS]:
        return await self.raw_eps

    async def get_episode(self, index: int) -> EPISODE_CLS:
        return (await self.raw_eps)[index]


nineanime_pool = UrlPool("9Anime", ["https://9anime.to", "https://www2.9anime.to"])
DefaultUrlFormatter.add_field("9ANIME_URL", lambda: nineanime_pool.url)

register_source(NineAnime)
