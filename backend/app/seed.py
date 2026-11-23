from datetime import datetime, timezone
import hashlib

from app.db import 连接


def _业务指纹(卡号, 进站站点键, 出站站点键, 进站事件时, 出站事件时) -> str:
    料 = "|".join([卡号 or "", 进站站点键 or "", 出站站点键 or "", 进站事件时 or "", 出站事件时 or ""])
    return "fp-" + hashlib.sha256(料.encode("utf-8")).hexdigest()

建表 = """
CREATE TABLE IF NOT EXISTS 站规 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 线路 (
  线路键 TEXT PRIMARY KEY,
  名称 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 站点 (
  站点键 TEXT PRIMARY KEY,
  线路键 TEXT NOT NULL REFERENCES 线路(线路键),
  站名 TEXT NOT NULL,
  站序 INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS 刷卡点 (
  事件编号 TEXT PRIMARY KEY,
  卡号 TEXT NOT NULL,
  站点键 TEXT NOT NULL,
  方向 TEXT NOT NULL,
  事件时 TEXT NOT NULL,
  处理时 TEXT NOT NULL,
  命运 TEXT NOT NULL DEFAULT '已入流',
  行程键 TEXT NOT NULL DEFAULT '',
  批次编号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 装载批次 (
  编号 TEXT PRIMARY KEY,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 开腿账 (
  开腿键 TEXT PRIMARY KEY,
  卡号 TEXT NOT NULL,
  进站事件编号 TEXT NOT NULL,
  进站站点键 TEXT NOT NULL,
  进站事件时 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '在途',
  更新处理时 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 行程账 (
  行程键 TEXT PRIMARY KEY,
  卡号 TEXT NOT NULL,
  进站事件编号 TEXT NOT NULL,
  出站事件编号 TEXT NOT NULL,
  进站站点键 TEXT NOT NULL,
  出站站点键 TEXT NOT NULL,
  进站事件时 TEXT NOT NULL,
  出站事件时 TEXT NOT NULL,
  历时秒 INTEGER NOT NULL DEFAULT 0,
  状态 TEXT NOT NULL DEFAULT '已成对',
  版本 INTEGER NOT NULL DEFAULT 1,
  处理时 TEXT NOT NULL,
  幂等指纹 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 旁路匣 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  原因 TEXT NOT NULL,
  卡号 TEXT NOT NULL DEFAULT '',
  事件编号 TEXT NOT NULL DEFAULT '',
  载荷 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 行程贯验 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  时刻 TEXT NOT NULL,
  刷卡数 INTEGER NOT NULL,
  行程数 INTEGER NOT NULL,
  开腿数 INTEGER NOT NULL,
  旁路数 INTEGER NOT NULL,
  是否通过 INTEGER NOT NULL,
  说明 TEXT NOT NULL
);
"""


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def 初始化库() -> None:
    conn = 连接()
    conn.executescript(建表)
    _迁移行程幂等(conn)
    if conn.execute("SELECT COUNT(*) AS c FROM 站规").fetchone()["c"] == 0:
        for k, v in {
            "站名": "闸对",
            "最大行程秒": "7200",
            "同站进出": "允许",
            "重复进站策略": "旧腿旁路并开新腿",
            "配对策略": "同卡先进后出",
            "骨架": "刷卡点装载→同卡进站出站成对物化→缺腿异向超时旁路→行程账与刷卡点互证",
        }.items():
            conn.execute("INSERT INTO 站规(键, 值) VALUES (?, ?)", (k, v))
    if conn.execute("SELECT COUNT(*) AS c FROM 线路").fetchone()["c"] == 0:
        conn.execute("INSERT INTO 线路(线路键, 名称) VALUES (?, ?)", ("线1", "一号线"))
        for i, (k, n) in enumerate(
            [("站A", "城东站"), ("站B", "中心站"), ("站C", "河西站")], start=1
        ):
            conn.execute(
                "INSERT INTO 站点(站点键, 线路键, 站名, 站序) VALUES (?,?,?,?)",
                (k, "线1", n, i),
            )
    conn.commit()
    conn.close()


def _迁移行程幂等(conn) -> None:
    """旧库补 幂等指纹 列并回填，再建唯一索引（行程账唯一约束的最终防线）。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(行程账)")}
    if "幂等指纹" not in cols:
        conn.execute("ALTER TABLE 行程账 ADD COLUMN 幂等指纹 TEXT NOT NULL DEFAULT ''")
    行 = conn.execute(
        "SELECT 行程键,卡号,进站站点键,出站站点键,进站事件时,出站事件时,幂等指纹 FROM 行程账"
    ).fetchall()
    for r in 行:
        if not r["幂等指纹"]:
            fp = _业务指纹(r["卡号"], r["进站站点键"], r["出站站点键"], r["进站事件时"], r["出站事件时"])
            conn.execute("UPDATE 行程账 SET 幂等指纹=? WHERE 行程键=?", (fp, r["行程键"]))
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS 行程账_幂等指纹_唯一 ON 行程账(幂等指纹)"
    )
    conn.commit()
