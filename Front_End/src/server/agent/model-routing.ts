/** Conservative task classification; source text cannot select a model directly. */
export const MODEL_ROUTING_VERSION = "arsia-task-routing-v1";
export type ModelRoute = {
  policy: typeof MODEL_ROUTING_VERSION;
  taskClass: "simple_question" | "standard_query" | "reasoning" | "research" | "source_onboarding";
  model: "gpt-5.6-terra" | "gpt-6.1-sol";
  reasoningEffort: "high";
  reason: string;
};
export function routeModel(task: {
  surface: "ask" | "studio" | "imports";
  message?: string;
  historyCount?: number;
  source?: string;
}): ModelRoute {
  const base = { policy: MODEL_ROUTING_VERSION, reasoningEffort: "high" as const } as const;
  const sol = (taskClass: ModelRoute["taskClass"], reason: string): ModelRoute =>
    ({ ...base, taskClass, model: "gpt-6.1-sol", reason });
  if (task.surface === "imports") return sol("source_onboarding", "Source semantics, evidence and adapter correctness require reasoning");
  if (task.surface === "studio") return sol("research", "Persistent studies require multi-step analysis");
  const text = (task.message || "").trim().replace(/^(?:请问|请帮我|请|麻烦|please\s+|can you\s+|could you\s+)/i, "").trim();
  if (task.historyCount) return sol("reasoning", "Follow-up interpretation depends on prior context");
  if (text.length > 180 || /比较|对比|原因|为什么|变化|增加|减少|上升|下降|趋势|同比|环比|相关|预测|建议|异常|解释|计算|分析|报告|排名|风险|比例|百分比|平均|均值|中位|标准差|置信|分布|概率|差异|同时|然后|以及|并且|\b(compare|comparison|versus|vs|why|average|median|deviation|rate|distribution|confidence|explain|trend|change|increase|decrease|cause|best|safest|correlat\w*|predict\w*|recommend\w*|analy[sz]\w*|report|rank\w*|risk|percent\w*|ratio|difference|calculate|and|then)\b/i.test(text))
    return sol("reasoning", "Comparison, explanation, calculation or multiple requirements");
  if (/^(你好|您好|谢谢|hi|hello|thanks)[！!。.\s]*$/i.test(text) ||
      /^(什么是|[^\n？?]{1,40}是什么意思|what (?:is|does) .*(?:mean|definition)|define\b)/i.test(text))
    return { ...base, taskClass:"simple_question", model:"gpt-5.6-terra", reason:"Short greeting or single definition" };
  if (task.source === "ALL" || task.source === "All" || task.source === "all" || /所有州|各州|全国|\ball (?:states|sources)\b/i.test(text))
    return sol("reasoning", "Multiple source definitions require separate interpretation");
  if ((/^(?:有多少|多少|总共|共有|查看|显示|列出|how many\b|(?:show|list|what is|what are)\b)/i.test(text) ||
      /(?:事故|死亡|伤亡|记录).{0,12}(?:多少|总数|数量)[？?\s]*$/.test(text)) && /crash|fatal|casualt|count|total|coverage|record|column|dataset|source|date|事故|死亡|伤亡|人数|总数|数量|字段|覆盖|日期|版本|数据源/i.test(text))
    return { ...base, taskClass:"standard_query", model:"gpt-5.6-terra", reason:"Short single-source count or lookup without reasoning markers" };
  return sol("reasoning", "Unclassified intent defaults to the reasoning model");
}
