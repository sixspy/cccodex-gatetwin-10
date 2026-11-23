import json
from app.seed import 此刻
from app.services import 时间
from app.modules import 行程键幂等


def 扫缺腿超时(conn, 最大行程秒: int, 水位事件时: str, 处理时: str) -> int:
    """水位推进后，把超最大行程秒仍在途的开腿打进旁路。"""
    n = 0
    rows = list(conn.execute("SELECT * FROM 开腿账 WHERE 状态='在途'"))
    for leg in rows:
        if 时间.差秒(leg["进站事件时"], 水位事件时) < 最大行程秒:
            continue
        conn.execute(
            "UPDATE 开腿账 SET 状态='已旁路', 更新处理时=? WHERE 开腿键=?",
            (处理时, leg["开腿键"]),
        )
        conn.execute(
            "UPDATE 刷卡点 SET 命运=? WHERE 事件编号=?",
            ("已旁路", leg["进站事件编号"]),
        )
        conn.execute(
            "INSERT INTO 旁路匣(原因, 卡号, 事件编号, 载荷, 时刻) VALUES (?,?,?,?,?)",
            (
                "缺腿超时",
                leg["卡号"],
                leg["进站事件编号"],
                json.dumps(
                    {
                        "开腿键": leg["开腿键"],
                        "进站事件时": leg["进站事件时"],
                        "水位": 水位事件时,
                        "最大行程秒": 最大行程秒,
                    },
                    ensure_ascii=False,
                ),
                处理时,
            ),
        )
        n += 1
    return n


def 成对写出站(conn, 开腿, 出站事件编号: str, 出站站点键: str, 出站事件时: str, 处理时: str) -> tuple[str, bool]:
    """探测+插入合一地写行程（同成败）。返回 (行程键, 是否新建)。

    行程幂等走行程键幂等模块：同进出业务对（改事件编号亦然）二次装载，
    INSERT OR IGNORE 被幂等指纹唯一索引挡下 → 不新建，回读既有行程键。
    """
    行程键 = f"行-{开腿['进站事件编号']}-{出站事件编号}"
    历时 = max(0, 时间.差秒(开腿["进站事件时"], 出站事件时))
    行程键, 新建 = 行程键幂等.幂等写行程(
        conn,
        行程键=行程键,
        卡号=开腿["卡号"],
        进站事件编号=开腿["进站事件编号"],
        出站事件编号=出站事件编号,
        进站站点键=开腿["进站站点键"],
        出站站点键=出站站点键,
        进站事件时=开腿["进站事件时"],
        出站事件时=出站事件时,
        历时秒=历时,
        处理时=处理时,
    )
    if 新建:
        conn.execute(
            "UPDATE 开腿账 SET 状态='已成对', 更新处理时=? WHERE 开腿键=?",
            (处理时, 开腿["开腿键"]),
        )
        conn.execute(
            "UPDATE 刷卡点 SET 命运=?, 行程键=? WHERE 事件编号 IN (?,?)",
            ("已成对", 行程键, 开腿["进站事件编号"], 出站事件编号),
        )
    return 行程键, 新建
