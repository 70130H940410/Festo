"""Read the existing sync_agent tables; never synthesize per-piece locations."""
from .mes_dashboard_service import cloud_snapshot


def floor_cloud_snapshot(client, order_id=None, mes_ono=None):
    result = cloud_snapshot(client)
    result.update(order_id=order_id, mes_ono=mes_ono, order=None,
                  steps=[], steps_error=None, piece_tracking_available=False,
                  robot_tracking_available=False)
    if mes_ono is None:
        result['order_message'] = ('此訂單尚無 MES 工單對應；不使用本機模擬進度代替。'
                                   if order_id else '全廠機台狀態；可選訂單查看 MES 製程紀錄。')
        return result
    try:
        orders = (client.table('tbl_order').select('ono,state,start,end')
                  .eq('ono', mes_ono).limit(1).execute().data)
        result['order'] = orders[0] if orders else None
        # tbl_fin_step has no piece/serial identity; these are history rows,
        # not proof that a particular workpiece is currently at a station.
        result['steps'] = (client.table('tbl_fin_step')
                           .select('ono,step_no,wp_no,description,resource_id,start,end')
                           .eq('ono', mes_ono).order('step_no').execute().data or [])
        result['order_message'] = ('MES 工單與製程紀錄已讀取。' if orders
                                   else '雲端尚未找到此 MES 工單。')
    except Exception:
        result.update(order=None, steps=[], steps_error='MES 工單／製程紀錄讀取失敗。',
                      order_message='MES 工單／製程紀錄讀取失敗。', connection='degraded')
    return result
