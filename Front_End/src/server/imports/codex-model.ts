/** Narrow Responses transport for a host-owned, isolated Codex task. */
export function codexModelRequest(value: unknown, trustedOutputCap?: number) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw Error("Invalid request");
  const body = value as Record<string, unknown>;
  if (body.model !== "gpt-6.1-sol" || body.stream !== true || !Array.isArray(body.input) ||
      (body.instructions !== undefined && typeof body.instructions !== "string") || (body.tools !== undefined && !Array.isArray(body.tools))) throw Error("Invalid Codex model contract");
  const validateTools = (tools: unknown, depth = 0) => {
    if (!Array.isArray(tools) || tools.length > 512 || depth > 3) throw Error("Invalid tool definitions");
    for (const tool of tools) {
      if (!tool || typeof tool !== "object" || !["function", "custom", "namespace"].includes(tool.type))
        throw Error("Only local Codex tools are supported");
      if (tool.type === "namespace") validateTools(tool.tools, depth + 1);
    }
  };
  if (body.tools !== undefined) validateTools(body.tools);
  let outputCap = 24000;
  if (trustedOutputCap !== undefined) {
    if (!Number.isSafeInteger(trustedOutputCap) || trustedOutputCap < 1 || trustedOutputCap > 24000) throw Error("Invalid trusted token cap");
    if (!Number.isSafeInteger(body.max_output_tokens) || (body.max_output_tokens as number) < 1) throw Error("Missing task output remainder");
    outputCap = Math.min(trustedOutputCap, body.max_output_tokens as number);
  }
  for (const item of body.input) if (item?.type === "additional_tools") validateTools(item.tools);
  // No upstream URL, auth, callbacks, background work or persistence delegated.
  return {
    model: "gpt-6.1-sol", stream: true, store: false,
    ...(body.instructions !== undefined ? { instructions: body.instructions } : {}), input: body.input,
    ...(body.tools !== undefined ? { tools: body.tools } : {}),
    ...(body.tool_choice !== undefined ? { tool_choice: body.tool_choice } : {}),
    include: ["reasoning.encrypted_content"], parallel_tool_calls: false,
    reasoning: { effort: "high", summary: "auto" }, max_output_tokens: outputCap,
  };
}

export function codexCompactionRequest(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw Error("Invalid compaction");
  const body = value as Record<string, unknown>;
  if (body.model !== "gpt-6.1-sol" || !Array.isArray(body.input) ||
      (body.instructions !== undefined && typeof body.instructions !== "string")) throw Error("Invalid compaction");
  return { model: "gpt-6.1-sol", input: body.input,
    ...(body.instructions !== undefined ? { instructions: body.instructions } : {}) };
}
