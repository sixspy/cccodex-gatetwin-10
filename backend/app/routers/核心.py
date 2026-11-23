import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import 夹具目录, 连接
from app.services import 装载, 贯验, 目录
from app.modules import 行程键幂等

路由 = APIRouter(prefix="/api")


class 装载请求(BaseModel):
    批次编号: str = ""
    事件: list = Field(default_factory=list)


@路由.get("/健康")
def 健康():
    return {
        "正常": True,
        "项目": "闸对",
        "骨架": "刷卡点装载→同卡进站出站成对物化→缺腿异向超时旁路→行程账与刷卡点互证",
    }


@路由.get("/总览")
def 取总览():
    return 目录.总览()


@路由.get("/站规")
def 站规():
    conn = 连接()
    try:
        return {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 站规")}
    finally:
        conn.close()


@路由.get("/线路")
def 列线路():
    conn = 连接()
    try:
        lines = [dict(r) for r in conn.execute("SELECT * FROM 线路 ORDER BY 线路键")]
        for ln in lines:
            ln["站点"] = [
                dict(s)
                for s in conn.execute(
                    "SELECT * FROM 站点 WHERE 线路键=? ORDER BY 站序", (ln["线路键"],)
                )
            ]
        return lines
    finally:
        conn.close()


@路由.get("/刷卡点")
def 列刷卡(命运: str = ""):
    conn = 连接()
    try:
        if 命运:
            rows = conn.execute(
                "SELECT * FROM 刷卡点 WHERE 命运=? ORDER BY 事件时 DESC LIMIT 200",
                (命运,),
            )
        else:
            rows = conn.execute("SELECT * FROM 刷卡点 ORDER BY 事件时 DESC LIMIT 200")
        return [dict(r) for r in rows]
    finally:
        conn.close()


@路由.get("/开腿账")
def 列开腿(状态: str = ""):
    conn = 连接()
    try:
        if 状态:
            rows = conn.execute(
                "SELECT * FROM 开腿账 WHERE 状态=? ORDER BY 进站事件时 DESC", (状态,)
            )
        else:
            rows = conn.execute("SELECT * FROM 开腿账 ORDER BY 进站事件时 DESC")
        return [dict(r) for r in rows]
    finally:
        conn.close()


@路由.get("/行程账")
def 列行程():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 行程账 ORDER BY 处理时 DESC LIMIT 200")]
    finally:
        conn.close()


@路由.get("/行程幂等/探测")
def 探测行程幂等(
    进站事件编号: str = "",
    出站事件编号: str = "",
    卡号: str = "",
    进站站点键: str = "",
    出站站点键: str = "",
    进站事件时: str = "",
    出站事件时: str = "",
):
    """行程幂等只读接口：探测键、命中行程或跳过、幽灵行程计数、valid。

    两种探测方式：
    - 进站事件编号+出站事件编号（行程键对）
    - 卡号+进出站点+进出事件时（进出业务对，口径乙，与事件编号解耦）
    """
    业务 = {
        "卡号": 卡号,
        "进站站点键": 进站站点键,
        "出站站点键": 出站站点键,
        "进站事件时": 进站事件时,
        "出站事件时": 出站事件时,
    }
    conn = 连接()
    try:
        return 行程键幂等.探测行程(
            conn,
            进站事件编号=进站事件编号,
            出站事件编号=出站事件编号,
            业务=业务,
        )
    finally:
        conn.close()


@路由.get("/行程幂等/态")
def 行程幂等态():
    """只读总览：口径、幂等拦截数、幽灵行程计数、重复指纹组、valid。"""
    conn = 连接()
    try:
        return 行程键幂等.幂等态(conn)
    finally:
        conn.close()


@路由.get("/旁路匣")
def 列旁路():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 旁路匣 ORDER BY 编号 DESC LIMIT 100")]
    finally:
        conn.close()


@路由.get("/批次")
def 列批次():
    conn = 连接()
    try:
        out = []
        for r in conn.execute("SELECT * FROM 装载批次 ORDER BY 时刻 DESC LIMIT 30"):
            d = dict(r)
            try:
                d["报告"] = json.loads(d["报告"])
            except Exception:
                pass
            out.append(d)
        return out
    finally:
        conn.close()


@路由.post("/装载")
def 做装载(体: 装载请求):
    return 装载.装一批(体.model_dump())


@路由.post("/装载/夹具")
def 装夹具(名: str = "成对样例"):
    路径 = 夹具目录 / f"{名}.json"
    if not 路径.exists():
        raise HTTPException(404, f"夹具不存在:{名}")
    return 装载.装一批(json.loads(路径.read_text(encoding="utf-8")))


@路由.post("/贯验")
def 做贯验():
    return 贯验.跑贯验()


@路由.get("/贯验")
def 列贯验():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 行程贯验 ORDER BY 编号 DESC LIMIT 20")]
    finally:
        conn.close()


@路由.get("/空桩")
def 列空桩():
    from pathlib import Path
    import importlib

    root = Path(__file__).resolve().parent.parent / "modules"
    names = sorted(
        p.name for p in root.iterdir() if p.is_dir() and (p / "__init__.py").exists()
    )
    out = []
    for n in names:
        try:
            m = importlib.import_module(f"app.modules.{n}")
            out.append({"名": n, "导出": getattr(m, "NAME", n)})
        except Exception as e:
            out.append({"名": n, "错误": str(e)})
    return out
