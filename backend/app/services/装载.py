import json
import sqlite3

from app.db import 连接
from app.seed import 此刻
from app.services import 时间, 配对
from app.modules import 行程键幂等


def 装一批(体: dict) -> dict:
    """装载入口：写锁竞争时有限重试，败者重放后由幂等闸收敛（不报错、不双写）。"""
    末次错 = None
    for _ in range(3):
        conn = 连接()
        try:
            return _事务装一批(conn, 体)
        except sqlite3.OperationalError as e:
            末次错 = e
            if "locked" not in str(e).lower():
                raise
            continue
        finally:
            conn.close()
    raise 末次错


def _事务装一批(conn, 体: dict) -> dict:
    """装载刷卡点：同卡进站开腿、出站成对；缺腿超时/孤儿旁路；行程键幂等。

    口径（全局唯一：乙-行程键/进出业务对幂等）：
    - 整批在单库事务（BEGIN IMMEDIATE）内完成：探测与插入同成败，
      异常即 rollback，杜绝半截幽灵行程与两键脏写。
    - 事件编号已存在 → 整事件跳过（同批重放闸），不产生任何写入。
    - 出站成对前先按进出业务对指纹探测：命中既有行程 → 本次新进站+新出站
      整体旁路（行程幂等重复），不写第二行程；改事件编号同业务对同样被挡。
    - 行程账对幂等指纹有唯一索引兜底，并发双装下竞争败者回读胜者行程。
    """
    批次编号 = 体.get("批次编号") or f"批-{此刻().replace(':', '').replace('-', '')}"
    事件列表 = 体.get("事件") or []
    try:
        # 立即拿写锁：并发双装在入口串行化，配合唯一索引，胜者全成、败者整体重放/回滚
        conn.execute("BEGIN IMMEDIATE")
        报告 = {
            "批次编号": 批次编号,
            "入流": 0,
            "开腿": 0,
            "成对": 0,
            "旁路": 0,
            "超时旁路": 0,
            "事件幂等跳过": 0,
            "行程幂等跳过": 0,
            "明细": [],
        }
        站 = {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 站规")}
        最大行程秒 = int(站.get("最大行程秒", "7200"))
        水位 = None

        for ev in 事件列表:
            事件编号 = ev["事件编号"]
            卡号 = ev["卡号"]
            站点键 = ev["站点键"]
            方向 = ev["方向"]
            事件时 = ev["事件时"]
            处理时 = ev.get("处理时") or 此刻()

            if 水位 is None or 时间.解析(事件时) > 时间.解析(水位):
                水位 = 事件时

            # 第一道闸：事件编号全局幂等（只管同事件重放，不承载行程唯一性）
            if conn.execute("SELECT 1 FROM 刷卡点 WHERE 事件编号=?", (事件编号,)).fetchone():
                报告["事件幂等跳过"] += 1
                报告["明细"].append({"事件编号": 事件编号, "命运": "幂等跳过"})
                continue

            站行 = conn.execute("SELECT * FROM 站点 WHERE 站点键=?", (站点键,)).fetchone()
            if not 站行:
                conn.execute(
                    "INSERT INTO 旁路匣(原因, 卡号, 事件编号, 载荷, 时刻) VALUES (?,?,?,?,?)",
                    ("未知站点", 卡号, 事件编号, json.dumps(ev, ensure_ascii=False), 处理时),
                )
                conn.execute(
                    """INSERT INTO 刷卡点(事件编号,卡号,站点键,方向,事件时,处理时,命运,行程键,批次编号)
                       VALUES (?,?,?,?,?,?, '已旁路', '', ?)""",
                    (事件编号, 卡号, 站点键, 方向, 事件时, 处理时, 批次编号),
                )
                报告["旁路"] += 1
                报告["入流"] += 1
                报告["明细"].append({"事件编号": 事件编号, "命运": "旁路-未知站"})
                continue

            if 方向 not in ("进站", "出站"):
                conn.execute(
                    "INSERT INTO 旁路匣(原因, 卡号, 事件编号, 载荷, 时刻) VALUES (?,?,?,?,?)",
                    ("方向非法", 卡号, 事件编号, json.dumps(ev, ensure_ascii=False), 处理时),
                )
                conn.execute(
                    """INSERT INTO 刷卡点(事件编号,卡号,站点键,方向,事件时,处理时,命运,行程键,批次编号)
                       VALUES (?,?,?,?,?,?, '已旁路', '', ?)""",
                    (事件编号, 卡号, 站点键, 方向, 事件时, 处理时, 批次编号),
                )
                报告["旁路"] += 1
                报告["入流"] += 1
                报告["明细"].append({"事件编号": 事件编号, "命运": "旁路-方向非法"})
                continue

            conn.execute(
                """INSERT INTO 刷卡点(事件编号,卡号,站点键,方向,事件时,处理时,命运,行程键,批次编号)
                   VALUES (?,?,?,?,?,?, '已入流', '', ?)""",
                (事件编号, 卡号, 站点键, 方向, 事件时, 处理时, 批次编号),
            )
            报告["入流"] += 1

            if 方向 == "进站":
                旧 = conn.execute(
                    "SELECT * FROM 开腿账 WHERE 卡号=? AND 状态='在途'", (卡号,)
                ).fetchone()
                if 旧:
                    conn.execute(
                        "UPDATE 开腿账 SET 状态='已旁路', 更新处理时=? WHERE 开腿键=?",
                        (处理时, 旧["开腿键"]),
                    )
                    conn.execute(
                        "UPDATE 刷卡点 SET 命运=? WHERE 事件编号=?",
                        ("已旁路", 旧["进站事件编号"]),
                    )
                    conn.execute(
                        "INSERT INTO 旁路匣(原因, 卡号, 事件编号, 载荷, 时刻) VALUES (?,?,?,?,?)",
                        (
                            "重复进站",
                            卡号,
                            旧["进站事件编号"],
                            json.dumps(
                                {"旧开腿": 旧["开腿键"], "新进站": 事件编号},
                                ensure_ascii=False,
                            ),
                            处理时,
                        ),
                    )
                    报告["旁路"] += 1
                    报告["明细"].append(
                        {"事件编号": 旧["进站事件编号"], "命运": "旁路-重复进站"}
                    )

                开腿键 = f"腿-{事件编号}"
                conn.execute(
                    """INSERT INTO 开腿账(开腿键,卡号,进站事件编号,进站站点键,进站事件时,状态,更新处理时)
                       VALUES (?,?,?,?,?,'在途',?)""",
                    (开腿键, 卡号, 事件编号, 站点键, 事件时, 处理时),
                )
                conn.execute(
                    "UPDATE 刷卡点 SET 命运=? WHERE 事件编号=?",
                    ("已开腿", 事件编号),
                )
                报告["开腿"] += 1
                报告["明细"].append({"事件编号": 事件编号, "命运": "已开腿", "开腿键": 开腿键})
            else:
                开腿 = conn.execute(
                    "SELECT * FROM 开腿账 WHERE 卡号=? AND 状态='在途' ORDER BY 进站事件时 ASC LIMIT 1",
                    (卡号,),
                ).fetchone()
                if not 开腿:
                    conn.execute(
                        "UPDATE 刷卡点 SET 命运=? WHERE 事件编号=?",
                        ("已旁路", 事件编号),
                    )
                    conn.execute(
                        "INSERT INTO 旁路匣(原因, 卡号, 事件编号, 载荷, 时刻) VALUES (?,?,?,?,?)",
                        (
                            "出站孤儿",
                            卡号,
                            事件编号,
                            json.dumps(ev, ensure_ascii=False),
                            处理时,
                        ),
                    )
                    报告["旁路"] += 1
                    报告["明细"].append({"事件编号": 事件编号, "命运": "旁路-出站孤儿"})
                    continue

                # 第二道闸（行程唯一性所在）：写行程前按进出业务对指纹探测
                命中 = 行程键幂等.拦重复出站(conn, 开腿, 事件编号, 站点键, 事件时)
                if 命中:
                    # 同业务对二次装载（即便改了事件编号）：新进站+新出站整体旁路，
                    # 不写第二行程、不留幽灵；开腿不转已成对
                    for 关联事件, 关联方向 in (
                        (开腿["进站事件编号"], "进站"),
                        (事件编号, "出站"),
                    ):
                        conn.execute(
                            "UPDATE 刷卡点 SET 命运=?, 行程键=? WHERE 事件编号=?",
                            ("已旁路", 命中["行程键"], 关联事件),
                        )
                        行程键幂等.记旁路(
                            conn,
                            "行程幂等重复",
                            卡号,
                            关联事件,
                            {
                                "命中行程键": 命中["行程键"],
                                "幂等指纹": 命中["幂等指纹"],
                                "重复方向": 关联方向,
                                "出站事件编号": 事件编号,
                            },
                            处理时,
                        )
                    conn.execute(
                        "UPDATE 开腿账 SET 状态='已旁路', 更新处理时=? WHERE 开腿键=?",
                        (处理时, 开腿["开腿键"]),
                    )
                    报告["行程幂等跳过"] += 1
                    报告["旁路"] += 2
                    报告["明细"].append(
                        {
                            "事件编号": 事件编号,
                            "命运": "旁路-行程幂等重复",
                            "命中行程键": 命中["行程键"],
                        }
                    )
                    continue

                行程键, 新建 = 配对.成对写出站(
                    conn, 开腿, 事件编号, 站点键, 事件时, 处理时
                )
                if not 新建:
                    # 探测与插入之间被并发抢先的兜底：按命中既有行程收口，不双写
                    conn.execute(
                        "UPDATE 刷卡点 SET 命运=?, 行程键=? WHERE 事件编号 IN (?,?)",
                        ("已旁路", 行程键, 开腿["进站事件编号"], 事件编号),
                    )
                    行程键幂等.记旁路(
                        conn, "行程幂等重复", 卡号, 事件编号,
                        {"命中行程键": 行程键, "并发抢先": True}, 处理时,
                    )
                    报告["行程幂等跳过"] += 1
                    报告["旁路"] += 2
                    报告["明细"].append(
                        {"事件编号": 事件编号, "命运": "旁路-行程幂等重复", "命中行程键": 行程键}
                    )
                    continue
                报告["成对"] += 1
                报告["明细"].append(
                    {"事件编号": 事件编号, "命运": "已成对", "行程键": 行程键}
                )

        if 水位:
            报告["超时旁路"] = 配对.扫缺腿超时(conn, 最大行程秒, 水位, 此刻())
            报告["旁路"] += 报告["超时旁路"]

        # 批次记录同样幂等：重放/并发重入同批次编号不撞主键
        conn.execute(
            "INSERT OR IGNORE INTO 装载批次(编号, 时刻, 报告) VALUES (?,?,?)",
            (批次编号, 此刻(), json.dumps(报告, ensure_ascii=False)),
        )
        conn.commit()
        return 报告
    except Exception:
        # 探测与插入同成败：任何失败整批回滚，库内不留半截状态
        conn.rollback()
        raise
