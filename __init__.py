#!/usr/bin/python
# -*- coding: utf-8 -*-
import datetime
import json
import random
from time import sleep

import lxml.html
import requests
import vk_api
from pymongo import MongoClient
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.longpoll import VkLongPoll, VkEventType

_CONFIG = json.loads(open('config.json', "r", encoding='UTF-8').read())

client = MongoClient('127.0.0.1', 27017)
db = client.ucbot

vk_session = vk_api.VkApi(token=open('.token', 'r', encoding='UTF-8').read())
vk = vk_session.get_api()
longpoll = VkLongPoll(vk_session)


class Group:
    @classmethod
    def get_group_list(cls, user_type: int, date: str):
        with requests.Session() as s:
            result = s.post(url='http://uc.osu.ru/back_parametr.php', data={
                'type_id': user_type,
                'data': date
            })
            s.cookies.clear_session_cookies()
        if result.status_code == 200:
            result.encoding = 'UTF-8'
            group_dict = result.text.replace('(с)', '').replace('(ТМ)', '').replace('(А)', '')
            r = json.loads(group_dict)
            rb = {val: key for (key, val) in r.items()}
            group_dumps = json.dumps(rb, ensure_ascii=False, sort_keys=True, indent=2)
            return json.loads(group_dumps)

    @classmethod
    def validate(cls, user_type: int, user_group: str, date: str):
        if cls.get_group_list(user_type, date) and user_group in cls.get_group_list(user_type, date):
            return True

    @classmethod
    def get_id(cls, user_type: int, user_group: str, date: str):
        if cls.validate(user_type, user_group, date):
            return cls.get_group_list(user_type, date)[user_group]


class Table:
    @classmethod
    def pars_table(cls, html_table, user_type):
        table_text = lxml.html.fromstring(html_table)
        tbl = []
        rows = table_text.cssselect("tr")
        for row in rows:
            tbl.append(list())
            for td in row.cssselect("td"):
                tbl[-1].append(td.text_content())
        if user_type == 1:
            tbl = tbl[1:]
        temp = []
        temp_dict = {}
        string = []

        for i in tbl:
            if len(i) > 1:
                temp.append(i)
            else:
                temp[-1] += i
        for i in temp:
            temp_dict[i[0]] = i[1:]
        for i in temp_dict.keys():
            string.append('%s. %s -- %s\n-- %s\n\n' % (i, temp_dict[i][0], temp_dict[i][1].replace('<\n/td>', ''),
                                                       temp_dict[i][2]))
        string = '\n'.join(string)
        return str(string)

    @classmethod
    def request(cls, user_type: int, user_group_id: str, date: str):
        with requests.Session() as s:
            result_server = s.post('http://uc.osu.ru/generate_data.php', data={
                'type': user_type,
                'data': date,
                'id': user_group_id
            })
            s.cookies.clear_session_cookies()
        if result_server.status_code == 200:
            result_server.encoding = 'UTF-8'
            return cls.pars_table(result_server.text, user_type)

    @classmethod
    def get(cls, user_type: int, user_group: str, date: str):
        if db.tables.count_documents({'group': user_group, 'date': date}) == 0:
            if Group.validate(user_type, user_group, date):
                result = cls.request(user_type, Group.get_id(user_type, user_group, date), date)
                db.tables.insert_one({'group': user_group, 'date': date, 'value': result})
                return result
            else:
                return 'error_request'
        elif db.tables.count_documents({'group': user_group, 'date': date}) > 0:
            result = db.tables.find_one({'group': user_group, 'date': date})
            return result['value']


class AutoSend:
    @classmethod
    def check_time(cls):
        now = datetime.datetime.now()
        hour = 18
        h = now.hour
        m = now.minute
        s = now.second
        if h < hour:
            return (hour - h) * 60 * 60 - m * 60 - s
        if h >= hour:
            return (24 - h) * 60 * 60 - m * 60 - s + hour * 60 * 60

    @classmethod
    def start(cls):
        while True:
            sleep(cls.check_time())
            print('Start auto-send')
            cursor = db.users.find({'sub': True})
            groups = []
            for u in cursor:
                if u['group'] not in groups:
                    groups.append(u['group'])

            for g in groups:
                r = Table.get(g['type_id'], g, get_date(True))
                if r.startswith('error_'):
                    print(r)
                    continue
                else:
                    for u in db.users.find({'group': g, 'sub': True}):
                        vk.messages.send(
                            user_id=u['_id'],
                            message=r
                        )
            print('End auto-send')


