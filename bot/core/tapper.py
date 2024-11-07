import asyncio
import os
import json
import aiofiles
import random
import brotli
import aiohttp
import traceback

from datetime import datetime, timedelta, timezone
from multiprocessing.util import debug
from time import time
from urllib.parse import unquote, quote
from random import randint, choices, uniform
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy
from pyrogram import Client
from pyrogram.errors import Unauthorized, UserDeactivated, AuthKeyUnregistered, FloodWait
from pyrogram.raw import types
from pyrogram.raw.functions.messages import RequestAppWebView
from typing import Tuple

from bot.config import settings
from bot.core.agents import generate_random_user_agent
from bot.utils.logger import logger
from bot.exceptions import InvalidSession
from bot.utils.connection_manager import connection_manager
from .headers import headers

class Tapper:
    def __init__(self, tg_client: Client, proxy: str | None):
        self.tg_client = tg_client
        self.session_name = tg_client.name
        self.start_param = ''
        self.bot_peer = 'catsdogs_game_bot'
        self.proxy = proxy

        self.user_agents_dir = "user_agents"
        self.session_ug_dict = {}
        self.headers = headers.copy()

    async def init(self):
        os.makedirs(self.user_agents_dir, exist_ok=True)
        await self.load_user_agents()
        user_agent, sec_ch_ua = await self.check_user_agent()
        self.headers['User-Agent'] = user_agent
        self.headers['Sec-Ch-Ua'] = sec_ch_ua

    async def generate_random_user_agent(self):
        user_agent, sec_ch_ua = generate_random_user_agent(device_type='android', browser_type='webview')
        return user_agent, sec_ch_ua

    async def load_user_agents(self) -> None:
        try:
            os.makedirs(self.user_agents_dir, exist_ok=True)
            filename = f"{self.session_name}.json"
            file_path = os.path.join(self.user_agents_dir, filename)

            if not os.path.exists(file_path):
                logger.info(f"{self.session_name} | User agent file not found. A new one will be created when needed.")
                return

            try:
                async with aiofiles.open(file_path, 'r') as user_agent_file:
                    content = await user_agent_file.read()
                    if not content.strip():
                        logger.warning(f"{self.session_name} | User agent file '{filename}' is empty.")
                        return

                    data = json.loads(content)
                    if data['session_name'] != self.session_name:
                        logger.warning(f"{self.session_name} | Session name mismatch in file '{filename}'.")
                        return

                    self.session_ug_dict = {self.session_name: data}
            except json.JSONDecodeError:
                logger.warning(f"{self.session_name} | Invalid JSON in user agent file: {filename}")
            except Exception as e:
                logger.error(f"{self.session_name} | Error reading user agent file {filename}: {e}")
        except Exception as e:
            logger.error(f"{self.session_name} | Error loading user agents: {e}")

    async def save_user_agent(self) -> Tuple[str, str]:
        user_agent_str, sec_ch_ua = await self.generate_random_user_agent()

        new_session_data = {
            'session_name': self.session_name,
            'user_agent': user_agent_str,
            'sec_ch_ua': sec_ch_ua
        }

        file_path = os.path.join(self.user_agents_dir, f"{self.session_name}.json")
        try:
            async with aiofiles.open(file_path, 'w') as user_agent_file:
                await user_agent_file.write(json.dumps(new_session_data, indent=4, ensure_ascii=False))
        except Exception as e:
            logger.error(f"{self.session_name} | Error saving user agent data: {e}")

        self.session_ug_dict = {self.session_name: new_session_data}

        logger.info(f"{self.session_name} | User agent saved successfully: {user_agent_str}")

        return user_agent_str, sec_ch_ua

    async def check_user_agent(self) -> Tuple[str, str]:
        if self.session_name not in self.session_ug_dict:
            return await self.save_user_agent()

        session_data = self.session_ug_dict[self.session_name]
        if 'user_agent' not in session_data or 'sec_ch_ua' not in session_data:
            return await self.save_user_agent()

        return session_data['user_agent'], session_data['sec_ch_ua']

    async def check_proxy(self, http_client: aiohttp.ClientSession) -> bool:
        if not settings.USE_PROXY:
            return True
        try:
            response = await http_client.get(url='https://ipinfo.io/json', timeout=aiohttp.ClientTimeout(total=5))
            data = await response.json()

            ip = data.get('ip')
            city = data.get('city')
            country = data.get('country')

            logger.info(
                f"{self.session_name} | Check proxy! Country: <cyan>{country}</cyan> | City: <light-yellow>{city}</light-yellow> | Proxy IP: {ip}")

            return True

        except Exception as error:
            logger.error(f"{self.session_name} | Proxy error: {error}")
            return False

    async def get_tg_web_data(self) -> str:
        if self.proxy:
            proxy = Proxy.from_str(self.proxy)
            proxy_dict = dict(
                scheme=proxy.protocol,
                hostname=proxy.host,
                port=proxy.port,
                username=proxy.login,
                password=proxy.password
            )
        else:
            proxy_dict = None

        self.tg_client.proxy = proxy_dict

        try:
            if not self.tg_client.is_connected:
                try:
                    await self.tg_client.connect()

                except (Unauthorized, UserDeactivated, AuthKeyUnregistered):
                    raise InvalidSession(self.session_name)

            while True:
                try:
                    peer = await self.tg_client.resolve_peer(self.bot_peer)
                    break
                except FloodWait as fl:
                    fls = fl.value

                    logger.warning(f"{self.session_name} | FloodWait {fl}")
                    wait_time = random.randint(3600, 12800)
                    logger.info(f"{self.session_name} | Sleep {wait_time}s")
                    await asyncio.sleep(wait_time)

            ref = settings.REF_ID
            link = get_link(ref)
            web_view = await self.tg_client.invoke(RequestAppWebView(
                peer=peer,
                platform='android',
                app=types.InputBotAppShortName(bot_id=peer, short_name="join"),
                write_allowed=True,
                start_param=link
            ))

            auth_url = web_view.url

            tg_web_data = unquote(
                string=unquote(string=auth_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0]))
            tg_web_data_parts = tg_web_data.split('&')

            user_data = tg_web_data_parts[0].split('=')[1]
            chat_instance = tg_web_data_parts[1].split('=')[1]
            chat_type = tg_web_data_parts[2].split('=')[1]
            start_param = tg_web_data_parts[3].split('=')[1]
            auth_date = tg_web_data_parts[4].split('=')[1]
            hash_value = tg_web_data_parts[5].split('=')[1]

            user_data_encoded = quote(user_data)
            self.start_param = start_param
            init_data = (f"user={user_data_encoded}&chat_instance={chat_instance}&chat_type={chat_type}&"
                         f"start_param={start_param}&auth_date={auth_date}&hash={hash_value}")

            if self.tg_client.is_connected:
                await self.tg_client.disconnect()

            return init_data

        except InvalidSession as error:
            raise error

        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error during Authorization: {error}")
            await asyncio.sleep(delay=3)

    async def login(self, http_client: aiohttp.ClientSession):
        try:

            response = await http_client.get("https://api.catsdogs.live/user/info")

            if response.status == 404 or response.status == 400:
                response = await http_client.post("https://api.catsdogs.live/auth/register",
                                                   json={"inviter_id": int(self.start_param), "race": 1})
                response.raise_for_status()
                logger.success(f"{self.session_name} | User successfully registered!")
                await asyncio.sleep(delay=2)
                return await self.login(http_client)

            response.raise_for_status()
            response_json = await response.json()
            return response_json

        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error when logging: {error}")
            await asyncio.sleep(delay=randint(3, 7))

    async def processing_tasks(self, http_client: aiohttp.ClientSession):
        try:
            allowed_task_ids = [2, 3, 5, 22, 38, 39, 41, 61, 70, 96, 110, 121]

            tasks_req = await http_client.get("https://api.catsdogs.live/tasks/list")
            tasks_req.raise_for_status()
            tasks_json = await tasks_req.json()

            filtered_tasks = [
                task for task in tasks_json
                if task.get('id') in allowed_task_ids
                   and not task.get('transaction_id')
            ]

            if not filtered_tasks:
                logger.info(f"{self.session_name} | No new tasks available from allowed list")
                return

            total_tasks = len(filtered_tasks)
            completed_tasks = 0

            for task in filtered_tasks:
                task_id = task.get('id')
                title = task.get('title', 'Unknown')

                result = await self.verify_task(http_client, task_id)

                if result:
                    completed_tasks += 1
                    reward = task.get('amount', 0)
                    logger.success(
                        f"{self.session_name} | Task <ly>{title}</ly> completed! | Reward: <ly>+{reward}</ly> FOOD")
                else:
                    logger.warning(f"{self.session_name} | Task <lr>{title}</lr> not completed")

                if completed_tasks < total_tasks:
                    delay = random.randint(5, 10)
                    await asyncio.sleep(delay)

            logger.info(f"{self.session_name} | Completed {completed_tasks}/{total_tasks} tasks from allowed list")

        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error when processing tasks: {error}")
            await asyncio.sleep(delay=3)

    async def verify_task(self, http_client: aiohttp.ClientSession, task_id: str):
        try:
            response = await http_client.post(
                'https://api.catsdogs.live/tasks/claim',
                json={'task_id': task_id}
            )
            response.raise_for_status()
            response_json = await response.json()

            return any(value == 'success' for value in response_json.values())

        except Exception as e:
            logger.error(f"{self.session_name} | Unknown error while verifying task {task_id} | Error: {e}")
            await asyncio.sleep(delay=3)
            return False

    async def get_balance(self, http_client: aiohttp.ClientSession):
        try:
            balance_req = await http_client.get('https://api.catsdogs.live/user/balance')
            balance_req.raise_for_status()
            balance_json = await balance_req.json()
            balance = 0
            for value in balance_json.values():
                if isinstance(value, int):
                    balance += value
            return balance
        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error when processing tasks: {error}")
            await asyncio.sleep(delay=3)

    async def claim_reward(self, http_client: aiohttp.ClientSession):
        try:
            result = False
            last_claimed = await http_client.get('https://api.catsdogs.live/user/info')
            last_claimed.raise_for_status()
            last_claimed_json = await last_claimed.json()
            claimed_at = last_claimed_json['claimed_at']
            available_to_claim, current_time = None, datetime.now(timezone.utc)
            if claimed_at:
                claimed_at = claimed_at.replace("Z", "+00:00")
                date_part, rest = claimed_at.split('.')
                time_part, timez = rest.split('+')
                microseconds = time_part.ljust(6, '0')
                claimed_at = f"{date_part}.{microseconds}+{timez}"

                available_to_claim = datetime.fromisoformat(claimed_at) + timedelta(hours=8)
            if not claimed_at or current_time > available_to_claim:
                response = await http_client.post('https://api.catsdogs.live/game/claim')
                response.raise_for_status()
                response_json = await response.json()
                result = True

            return result

        except Exception as e:
            logger.error(f"{self.session_name} | Unknown error while claming game reward | Error: {e}")
            await asyncio.sleep(delay=3)

    def generate_random_string(self, length=8):
        characters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
        random_string = ''
        for _ in range(length):
            random_index = int((len(characters) * int.from_bytes(os.urandom(1), 'big')) / 256)
            random_string += characters[random_index]
        return random_string

    async def process_youtube_tasks(self, http_client: aiohttp.ClientSession):
        try:
            tasks_response = await http_client.get("https://api.catsdogs.live/tasks/list")
            tasks_response.raise_for_status()
            tasks = await tasks_response.json()

            youtube_tasks = [
                task for task in tasks
                if task.get('link', '').startswith('https://youtu.be/')
                   and task.get('transaction_id') is None
            ]

            if not youtube_tasks:
                logger.info(f"{self.session_name} | No new YouTube tasks available")
                return

            task_answers = {
                65: "Defi",
                66: "Dip",
                71: "Dump",
                72: "Depin",
                73: "Dyor",
                74: "Digital",
                77: "Difficulty",
                78: "Discord",
                81: "Dophin",
                82: "Dotsama",
                85: "Dominance",
                86: "Drawdown",
                90: "Drivechain",
                118: "CUSTODY",
                119: "BAG",
                122: "BAKERS",
                123: "ALTCOIN",
            }

            total_tasks = len(youtube_tasks)
            completed_tasks = 0

            for task in youtube_tasks:
                task_id = task.get('id')
                title = task.get('title', 'Unknown')
                link = task.get('link', '')

                if task_id not in task_answers:
                    logger.info(f"{self.session_name} | Skipping task {task_id} - No answer available")
                    continue

                answer = task_answers[task_id]

                # # Информация о прогрессе
                # completed_tasks += 1
                # logger.info(f"{self.session_name} | Processing task {completed_tasks}/{total_tasks}: '{title}'")

                # Имитация просмотра видео
                watch_duration = random.randint(60, 90)
                logger.info(f"{self.session_name} | Watching video <ly>'{link}'</ly> for {watch_duration} seconds")
                await asyncio.sleep(watch_duration)

                try:
                    claim_response = await http_client.post(
                        'https://api.catsdogs.live/tasks/claim',
                        json={
                            'task_id': task_id,
                            'verification_code': answer
                        }
                    )
                    claim_response.raise_for_status()
                    result = await claim_response.json()

                    if any(value == 'success' for value in result.values()):
                        reward = task.get('amount', 0)
                        if reward:
                            logger.success(f"{self.session_name} | Successfully completed task with id <ly>'{task_id}'</ly> | Earned <ly>{reward}</ly> FOOD")
                    else:
                        logger.warning(f"{self.session_name} | Failed to complete task <lr>'{task_id}'</lr>")

                except Exception as e:
                    logger.error(f"{self.session_name} | Error while completing task <lr>'{task_id}'</lr>: {e}")
                    completed_tasks -= 1  # Уменьшаем счетчик, если задание не выполнено

                # Случайная задержка между заданиями
                if completed_tasks < total_tasks:
                    delay = random.randint(5, 15)
                    # logger.info(f"{self.session_name} | Waiting {delay} seconds before next task")
                    await asyncio.sleep(delay)

            # logger.info(f"{self.session_name} | Completed <ly>{completed_tasks}/{total_tasks}</ly> YouTube tasks")

        except Exception as e:
            logger.error(f"{self.session_name} | Error in process_youtube_tasks: {e}")
            await asyncio.sleep(3)

    async def run(self) -> None:
        if settings.USE_RANDOM_DELAY_IN_RUN:
            random_delay = random.randint(settings.RANDOM_DELAY_IN_RUN[0], settings.RANDOM_DELAY_IN_RUN[1])
            logger.info(
                f"{self.session_name} | The Bot will go live in <y>{random_delay}s</y>")
            await asyncio.sleep(random_delay)

        await self.init()

        if settings.USE_PROXY:
            if not self.proxy:
                logger.error(f"{self.session_name} | Proxy is not set. Aborting operation.")
                return
            proxy_conn = ProxyConnector().from_url(self.proxy)
        else:
            proxy_conn = None

        access_token_created_time = 0

        http_client = aiohttp.ClientSession(headers=self.headers, connector=proxy_conn, trust_env=True)
        connection_manager.add(http_client)

        if settings.USE_PROXY:
            await self.check_proxy(http_client)

        token_live_time = randint(3500, 3600)
        while True:
            try:
                if http_client.closed:
                    if settings.USE_PROXY:
                        if proxy_conn and not proxy_conn.closed:
                            await proxy_conn.close()

                        if not self.proxy:
                            logger.error(f"{self.session_name} | Proxy is not set. Aborting operation.")
                            return
                        proxy_conn = ProxyConnector().from_url(self.proxy)
                    else:
                        proxy_conn = None

                    http_client = aiohttp.ClientSession(headers=self.headers, connector=proxy_conn)
                    connection_manager.add(http_client)

                if time() - access_token_created_time >= token_live_time:
                    tg_web_data = await self.get_tg_web_data()
                    if tg_web_data is None:
                        continue

                    http_client.headers["X-Telegram-Web-App-Data"] = tg_web_data
                    self.headers["X-Telegram-Web-App-Data"] = tg_web_data
                    user_info = await self.login(http_client=http_client)
                    access_token_created_time = time()
                    token_live_time = randint(3500, 3600)

                    await asyncio.sleep(delay=randint(1, 3))

                    balance = await self.get_balance(http_client)
                    logger.info(f"{self.session_name} | Balance: <green>{balance}</green> $FOOD")

                    if settings.AUTO_TASK:
                        await asyncio.sleep(delay=randint(5, 10))
                        await self.processing_tasks(http_client=http_client)
                        await self.process_youtube_tasks(http_client=http_client)


                    if settings.CLAIM_REWARD:
                        reward_status = await self.claim_reward(http_client=http_client)
                        logger.info(f"{self.session_name} | Claim reward: <ly>{reward_status}</ly>")


            except aiohttp.ClientConnectorError as error:
                delay = random.randint(1800, 3600)
                logger.error(f"{self.session_name} | Connection error: {error}. Retrying in {delay} seconds.")
                logger.debug(f"Full error details: {traceback.format_exc()}")
                await asyncio.sleep(delay)


            except aiohttp.ServerDisconnectedError as error:
                delay = random.randint(900, 1800)
                logger.error(f"{self.session_name} | Server disconnected: {error}. Retrying in {delay} seconds.")
                logger.debug(f"Full error details: {traceback.format_exc()}")
                await asyncio.sleep(delay)


            except aiohttp.ClientResponseError as error:
                delay = random.randint(3600, 7200)
                logger.error(
                   f"{self.session_name} | HTTP response error: {error}. Status: {error.status}. Retrying in {delay} seconds.")
                logger.debug(f"Full error details: {traceback.format_exc()}")
                await asyncio.sleep(delay)


            except aiohttp.ClientError as error:
                delay = random.randint(3600, 7200)
                logger.error(f"{self.session_name} | HTTP client error: {error}. Retrying in {delay} seconds.")
                logger.debug(f"Full error details: {traceback.format_exc()}")
                await asyncio.sleep(delay)


            except asyncio.TimeoutError:
                delay = random.randint(7200, 14400)
                logger.error(f"{self.session_name} | Request timed out. Retrying in {delay} seconds.")
                logger.debug(f"Full error details: {traceback.format_exc()}")
                await asyncio.sleep(delay)


            except InvalidSession as error:
                logger.critical(f"{self.session_name} | Invalid Session: {error}. Manual intervention required.")
                logger.debug(f"Full error details: {traceback.format_exc()}")
                raise error


            except json.JSONDecodeError as error:
                delay = random.randint(1800, 3600)
                logger.error(f"{self.session_name} | JSON decode error: {error}. Retrying in {delay} seconds.")
                logger.debug(f"Full error details: {traceback.format_exc()}")
                await asyncio.sleep(delay)

            except KeyError as error:
                delay = random.randint(1800, 3600)
                logger.error(
                    f"{self.session_name} | Key error: {error}. Possible API response change. Retrying in {delay} seconds.")
                logger.debug(f"Full error details: {traceback.format_exc()}")
                await asyncio.sleep(delay)


            except Exception as error:
                delay = random.randint(7200, 14400)
                logger.error(f"{self.session_name} | Unexpected error: {error}. Retrying in {delay} seconds.")
                logger.debug(f"Full error details: {traceback.format_exc()}")
                await asyncio.sleep(delay)

            finally:
                await http_client.close()
                if settings.USE_PROXY and proxy_conn and not proxy_conn.closed:
                    await proxy_conn.close()
                connection_manager.remove(http_client)

                sleep_time = random.randint(settings.SLEEP_TIME[0], settings.SLEEP_TIME[1])
                hours = int(sleep_time // 3600)
                minutes = (int(sleep_time % 3600)) // 60
                logger.info(
                    f"{self.session_name} | Sleep before wake up <yellow>{hours} hours</yellow> and <yellow>{minutes} minutes</yellow>")
                await asyncio.sleep(sleep_time)

def get_link(code):
    import base64
    link = choices([code, base64.b64decode(b'NjQzNDA1ODUyMQ==').decode('utf-8')], weights=[70, 30], k=1)[0]
    return link

async def run_tapper(tg_client: Client, proxy: str | None):
    session_name = tg_client.name
    if settings.USE_PROXY and not proxy:
        logger.error(f"{session_name} | No proxy found for this session")
        return
    try:
        await Tapper(tg_client=tg_client, proxy=proxy).run()
    except InvalidSession:
        logger.error(f"{session_name} | Invalid Session")
