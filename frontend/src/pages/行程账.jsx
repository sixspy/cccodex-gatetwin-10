import React, { useEffect, useState } from "react";
import { 取 } from "../api.js";

export default function 行程账() {
  const [行, 设] = useState([]);
  const [态, 设态] = useState(null);
  const 刷 = () => {
    取("/行程账").then(设);
    取("/行程幂等/态").then(设态);
  };
  useEffect(() => { 刷(); }, []);
  return (
    <div>
      <h1 className="题">行程账</h1>
      <p className="述">进站+出站成对后的正式行程。贯验时与两笔刷卡点互证；幂等指纹唯一，同进出业务对不得双写。</p>
      {态 && (
        <div className="提示条">
          {态.口径}：幂等拦截 <strong>{态.幂等拦截数}</strong> · 幽灵行程{" "}
          <strong>{态.幽灵行程计数}</strong> · 重复指纹组 <strong>{态.重复指纹组数}</strong> ·{" "}
          <span className={`徽章 ${态.valid ? "通" : "败"}`}>{态.valid ? "valid" : "破裂"}</span>
        </div>
      )}
      <div className="行"><button className="次" onClick={刷}>刷新</button></div>
      {!行.length ? <div className="空态">暂无行程。先灌成对样例。</div> : (
        <table>
          <thead>
            <tr><th>行程键</th><th>卡号</th><th>进→出</th><th>进站时</th><th>出站时</th><th>历时秒</th><th>状态</th><th>幂等指纹</th></tr>
          </thead>
          <tbody>
            {行.map((r) => (
              <tr key={r.行程键}>
                <td>{r.行程键}</td><td>{r.卡号}</td>
                <td>{r.进站站点键}→{r.出站站点键}</td>
                <td>{r.进站事件时}</td><td>{r.出站事件时}</td>
                <td>{r.历时秒}</td><td>{r.状态}</td>
                <td className="讯" style={{ wordBreak: "break-all", maxWidth: 180 }}>{r.幂等指纹}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