def get_date(is_tomorrow: bool = False):
    today = datetime.date.today()
    if is_tomorrow is True:
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        return tomorrow.strftime("%d-%m-%Y")
    else:
        return today.strftime("%d-%m-%Y")


def send(user_id, msg, raw=False, k=None):
    if raw and msg.startswith('error_') or raw is False:
        msg = _CONFIG['messages'][msg]

    if k is None:
        vk.messages.send(
            user_id=user_id,
            message=msg,
            random_id=random.randint(10000000000, 99999999999)
        )
        print("* \033[95m(: \033[0m : id" + str(user_id) + " < " + msg[:10])
    else:
        vk.messages.send(
            user_id=user_id,
            message=msg,
            random_id=random.randint(10000000000, 99999999999),
            keyboard=k
        )
        print("* \033[95m(: \033[0m : id" + str(user_id) + " < " + msg[:10])


def main():
    print("* \033[92m(^_^)\033[0m")
    for event in longpoll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me and event.text:
            print("* \033[95m0.o\033[0m : id" + str(event.user_id) + " > " + event.text[:10] + '...')
            get_type = VkKeyboard(True)
            get_type.add_button('Преподователь', VkKeyboardColor.POSITIVE)
            get_type.add_button('Студент', VkKeyboardColor.POSITIVE)

            if vk.groups.isMember(group_id=_CONFIG['group_id'], user_id=event.user_id) == 1:
                if db.users.count_documents({'_id': event.user_id}) == 0:
                    cancel_key = VkKeyboard()
                    cancel_key.add_button('Вернуться обратно', VkKeyboardColor.DEFAULT)

                    send(event.user_id, 'get_user_type', k=get_type.get_keyboard())
                    if event.text == 'Преподователь':
                        db.users.insert_one({
                            '_id': event.user_id,
                            'type_id': 2,
                            'sub': False,
                            'group': None
                        })
                        send(event.user_id, 'get_teacher_name', k=cancel_key.get_keyboard())
                    elif event.text == 'Студент':
                        db.users.insert_one({
                            '_id': event.user_id,
                            'type_id': 1,
                            'sub': False,
                            'group': None
                        })
                        send(event.user_id, 'get_student_group', k=cancel_key.get_keyboard())
                else:
                    c_user = db.users.find_one({'_id': event.user_id})
                    if c_user['group'] is None:
                        if event.text == 'Вернуться обратно':
                            db.users.delete_one({'_id': event.user_id})
                            send(event.user_id, 'get_user_type', k=get_type.get_keyboard())
                        elif Group.validate(c_user['type_id'], event.text.upper(), get_date()) or Group.validate(
                                c_user['type_id'],
                                event.text,
                                get_date(
                                    is_tomorrow=True)):
                            db.users.update_one({
                                '_id': event.user_id
                            }, {
                                '$set': {
                                    'group': event.text
                                }
                            })
                            day_count = VkKeyboard(False)
                            day_count.add_button('На сегодня', VkKeyboardColor.PRIMARY)
                            day_count.add_button('На завтра', VkKeyboardColor.PRIMARY)
                            send(event.user_id, 'success_add', k=day_count.get_keyboard())
                        else:
                            send(event.user_id, 'error_group_not_found')
                    else:
                        """
                            Блок команд для авторизованных пользователей
                        """
                        if event.text.startswith('!'):
                            args = event.text[1:].split()
                            if len(args) == 2:
                                send(event.user_id, Table.get(1, args[0].upper(), args[1]), raw=True)
                            else:
                                send(event.user_id, 'error_lack_of_args')
                            continue
                        elif event.text == '+':
                            db.users.update_one({'_id': event.user_id}, {'$set': {'sub': True}})
                            send(event.user_id, 'success_sub')
                            continue
                        elif event.text == '-':
                            db.users.update_one({'_id': event.user_id}, {'$set': {'sub': False}})
                            send(event.user_id, 'success_unsub')
                            continue
                        elif event.text.lower() == 'инфо':
                            send(event.user_id, 'info')
                        elif event.text == 'На завтра':
                            send(event.user_id,
                                 Table.get(c_user['type_id'], c_user['group'], get_date(is_tomorrow=True)), raw=True)
                        elif event.text == 'На сегодня':
                            send(event.user_id, Table.get(c_user['type_id'], c_user['group'], get_date()), raw=True)
                        elif event.text.lower() == 'удалить':
                            db.users.delete_one({'_id': event.user_id})
                            send(event.user_id, 'get_user_type', k=get_type.get_keyboard())
                        else:
                            send(event.user_id, 'error_command_not_found')
            else:
                send(event.user_id, 'error_is_not_group')


if __name__ == '__main__':
    main()
