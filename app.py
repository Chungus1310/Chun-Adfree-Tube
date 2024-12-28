import streamlit as st
from googleapiclient.discovery import build
from googleapiclient.discovery_cache.base import Cache
import tempfile
import ffmpeg

# Disable the discovery cache warning
class MemoryCache(Cache):
    _CACHE = {}

    def get(self, url):
        return MemoryCache._CACHE.get(url)

    def set(self, url, content):
        MemoryCache._CACHE[url] = content

from datetime import datetime
import os
import atexit
import glob
import threading
import time
import os
import glob
import atexit
import logging as logger
from contextlib import contextmanager
import yt_dlp
import json

# Enhanced logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('youtube_app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Custom CSS to improve design
CUSTOM_CSS = """
<style>
    .thumbnail-container img {
        max-width: 240px !important;
        height: auto !important;
    }
    .channel-thumbnail-container img {
        max-width: 240px !important;
        height: auto !important;
        border-radius: 50% !important;
    }
    .video-title {
        font-size: 14px !important;
        font-weight: 600 !important;
        margin: 8px 0 !important;
    }
    .video-info {
        font-size: 12px !important;
        color: #666 !important;
        margin: 4px 0 !important;
    }
    .stButton button {
        width: 100% !important;
        margin: 4px 0 !important;
    }
</style>
"""

class TempFileManager:
    """Enhanced temporary file manager with timed cleanup and individual file tracking"""
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp(prefix='streamlit_youtube_')
        # Dictionary to store file paths and their creation timestamps
        self.active_files = {}
        # Set cleanup interval (15 minutes in seconds)
        self.cleanup_interval = 15 * 60
        # Start the cleanup thread
        self.cleanup_thread = threading.Thread(target=self._periodic_cleanup, daemon=True)
        self.cleanup_thread.start()
        atexit.register(self.cleanup_all)
        logger.info(f"Initialized TempFileManager with directory: {self.temp_dir}")
    
    def create_temp_file(self, video_id):
        temp_path = os.path.join(self.temp_dir, f"{video_id}.mp4")
        # Store the file path with current timestamp
        self.active_files[temp_path] = time.time()
        logger.info(f"Created temporary file: {temp_path}")
        return temp_path
    
    def cleanup_file(self, file_path):
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                # Remove from tracking dictionary
                self.active_files.pop(file_path, None)
                logger.info(f"Cleaned up file: {file_path}")
        except Exception as e:
            logger.error(f"Error cleaning up file {file_path}: {str(e)}")
    
    def _periodic_cleanup(self):
        """Periodically check and clean files older than 15 minutes"""
        while True:
            current_time = time.time()
            # Create a list of files to clean (avoid modifying dict during iteration)
            files_to_clean = [
                file_path
                for file_path, timestamp in self.active_files.items()
                if current_time - timestamp > self.cleanup_interval
            ]
            
            # Clean up old files
            for file_path in files_to_clean:
                self.cleanup_file(file_path)
            
            # Sleep for a minute before next check
            time.sleep(60)
    
    def cleanup_all(self):
        """Clean up all files and stop the cleanup thread"""
        # Clean up all tracked files
        for file_path in list(self.active_files.keys()):
            self.cleanup_file(file_path)
        
        try:
            # Clean up any remaining files that might have been missed
            remaining_files = glob.glob(os.path.join(self.temp_dir, "*"))
            for file_path in remaining_files:
                os.remove(file_path)
                logger.info(f"Cleaned up remaining file: {file_path}")
            
            if os.path.exists(self.temp_dir):
                os.rmdir(self.temp_dir)
                logger.info(f"Cleaned up temporary directory: {self.temp_dir}")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

