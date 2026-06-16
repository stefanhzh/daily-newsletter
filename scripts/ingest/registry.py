#!/usr/bin/env python3
"""Adapter registry."""

from __future__ import annotations

from .a16z_blog import A16ZBlogAdapter
from .ap import APAdapter
from .anthropic_news import AnthropicNewsAdapter
from .axios import AxiosAdapter
from .bbc import BBCAdapter
from .bilibili_popular import BilibiliPopularAdapter
from .bloomberg import BloombergAdapter
from .cailian import CailianAdapter
from .caixin import CaixinAdapter
from .cnbc import CNBCAdapter
from .discord_blog import DiscordBlogAdapter
from .ft import FTAdapter
from .gelonghui import GelonghuiAdapter
from .github_trending import GitHubTrendingAdapter
from .github_issues_trends import GitHubIssuesTrendsAdapter
from .google_trends import GoogleTrendsAdapter
from .huggingface import HuggingFaceAdapter
from .kr36 import Kr36Adapter
from .latent_space import LatentSpaceAdapter
from .lennys_newsletter import LennysNewsletterAdapter
from .lesswrong import LessWrongAdapter
from .lobsters import LobstersAdapter
from .nikkei_asia import NikkeiAsiaAdapter
from .openai_blog import OpenAIBlogAdapter
from .politico import PoliticoAdapter
from .reuters import ReutersAdapter
from .scmp import SCMPAdapter
from .semafor import SemaforAdapter
from .semianalysis import SemianalysisAdapter
from .stratechery import StratecheryAdapter
from .techcrunch import TechCrunchAdapter
from .telegram_blog import TelegramBlogAdapter
from .ths_hotrank import THSHotrankAdapter
from .tiktok_profile_signals import TikTokProfileSignalsAdapter
from .tradingview_news import TradingViewNewsAdapter
from .unusual_whales import UnusualWhalesAdapter
from .wallstreetcn import WallstreetCNAdapter
from .wind_news import WindNewsAdapter
from .wsj import WSJAdapter
from .x_account_posts import XAccountPostsAdapter
from .xiaohongshu_search import XiaohongshuSearchAdapter
from .xiaoyuzhou_feeds import XiaoyuzhouFeedsAdapter
from .y_combinator import YCombinatorAdapter
from .youtube_channel_feeds import YouTubeChannelFeedsAdapter
from .zerohedge import ZeroHedgeAdapter
from .base import BaseAdapter
from .yicai import YicaiAdapter
from .reddit_hot import RedditHotAdapter
from .wechat_search import WeChatSearchAdapter
from .zhihu_hot import ZhihuHotAdapter


ADAPTERS: dict[str, type[BaseAdapter]] = {
    "a16z-blog": A16ZBlogAdapter,
    "ap": APAdapter,
    "anthropic-news": AnthropicNewsAdapter,
    "axios": AxiosAdapter,
    "bbc": BBCAdapter,
    "bilibili-popular": BilibiliPopularAdapter,
    "bloomberg": BloombergAdapter,
    "cailian": CailianAdapter,
    "caixin": CaixinAdapter,
    "cnbc": CNBCAdapter,
    "discord-blog": DiscordBlogAdapter,
    "ft": FTAdapter,
    "gelonghui": GelonghuiAdapter,
    "github-trending": GitHubTrendingAdapter,
    "github-issues-trends": GitHubIssuesTrendsAdapter,
    "google-trends": GoogleTrendsAdapter,
    "huggingface": HuggingFaceAdapter,
    "36kr": Kr36Adapter,
    "latent-space": LatentSpaceAdapter,
    "lennys-newsletter": LennysNewsletterAdapter,
    "lesswrong": LessWrongAdapter,
    "lobsters": LobstersAdapter,
    "nikkei-asia": NikkeiAsiaAdapter,
    "openai-blog": OpenAIBlogAdapter,
    "politico": PoliticoAdapter,
    "reuters": ReutersAdapter,
    "scmp": SCMPAdapter,
    "semafor": SemaforAdapter,
    "semianalysis": SemianalysisAdapter,
    "stratechery": StratecheryAdapter,
    "techcrunch": TechCrunchAdapter,
    "telegram-blog": TelegramBlogAdapter,
    "ths-hotrank": THSHotrankAdapter,
    "tiktok-profile-signals": TikTokProfileSignalsAdapter,
    "tradingview-news": TradingViewNewsAdapter,
    "unusual-whales": UnusualWhalesAdapter,
    "wallstreetcn": WallstreetCNAdapter,
    "wind-news": WindNewsAdapter,
    "wsj": WSJAdapter,
    "wall-street-journal": WSJAdapter,
    "x-account-posts": XAccountPostsAdapter,
    "xiaohongshu-search": XiaohongshuSearchAdapter,
    "xiaoyuzhou-feeds": XiaoyuzhouFeedsAdapter,
    "y-combinator": YCombinatorAdapter,
    "youtube-channel-feeds": YouTubeChannelFeedsAdapter,
    "yicai": YicaiAdapter,
    "zerohedge": ZeroHedgeAdapter,
    "reddit-hot": RedditHotAdapter,
    "wechat-search": WeChatSearchAdapter,
    "zhihu-hot": ZhihuHotAdapter,
}


def build_adapters(source_ids: list[str], *, lookback_hours: int) -> list[BaseAdapter]:
    adapters: list[BaseAdapter] = []
    for source_id in source_ids:
        adapter_cls = ADAPTERS.get(source_id)
        if adapter_cls is None:
            continue
        adapters.append(adapter_cls(lookback_hours=lookback_hours))
    return adapters
