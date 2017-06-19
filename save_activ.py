import configparser as cfg
import datetime
import logging
import os
import sys
import sqlite3

import cx_Oracle

from TogglPy import Toggl

MILSEC_FACTOR = 1000
PATH_TO_CFG = "config.ini"
HIST_HORIZONT = 30
SCRIPT_CREATE_WORK = """
declare
    ln_user number(10) := {};
	ln_request number(10) := {};
	ln_status_work number(10) := 13;
	lf_work_dur number := {};
	ls_comment varchar2(200) := 'Отметка о затраченном времени из Toggl';
begin
  p_suza_exchange.savework_for_req(pACTION         => p_consts.FLEXY_ACTION_CREATE,
                                   pID_MANAGER     => ln_user,
                                   pPID_REQUEST    => ln_request,
                                   pID_WORKER      => ln_user,
                                   pF_TIME_SUM     => lf_work_dur,
                                   pID_STATUS      => ln_status_work,
                                   pV_WORK_COMMENT => ls_comment,
                                   pID_USER_UPD    => null,
                                   pDT_UPD         => null,
                                   pID_USER_INS    => ln_user,
                                   pDT_INS         => current_timestamp,
                                   pID_REQ_STATUS  => ID_REQ_STATUS.nextval,
                                   pID_FILE        => null,
                                   pN_PERC_WORK    => null);
end;"""


def connect_local_db(userlogin):
    conn = sqlite3.connect("lstorage_{}.db".format(userlogin))
    return conn


def local_db_init(conn):
    db_cur = conn.cursor()
    db_cur.execute('''CREATE TABLE IF NOT EXISTS synchronized_tasks
                      (task_id INTEGER PRIMARY KEY, description TEXT, duration REAL, 
                       dt_sync DATETIME DEFAULT current_timestamp)''')
    conn.commit()
    conn.close()


def get_all_synchronized_tasks(userlogin):
    conn = connect_local_db(userlogin)
    cur = conn.cursor()
    cur.execute("SELECT task_id FROM synchronized_tasks")
    results = cur.fetchall()
    conn.close()

    results = [x[0] for x in results]
    return results


def get_last_sync_date(userlogin):
    conn = connect_local_db(userlogin)
    cur = conn.cursor()
    cur.execute("SELECT max(t.dt_sync) FROM synchronized_tasks t")
    res = cur.fetchone()[0]
    conn.close()
    return res


def save_tasks_lstorage(userlogin, tasks):
    conn = connect_local_db(userlogin)
    cur = conn.cursor()
    cur.executemany("INSERT INTO synchronized_tasks VALUES (?, ?, ?, current_timestamp);", tasks)
    conn.commit()
    conn.close()


def main():
    logging.basicConfig(filename="main_.log",
                        level=logging.INFO,
                        format='[%(asctime)s][%(levelname)s] %(message)s',
                        datefmt='%m/%d/%Y %I:%M:%S',
                        filemode="a+")

    ldir = os.path.dirname(os.path.realpath(sys.argv[0]))
    config = cfg.ConfigParser()
    pth_cfg = os.path.join(ldir, PATH_TO_CFG)
    config.read(pth_cfg)
    logging.info("Путь к конфигу {}".format(pth_cfg))

    user_id = 0
    userlogin = config.get("info", "author")
    toggl = Toggl()
    toggl.setAPIKey(config.get("info", "apitoken"))
    workspace_id = toggl.getWorkspaces()[0]['id']

    # подключение к локальной бд
    local_db_init(connect_local_db(userlogin))
    synch_tasks = get_all_synchronized_tasks(userlogin)
    dt_last_sync = get_last_sync_date(userlogin)
    print("Дата последней синхронизации {}".format(dt_last_sync))
    logging.info("Дата последней синхронизации {}".format(dt_last_sync))

    # получим дату последнего успешного обновления
    if dt_last_sync is None:
        since_dt = (datetime.date.today() - datetime.timedelta(days=HIST_HORIZONT)).strftime("%Y-%m-%d")
    else:
        since_dt = dt_last_sync
    until_dt = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    data = {
        'workspace_id': workspace_id,
        'since': since_dt,
        'until': until_dt,
    }
    logging.info("Параметры: {}".format(data))
    detail_info_arr = toggl.getDetailedReport(data)
    arr_real_active = [[i['id'], i['description'], i['dur'] / datetime.timedelta(hours=1).seconds / MILSEC_FACTOR] for i
                       in detail_info_arr['data']]

    logging.info("Полученные задачи:")
    for i in arr_real_active:
        logging.info(i)
    logging.info("Начало фиксирования результатов")

    task_future_sync = []

    con = cx_Oracle.connect("support3/db@SUPDEP")
    cur = con.cursor()
    select_id_user = '''SELECT t.id_user 
                          FROM ci_users t 
                         WHERE t.b_deleted = 0 
                           AND t.v_status = :stat  
                           AND t.v_username = :userlogin'''
    select_id_request = '''SELECT sr.id_request, sr.v_number, sr.v_title 
                             FROM sup_req  sr 
                            WHERE sr.id_worker_plan = :user_id 
                              AND sr.id_mailtype IS NOT NULL 
                              AND sr.id_mailtype NOT IN (2, 5, 102, 2005, 2006, 9, 10) 
                              AND :task_name LIKE sr.v_number'''
    cur.prepare(select_id_user)
    cur.execute(None, stat='A', userlogin=userlogin)
    res = cur.fetchall()
    if len(res) == 0 or len(res) > 1:
        print("Incorrect username")
        logging.error("Incorrect user id {} for username {}".format(user_id, userlogin))
    else:
        user_id = res[0][0]
    cur.close()

    cur = con.cursor()
    for task_id, task_name, task_dur in arr_real_active:
        cur.prepare(select_id_request)
        cur.execute(None, user_id=user_id, task_name=task_name)
        res_all = cur.fetchall()
        if len(res_all) == 1 and task_id not in synch_tasks:
            res_id = res_all[0][0]
            print("Create work row in task: {}".format(res_all))
            logging.info("Create work row in task: {}".format(res_all))
            calpr = con.cursor()
            call_script_str = SCRIPT_CREATE_WORK.format(user_id, res_id, round(task_dur, 2))
            calpr.execute(call_script_str)
            calpr.close()

            task_future_sync.append((task_id, task_name, task_dur))
        else:
            logging.warning("Skip task {}".format(task_name))
    cur.close()
    con.commit()
    con.close()

    save_tasks_lstorage(userlogin, task_future_sync)
    logging.info("Завершение процесса")


if __name__ == '__main__':
    main()
