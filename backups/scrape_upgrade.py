import os
import re
import json
import random
import asyncio
import logging
import aiohttp
import requests
import html2text
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin, quote, urlparse
from typing import List, Dict, Any
from flask_socketio import emit

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class VideoSearchCrawler:
    def __init__(self, topic: str):
        self.main_topic = topic
        self.search_results = []
        self.seen_links = set()
        
        # Initialize HTML converter
        self.html_converter = html2text.HTML2Text()
        self.html_converter.ignore_links = False
        
        # Initialize headers
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0'
        ]
        
        self.headers = {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }

    async def collect_results(self):
        """Collect video results from multiple sources"""
        try:
            logger.info(f"Starting search for: {self.main_topic}")
            all_results = []
            
            # Search YouTube (up to 150 results)
            youtube_results = await self._search_youtube(self.main_topic)
            if youtube_results:
                all_results.extend(youtube_results)
                logger.info(f"Found {len(youtube_results)} results from YouTube")
            
            # Search Vimeo (up to 75 results)
            vimeo_results = await self._search_vimeo(self.main_topic)
            if vimeo_results:
                all_results.extend(vimeo_results)
                logger.info(f"Found {len(vimeo_results)} results from Vimeo")
            
            # Search Dailymotion (up to 75 results)
            dailymotion_results = await self._search_dailymotion(self.main_topic)
            if dailymotion_results:
                all_results.extend(dailymotion_results)
                logger.info(f"Found {len(dailymotion_results)} results from Dailymotion")
            
            return all_results
            
        except Exception as e:
            logger.error(f"Error in collect_results: {str(e)}")
            raise

    async def _search_youtube(self, query: str) -> List[Dict]:
        """Search for videos on YouTube."""
        results = []
        try:
            # Try different sorting options to get more results
            sort_params = ['', '&sp=CAI%253D', '&sp=CAM%253D']  # Default, Date, Rating
            
            for sort_param in sort_params:
                if len(results) >= 150:
                    break
                    
                # YouTube search URL with sort parameter
                search_url = f"https://www.youtube.com/results?search_query={quote(query)}{sort_param}"
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(search_url, headers=self.headers) as response:
                        if response.status == 200:
                            html = await response.text()
                            
                            # Extract video IDs using regex
                            video_ids = re.findall(r'"videoId":"([^"]+)"', html)
                            video_titles = re.findall(r'"title":{"runs":\[{"text":"([^"]+)"}]}', html)
                            video_durations = re.findall(r'"simpleText":"([0-9:]+)"', html)
                            video_views = re.findall(r'"viewCountText":{"simpleText":"([^"]+)"}', html)
                            
                            # Process unique video IDs
                            seen_ids = set()
                            for i, video_id in enumerate(video_ids):
                                if video_id in seen_ids or len(results) >= 150:
                                    continue
                                    
                                seen_ids.add(video_id)
                                title = video_titles[i] if i < len(video_titles) else "Untitled Video"
                                duration = video_durations[i] if i < len(video_durations) else "Unknown"
                                views = video_views[i] if i < len(video_views) else "Unknown views"
                                
                                video_url = f"https://www.youtube.com/watch?v={video_id}"
                                thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                                
                                results.append({
                                    'title': title,
                                    'url': video_url,
                                    'thumbnail': thumbnail_url,
                                    'duration': duration,
                                    'views': views,
                                    'platform': 'YouTube',
                                    'description': f"Watch this video on YouTube: {title}",
                                    'source': 'YouTube'
                                })
                                
        except Exception as e:
            logger.error(f"Error searching YouTube: {str(e)}")
        
        return results[:150]

    async def _search_vimeo(self, query: str) -> List[Dict]:
        """Search for videos on Vimeo."""
        results = []
        try:
            # Search multiple pages
            for page in range(1, 4):  # Search 3 pages
                if len(results) >= 75:
                    break
                    
                # Vimeo search URL with page parameter
                search_url = f"https://vimeo.com/search/page:{page}?q={quote(query)}"
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(search_url, headers=self.headers) as response:
                        if response.status == 200:
                            html = await response.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            
                            # Find video elements
                            video_elements = soup.find_all(['a', 'div'], {'data-fatal-attraction': 'container'})
                            
                            for element in video_elements:
                                try:
                                    if len(results) >= 75:
                                        break
                                        
                                    # Extract video ID from URL
                                    href = element.get('href', '')
                                    if not href:
                                        continue
                                        
                                    video_id = href.split('/')[-1]
                                    if not video_id.isdigit():
                                        continue
                                        
                                    title = element.get('title', '')
                                    if not title:
                                        title_elem = element.find(['h5', 'h3', 'h4'])
                                        if title_elem:
                                            title = title_elem.text.strip()
                                    if not title:
                                        title = 'Untitled Vimeo Video'
                                        
                                    thumbnail = None
                                    img = element.find('img')
                                    if img:
                                        thumbnail = img.get('src') or img.get('data-src')
                                        
                                    results.append({
                                        'title': title,
                                        'url': f"https://vimeo.com/{video_id}",
                                        'thumbnail': thumbnail,
                                        'duration': 'Unknown',
                                        'platform': 'Vimeo',
                                        'description': f"Watch this video on Vimeo: {title}",
                                        'source': 'Vimeo'
                                    })
                                    
                                except Exception as e:
                                    logger.error(f"Error processing Vimeo result: {str(e)}")
                                    continue
                                    
                # Small delay between pages
                await asyncio.sleep(1)
                                
        except Exception as e:
            logger.error(f"Error searching Vimeo: {str(e)}")
        
        return results[:75]

    async def _search_dailymotion(self, query: str) -> List[Dict]:
        """Search for videos on Dailymotion."""
        results = []
        try:
            # Search multiple pages
            for page in range(1, 4):  # Search 3 pages
                if len(results) >= 75:
                    break
                    
                # Dailymotion search URL with page parameter
                search_url = f"https://www.dailymotion.com/search/{quote(query)}/page-{page}"
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(search_url, headers=self.headers) as response:
                        if response.status == 200:
                            html = await response.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            
                            # Find video elements
                            video_elements = soup.find_all(['div', 'a'], {'class': ['media-block', 'video-item']})
                            
                            for element in video_elements:
                                try:
                                    if len(results) >= 75:
                                        break
                                        
                                    link = element.find('a') if element.name != 'a' else element
                                    if not link:
                                        continue
                                        
                                    href = link.get('href', '')
                                    if not href or '/video/' not in href:
                                        continue
                                        
                                    video_id = href.split('/')[-1]
                                    title = link.get('title', '')
                                    if not title:
                                        title_elem = element.find(['h3', 'h4'])
                                        if title_elem:
                                            title = title_elem.text.strip()
                                    if not title:
                                        title = 'Untitled Dailymotion Video'
                                        
                                    thumbnail = None
                                    img = element.find('img')
                                    if img:
                                        thumbnail = img.get('data-src') or img.get('src')
                                        
                                    results.append({
                                        'title': title,
                                        'url': f"https://www.dailymotion.com/video/{video_id}",
                                        'thumbnail': thumbnail,
                                        'duration': 'Unknown',
                                        'platform': 'Dailymotion',
                                        'description': f"Watch this video on Dailymotion: {title}",
                                        'source': 'Dailymotion'
                                    })
                                    
                                except Exception as e:
                                    logger.error(f"Error processing Dailymotion result: {str(e)}")
                                    continue
                                    
                # Small delay between pages
                await asyncio.sleep(1)
                                
        except Exception as e:
            logger.error(f"Error searching Dailymotion: {str(e)}")
        
        return results[:75]

