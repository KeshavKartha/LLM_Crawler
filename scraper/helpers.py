import random
import time
import re
from typing import List, Tuple, Dict
from urllib.parse import urlparse, parse_qs, urljoin

from bs4 import BeautifulSoup, Tag, NavigableString, Comment
import requests, json
from django.conf import settings
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import NoTranscriptFound, VideoUnavailable


# List of user-agent strings
user_agents = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
]


class Cleaner:
    @staticmethod
    def clean_text(text: str) -> str:
        cleaned_text = text.strip()
        cleaned_text = re.sub(r'src=".*?\.js">', '', text)
        cleaned_text = re.sub(r'You need to enable JavaScript to run this app.', '', cleaned_text)
        cleaned_text = re.sub(r'<.*?>', '', cleaned_text)
        cleaned_text = re.sub(r'http[s]?://\S+', '', cleaned_text)
        cleaned_text = re.sub(r'www\.\S+', '', cleaned_text)
        cleaned_text = re.sub(r'\S+@\S+', '', cleaned_text)
        cleaned_text = re.sub(r'<!--.*?-->', '', cleaned_text, flags=re.DOTALL)
        cleaned_text = re.sub(r'[^\x20-\x7E]', '', cleaned_text)
        cleaned_text = cleaned_text.replace('\n', ' ').replace('\t', ' ')
        cleaned_text = cleaned_text.strip()
        cleaned_text = ' '.join(cleaned_text.split())
        return cleaned_text
    
    @staticmethod
    def remove_unwanted_tags(soup):
        comments = soup.find_all(string=lambda text: isinstance(text, Comment))
        for comment in comments:
            comment.extract()
        for style in soup.find_all("style"):
            style.decompose()
        for ad in soup.find_all(class_='ad'):
            ad.decompose()
        for popup in soup.find_all(class_='popup'):
            popup.decompose()
        for script in soup.find_all('script'):
            script.decompose()  
        for tag in soup.find_all('svg'):
            tag.decompose()
        for n in soup.find_all('nav'):
            n.decompose()
        for form in soup.find_all('form'):
            form.decompose()
        for br in soup.find_all('br'):
            br.decompose()
        return soup


class YouTubeTranscriptFetcher:
    @staticmethod
    def is_youtube_url(url: str) -> bool:
        return url.startswith("https://www.youtube.com/watch")
    
    @staticmethod
    def construct_urls(urls: List[str]):
        prefix = "https://www.youtube.com/embed/"
        final_list = []
        for url in urls:
            if(url.startswith(prefix)):
                start_pos = url.find(prefix) + len(prefix)
                video_id = url[start_pos:start_pos + 11]
                final_url = "https://www.youtube.com/watch?v=" + video_id
                final_list.append(final_url)
        return final_list
                
    @staticmethod
    def get_youtube_video_id(url: str) -> str:
        parsed_url = urlparse(url)
        if 'youtube' in parsed_url.netloc:
            query = parse_qs(parsed_url.query)
            if 'v' in query:
                return query['v'][0]
        return None

    @staticmethod
    def fetch_youtube_transcript(video_id: str) -> str:
        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
            transcript = " ".join([entry['text'] for entry in transcript_list])
            return transcript
        except (NoTranscriptFound, VideoUnavailable):
            return None
        
class LLMText:
    def __init__(self, structured_text):
        self.structured_text = structured_text

    def process_text(self):
        """
        Takes all the structured text and converts it into one string.
        """
        def process_node(node):
            result = node['title'] + "\n" + "\n".join(node['content']) + "\n"
            for child in node.get('children', []):
                result += process_node(child)
            return result
        result = ""
        for item in self.structured_text:
            result += process_node(item) + "\n"
        return result.strip()
    
    def get_llm_text(self):
        """
        Main LLM text extraction logic.
        """

        processed_text = self.process_text(self.structured_text)
        prompt = """
I will provide text scraped from a website. The goal is to vectorize meaningful sentences or paragraphs about the company/product. The text is partially structured,
 and I need you to remove noise and rephrase sentences to enhance clarity. Ensure all sentences/paragraphs make perfect sense and only include those that add value in
 understanding the company/product. Quality is more important than quantity.

Here is the data:
%s

Output the cleaned and structured data as a list of dictionaries in the following format:

[
    {
        "level": 1,
        "title": "Main Title",
        "content": "There are many services available.",
        "children": [
            {
                "level": 2,
                "title": "Service-1",
                "content": "This is the first service.",
                "children": [
                    {
                        "level": 3,
                        "title": "Service-1 Part1",
                        "content": "Deals with screws and nuts.",
                        "children": []
                    }
                ]
            }
        ]
    },
    {
        "level": 1,
        "title": "",
        "content": "",
        "children": []
    }
]
""" % (processed_text)

        KIP_HOST = settings.KIP_HOST
        KIP_PORT = settings.KIP_PORT
        KIP_KEY = settings.KIP_KEY

        url = f"http://{KIP_HOST}:{KIP_PORT}/api/v1/get-interaction-output/"
        headers = {
            "Content-Type": "application/json",
            "api-key": KIP_KEY
        }
        model = "gpt-3.5-turbo"
        data = {
            "parameters": {
                "prompt": prompt,
                "model": model
            }
        }

        response = requests.post(url, json=data, headers=headers)
        response_dict = response.json()
        response_string = response_dict['results']
        llm_text = json.loads(response_string)
        return llm_text