def download_and_stream_video(video_id, temp_file_manager):
    """Enhanced video download function with better quality control and error handling"""
    try:
        ydl_opts = {
            'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]',
            'outtmpl': os.path.join(temp_file_manager.temp_dir, f'{video_id}.%(ext)s'),
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': True,
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            with st.spinner("Preparing video stream..."):
                info_dict = ydl.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=True)
                video_path = ydl.prepare_filename(info_dict)
                
                # Verify the downloaded file
                if not os.path.exists(video_path):
                    raise Exception("Downloaded video file not found")
                
                file_size = os.path.getsize(video_path)
                if file_size == 0:
                    raise Exception("Downloaded video file is empty")
                
                logger.info(f"Successfully downloaded video {video_id} to {video_path}")
                return video_path
            
    except Exception as e:
        logger.error(f"Error downloading video {video_id}: {str(e)}")
        st.error(f"Error downloading video: {str(e)}")
        return None

def format_duration(duration_str):
    """Convert YouTube duration format to readable format"""
    import re
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str)
    if not match:
        return "Unknown"
    
    hours, minutes, seconds = match.groups()
    time_parts = []
    
    if hours:
        time_parts.append(f"{int(hours)}h")
    if minutes:
        time_parts.append(f"{int(minutes)}m")
    if seconds:
        time_parts.append(f"{int(seconds)}s")
    
    return " ".join(time_parts)

def format_number(number_str):
    """Format large numbers with K/M/B suffixes"""
    try:
        number = int(number_str)
        if number >= 1000000000:
            return f"{number/1000000000:.1f}B"
        elif number >= 1000000:
            return f"{number/1000000:.1f}M"
        elif number >= 1000:
            return f"{number/1000:.1f}K"
        return str(number)
    except:
        return "N/A"

# Enhanced search functions with data caching
def search_videos_with_details(youtube, query, max_results=4):
    """Search for videos and fetch their details in a single function to minimize API calls"""
    cache_key = f"search_videos_{query}_{max_results}"
    
    # Check if results are in session state cache
    if cache_key in st.session_state:
        return st.session_state[cache_key]
    
    try:
        # Get video search results with all needed parts in one request
        request = youtube.search().list(
            q=query,
            part='snippet',
            type='video',
            maxResults=max_results
        )
        search_response = request.execute()
        
        # Extract video IDs for bulk details fetch
        video_ids = [item['id']['videoId'] for item in search_response['items']]
        
        # Fetch details for all videos in one batch request
        if video_ids:
            details_request = youtube.videos().list(
                part='snippet,statistics,contentDetails',
                id=','.join(video_ids)
            )
            details_response = details_request.execute()
            details_map = {item['id']: item for item in details_response['items']}
        
        # Combine search results with details
        videos = []
        for item in search_response['items']:
            video_id = item['id']['videoId']
            details = details_map.get(video_id, {})
            
            video_data = {
                'title': item['snippet']['title'],
                'video_id': video_id,
                'thumbnail': item['snippet']['thumbnails']['default']['url'],
                'channel': item['snippet']['channelTitle'],
                'channel_id': item['snippet']['channelId'],
                'published_at': datetime.strptime(
                    item['snippet']['publishedAt'], 
                    '%Y-%m-%dT%H:%M:%SZ'
                ).strftime('%Y-%m-%d'),
                'description': item['snippet']['description'],
                'duration': details.get('contentDetails', {}).get('duration'),
                'views': details.get('statistics', {}).get('viewCount'),
                'likes': details.get('statistics', {}).get('likeCount')
            }
            videos.append(video_data)
        
        # Cache the results in session state
        st.session_state[cache_key] = videos
        return videos
        
    except Exception as e:
        logger.error(f"Error in search_videos_with_details: {str(e)}")
        return []

