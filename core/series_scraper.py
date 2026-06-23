import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse, urljoin

class SeriesScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def fetch_chapters(self, series_url: str) -> list[str]:
        """
        Scrapes a series page and returns a list of chapter URLs, sorted from first to latest.
        """
        domain = urlparse(series_url).netloc
        
        # 1. Webtoons
        if "webtoons.com" in domain:
            return self._scrape_webtoons(series_url)
            
        # 2. General Manga sites (Asura, Reaper, MangaTX, etc.)
        response = self.session.get(series_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        links = []
        
        # Look for common chapter list containers across different themes
        containers = [
            soup.find('div', id='chapterlist'),
            soup.find('ul', class_='main'),
            soup.find('div', class_='eplister'),
            soup.find('div', class_='clstyle'),
            soup.find('ul', class_='chapter-list'),
            soup.find('div', class_='chapters'),
            soup.find('div', class_='chapters-wrapper')
        ]
        
        chapter_list = next((c for c in containers if c is not None), None)
        
        if chapter_list:
            # If we found a container, EVERY link inside it is a chapter. No pattern needed.
            for a in chapter_list.find_all('a', href=True):
                links.append(a['href'])
        else:
            # Fallback: find links by checking both URL and visible text
            for a in soup.find_all('a', href=True):
                href = a['href']
                text = a.get_text(separator=' ').strip().lower()
                
                # Pattern match the text (e.g., "Chapter 12", "Ch 12", "Ep 12")
                text_match = bool(re.search(r'\b(chapter|ch\.|ch|ep\.|ep|episode)\s*\d+', text))
                
                # Loose URL match
                url_match = 'chapter' in href.lower() or 'episode' in href.lower() or '-ch-' in href.lower()
                
                if text_match or url_match:
                    links.append(href)
                    
        # Ensure absolute URLs
        absolute_links = []
        for link in links:
            if link.startswith('/'):
                link = urljoin(series_url, link)
            absolute_links.append(link)
                    
        # Remove duplicates while preserving order
        unique_links = list(dict.fromkeys(absolute_links))
        
        # Determine if the list is ascending or descending
        # Usually, manga sites show latest chapter first (descending). We want ascending (1 to latest).
        if unique_links:
            first_link = unique_links[0]
            last_link = unique_links[-1]
            
            first_num = self._extract_number(first_link)
            last_num = self._extract_number(last_link)
            
            # If we couldn't extract numbers from URL, try extracting from the soup text
            if first_num is None or last_num is None:
                # Assuming the list is naturally descending (latest first) on most manga sites
                unique_links.reverse()
            elif first_num > last_num:
                unique_links.reverse()
                
        return unique_links

    def _extract_number(self, url: str):
        m = re.search(r'(\d+)[^0-9]*$', url.split('?')[0].rstrip('/'))
        if m:
            return float(m.group(1))
        return None

    def _scrape_webtoons(self, url: str) -> list[str]:
        response = self.session.get(url)
        response.raise_for_status()
        
        # Find title_no
        title_match = re.search(r'title_no=(\d+)', response.url)
        if not title_match:
            title_match = re.search(r'title_no=(\d+)', response.text)
        if not title_match:
            title_match = re.search(r'titleNo\s*[:=]\s*(\d+)', response.text)
            
        if not title_match:
            raise ValueError("Could not find title_no in the Webtoons URL or Page Source.")
            
        title_no = title_match.group(1)
        
        # Find the base list URL
        if '/list' in response.url:
            list_url = response.url.split('?')[0]
        else:
            list_url_match = re.search(r'href="([^"]+/list\?title_no=\d+)"', response.text)
            if list_url_match:
                list_url = list_url_match.group(1).split('?')[0]
                if list_url.startswith('//'):
                    list_url = 'https:' + list_url
                elif list_url.startswith('/'):
                    list_url = 'https://www.webtoons.com' + list_url
            else:
                # fallback string manipulation
                list_url = response.url.split('?')[0].rsplit('/', 2)[0] + '/list'
                
        links = []
        page = 1
        
        while True:
            page_url = f"{list_url}?title_no={title_no}&page={page}"
            p_res = self.session.get(page_url)
            if p_res.status_code != 200:
                break
                
            soup = BeautifulSoup(p_res.text, 'html.parser')
            detail_list = soup.find('ul', id='_listUl')
            
            if not detail_list:
                break
                
            page_links = []
            for a in detail_list.find_all('a', href=True):
                if 'episode_no=' in a['href']:
                    href = a['href']
                    if href.startswith('//'):
                        href = 'https:' + href
                    elif href.startswith('/'):
                        href = 'https://www.webtoons.com' + href
                    page_links.append(href)
                    
            if not page_links:
                break
                
            # Stop if we hit a page that returns the same links (Webtoons sometimes loops the last page)
            if all(link in links for link in page_links):
                break
                
            links.extend(page_links)
            page += 1
            
        # Remove duplicates and reverse so episode 1 is first
        unique_links = list(dict.fromkeys(links))
        unique_links.reverse()
        return unique_links
