import json
import time
import random
import logging
from typing import Optional, List, Dict
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from fake_useragent import UserAgent, FakeUserAgentError
import requests

# 配置常量
BASE_URL = 'https://www.4kvm.net/seasons/wczt9'
FOLDER_NAME = 'video'
GRAPHQL_PAYLOAD = {
    # 保持原有的GraphQL查询结构
}

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('video_downloader.log'),
        logging.StreamHandler()
    ]
)


class VideoDownloader:
    def __init__(self):
        self.session = self._create_session()
        self.ua_refresh_interval = 3600  # UA池刷新间隔（秒）
        self.last_ua_refresh = 0
        self.user_agents: List[str] = []
        self._refresh_user_agents()

    def _create_session(self):
        """创建带重试机制的会话"""
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('https://', adapter)
        return session

    def _refresh_user_agents(self):
        """刷新用户代理池"""
        try:
            ua = UserAgent(
                browsers=['chrome', 'firefox', 'safari', 'edge'],
                use_external_data=True,
                fallback=None,
                cache_update=True
            )
            new_agents = [ua.random for _ in range(100)]
            combined = list(set(new_agents + self._get_fallback_agents()))
            random.shuffle(combined)

            self.user_agents = combined[:100]
            self.last_ua_refresh = time.time()
            logging.info("UA池刷新成功，当前数量：%d", len(self.user_agents))

        except FakeUserAgentError as e:
            logging.warning("UA更新失败: %s", str(e))
            if not self.user_agents:
                self.user_agents = self._get_fallback_agents()

    def _get_fallback_agents(self) -> List[str]:
        """获取备用UA列表"""
        return [
            # 保持原有的备用UA列表
        ]

    def _get_random_headers(self) -> Dict[str, str]:
        """生成动态请求头"""
        if time.time() - self.last_ua_refresh > self.ua_refresh_interval:
            self._refresh_user_agents()

        return {
            'User-Agent': random.choice(self.user_agents),
            'Accept': random.choice([
                'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            ]),
            'Accept-Language': random.choice([
                'en-US,en;q=0.9',
                'zh-CN,zh;q=0.9,en;q=0.8'
            ]),
            'Referer': random.choice([
                'https://www.google.com/',
                'https://www.bing.com/',
                BASE_URL  # 使用常量
            ]),
            'DNT': str(random.randint(0, 1))
        }

    def validate_response(self, data: dict) -> bool:
        """验证API响应结构"""
        try:
            episode = data['data']['visionTubeEpisode']
            return all(key in episode for key in ['photo', 'tags']) \
                and len(episode['tags']) >= 3 \
                and 'photoUrl' in episode['photo']
        except KeyError:
            return False

    def fetch_video_data(self, page: int) -> Optional[dict]:
        """获取指定页码的视频数据"""
        payload = GRAPHQL_PAYLOAD.copy()
        payload["variables"]["episodeNumber"] = page

        try:
            headers = self._get_random_headers()
            response = self.session.post(
                url=BASE_URL,
                json=payload,
                headers=headers,
                timeout=(5, 15)
            )

            if response.status_code == 403:
                logging.warning("检测到403错误，刷新UA池")
                self._refresh_user_agents()
                return None

            response.raise_for_status()
            json_data = response.json()

            if not self.validate_response(json_data):
                logging.error("第%d页数据格式异常", page)
                return None

            return json_data

        except requests.RequestException as e:
            logging.error("请求失败[%d]: %s", page, str(e))
        except json.JSONDecodeError as e:
            logging.error("JSON解析失败[%d]: %s", page, str(e))
        except Exception as e:
            logging.error("未知错误[%d]: %s", page, str(e), exc_info=True)

        return None

    def download_page(self, page: int):
        """处理单个页面下载"""
        logging.info("正在下载第%d页...", page)

        try:
            json_data = self.fetch_video_data(page)
            if not json_data:
                return

            episode = json_data['data']['visionTubeEpisode']
            video_url = episode['photo']['photoUrl']
            title = episode['tags'][2]['name']

            video_res = self.session.get(video_url, timeout=30)
            video_res.raise_for_status()

            self._save_video(
                content=video_res.content,
                filename=f"{self._clean_filename(title)}_{page}"
            )

        except KeyError as e:
            logging.error("键错误[%d]: %s", page, str(e))
        except requests.RequestException as e:
            logging.error("下载失败[%d]: %s", page, str(e))
        except Exception as e:
            logging.error("处理失败[%d]: %s", page, str(e), exc_info=True)

    @staticmethod
    def _clean_filename(filename: str) -> str:
        """清理文件名"""
        return re.sub(r'[\\/*?:"<>|]', '', filename)[:100].strip()

    def _save_video(self, content: bytes, filename: str):
        """保存视频文件"""
        try:
            filepath = os.path.join(FOLDER_NAME, f"{filename}.mp4")
            with open(filepath, 'wb') as f:
                f.write(content)
            logging.info("文件保存成功: %s", filename)
        except OSError as e:
            logging.error("保存失败: %s", str(e))