class Scraper:
    def __init__(self, url: str, depth: int):
        self.url = url
        self.cur_depth = depth
        self.user_agent = random.choice(user_agents)
        self.options = Options()
        self.options.set_preference("general.useragent.override", self.user_agent)
        self.options.add_argument("--headless")
        self.service = Service('/snap/bin/geckodriver')
        self.driver = webdriver.Firefox(service=self.service, options=self.options)

    def fetch_and_parse(self):
        try:
            self.driver.get(self.url)
            self.driver.implicitly_wait(10)
            time.sleep(5)
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            return soup
        except Exception as e:
            print(f"Error fetching {self.url}: {e}")
            return None
        finally:
            self.driver.quit()

    @staticmethod
    def extract_images(soup):
        def is_valid_image_src(src: str) -> bool:
            return src.startswith("http")
        
        img_tags = soup.find_all('img')
        image_sources = []
        for img in img_tags:
            src = img.get('src')
            if src and is_valid_image_src(src):
                image_sources.append(src)
        return image_sources
    
    @staticmethod
    def extract_seo_meta(soup):
        meta_data = []
        meta_tags = soup.find_all('meta')
        for tag in meta_tags:
            name = tag.get('name', '').lower()
            content = tag.get('content', '')
            if name == 'description' or name == 'keywords':
                meta_data.append(content)
        return meta_data

    def convert_absolute_url(self, urls: List[str]):
        absolute_urls = []
        for url_int in urls:
            if not url_int.startswith("http"):
                absolute_url = urljoin(self.url, url_int)
            else:
                absolute_url = url_int
            absolute_urls.append({absolute_url: self.cur_depth + 1})
        return absolute_urls

    @staticmethod
    def extract_urls(soup):
        urls = [a['href'] for a in soup.find_all('a', href=True)]
        youtube_urls = [iframe['src'] for iframe in soup.find_all('iframe', src=True)]
        youtube_urls = YouTubeTranscriptFetcher.construct_urls(youtube_urls)
        print(youtube_urls)
        return urls+youtube_urls


    @staticmethod
    def extract_text(soup) -> str:
        """
        Main text extraction logic that returns the structured text.
        """
        def build_tree(soup):
            levels = {'h1': 1, 'h2': 2, 'h3': 3, 'h4': 4, 'h5': 5, 'h6': 6}
            stack = []
            root = []
            current = root

            def isheader(tag : str) -> bool:
                header_tags_regex = re.compile(r'h[1-6]')
                if(header_tags_regex.fullmatch(tag)):
                    return True
                return False

            
            tags_to_skip=[]
            def has_valuable_text(tag) -> bool:
                if(len(tags_to_skip)>0 and tag.name in tags_to_skip):
                    tags_to_skip.pop(0)
                    return False
                for par in tag.parents:
                    if(isheader(par.name)):
                        return False
                contains_direct_string=False
                for content in tag.contents:
                    if(isinstance(content, NavigableString)==False):
                        continue
                    contains_direct_string=True
                if(contains_direct_string==False):
                    return False
                return True
            
            encountered_heading = False

            for tag in soup.find_all(True):

                #for dealing with text before hitting first <hx> tag, usually <title> will be considered to be <h1>
                if(not encountered_heading and tag.string):
                    tag.name = "h1"
                    level = levels[tag.name]
                    while stack and stack[-1]['level'] >= level:
                        stack.pop()
                    new_section = {"level": level, "title": tag.get_text(), "content": [], "children": []}
                    if stack:
                        stack[-1]['children'].append(new_section)
                    else:
                        root.append(new_section)
                    stack.append(new_section)
                    current = new_section
                    encountered_heading=True

                #If we hit a <hx> tag
                elif(isheader(tag.name)):
                    encountered_heading=True
                    level = levels[tag.name]
                    while stack and stack[-1]['level'] >= level:
                        stack.pop()
                    text=tag.get_text()
                    text = Cleaner.clean_text(text)
                    new_section = {"level": level, "title": text, "content": [], "children": []}
                    if stack:
                        stack[-1]['children'].append(new_section)
                    else:
                        root.append(new_section)
                    stack.append(new_section)
                    current = new_section
                
                #Any other tag check if it has text
                elif (has_valuable_text(tag)):
                    if current:
                        for content in tag.contents:
                            if(isinstance(content, NavigableString)):
                                text = Cleaner.clean_text(content)
                                if(text and text not in current['content'] and len(text)>0):
                                    current['content'].append(text)
                            elif(isinstance(content, Tag)):
                                text = content.string
                                if(text and text not in current['content']):
                                    text = Cleaner.clean_text(text)
                                    if(len(text)>0):
                                        current['content'].append(text)
                                        tags_to_skip.append(content.name) 
            return root

        structured_text = build_tree(soup)
        return structured_text

    def scrape(self):
        soup = self.fetch_and_parse()
        if soup:
            soup = Cleaner.remove_unwanted_tags(soup)
            urls = self.extract_urls(soup)
            absolute_urls = self.convert_absolute_url(urls)
            structured_text = Scraper.extract_text(soup)
            meta_info = Scraper.extract_seo_meta(soup)
            images = Scraper.extract_images(soup)
            youtube_transcript = None
            if YouTubeTranscriptFetcher.is_youtube_url(self.url):
                video_id = YouTubeTranscriptFetcher.get_youtube_video_id(self.url)
                if video_id:
                    youtube_transcript = YouTubeTranscriptFetcher.fetch_youtube_transcript(video_id)

            return structured_text, meta_info, images, absolute_urls, youtube_transcript
        return None, None, None, None, None
    


