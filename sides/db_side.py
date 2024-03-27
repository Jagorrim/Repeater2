import sqlite3

from addition import Cursor, BotException, SubscriptionData, GroupData
import typing


class DBSide:
    @staticmethod
    def update_group(conn: sqlite3.Connection, vk_group_id: int, param_name: str, value: typing.Any) -> None:
        with Cursor(conn) as cur:
            cur.execute(f'UPDATE vk_groups SET {param_name}=? WHERE vk_group_id=?', (value, vk_group_id,))
            conn.commit()

    # Проверяем наличие какой-либо группы
    @staticmethod
    def has_group(conn: sqlite3.Connection, vk_group_id: int) -> bool:
        with Cursor(conn) as cur:
            result = cur.execute('SELECT vk_group_id FROM vk_groups WHERE vk_group_id=?', (vk_group_id,)).fetchone()
        return result is not None

    # Добавляем группу
    @staticmethod
    def add_group(
            conn: sqlite3.Connection,
            vk_group_id: int,
            vk_group_name: str,
            vk_group_url: str,
            last_post_id: int
    ) -> None:
        with Cursor(conn) as cur:
            # Добавляем в БД новую подписку
            cur.execute(f"""INSERT INTO vk_groups (vk_group_id, vk_group_name, vk_group_url, last_post_id) VALUES
                 (?, ?, ?, ?)""", (vk_group_id, vk_group_name, vk_group_url, last_post_id))

    # Получаем все группы, на которые вообще есть подписки
    @staticmethod
    def get_all_groups(conn: sqlite3.Connection) -> list[GroupData]:
        with Cursor(conn) as cur:
            result = [GroupData(*item) for item in cur.execute(
                'SELECT vk_group_id, vk_group_name, vk_group_url, last_post_id FROM vk_groups'
            )]
        return result

    # Получаем все подписки на какую-либо группу
    @staticmethod
    def get_ss_by_group(conn: sqlite3.Connection, vk_group_id: int) -> list[SubscriptionData]:
        with Cursor(conn) as cur:
            result = [SubscriptionData(*item) for item in cur.execute(
                'SELECT id, vk_group_id, ds_channel_id, ds_guild_id, pinged_role_id FROM subscriptions '
                'WHERE vk_group_id=?', (vk_group_id,)
            )]
        return result

    @staticmethod
    def delete_channel(conn: sqlite3.Connection, channel_id) -> None:
        with Cursor(conn) as cur:
            cur.execute('DELETE FROM subscriptions WHERE ds_channel_id=?', (channel_id,))
            conn.commit()

    @staticmethod
    def delete_guild(conn: sqlite3.Connection, guild_id) -> None:
        with Cursor(conn) as cur:
            cur.execute('DELETE FROM subscriptions WHERE ds_guild_id=?', (guild_id,))
            conn.commit()

    # Добавление новой подписки на данный vk паблик для данного ds канала
    @staticmethod
    def db_add_s(
            conn: sqlite3.Connection, vk_group_id: int, channel_id: int, guild_id: int, pinged_role_id: int = None
    ) -> None:
        with Cursor(conn) as cur:
            # Надо проверить на наличие такой подписки
            result = cur.execute("""SELECT vk_group_id FROM subscriptions WHERE ds_channel_id=? AND vk_group_id=?""",
                                 (channel_id, vk_group_id)).fetchone()

            if result is not None:
                raise BotException('Этот канал уже подписан на эту группу!')

            # Это мы дальше закинем в новую подписку
            new_subscription = [vk_group_id, channel_id, guild_id]  # Значения
            columns = ['vk_group_id', 'ds_channel_id', 'ds_guild_id']  # Названия колонок, в которые попадут значения

            if pinged_role_id is not None:
                columns += ['pinged_role_id']
                new_subscription += [pinged_role_id]

            # Добавляем в БД новую подписку
            cur.execute(f"""INSERT INTO subscriptions ({', '.join(columns)}) VALUES
                 ({', '.join('?' for _ in range(len(columns)))})""",
                        new_subscription)
            conn.commit()

    # Удаление подписки
    @staticmethod
    def db_delete_s(conn: sqlite3.Connection, ds_channel_id: int, vk_group_url: str) -> None:
        with Cursor(conn) as cur:
            # Надо сначала проверить, что такая подписка вообще есть
            vk_group_id = cur.execute("""SELECT vk_group_id FROM vk_groups WHERE vk_group_url=?""",
                                      (vk_group_url,)).fetchone()
            if vk_group_id is None:
                raise BotException('Такой подписки не существует!')
            vk_group_id = vk_group_id[0]

            subscription = cur.execute("""SELECT id FROM subscriptions WHERE vk_group_id=? AND ds_channel_id=?""",
                                       (vk_group_id, ds_channel_id)).fetchone()

            if subscription is None:
                raise BotException('Такой подписки не существует!')

            cur.execute('DELETE FROM subscriptions WHERE vk_group_id=? AND ds_channel_id=?',
                        (vk_group_id, ds_channel_id))
            conn.commit()

    # Настройка параметров подписки
    @staticmethod
    def db_set_s(conn: sqlite3.Connection, ds_channel_id: int, vk_group_url: str, param: str, arg: str) -> None:
        with Cursor(conn) as cur:
            # Надо сначала проверить, что такая подписка вообще есть
            vk_group_id = cur.execute("""SELECT vk_group_id FROM vk_groups WHERE vk_group_url=?""",
                                      (vk_group_url,)).fetchone()
            if vk_group_id is None:
                raise BotException('Такой подписки не существует!')
            vk_group_id = vk_group_id[0]

            _ds_channel_id = cur.execute(
                'SELECT ds_channel_id FROM subscriptions WHERE ds_channel_id=? AND vk_group_id=?',
                (ds_channel_id, vk_group_id)).fetchone()

            if _ds_channel_id is None:
                raise BotException('Такой подписки не существует!')

            # Я не понимаю, почему не могу в этой строке вместо {param} поставить ? и передавать ещё и param
            # вместе с arg и vk_group_url, это странно
            cur.execute(f'UPDATE subscriptions SET {param}=? WHERE vk_group_id=? AND ds_channel_id=?',
                        (arg, vk_group_id, ds_channel_id))
            conn.commit()

    # Это НЕ СС, это сокращение от subscriptions (как в названиях предыдущих методов)!!!
    @staticmethod
    def db_get_ss(conn: sqlite3.Connection, ds_channel_id: int, parametres: typing.Iterable) -> list[list]:
        # parametres - список имён параметров, которые есть у публикации. Передаются при вызове из главного класса,
        # т.к. они могут меняться и прописаны только там
        result = []
        with Cursor(conn) as cur:
            # Надо проверить на наличие такой подписки
            subscribes = cur.execute(
                f"""SELECT vk_group_id, {','.join(parametres)} 
                FROM subscriptions WHERE ds_channel_id=?""",
                (ds_channel_id,)).fetchall()

            for vk_group_id, *values in subscribes:
                vk_group_url, vk_group_name = cur.execute(
                    f"""SELECT vk_group_url, vk_group_name FROM vk_groups WHERE vk_group_id=?""",
                    (vk_group_id,)
                ).fetchone()
                result.append([vk_group_url, vk_group_name] + values)

        return result


# Тесты
if __name__ == '__main__':
    with sqlite3.connect('../db.sqlite') as conn:
        print(DBSide().get_all_groups(conn))
        # print(DBSide().has_group(conn, 173813383))
        # for i in DBSide.get_all_ss(conn):
        #     print(i)
