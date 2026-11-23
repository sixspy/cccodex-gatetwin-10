"""行程键幂等（主链落地，全局唯一口径：乙 —— 行程键/进出业务对幂等）。

设计取舍（全局只贯彻此一种）：
- 不采用「甲：事件编号全局幂等」。事件编号幂等只作为*同批重放*的第一道闸，
  行程的唯一性不依附事件编号唯一。
- 采用「乙：行程键（进站事件编号+出站事件编号）所代表的进出业务对幂等」。
  幂等指纹取业务身份字段（卡号/进站站点键/出站站点键/进站事件时/出站事件时），
  与事件编号解耦：复制进出业务对、只改事件编号再装载，命中同一指纹 → 不写第二行程。
- 探测与插入必须同成败：装载在单库事务（BEGIN IMMEDIATE）内先探测后插入，
  行程账对幂等指纹建唯一索引做最终防线；幂等写入用 INSERT OR IGNORE + 回读，
  并发双装下二者一成一对、败则整批回滚，不留半截幽灵行程、不双行程并存。

对外：
- 业务指纹(...)        幂等键推导
- 探测行程(...)        只读探测：命中行程或跳过
- 幂等写行程(...)      探测+插入合一的写闸（同成败）
- 拦重复出站(...)      装载侧出站前的行程键去重拦截
- 幂等态(...)          只读接口载荷（探测键/命中/跳过/幽灵行程计数/valid）
"""

import hashlib
import json

from app.seed import 此刻

NAME = "行程键幂等"

# 幽灵行程：行程账里存在、却找不齐两笔「已成对且同行程键同票」刷卡点的行程
幽灵查询 = """
SELECT t.行程键 FROM 行程账 t
WHERE NOT EXISTS (
  SELECT 1 FROM 刷卡点 s
  WHERE s.事件编号=t.进站事件编号 AND s.命运='已成对' AND s.行程键=t.行程键
    AND s.卡号=t.卡号 AND s.方向='进站'
)
OR NOT EXISTS (
  SELECT 1 FROM 刷卡点 s
  WHERE s.事件编号=t.出站事件编号 AND s.命运='已成对' AND s.行程键=t.行程键
    AND s.卡号=t.卡号 AND s.方向='出站'
)
"""


def 业务指纹(卡号: str, 进站站点键: str, 出站站点键: str, 进站事件时: str, 出站事件时: str) -> str:
    """进出业务对幂等键：只认业务身份，不含事件编号/处理时/批次。

    改事件编号保留同进出业务对再装 → 同指纹 → 必须挡下第二行程。
    """
    料 = "|".join([卡号 or "", 进站站点键 or "", 出站站点键 or "", 进站事件时 or "", 出站事件时 or ""])
    return "fp-" + hashlib.sha256(料.encode("utf-8")).hexdigest()


def 探测行程(conn, *, 指纹: str = "", 进站事件编号: str = "", 出站事件编号: str = "",
             业务: dict | None = None) -> dict:
    """只读探测。三种键任一：指纹 / 进站+出站事件编号（行程键）/ 业务字段。

    返回：探测键、命中与否、命中行程（或 None）、是否跳过、幽灵行程计数、valid。
    """
    业务 = 业务 or {}
    if not 指纹 and (进站事件编号 or 出站事件编号):
        指纹 = _指纹自事件(conn, 进站事件编号, 出站事件编号)
    if not 指纹 and 业务 and any(业务.values()):
        指纹 = 业务指纹(
            业务.get("卡号", ""), 业务.get("进站站点键", ""), 业务.get("出站站点键", ""),
            业务.get("进站事件时", ""), 业务.get("出站事件时", ""),
        )

    命中 = None
    if 指纹:
        命中 = conn.execute(
            "SELECT * FROM 行程账 WHERE 幂等指纹=? LIMIT 1", (指纹,)
        ).fetchone()
    if 命中 is None and 进站事件编号 and 出站事件编号:
        命中 = conn.execute(
            "SELECT * FROM 行程账 WHERE 进站事件编号=? AND 出站事件编号=? LIMIT 1",
            (进站事件编号, 出站事件编号),
        ).fetchone()

    幽灵数 = conn.execute(f"SELECT COUNT(*) AS c FROM ({幽灵查询})").fetchone()["c"]
    重指纹 = conn.execute(
        "SELECT 幂等指纹, COUNT(*) AS c FROM 行程账 GROUP BY 幂等指纹 HAVING c > 1"
    ).fetchall()
    命中行 = dict(命中) if 命中 is not None else None
    valid = (幽灵数 == 0 and not 重指纹 and (命中 is None or bool(命中行)))
    return {
        "口径": "乙-行程键(进出业务对)幂等",
        "探测键": 指纹 or "",
        "命中": 命中 is not None,
        "行程": 命中行,
        "跳过": 命中 is not None,
        "幽灵行程计数": 幽灵数,
        "重复指纹组数": len(重指纹),
        "valid": bool(valid),
    }


