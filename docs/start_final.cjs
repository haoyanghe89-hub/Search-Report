const base="http://127.0.0.1:8000";
const title="谷歌Gemini 4 Argon实际能力与官方宣称是否相符";
const payload={
  title,
  event_description:"谷歌2026年9月30日发布的Gemini 4 Argon：其编程、金融、法律基准领先是否经第三方实测验证？单次输出破百万token、推广价约竞品五分之一的真实性价比如何？存在哪些缺口与争议？",
  investigation_goal:`围绕“${title}”检索公开资料，梳理事实与背景，交叉验证关键说法，明确争议和证据缺口。`,
  questions:[
    "Gemini 4 Argon官方宣称的编程、金融、法律基准领先具体是哪些数据？",
    "是否有第三方独立实测复现这些基准，结论与官方是否一致？",
    "百万token级单次输出与约竞品五分之一的定价，真实性价比与限制如何？",
    "有哪些相互矛盾的说法、反证、缺口或尚未解决的问题？",
  ],
};
(async()=>{
  const c=await fetch(base+"/api/investigations",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
  const created=await c.json();
  console.log("INV",created.investigation_id);
  const r=await fetch(base+`/api/investigations/${created.investigation_id}/runs`,{method:"POST"});
  const run=await r.json();
  console.log("RUN",run.run_id, r.status);
})();
