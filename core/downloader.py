import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Downloader:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def is_supported_url(self, url: str) -> bool:
        return True

    def extract_image_urls(self, url: str) -> list[str]:
        # Handle local PDF files natively
        if url.lower().endswith('.pdf'):
            if not os.path.exists(url):
                raise ValueError(f"PDF file not found: {url}")
            try:
                import fitz # PyMuPDF
            except ImportError:
                raise ImportError("PyMuPDF is required for PDF support. Please install it with 'pip install PyMuPDF'")
                
            doc = fitz.open(url)
            image_urls = []
            for i in range(len(doc)):
                # Return a special pseudo-url that tells download_image how to render this page
                image_urls.append(f"pdf://{url}?page={i}")
            doc.close()
            return image_urls

        # Handle local CBZ / ZIP files natively
        if url.lower().endswith('.cbz') or url.lower().endswith('.zip'):
            if not os.path.exists(url):
                raise ValueError(f"CBZ/ZIP file not found: {url}")
            
            import zipfile
            image_urls = []
            with zipfile.ZipFile(url, 'r') as z:
                # Filter only image files inside the archive, sorted by name
                valid_exts = ('.jpg', '.jpeg', '.png', '.webp')
                images_in_zip = [f for f in z.namelist() if f.lower().endswith(valid_exts)]
                images_in_zip.sort()
                
                for img_name in images_in_zip:
                    # Return a special pseudo-url
                    import urllib.parse
                    encoded_name = urllib.parse.quote(img_name)
                    image_urls.append(f"cbz://{url}?file={encoded_name}")
                    
            if not image_urls:
                raise ValueError(f"No images found inside {url}")
            return image_urls

        # Always set referer
        self.session.headers.update({"Referer": url})
        
        response = self.session.get(url)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        image_urls = []
        domain = urlparse(url).netloc
        
        # 1. Webtoons
        if "webtoons.com" in domain:
            viewer = soup.find('div', id='_imageList')
            if viewer:
                for img in viewer.find_all('img'):
                    img_url = img.get('data-url') or img.get('src')
                    if img_url:
                        image_urls.append(img_url)
        
        # 2. MangaStream themes (AsuraScans, FlameComics, LuminousScans, etc)
        elif soup.find('div', id='readerarea'):
            viewer = soup.find('div', id='readerarea')
            for img in viewer.find_all('img'):
                img_url = img.get('data-src') or img.get('src')
                if img_url and img_url.startswith('http') and not 'discord' in img_url.lower():
                    image_urls.append(img_url.strip())
                    
        # 3. Madara themes (ReaperScans, MangaTX, etc)
        elif soup.find('div', class_='reading-content'):
            viewer = soup.find('div', class_='reading-content')
            for img in viewer.find_all('img'):
                img_url = img.get('data-src') or img.get('src')
                if img_url and img_url.startswith('http'):
                    image_urls.append(img_url.strip())
                    
        # 4. Generic Fallback
        else:
            for img in soup.find_all('img'):
                img_url = img.get('data-src') or img.get('data-lazy-src') or img.get('src')
                if img_url and img_url.startswith('http'):
                    if not any(x in img_url.lower() for x in ['logo', 'icon', 'avatar', 'banner']):
                        image_urls.append(img_url.strip())
        
        if not image_urls:
            raise ValueError(f"Could not find any comic images on {url}.")
            
        return image_urls

    def download_image(self, url: str, output_path: str):
        # Handle local PDF page extraction
        if url.startswith('pdf://'):
            import fitz
            file_path = url[6:].split('?page=')[0]
            page_num = int(url.split('?page=')[1])
            
            doc = fitz.open(file_path)
            page = doc.load_page(page_num)
            
            # Render page to a high quality image (2x zoom)
            zoom_matrix = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=zoom_matrix, alpha=False)
            pix.save(output_path)
            doc.close()
            return
            
        # Handle local CBZ/ZIP extraction
        if url.startswith('cbz://'):
            import zipfile
            import urllib.parse
            import shutil
            
            file_path = url[6:].split('?file=')[0]
            img_name = urllib.parse.unquote(url.split('?file=')[1])
            
            with zipfile.ZipFile(file_path, 'r') as z:
                with z.open(img_name) as source, open(output_path, 'wb') as target:
                    shutil.copyfileobj(source, target)
            return

        response = self.session.get(url, stream=True)
        response.raise_for_status()
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
