#!/usr/bin/python3

import asyncio
import os
import re
import sys
from collections import namedtuple
from concurrent.futures.thread import ThreadPoolExecutor
from contextlib import contextmanager

import aiofiles
import aiohttp
import click
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.expected_conditions import visibility_of_element_located
from selenium.webdriver.support.wait import WebDriverWait
from tqdm import tqdm

SITE = "https://sdarot.tv/watch"

EPISODE_REGEX = re.compile(r'<li data-episode="(\d+)"')
NUMBER_OF_PARALLEL_MISSIONS = 4

Mission = namedtuple('Mission', 'season episode url output')


@contextmanager
def quit_web(driver):
    try:
        yield driver
    finally:
        driver.quit()


def load_episode(url):
    with quit_web(webdriver.Firefox()) as driver:
        driver.get(url)

        WebDriverWait(driver, 40).until(
            visibility_of_element_located((By.ID, "afterLoad")))
        proceed = driver.find_element_by_id("proceed")
        proceed.click()

        WebDriverWait(driver, 5).until(
            visibility_of_element_located((By.ID, "videojs_html5_api")))
        video = driver.find_element_by_id("videojs_html5_api")
        cookies = {cookie.get('name'): cookie.get('value') for cookie in driver.get_cookies()}
        return video.get_attribute("src"), cookies


async def download_video(url, output, **kwargs):
    async with aiohttp.ClientSession(**kwargs) as session:
        async with session.get(url) as response:
            if not response.status == 200:
                return False

            async with aiofiles.open(output, mode='wb') as f:
                async for data, _ in response.content.iter_chunks():
                    await f.write(data)

            return True


async def get_episodes(url, **kwargs):
    async with aiohttp.ClientSession(**kwargs) as session:
        async with session.get(url) as response:
            if not response.status == 200:
                return []

            text = await response.text()
            return [int(i) for i in EPISODE_REGEX.findall(text)]


def run_mission(mission):
    async def run_mission_async():
        loop = asyncio.get_running_loop()
        try:
            video_url, cookies = await loop.run_in_executor(None, load_episode, mission.url)
        except Exception:
            print(f'Failed to get episode url of season {mission.season} / episode {mission.episode}')
            return

        if not await download_video(video_url, mission.output, cookies=cookies):
            print(f'Failed to download video of season {mission.season} / episode {mission.episode}')

    asyncio.new_event_loop().run_until_complete(run_mission_async())


async def download(show_id, seasons):
    missions = []
    for season in seasons:
        season_url = f'{SITE}/{show_id}/season/{season}'
        episodes = await get_episodes(season_url)
        season_directory = f'Season_{season}'

        if not os.path.exists(season_directory):
            os.mkdir(season_directory)

        for episode in episodes:
            episode_url = f'{season_url}/episode/{episode}'
            episode_output = os.path.join(season_directory, f'Episode_{episode}.mp4')
            missions.append(Mission(season, episode, episode_url, episode_output))

    with ThreadPoolExecutor(max_workers=NUMBER_OF_PARALLEL_MISSIONS) as pool, \
            tqdm(total=len(missions), unit='ep') as progress_bar:
        for _ in pool.map(run_mission, missions):
            progress_bar.update(1)


@click.command()
@click.argument('show_id', type=click.INT)
@click.argument('first_season', type=click.INT)
@click.argument('last_season', type=click.INT)
def main(show_id, first_season, last_season):
    """
    Download agent from sdarot.tv

    The program receives the `show_id` and seasons range.
    The `show_id` can be extracted from parameters, like so:

    https://sdarot.tv/watch/{show_id}*

    For example, the following URLs are equivalent:
    https://sdarot.tv/watch/82-Games of thrones

    https://sdarot.tv/watch/82-ABC

    https://sdarot.tv/watch/82-123
    """
    if sys.version_info[0] == 3 and sys.version_info[1] >= 8 and \
            sys.platform.startswith('win'):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(download(show_id, range(first_season, last_season + 1)))


if __name__ == '__main__':
    main()