class MainScraper:
    def __init__(self, max_depth, max_limit, use_llm):
        self.url_queue = []
        self.scraped_url_set = set()
        self.scraped_url_list = []

        self.max_depth = max_depth
        self.max_limit = max_limit
        self.use_llm = use_llm

    def main_scraper(self):
        data_related = []
        cnt = 0
        while(len(self.url_queue) > 0 and cnt < self.max_limit):
            url_dict = self.url_queue.pop(0)
            next_url = next(iter(url_dict.keys()))
            cur_depth = url_dict[next(iter(url_dict))]
            if cur_depth > self.max_depth:
                break

            scraper = Scraper(next_url, cur_depth)
            structured_text, meta_info, images, child_urls, youtube_transcript = scraper.scrape()

            '''
            Implement logic to decide whether to use LLM
            '''

            if(self.use_llm):
                llm = LLMText(structured_text)
                structured_text = llm.get_llm_text()
            
            
            if structured_text is not None:
                
                self.scraped_url_set.add(next_url)
                self.scraped_url_list.append(next_url)

                final_child_urls = child_urls

                for child_url_dict in child_urls:
                    child_url = next(iter(child_url_dict.keys()))
                    if child_url not in self.scraped_url_set:
                        self.url_queue.append(child_url_dict)
                    else:
                        final_child_urls.remove(child_url_dict)
                
                final_child_urls = [key for dict_elem in final_child_urls for key in dict_elem.keys()]

                data_int = {
                    "page_url": next_url,
                    "text": structured_text,
                    "meta_info": meta_info,
                    "youtube_transcript": youtube_transcript,
                    "img_src_list": images,
                    "child_urls": final_child_urls,
                }
                data_related.append(data_int)
                cnt += 1

        print(self.scraped_url_list)
        return data_related


    def main(self, urls_to_scrape: List[str]):
        final_data = []
        for url in urls_to_scrape:
            self.url_queue.clear()
            self.url_queue.append({url: 0})
            related_data = self.main_scraper()
            final_data_related = {"data": related_data, "base_url": url}
            final_data.append(final_data_related)
        return final_data
