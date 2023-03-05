import json
import os
import re
from dataclasses import dataclass
from random import randint
from time import sleep
from typing import Optional, Union

from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from httpx import Client

URL = str
Part = Union[str, int]

PARTS_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), "parts")
FORCE_REWRITE_URLS_STR = str(os.environ.get("BEAU_FORCEREWRITEURLS", "0"))

def get_force_rewrite_urls():
    return FORCE_REWRITE_URLS_STR.lower() in ("1", "true", "y", "yes")

ua = UserAgent()
session = Client(headers={"User-Agent": ua.firefox})


class PartJSON:
    def __init__(self, file_path, force_rewrite = False) -> None:
        self.new_file = not os.path.exists(file_path) and not force_rewrite
        self.file_path = file_path
        if not self.new_file:
            with open(file_path, "r", encoding="utf-8") as f:
                self._url_dict = json.load(f)
        else:
            self._url_dict = dict()
    
    def save(self):
        with open(self.file_path, "w+", encoding="utf-8") as f:
            json.dump(self._url_dict, f, indent=4)
    
    @property
    def urls_dict(self) -> dict[str, URL]:
        return self._url_dict
    
    @property
    def urls_dict_int(self) -> dict[int, URL]:
        return {int(k): v for k, v in self._url_dict.items()}
    
    @property
    def urls_list(self) -> list[URL]:
        dict_rev = {v: k for k, v in self._url_dict.items()}
        return list(sorted(self._url_dict.values(), key=lambda x: int(dict_rev[x])))
    
    def last_part(self):
        return max(self._url_dict.items(), key=lambda x: int(x[0]))
    
    def last_part_num(self) -> Part:
        return self.last_part()[0]
    
    def last_part_num_int(self) -> Part:
        return int(self.last_part()[0])
    
    def last_part_url(self) -> URL:
        return self.last_part()[1]
    
    def __getitem__(self, key) -> Optional[str]:
        return self._url_dict.get(str(key))
    
    def __setitem__(self, key: Part, value: URL):
        self._url_dict[str(key)] = value
    
    def extend_url(self, url: URL):
        self._url_dict[str(self.last_part_num_int() + 1)] = url
    
    def __iadd__(self, url: URL):
        self.extend_url(url)
        return self
    
    def extend_urls(self, data: Union[dict, list]):
        if isinstance(data, list):
            last_part = int(self.last_part_num())
            data = {str(last_part + k + 1): v for k, v in enumerate(data)}
        if isinstance(data, dict):
            self._url_dict.update({str(k): v for k, v in data.items()})
        else:
            raise TypeError


@dataclass
class BaseInstance:
    language: str

    def get_filename(self, extension: str=None):
        if extension is None:
            extension = ".json"
        return self.language + extension


@dataclass
class TumblrPerPageInstance(BaseInstance):
    first_url: URL
    next_titles: tuple[str]
    get_content: bool = True
    body_id: str = "content"

    def from_instance(self):
        return TumblrPerPage(self)


class TumblrPerPage:
    def __init__(self, inst: TumblrPerPageInstance) -> None:
        self.inst = inst
        self.data = PartJSON(os.path.join(PARTS_FOLDER, self.inst.get_filename()),
                             get_force_rewrite_urls())
        if self.data.new_file:
            self.data[1] = self.inst.first_url
    
    def _get_contents(self, soup):
        if not self.inst.get_content:
            return soup
        return soup.find(id=self.inst.body_id)
    
    def _find_next_page_a_tag(self, content_soup):
        for next_title in self.inst.next_titles:
            if (res := content_soup.find("a", text=next_title)) is not None:
                return res

    def _get_url_from_redirect(self, url):
        return str(session.get(url, follow_redirects=True).url)
    
    def _get_next_url(self, url) -> Optional[URL]:
        res_raw = session.get(url)
        html = self._get_contents(BeautifulSoup(res_raw.content, "lxml"))
        if (next_page_tag := self._find_next_page_a_tag(html)) is not None:
            if "https://at.tumblr.com" in next_page_tag.attrs["href"]:
                return self._get_url_from_redirect(next_page_tag.attrs["href"])
            return next_page_tag.attrs["href"]
    
    def find_new_urls(self) -> bool:
        found_new_flag = False
        while (next_url := self._get_next_url(self.data.last_part_url())) is not None:
            self.data.extend_url(next_url)
            found_new_flag = True
            sleep(randint(1, 3))
        return found_new_flag

        
    def update(self):
        found_new = self.find_new_urls()
        if found_new:
            self.data.save()


@dataclass
class TumblrFromMasterlistInstance(BaseInstance):
    url: str
    body_class: str
    regex_pattern: str

    def from_instance(self):
        return TumblrFromMasterlist(self)


class TumblrFromMasterlist:
    def __init__(self, inst: TumblrFromMasterlistInstance) -> None:
        self.inst = inst
        self.data = PartJSON(os.path.join(PARTS_FOLDER, self.inst.get_filename()),
                             get_force_rewrite_urls())
    
    def _get_post_body(self):
        res_raw = session.get(self.inst.url)
        html = BeautifulSoup(res_raw.content, "lxml")
        html_post = html.find(class_=self.inst.body_class)
        return html_post
    
    def _find_and_replace_redirections(self, urls):
        for part_num, url in urls.items():
            if "at.tumblr.com/" in url:
                urls[part_num] = str(session.get(url, follow_redirects=True).url)
        return urls
    
    def get_all_urls(self) -> dict[Part, URL]:
        html_post = self._get_post_body()
        urls = {re.match(self.inst.regex_pattern, x.text).groups()[0]: x.attrs["href"] for x in html_post.find_all("a") if re.match(self.inst.regex_pattern, x.text)}
        urls = self._find_and_replace_redirections(urls)
        return urls
    
    def update(self):
        urls = self.get_all_urls()
        if self.data.urls_dict != urls:
            self.data.extend_urls(urls)
            self.data.save()


language_inst = [
    TumblrPerPageInstance(language="en",
                          first_url="https://buggachat.tumblr.com/post/643600496684351488/part-1-this-uber-specific-au-popped-into-my-head",
                          next_titles=("Next", "Next ", "Next "),
                          get_content=True,
                          body_id="content"),
    TumblrFromMasterlistInstance(language="en-ids",
                                 url="https://iveofficiallygonemad.tumblr.com/post/679210281835134976/bakery-enemies-au-masterlist",
                                 regex_pattern="ep\s?(\d+)",
                                 body_class="post-content"),
    TumblrPerPageInstance(language="ru",
                          first_url="https://djratty.tumblr.com/post/693142158949203968/part-1-bakery-enemies-ru",
                          next_titles=("Следующая", ),
                          get_content=True,
                          body_id="content")
]


def main():
    for inst in language_inst:
        instance = inst.from_instance()
        instance.update()


if __name__ == "__main__":
    main()
