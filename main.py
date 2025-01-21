import nextcord
import aiohttp
import time
import config
import sqlite3
import asyncio
from sides.db_side import DBSide
from sides.vk_side import VKSide
from addition import BotException, interaction_saver, admin_only, SubscriptionData, GroupData, PostData
from io import BytesIO
import sys


class Repeater(DBSide, VKSide, nextcord.Client):
    def __init__(self):
        bot_intents = nextcord.Intents().all()

        nextcord.Client.__init__(self, intents=bot_intents, allowed_mentions=nextcord.AllowedMentions(everyone=True))
        # Делаем функции слэш-командами бота
        self.ping = self.slash_command(name="ping", description="Текущий пинг бота")(self.ping)
        self.add = self.slash_command(name='add', description='Добавить подписку')(self.add)
        self.help = self.slash_command(name='help', description='Помощь по боту')(self.help)
        self.set = self.slash_command(name='set', description='Настроить подписку')(self.set)
        self.delete = self.slash_command(name='delete', description='Удалить подписку')(self.delete)
        self.subscriptions = self.slash_command(
            name='subscriptions', description='Подписки этого канала')(self.subscriptions)

        self.subscribe_parameters = {'pinged_role_id': 'ID роли, которую нужно пинговать '
                                                       'при отправке поста по какой-либо подписке'}
        self.description = ['Это Repeater!',
                            'Этот бот пересылает посты из VK сообществ.',
                            'Но есть несколько нюансов:',
                            '1) Видео из VK приходят в виде ссылок на них.',
                            '2) Подписаться на приватные группы нельзя\n',

                            'Текущие параметры команд:',
                            ''.join(
                                [f'{name} - {description}' for name, description in self.subscribe_parameters.items()]
                            ) + '\n',

                            'Список команд:\n',

                            '/ping - простое получение данных о пинге.\n',

                            '/add <url VK сообщества> <параметр=аргумент> - |ТРЕБУЮТСЯ ПРАВА АДМИНИСТРАТОРА| добавить подписку на заданное сообщество.\n',

                            '/help - информация о боте и том, как им пользоваться.\n',

                            '/set <url VK сообщества> <параметр=аргумент> - |ТРЕБУЮТСЯ ПРАВА АДМИНИСТРАТОРА| '
                            'настройка параметров подписки на какой-либо паблик.\n',

                            '/delete <url VK сообщества> - |ТРЕБУЮТСЯ ПРАВА АДМИНИСТРАТОРА| '
                            'удаляет переданное сообщество из подписок канала.\n',

                            '/subscriptions - список всех подписок канала, из которого вызывалась команда.\n',

                            'В командах /set и /delete следует передавать тот url, '
                            'который показывается при вызове команды /subscriptions, '
                            'ибо другие url не хранятся по причине того, что они могут поменяться. '
                            'В /add можно передавать какой угодно url.\n',

                            'На данный момент бот находится в разработке, возможны баги и прочая муть.',
                            'Пишите мне о багах, недочётах и предложениях по улучшению, мой дс - Jagorrim.',
                            'Возможны перебои в работе бота из-за отсутствия постоянного хоста.']
        self.conn = None
        self.length_limit = 2000  # Ограничение по длине символов в сообщении в дискорде

    def start_bot(self, token: str) -> None:
        with sqlite3.connect(config.db_path) as conn:
            try:
                self.conn = conn
                self.run(token)
            except (Exception, KeyboardInterrupt, SystemExit) as msg:
                print(msg)
                # Тут логи надо бы по-хорошему

    async def check_updates(self):
        while True:
            try:
                start = time.time()
                async with aiohttp.ClientSession() as session:
                    groups = self.get_all_groups(self.conn)
                    try:
                        for group in groups:
                            latest_post = await self.get_latest_post(group.vk_group_id, session)

                            # Если текущий id последнего поста меньше либо равен зафиксированному id последнего поста,
                            # то следует пропустить данную группу,
                            # т.к. в группе либо удалили пост, либо ничего нового не появилось.
                            if latest_post.post_id <= group.last_post_id:
                                continue

                            # Обновляем последний id у подписки, т.к. у неё вышел новый пост
                            self.update_group(self.conn, group.vk_group_id, 'last_post_id', latest_post.post_id)
                            for subscription in self.get_ss_by_group(self.conn, group.vk_group_id):
                                await self.send_post(subscription, group, latest_post)
                    except Exception as e:
                        print(f'Ошибка при обходе сообщества {group}', e)
                print(time.time() - start)
            except Exception as e:
                print(f'Ошибка в обходе сообществ: {e}')
            await asyncio.sleep(config.timeout)  # Ждём некоторое время чтобы потом снова вернуться

    async def send_post(self, subscription: SubscriptionData, group: GroupData, post: PostData):
        try:
            title = f"Новый пост от: [{group.vk_group_name}]({group.vk_group_url})""\n\n\n"
            videos = '\n'.join(
                [f'[Видео №{counter}]({url})' for counter, url in enumerate(post.videos, start=1)]
            )
            photos = [nextcord.File(BytesIO(photo.content), photo.filename) for photo in post.photos]
            text = title + post.text

            # Репосты
            if post.reposted_text:
                for index in post.reposted_text:
                    text += '\n\n' + f'Текст из репоста №{index}:' + '\n\n' + post.reposted_text[index]

            # Ссылки на видео
            if videos:
                text += '\n\n' + videos

            # Пинги
            if subscription.pinged_role_id:
                # Если пинг не для всех, то он точно пингует определённую роль, => надо проверить, что она есть
                role = self.get_guild(subscription.ds_guild_id).get_role(subscription.pinged_role_id)
                ping = f'<@&{subscription.pinged_role_id}>'  # Это пинг роли да
                if role is None:
                    ping = '@удалённая роль'
                text += '\n\n' + ping

            # Выводим текст, постепенно обрезая его на части (по 1996 символов + 4 "*" для стилизации,
            # т.к. лимит в 2000 символов)
            channel = self.get_channel(subscription.ds_channel_id)

            while True:
                # Если длина текста + 4 звёздочки больше лимита, то берём кусок текста, а не весь
                if len(text) + 4 > self.length_limit:
                    await channel.send("**" + text[0: self.length_limit - 4] + "**")
                    # Обрезаем текст
                    text = text[self.length_limit - 4:]
                else:
                    await channel.send("**" + text + "**", files=photos)
                    break
        except Exception as e:
            print(f'Ошибка в отправке нового поста: {e}')
            # ТУТ ЛОГИ ААААА

    # Финальная настройка бота, уведомление о его запуске
    async def on_ready(self):
        print('Авторизовались')
        await self.change_presence(status=nextcord.Status.online, activity=nextcord.Game("перебор VK сообществ"))

        # Создаём отдельную задачу для бота, которая будет постоянно крутиться и
        # обходить группы вк раз в self.timeout секунд
        await self.loop.create_task(self.check_updates())

    # Бот может каким-либо образом потерять доступ к серверу, поэтому надо сделать так,
    # чтобы в случае чего он почистил свои записи о нём
    async def on_guild_remove(self, guild: nextcord.Guild):
        self.delete_guild(self.conn, guild.id)

    # Бот также может потерять доступ к какому-то конкретному каналу, так что тогда тоже надо чистить БД
    async def on_guild_channel_delete(self, channel: nextcord.TextChannel):
        self.delete_channel(self.conn, channel.id)

    #
    # Далее идут функции-обёртки, вызывающие рабочие функции.
    # Это сделано для того, чтобы можно было обернуть рабочие функции в различные декораторы
    # и при этом не потерять названия, количество и обязательность аргументов при вызове команды из дискода
    #

    # Пинг бота
    async def ping(self, interaction: nextcord.Interaction):
        await self._ping(interaction)

    # Добавление новой группы в подписки канала
    async def add(self, interaction: nextcord.Interaction, vk_group_url: str, pinged_role_id: int = None):
        unnecessary_args = []
        if pinged_role_id is not None:
            unnecessary_args.append(pinged_role_id)
        await self._add(interaction, vk_group_url, *unnecessary_args)

    async def help(self, interaction: nextcord.Interaction):
        await self._help(interaction)

    async def set(self, interaction: nextcord.Interaction, vk_group_url: str, param: str, arg: str = None):
        await self._set(interaction, vk_group_url, param, arg)

    async def delete(self, interaction: nextcord.Interaction, vk_group_url):
        await self._delete(interaction, vk_group_url)

    async def subscriptions(self, interaction: nextcord.Interaction):
        await self._subscriptions(interaction)

    #
    # Далее идут функции, которые уже непосредственно выполняют работу, которую дают им функции-обёртки
    #

    # Пинг бота
    @interaction_saver
    async def _ping(self, interaction: nextcord.Interaction):
        await interaction.response.send_message(f"Текущий пинг - {round(self.latency * 1000)}ms")

    # Добавление новой группы в подписки канала
    @interaction_saver
    @admin_only
    async def _add(self, interaction: nextcord.Interaction, vk_group_url: str, pinged_role_id: int = None):
        if not isinstance(interaction.channel, nextcord.TextChannel):
            raise BotException('Для каналов этого типа нельзя добавить подписку!')

        if not vk_group_url.startswith('https://vk.com/'):
            if vk_group_url.startswith('vk.com/'):
                vk_group_url = 'https://' + vk_group_url
            else:
                raise BotException('Ссылка не относится к домену vk!')

        async with aiohttp.ClientSession() as session:
            vk_group_id, group_type = await self.get_group_id(vk_group_url, session)

            # Если подписок на эту группу вк ещё нет, то просто добавляем в БД запись о этой группе
            if not self.has_group(self.conn, vk_group_id):
                vk_group_name = await self.get_group_name(vk_group_id, session)

                if group_type == 'group':
                    group_type = 'club'
                else:
                    group_type = 'public'

                system_group_url = f'https://vk.com/{group_type}{vk_group_id}'

                last_post_id = (
                    await self.get_latest_post(vk_group_id, session,
                                               get_photos=False, get_videos=False, only_get_last_post_id=True)).post_id

                self.add_group(self.conn, vk_group_id, vk_group_name, system_group_url, last_post_id=last_post_id)

        unnecessary_args = []
        if pinged_role_id is not None:
            unnecessary_args.append(pinged_role_id)

        self.db_add_s(self.conn, vk_group_id, interaction.channel_id, interaction.guild_id, *unnecessary_args)
        await interaction.response.send_message('Добавлено!')

    @interaction_saver
    async def _help(self, interaction: nextcord.Interaction):
        embed = nextcord.Embed(title='Привет!')
        embed.set_footer(text='\n'.join(self.description))
        await interaction.response.send_message(embed=embed)

    @interaction_saver
    @admin_only
    async def _set(self, interaction: nextcord.Interaction, vk_group_url: str, param: str, arg: str):
        if param not in self.subscribe_parameters:
            raise BotException('Такого параметра подписки не существует!')

        self.db_set_s(self.conn, interaction.channel_id, vk_group_url, param, arg)
        await interaction.response.send_message('Изменено!')

    @interaction_saver
    @admin_only
    async def _delete(self, interaction: nextcord.Interaction, vk_group_url):
        self.db_delete_s(self.conn, interaction.channel_id, vk_group_url)
        await interaction.response.send_message('Удалено!')

    @interaction_saver
    async def _subscriptions(self, interaction: nextcord.Interaction):
        embed = nextcord.Embed(title='Текущие подписки этого канала:')
        subscriptions = self.db_get_ss(self.conn, interaction.channel_id, self.subscribe_parameters.keys())

        if not subscriptions:
            raise BotException('У этого канала отсутствуют подписки!')

        cooked_subscriptions = []
        for index in range(len(subscriptions)):
            url = subscriptions[index][0]
            name = subscriptions[index][1]

            params = ', '.join(map(lambda name, value: f'{name}={value}',
                                   self.subscribe_parameters.keys(), subscriptions[index][2:]))

            cooked_subscriptions.append(f'{index + 1}. [{name}]({url}) {params}')
        embed.description = '\n'.join(cooked_subscriptions)
        await interaction.response.send_message(embed=embed)


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    client = Repeater()
    client.start_bot(config.ds_token)