def get_channel_videos_with_details(youtube, channel_id, max_results=2):
    """Fetch channel videos with details in a single function to minimize API calls"""
    cache_key = f"channel_videos_{channel_id}_{max_results}"
    
    # Check cache first
    if cache_key in st.session_state:
        return st.session_state[cache_key]
    
    try:
        # Get channel videos with all needed parts in one request
        request = youtube.search().list(
            part='snippet',
            channelId=channel_id,
            type='video',
            maxResults=max_results,
            order='date'
        )
        search_response = request.execute()
        
        # Extract video IDs for bulk details fetch
        video_ids = [item['id']['videoId'] for item in search_response['items']]
        
        # Fetch details for all videos in one batch request
        if video_ids:
            details_request = youtube.videos().list(
                part='snippet,statistics,contentDetails',
                id=','.join(video_ids)
            )
            details_response = details_request.execute()
            details_map = {item['id']: item for item in details_response['items']}
        
        # Combine search results with details
        videos = []
        for item in search_response['items']:
            video_id = item['id']['videoId']
            details = details_map.get(video_id, {})
            
            video_data = {
                'title': item['snippet']['title'],
                'video_id': video_id,
                'thumbnail': item['snippet']['thumbnails']['default']['url'],
                'channel': item['snippet']['channelTitle'],
                'channel_id': item['snippet']['channelId'],
                'published_at': datetime.strptime(
                    item['snippet']['publishedAt'], 
                    '%Y-%m-%dT%H:%M:%SZ'
                ).strftime('%Y-%m-%d'),
                'description': item['snippet']['description'],
                'duration': details.get('contentDetails', {}).get('duration'),
                'views': details.get('statistics', {}).get('viewCount'),
                'likes': details.get('statistics', {}).get('likeCount')
            }
            videos.append(video_data)
        
        # Cache the results
        st.session_state[cache_key] = videos
        return videos
        
    except Exception as e:
        logger.error(f"Error in get_channel_videos_with_details: {str(e)}")
        return []