def setup_routes(app, socketio):
    """Set up Flask routes and Socket.IO event handlers"""
    
    # Track search status
    search_in_progress = False
    
    @socketio.on('connect')
    def handle_connect():
        logger.info("Client connected")
        emit('connected', {'status': 'Connected to server'})

    @socketio.on('disconnect')
    def handle_disconnect():
        logger.info("Client disconnected")

    @socketio.on('search_query')
    def handle_search_query(data):
        """Handle incoming search queries"""
        nonlocal search_in_progress
        
        try:
            logger.info(f"Received search query: {json.dumps(data, indent=2)}")
            
            if search_in_progress:
                logger.warning("Search already in progress")
                emit('search_error', {'error': 'A search is already in progress'})
                return
            
            query = data.get('query', '').strip()
            if not query:
                logger.warning("Empty query received")
                emit('search_error', {'error': 'Please enter a search query'})
                return

            search_in_progress = True
            logger.info(f"Starting search for: {query}")
            
            # Notify client
            emit('search_started', {
                'query': query,
                'message': f'Starting search for: {query}'
            })
            
            # Create crawler and run search
            try:
                crawler = VideoSearchCrawler(query)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                all_results = loop.run_until_complete(crawler.collect_results())
                loop.close()
                
                # Process and emit results
                processed_results = []
                for result in all_results:
                    processed_result = {
                        'url': result.get('url', ''),
                        'title': result.get('title', 'Untitled Video'),
                        'description': result.get('description', ''),
                        'thumbnail': result.get('thumbnail', ''),
                        'source': result.get('source', 'Unknown'),
                        'duration': result.get('duration', 'Unknown'),
                        'type': 'video'
                    }
                    processed_results.append(processed_result)
                    # Emit each result as it's processed
                    emit('new_result', {'result': processed_result})
                
                logger.info(f"Search completed with {len(processed_results)} results")
                emit('search_completed', {
                    'results': processed_results,
                    'total': len(processed_results),
                    'query': query
                })
                
            except Exception as e:
                logger.error(f"Search error: {str(e)}")
                emit('search_error', {'error': str(e)})
                
            finally:
                search_in_progress = False
            
        except Exception as e:
            logger.error(f"Error in handle_search_query: {str(e)}")
            emit('search_error', {'error': str(e)})
            search_in_progress = False

if __name__ == '__main__':
    from flask import Flask
    from flask_socketio import SocketIO
    
    app = Flask(__name__)
    socketio = SocketIO(app)
    setup_routes(app, socketio)
    socketio.run(app, debug=True, port=5001)