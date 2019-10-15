#!/usr/bin/python
# -*- coding: utf-8 -*-
import datetime
import json
import random

import lxml.html
import requests
import vk_api
from pymongo import MongoClient
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.longpoll import VkLongPoll, VkEventType


_CONFIG = json.loads(open('config.json', "r", encoding='UTF-8').read())

"""
    MongoDB auth
"""
client = MongoClient('127.0.0.1', 27017)
db = client.ucbot


"""
    Vk auth
"""
vk_session = vk_api.VkApi(token=open('token.txt', 'r', encoding='UTF-8').read())
vk = vk_session.get_api()
bot = VkLongPoll(vk_session)

"""
    Keyboards
"""
START_KEYBOARD = VkKeyboard()
START_KEYBOARD.add_button('Начать', VkKeyboardColor.POSITIVE)

GET_TYPE_KEYBOARD = VkKeyboard()
GET_TYPE_KEYBOARD.add_button('Преподователь', VkKeyboardColor.POSITIVE)
GET_TYPE_KEYBOARD.add_button('Студент', VkKeyboardColor.POSITIVE)

RETURN_KEYBOARD = VkKeyboard()
RETURN_KEYBOARD.add_button('Вернуться обратно', VkKeyboardColor.DEFAULT)

MAIN_KEYBOARD = VkKeyboard()
MAIN_KEYBOARD.add_button('На сегодня', VkKeyboardColor.POSITIVE)
MAIN_KEYBOARD.add_button('На завтра', VkKeyboardColor.POSITIVE)


def get_groups(user_type, date) -> object:
    if db.groups.count_documents({'user_type': user_type, 'date': date}) == 0:
        with requests.Session() as s:
            result = s.post(url='http://uc.osu.ru/back_parametr.php', data={
                'type_id': user_type,
                'data': date
            })
            s.cookies.clear_session_cookies()
        if result.status_code == 200:
            result.encoding = 'UTF-8'

            group_dict = result.text\
                .replace('(с)', '')\
                .replace('(ТМ)', '')\
                .replace('(А)', '')

            r = json.loads(group_dict)

            rb = {val: key for (key, val) in r.items()}
            group_dumps = json.dumps(rb, ensure_ascii=False, sort_keys=True, indent=2)

            res = json.loads(group_dumps)
            db.groups.insert_one({'user_type': user_type, 'date': date, 'value': res})
            return res
    else:
        return db.groups.find_one({'user_type': user_type, 'date': date})['value']


def parse_timetable(html, user_type):
    table_text = lxml.html.fromstring(html)
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
    return str('\n'.join(string))


def get_timetable(user_type: int, user_group: str, date: str) -> str:
    if db.tables.count_documents({'group': user_group, 'date': date}) == 0:
        with requests.Session() as s:
            result = s.post('http://uc.osu.ru/generate_data.php', data={
                'type': user_type,
                'data': date,
                'id': user_group
            })
            s.cookies.clear_session_cookies()
        if result.status_code == 200:
            result.encoding = 'UTF-8'

            timetable = parse_timetable(result.text, user_type)

            db.tables.insert_one({'group': user_group, 'date': date, 'value': timetable})
            return timetable

    elif db.tables.count_documents({'group': user_group, 'date': date}) > 0:
        result = db.tables.find_one({'group': user_group, 'date': date})
        return result['value']


def get_table(user_type, user_date, group):
    return get_timetable(user_type, get_groups(user_type, user_date)[group.upper()], user_date)


def get_date(days):
    tomorrow = datetime.date.today() + datetime.timedelta(days=days)
    return tomorrow.strftime("%d-%m-%Y")


class User:
    def __init__(self, user_id):
        self.user = db.users.find_one({'_id': user_id})
        self.id = self.user['_id']
        self.type_id = self.user['type_id']
        self.group = self.user['group']

    def set_type_id(self, type_id):
        db.users.update_one({'_id': self.id}, {'$set': {'type_id': type_id}})

    def is_set_type_id(self):
        return self.type_id is None

    def set_group(self, group):
        db.users.update_one({'_id': self.id}, {'$set': {'group': group}})

    def is_set_group(self):
        return self.group is None

    def send(self, msg, raw=False, keyboard=None):
        rnd = random.randint(10000000000, 99999999999)

        if raw and msg.startswith('error_') or raw is False:
            msg = _CONFIG['messages'][msg]

        if keyboard is None:
            vk.messages.send(user_id=self.id, message=msg, random_id=rnd)
        else:
            vk.messages.send(user_id=self.id, message=msg, random_id=rnd, keyboard=keyboard)

        print("* \033[95m(: \033[0m : id" + str(self.id) + " < ")

    def send_table(self, days):
        self.send(get_table(self.type_id, get_date(days), self.group), raw=True)

    def delete(self):
        db.users.delete_one({'_id': self.id})

    @staticmethod
    def create(user_id):
        db.users.insert_one({
            '_id': user_id,
            'type_id': None,
            'sub': False,
            'group': None,
        })
        vk.messages.send(user_id=user_id,
                         message=_CONFIG['messages']['get_user_type'],
                         random_id=random.randint(10000000000, 99999999999),
                         keyboard=GET_TYPE_KEYBOARD.get_keyboard())


def main():
    print('run')
    for event in bot.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me and event.text:
            if db.users.count_documents({'_id': event.user_id}) == 0:

                User.create(event.user_id)
                continue

            user = User(event.user_id)

            if user.is_set_type_id():
                if event.text in ['Преподователь', '2']:

                    user.set_type_id(2)
                    user.send('get_teacher_name', keyboard=RETURN_KEYBOARD.get_keyboard())

                elif event.text in ['Студент', '1']:

                    user.set_type_id(1)
                    user.send('get_student_group', keyboard=RETURN_KEYBOARD.get_keyboard())

                continue

            if user.is_set_group():
                if event.text in ['Вернуться обратно', '1']:

                    user.set_type_id(None)
                    user.send('get_user_type', keyboard=GET_TYPE_KEYBOARD.get_keyboard())

                elif event.text.upper() in get_groups(user.type_id, get_date(0)) \
                        or event.text.upper() in get_groups(user.type_id, get_date(1)) \
                        or event.text.upper() in get_groups(user.type_id, get_date(2)):

                    user.set_group(event.text)
                    user.send('success_add', keyboard=MAIN_KEYBOARD.get_keyboard())

                else:
                    user.send('error_group_not_found')
                continue

            if event.text.startswith('/'):

                args = event.text[1:].split()

                if len(args) == 2:
                    user.send(get_table(1, args[1], args[0].upper()), raw=True)
                else:
                    user.send('error_lack_of_args')

            elif event.text.lower() in ['инфо', '?']:

                user.send('info')

            elif event.text in ['На сегодня', '1']:

                user.send_table(0)

            elif event.text in ['На завтра', '2']:

                user.send_table(1)

            elif event.text.lower() in ['удалить', '-']:

                user.send('start', keyboard=START_KEYBOARD.get_keyboard())
                user.delete()
            else:
                user.send('error_command_not_found')


if __name__ == '__main__':
    main()

