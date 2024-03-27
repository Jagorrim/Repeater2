import time

import asyncio
import addition
import config
from addition import BotException, PostData, parse_hyperlinks
import aiohttp

from pprint import pprint


class VKSide:
    # Получение url VK видео
    @staticmethod
    async def get_videos_url(videos: list, session: aiohttp.ClientSession) -> list:
        params = {
            'access_token': config.access_token, 'url': 'https://api.vk.com/method/video.get',
            'count': len(videos),
            'client_id': config.api_acc_id,
            'videos': ','.join(videos),
            'v': config.vk_api_version
        }
        async with session.get(url=params['url'], params=params, ssl=False) as response:
            answer = await response.json()
        try:
            result = [item['player'] for item in answer['response']['items']]
            return result
        except IndexError:
            raise Exception('Видео не найдено')
        except KeyError:
            raise Exception('Сбой в API VK')

    # Функция для получения последнего поста сообщества. Использует request
    @staticmethod
    async def get_latest_post(
            owner_id: int,
            session: aiohttp.ClientSession,
            get_photos: bool = True, get_videos: bool = True
    ) -> PostData:
        owner_id = -abs(owner_id)

        # в этом методе owner_id должен быть меньше 0 если это группа
        # Параметры запроса для vk api
        params = {
            'access_token': config.access_token, 'url': 'https://api.vk.com/method/wall.get',
            'count': 2,
            'client_id': config.api_acc_id, 'owner_id': owner_id,
            'v': config.vk_api_version, 'extended': 1
        }
        async with session.get(url=params['url'], params=params, ssl=False) as response:
            post = await response.json()

        # pprint(post)

        if 'response' in post:
            post = post['response']
        else:
            raise Exception('Что-то не так (строка 54)')

        # От поста берутся только текст и фото, потому что я не знаю, как взять видео
        # Проверка на количество постов. Если постов 0, то, в некоторых случаях, дальнейшее действие останавливается.
        if len(post['items']) == 2:
            if post['items'][0]['id'] > post['items'][1]['id']:
                index = 0
            else:
                index = 1
        elif len(post['items']) == 1:
            index = 0
        else:
            raise Exception('В группе нет постов (строка 63)')

        answer = addition.PostData()

        answer.text = parse_hyperlinks(post['items'][index]['text'])
        answer.group_id = post['items'][0]['owner_id']
        answer.post_id = post['items'][index]['id']

        answer.group_name = list(filter(lambda item: int(item['id']) == abs(int(owner_id)),
                                        post['groups']))[0]['name']

        media = post['items'][index]['attachments'].copy()  # Список со всеми вложениями поста
        _videos = []

        # Если есть репосты, то сохраняем тексты и добавляем в список фотографий и видео фотографии и видео с репоста
        if 'copy_history' in post['items'][index]:
            len_copy = len(post['items'][index]['copy_history'])
            for repost_index in range(len_copy):
                answer.reposted_text[repost_index + 1] = \
                    parse_hyperlinks(
                        post['items'][index]['copy_history'][repost_index]['text']
                    )
                if 'attachments' in post['items'][index]['copy_history'][repost_index]:
                    media += post['items'][index]['copy_history'][repost_index]['attachments'].copy()

        # Проходимся по вложениям и ищем фотографии.
        for counter in range(len(media)):
            # Если фотографии всё-таки есть (и их надо брать), то сохраняем их.
            if get_photos and 'photo' in media[counter]:
                # Тут выбирается url фотографии самого лучшего разрешения (=оригинал)
                url_image: str = max(media[counter]['photo']['sizes'],
                                     key=lambda inspect_image: inspect_image['height'] * inspect_image['width'])['url']

                async with session.get(url=url_image, ssl=False) as response:
                    image = await response.content.read()  # Сама фотография, собственно
                filename = url_image.split('/')[-1].split('?')[0]
                res = addition.ImageToDiscord(image, filename)

                answer.photos.append(res)

            # Если есть видео, то забираем url их проигрывателя
            if get_videos and 'video' in media[counter]:
                video = media[counter]['video']
                video_owner_id = video['owner_id']
                video_id = video['id']

                _videos.append(f'{video_owner_id}_{video_id}')

        if _videos:
            answer.videos = await VKSide.get_videos_url(_videos, session)

        return answer

    # Получение ID и типа группы vk по ссылке, нужен при настройки подписки, удалении и добавлении, т.к. в бд
    # хранятся только id и ссылка, системная ссылка
    # (club<id>, если это группа и public<id>, если это публичная страница)
    @staticmethod
    async def get_group_id(group_url: str, session: aiohttp.ClientSession) -> tuple[int, str]:
        name = group_url.rsplit('/', 1)[1]

        # Параметры запроса для vk api
        params = {
            'access_token': config.access_token, 'url': 'https://api.vk.com/method/utils.resolveScreenName',
            'screen_name': name,
            'v': config.vk_api_version
        }
        async with session.get(url=params['url'], params=params, ssl=False) as response:
            answer = await response.json()

        # if 'response' not in answer:
        #     raise BotException('Внутренняя ошибка! '
        #                        'Сообщите разработчику об ошибке и деталях добавляемой подписки, '
        #                        'пожалуйста, она будет исправлена')

        # если vk api выдало ошибку, то почти наверняка из-за того, что такой группы не существует
        if not answer['response']:
            raise BotException('Такой группы не существует!')

        # Остальные типы vk объектов не подходят, т.к. они не сообщсетва
        if answer['response']['type'] not in ['group', 'page']:
            raise BotException('Это не группа!')

        return answer['response']['object_id'], answer['response']['type']

    # Метод получения имени группы, нужен только при занесении подписки в базу,
    # т.к. при получении поста можно обновить имя
    @staticmethod
    async def get_group_name(group_id: int, session: aiohttp.ClientSession) -> str:
        # в этом методе group_id должен быть больше 0, т.к. здесь метод работает только с группами
        group_id = abs(group_id)  # это лишь на всякий случай

        params = {
            'access_token': config.access_token,
            'url': 'https://api.vk.com/method/groups.getById',
            'group_id': group_id,
            'v': config.vk_api_version,
        }
        async with session.get(url=params['url'], params=params, ssl=False) as response:
            answer = await response.json()
        return answer['response']['groups'][0]['name']


# Тесты
if __name__ == '__main__':
    async def main(group_ids):
        async with aiohttp.ClientSession() as session:
            tasks = []
            for group_id in group_ids:
                tasks.append(asyncio.create_task(VKSide().get_latest_post(group_id, session)))

            result = await asyncio.gather(*tasks)
        for res in result:
            print(res.group_name)

    # print('id group---', VKSide().get_group_id('https://vk.com/hoi4nw'))
    # print('name---', VKSide().get_group_name(-218675277))
    # start = time.time()
    a = time.time()
    asyncio.run(main([-218675277, -169099825, -170023851, -173306991]))
    print(time.time() - a)
    # print(time.time() - start)
