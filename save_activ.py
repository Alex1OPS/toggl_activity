from TogglPy import Toggl
import json
import datetime
import cx_Oracle

MILSEC_FACTOR = 1000


def main():
    toggl = Toggl()
    toggl.setAPIKey("")
    workspace_id = toggl.getWorkspaces()[0]['id']
    since_dt = datetime.date.today().strftime("%Y-%m-%d")
    until_dt = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    data = {
        'workspace_id': workspace_id,  # see the next example for getting a workspace id
        'since': since_dt,
        'until': until_dt,
    }
    detail_info_arr = toggl.getDetailedReport(data)
    arr_real_active = [[i['description'], i['dur'] / datetime.timedelta(hours=1).total_seconds() / MILSEC_FACTOR] for i
                       in detail_info_arr['data']]

    for i in arr_real_active:
        print(i)


if __name__ == '__main__':
    main()