def display_video_card(video, idx, video_type, temp_file_manager):
    """Display a video card using pre-fetched details"""
    with st.container():
        st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
        
        # Thumbnail with controlled size
        st.markdown(f'<div class="thumbnail-container">', unsafe_allow_html=True)
        st.image(video['thumbnail'], use_container_width=False)
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Video information with proper styling
        st.markdown(f'<div class="video-title">{video["title"]}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="video-info">Channel: {video["channel"]}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="video-info">Published: {video["published_at"]}</div>', unsafe_allow_html=True)
        
        # Use pre-fetched details
        duration = format_duration(video.get('duration', 'PT0S'))
        views = format_number(video.get('views', '0'))
        likes = format_number(video.get('likes', '0'))
        
        st.markdown(f'<div class="video-info">Duration: {duration}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="video-info">Views: {views} • Likes: {likes}</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button(f"▶ Stream", key=f"stream_{video_type}_{idx}_{video['video_id']}"):
                handle_video_stream(video, temp_file_manager)
        
        with col2:
            if st.button(f"⬇ Download", key=f"download_{video_type}_{idx}_{video['video_id']}"):
                handle_video_download(video, temp_file_manager)

def handle_video_stream(video, temp_file_manager):
    """Handle video streaming with proper error handling and video playback"""
    try:
        if st.session_state.current_video:
            st.session_state.previous_video = st.session_state.current_video
        
        video_path = download_and_stream_video(video['video_id'], temp_file_manager)
        if video_path:
            st.session_state.current_video = video_path
            
            # Create video player with proper controls
            video_file = open(video_path, 'rb')
            video_bytes = video_file.read()
            video_file.close()
            
            st.video(video_bytes)
            
            # Add video information below player
            st.markdown(f"""
            **Now Playing:** {video['title']}  
            **Channel:** {video['channel']}  
            **Published:** {video['published_at']}
            """)
            
    except Exception as e:
        logger.error(f"Error streaming video: {str(e)}")
        st.error("Failed to stream video. Please try again.")

def handle_video_download(video, temp_file_manager):
    """Handle video download with proper error handling"""
    try:
        video_path = download_and_stream_video(video['video_id'], temp_file_manager)
        if video_path:
            with open(video_path, "rb") as file:
                file_stats = os.stat(video_path)
                if file_stats.st_size == 0:
                    st.error("Downloaded file is empty. Please try again.")
                    return
                
                st.download_button(
                    label="📥 Download Now",
                    data=file,
                    file_name=f"{video['title']}.mp4",
                    mime="video/mp4",
                    key=f"download_button_{video['video_id']}"
                )
    except Exception as e:
        logger.error(f"Error downloading video: {str(e)}")
        st.error("Failed to download video. Please try again.")

def setup_youtube_api(api_key):
    """Initialize YouTube API client."""
    try:
        youtube = build('youtube', 'v3', developerKey=api_key, cache=MemoryCache())
        return youtube
    except Exception as e:
        st.error(f"Error initializing YouTube API: {str(e)}")
        return None

def search_channels(youtube, query, max_results=2):
    """Search for channels using YouTube API."""
    try:
        request = youtube.search().list(
            q=query,
            part='snippet',
            type='channel',
            maxResults=max_results
        )
        response = request.execute()
        
        channels = []
        for item in response['items']:
            channel_data = {
                'title': item['snippet']['title'],
                'channel_id': item['snippet']['channelId'],
                'thumbnail': item['snippet']['thumbnails']['default']['url'],
                'description': item['snippet']['description']
            }
            channels.append(channel_data)
        
        return channels
    except Exception as e:
        st.error(f"Error searching channels: {str(e)}")
        return []

def main():
    st.set_page_config(
        page_title="ChunTube",
        page_icon="🎥",
        layout="wide",
        initial_sidebar_state="collapsed"
    )
    
    # Initialize session state
    if 'temp_file_manager' not in st.session_state:
        st.session_state.temp_file_manager = TempFileManager()
    if 'current_video' not in st.session_state:
        st.session_state.current_video = None
    if 'previous_video' not in st.session_state:
        st.session_state.previous_video = None
    if 'selected_channel' not in st.session_state:
        st.session_state.selected_channel = None
    
    # Clean up previous video if exists
    if st.session_state.previous_video:
        st.session_state.temp_file_manager.cleanup_file(st.session_state.previous_video)
        st.session_state.previous_video = None
    
    # API Key input with password mask
    api_key = st.text_input(
        "Enter your YouTube Data API Key",
        type="password",
        help="Get your API key from Google Cloud Console"
    )
    
    if not api_key:
        st.warning("Please enter your YouTube Data API key to continue.")
        st.info("""
        To get an API key:
        1. Go to Google Cloud Console
        2. Create a new project or select existing one
        3. Enable YouTube Data API v3
        4. Create credentials (API key)
        """)
        return
    
    # Initialize YouTube API client
    youtube = setup_youtube_api(api_key)
    if not youtube:
        return
    
    # Search interface
    search_query = st.text_input("Search for videos and channels", "")
    
    if search_query:
        # Fetch channels first
        with st.spinner("Searching channels..."):
            channels = search_channels(youtube, search_query)
        
        # Display channels in a grid layout
        if channels:
            st.subheader("Channels")
            cols = st.columns(2)
            for idx, channel in enumerate(channels):
                with cols[idx % 2]:
                    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
                    st.markdown(f'<div class="channel-thumbnail-container">', unsafe_allow_html=True)
                    st.image(
                        channel['thumbnail'],
                        use_container_width=False,
                        caption=channel['title']
                    )
                    st.markdown('</div>', unsafe_allow_html=True)
                    st.write(f"Description: {channel['description']}")
                    
                    # Add button to fetch latest videos from the channel
                    if st.button(f"View Latest Videos", key=f"channel_{channel['channel_id']}"):
                        st.session_state.selected_channel = channel['channel_id']
                        st.rerun()

        # Search videos with combined details
        with st.spinner("Searching videos..."):
            videos = search_videos_with_details(youtube, search_query)
        
        # Display videos
        if videos:
            st.subheader("Videos")
            cols = st.columns(2)
            for idx, video in enumerate(videos):
                with cols[idx % 2]:
                    display_video_card(video, idx, "search", st.session_state.temp_file_manager)
        
        # If a channel is selected, fetch its videos with combined details
        if st.session_state.selected_channel:
            with st.spinner("Fetching channel videos..."):
                channel_videos = get_channel_videos_with_details(youtube, st.session_state.selected_channel)
            
            if channel_videos:
                st.subheader("Latest Videos from Channel")
                cols = st.columns(2)
                for idx, video in enumerate(channel_videos):
                    with cols[idx % 2]:
                        display_video_card(video, idx, "channel", st.session_state.temp_file_manager)

if __name__ == "__main__":
    main()
