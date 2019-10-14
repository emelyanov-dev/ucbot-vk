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

client = MongoClient('127.0.0.1', 27017)
db = client.ucbot

vk_session = vk_api.VkApi(token=open('token.txt', 'r', encoding='UTF-8').read())
vk = vk_session.get_api()
long_poll = VkLongPoll(vk_session)

start_kbd = VkKeyboard()
start_kbd.add_button('Начать', VkKeyboardColor.POSITIVE)

get_type = VkKeyboard()
get_type.add_button('Преподователь', VkKeyboardColor.POSITIVE)
get_type.add_button('Студент', VkKeyboardColor.POSITIVE)

cancel_key = VkKeyboard()
cancel_key.add_button('Вернуться обратно', VkKeyboardColor.DEFAULT)

day_count = VkKeyboard()
day_count.add_button('На сегодня', VkKeyboardColor.POSITIVE)
day_count.add_button('На завтра', VkKeyboardColor.POSITIVE)


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
    return get_timetable(user_type, get_groups(user_type, user_date)[group], user_date)


def get_date(days):
    tomorrow = datetime.date.today() + datetime.timedelta(days=days)
    return tomorrow.strftime("%d-%m-%Y")


def send(user_id, msg, raw=False, keyboard=None):
    rnd = random.randint(10000000000, 99999999999)

    if raw and msg.startswith('error_') or raw is False:
        msg = _CONFIG['messages'][msg]

    if keyboard is None:
        vk.messages.send(user_id=user_id, message=msg, random_id=rnd)
    else:
        vk.messages.send(user_id=user_id, message=msg, random_id=rnd, keyboard=keyboard)

    print("* \033[95m(: \033[0m : id" + str(user_id) + " < ")


def main():
    print('run')
    for event in long_poll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me and event.text:
            if db.users.count_documents({'_id': event.user_id}) == 0:
                db.users.insert_one({
                    '_id': event.user_id,
                    'type_id': None,
                    'sub': False,
                    'group': None
                })
                send(event.user_id, 'get_user_type', keyboard=get_type.get_keyboard())
            else:
                c_user = db.users.find_one({'_id': event.user_id})
                if c_user['type_id'] is None:
                    if event.text == 'Преподователь':
                        db.users.update_one({'_id': event.user_id}, {'$set': {'type_id': 2}})
                        send(event.user_id, 'get_teacher_name', keyboard=cancel_key.get_keyboard())
                    elif event.text == 'Студент':
                        db.users.update_one({'_id': event.user_id}, {'$set': {'type_id': 1}})
                        send(event.user_id, 'get_student_group', keyboard=cancel_key.get_keyboard())

                else:
                    if c_user['group'] is None:
                        if event.text == 'Вернуться обратно':
                            db.users.update_one({'_id': event.user_id}, {'$set': {'type_id': None}})
                            send(event.user_id, 'get_user_type', keyboard=get_type.get_keyboard())

                        elif event.text.upper() in get_groups(c_user['type_id'], get_date(0)) \
                                or event.text.upper() in get_groups(c_user['type_id'], get_date(1)) \
                                or event.text.upper() in get_groups(c_user['type_id'], get_date(2)):
                            db.users.update_one({'_id': event.user_id}, {'$set': {'group': event.text}})
                            send(event.user_id, 'success_add', keyboard=day_count.get_keyboard())

                        else:
                            send(event.user_id, 'error_group_not_found')
                    else:
                        if event.text.startswith('!'):
                            args = event.text[1:].split()
                            if len(args) == 2:
                                send(event.user_id, get_table(1, args[1], args[0].upper()), raw=True)
                            else:
                                send(event.user_id, 'error_lack_of_args')
                        elif event.text.lower() == 'инфо':
                            send(event.user_id, 'info')
                        elif event.text == 'На сегодня':
                            send(event.user_id, get_table(c_user['type_id'], get_date(0), c_user['group']),
                                 raw=True)
                        elif event.text == 'На завтра':
                            send(event.user_id,
                                 get_table(c_user['type_id'], get_date(1), c_user['group']), raw=True)
                        elif event.text.lower() == 'удалить':
                            db.users.delete_one({'_id': event.user_id})
                            send(event.user_id, 'start', keyboard=start_kbd.get_keyboard())
                        else:
                            send(event.user_id, 'error_command_not_found')


if __name__ == '__main__':
    main()