def 幂等写行程(conn, *, 行程键: str, 卡号: str, 进站事件编号: str, 出站事件编号: str,
               进站站点键: str, 出站站点键: str, 进站事件时: str, 出站事件时: str,
               历时秒: int, 处理时: str) -> tuple[str, bool]:
    """探测+插入合一的写闸。返回 (行程键, 是否新建)。

    INSERT OR IGNORE 靠幂等指纹唯一索引收口并发：竞争败者回读到胜者行程，
    不抛唯一约束异常、不写第二行；调用方与刷卡点更新在同一事务内同成败。
    """
    指纹 = 业务指纹(卡号, 进站站点键, 出站站点键, 进站事件时, 出站事件时)
    cur = conn.execute(
        """INSERT OR IGNORE INTO 行程账(行程键,卡号,进站事件编号,出站事件编号,进站站点键,出站站点键,
           进站事件时,出站事件时,历时秒,状态,版本,处理时,幂等指纹)
           VALUES (?,?,?,?,?,?,?,?,?,'已成对',1,?,?)""",
        (行程键, 卡号, 进站事件编号, 出站事件编号, 进站站点键, 出站站点键,
         进站事件时, 出站事件时, 历时秒, 处理时, 指纹),
    )
    if cur.rowcount == 1:
        return 行程键, True
    既有 = conn.execute(
        "SELECT 行程键, 幂等指纹 FROM 行程账 WHERE 幂等指纹=? LIMIT 1", (指纹,)
    ).fetchone()
    if 既有 is not None:
        return 既有["行程键"], False
    # 非指纹冲突（同行程键主键）：回读既有行，同样不双写
    同键 = conn.execute(
        "SELECT 行程键 FROM 行程账 WHERE 行程键=? LIMIT 1", (行程键,)
    ).fetchone()
    if 同键 is not None:
        return 同键["行程键"], False
    raise RuntimeError(f"行程幂等写入异常：INSERT OR IGNORE 未建行且无既有行程 {行程键}")


def 拦重复出站(conn, 开腿, 出站事件编号: str, 出站站点键: str, 出站事件时: str) -> dict | None:
    """出站成对前的行程键去重探测。命中既有业务对 → 返回命中行程，否则 None。"""
    指纹 = 业务指纹(
        开腿["卡号"], 开腿["进站站点键"], 出站站点键,
        开腿["进站事件时"], 出站事件时,
    )
    行 = conn.execute(
        "SELECT * FROM 行程账 WHERE 幂等指纹=? LIMIT 1", (指纹,)
    ).fetchone()
    return dict(行) if 行 is not None else None


def 幂等态(conn) -> dict:
    """只读总览：探测口径、拦截计数、幽灵行程、valid。供只读接口与贯验协同。"""
    幽灵 = conn.execute(f"SELECT COUNT(*) AS c FROM ({幽灵查询})").fetchone()["c"]
    重 = conn.execute(
        "SELECT COUNT(*) AS c FROM (SELECT 幂等指纹 FROM 行程账 GROUP BY 幂等指纹 HAVING COUNT(*)>1)"
    ).fetchone()["c"]
    拦截 = conn.execute(
        "SELECT COUNT(*) AS c FROM 旁路匣 WHERE 原因='行程幂等重复'"
    ).fetchone()["c"]
    行程数 = conn.execute("SELECT COUNT(*) AS c FROM 行程账").fetchone()["c"]
    return {
        "口径": "乙-行程键(进出业务对)幂等",
        "行程数": 行程数,
        "幂等拦截数": 拦截,
        "幽灵行程计数": 幽灵,
        "重复指纹组数": 重,
        "valid": 幽灵 == 0 and 重 == 0,
        "时刻": 此刻(),
    }


def 记旁路(conn, 原因: str, 卡号: str, 事件编号: str, 载荷: dict, 处理时: str) -> None:
    conn.execute(
        "INSERT INTO 旁路匣(原因, 卡号, 事件编号, 载荷, 时刻) VALUES (?,?,?,?,?)",
        (原因, 卡号, 事件编号, json.dumps(载荷, ensure_ascii=False), 处理时),
    )


def _指纹自事件(conn, 进站事件编号: str, 出站事件编号: str) -> str:
    if not (进站事件编号 and 出站事件编号):
        return ""
    行 = conn.execute(
        "SELECT 幂等指纹 FROM 行程账 WHERE 进站事件编号=? AND 出站事件编号=? LIMIT 1",
        (进站事件编号, 出站事件编号),
    ).fetchone()
    return 行["幂等指纹"] if 行 else ""
