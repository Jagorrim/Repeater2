import sqlite3
import nextcord
from dataclasses import dataclass, field


@dataclass
class ImageToDiscord:
    content: bytes
    filename: str


@dataclass
class PostData:
    text: str = ''
    reposted_text: dict = field(default_factory=dict)
    photos: list = field(default_factory=list)
    videos: list = field(default_factory=list)
    group_name: str = ''
    post_id: int = None
    group_id: int = None


@dataclass
class SubscriptionData:
    id: int
    vk_group_id: int
    ds_channel_id: int
    ds_guild_id: int
    pinged_role_id: int


@dataclass
class GroupData:
    vk_group_id: int
    vk_group_name: str
    vk_group_url: str
    last_post_id: int


class Cursor:
    def __init__(self, conn: sqlite3.Connection):
        self.cur = conn.cursor()

    def __enter__(self):
        return self.cur

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cur.close()


class BotException(Exception):
    # Это исключение, которое вызывается исключительно ботом (например, при неправильных данных).
    # Оно нужно для того, чтобы разделять непредвиденные ошибки и те, которые вызываются самим ботом
    pass


def interaction_saver(func):
    # хоть interaction и не объявлена, она будет передаваться (так или иначе)
    async def safe_func(self, interaction, *args, **kwargs):
        try:
            await func(self, interaction, *args, **kwargs)
        except BotException as msg:
            await interaction.response.send_message(msg)
        except Exception as msg:
            print(msg)
            await interaction.response.send_message(
                "Что-то пошло не так! "
                "Сообщите разработчику (Jagorrim) о деталях действий, "
                "приведших к данной ошибке, пожалуйста, она будет исправлена"
            )

    return safe_func


def admin_only(func):
    async def wrapped_func(self, interaction: nextcord.Interaction, *args, **kwargs):
        if not interaction.user.guild_permissions.administrator:
            raise BotException('У вас недостаточно прав для выполнения этой команды!')

        await func(self, interaction, *args, **kwargs)

    return wrapped_func


# Перебираем текст на наличие гиперссылок, меняя их формат на дискордовский
# кстати странно, но вк не поддерживает гиперссылки на внешние ресурсы
def parse_hyperlinks(post_text: str) -> str:
    text_index = 0
    new_text = ''
    while text_index < len(post_text):
        # Если текущий символ - "[", а после него есть и "]", а между ними есть "|", то
        # пробуем вычленить оттуда ссылку и текст, который замещает её
        if '[' == post_text[text_index] and ']' in post_text[text_index:] and \
                '|' in post_text[text_index: post_text[text_index:].find(']') + 1 + text_index]:
            link_place = post_text[
                         text_index: post_text[text_index:].find(']') + 1 + text_index
                         ]
            link = link_place[1:link_place.find('|')]
            # Если ссылка НЕ имеет при себе префикса в виде сетевого протокола и домена вк (а такое может быть),
            # то добавляем их, чтобы ссылка была настоящей.
            if not link.startswith('https://vk.com/'):
                link = 'https://vk.com/' + link
            text = link_place[link_place.find('|') + 1: -1]

            new_text += f'[{text}]({link})'  # создание гиперссылок, но уже дискордовских
            text_index += len(link_place)
        else:
            new_text += post_text[text_index]
            text_index += 1
    return new_text


# тесты
if __name__ == '__main__':
    print(parse_hyperlinks('привет[|h]2'))
