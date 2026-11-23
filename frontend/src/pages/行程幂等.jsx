import React, { useEffect, useState } from "react";
import { 取 } from "../api.js";

const 空业务 = { 卡号: "", 进站站点键: "", 出站站点键: "", 进站事件时: "", 出站事件时: "" };

export default function 行程幂等() {
  const [态, 设态] = useState(null);
  const [业务, 设业务] = useState(空业务);
  const [事件对, 设事件对] = useState({ 进站事件编号: "", 出站事件编号: "" });
  const [果, 设果] = useState(null);
  const [讯, 设讯] = useState("");
  const 刷态 = () => 取("/行程幂等/态").then(设态);
  useEffect(() => { 刷态(); }, []);

  const 探业务 = async () => {
    const p = new URLSearchParams(Object.entries(业务).filter(([, v]) => v));
    const r = await 取(`/行程幂等/探测?${p}`);
    设果(r);
    设讯("按进出业务对（口径乙，与事件编号解耦）探测");
  };
  const 探事件对 = async () => {
    const p = new URLSearchParams(事件对);
    const r = await 取(`/行程幂等/探测?${p}`);
    设果(r);
    设讯("按进站+出站事件编号（行程键对）探测");
  };

  return (
    <div>
      <h1 className="题">行程键幂等</h1>
      <p className="述">
        全局唯一口径：<strong>乙 —— 行程键（进站事件编号+出站事件编号）代表的进出业务对幂等</strong>。
        幂等指纹取卡号/进出站点/进出事件时，与事件编号解耦：复制进出业务对、只改事件编号再装载，
        命中同指纹，不写第二行程。探测与插入在同一事务内同成败。
      </p>

      {态 && (
        <div className="阶条">
          <div className="阶"><div className="序">行程</div><b>{态.行程数}</b><span>行程账笔数</span></div>
          <div className="阶"><div className="序">幂等拦截</div><b>{态.幂等拦截数}</b><span>重复业务对旁路</span></div>
          <div className="阶"><div className="序">幽灵行程</div><b>{态.幽灵行程计数}</b><span>缺同票刷卡</span></div>
          <div className="阶"><div className="序">重复指纹</div><b>{态.重复指纹组数}</b><span>双行程组</span></div>
          <div className="阶">
            <div className="序">valid</div>
            <b><span className={`徽章 ${态.valid ? "通" : "败"}`}>{态.valid ? "真" : "破"}</span></b>
            <span>不变量</span>
          </div>
        </div>
      )}
      <div className="行"><button className="次" onClick={刷态}>刷新幂等态</button></div>

      <h2 className="题" style={{ fontSize: "1.05rem" }}>探测①：进出业务对（改事件编号也能命中）</h2>
      <div className="行" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
        {Object.keys(空业务).map((k) => (
          <label key={k} className="讯">{k}
            <input value={业务[k]} onChange={(e) => 设业务({ ...业务, [k]: e.target.value })} />
          </label>
        ))}
        <button onClick={探业务}>按业务对探测</button>
      </div>

      <h2 className="题" style={{ fontSize: "1.05rem", marginTop: "1.2rem" }}>探测②：行程键事件对</h2>
      <div className="行" style={{ gap: "0.5rem" }}>
        <label className="讯">进站事件编号
          <input value={事件对.进站事件编号} onChange={(e) => 设事件对({ ...事件对, 进站事件编号: e.target.value })} />
        </label>
        <label className="讯">出站事件编号
          <input value={事件对.出站事件编号} onChange={(e) => 设事件对({ ...事件对, 出站事件编号: e.target.value })} />
        </label>
        <button className="次" onClick={探事件对}>按事件对探测</button>
      </div>

      {讯 && <p className="讯">{讯}</p>}
      {果 && (
        <table>
          <thead><tr><th>字段</th><th>值</th></tr></thead>
          <tbody>
            <tr><td>口径</td><td>{果.口径}</td></tr>
            <tr><td>探测键（指纹）</td><td style={{ wordBreak: "break-all" }}>{果.探测键 || "—（空键，未命中）"}</td></tr>
            <tr><td>命中 / 跳过</td><td>{果.命中 ? "命中 → 跳过，不写第二行程" : "未命中 → 可写新行程"}</td></tr>
            <tr><td>命中行程</td><td style={{ wordBreak: "break-all" }}>{果.行程 ? JSON.stringify(果.行程) : "无"}</td></tr>
            <tr><td>幽灵行程计数</td><td>{果.幽灵行程计数}</td></tr>
            <tr><td>重复指纹组数</td><td>{果.重复指纹组数}</td></tr>
            <tr><td>valid</td><td><span className={`徽章 ${果.valid ? "通" : "败"}`}>{String(果.valid)}</span></td></tr>
          </tbody>
        </table>
      )}
    </div>
  );
}
