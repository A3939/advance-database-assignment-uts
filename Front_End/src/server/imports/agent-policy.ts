import { createHash } from "node:crypto";

export type ImportModelPolicy = {
  profile: string;
  catalog_sha256: string;
  model: string;
  reasoning_effort: "low" | "medium" | "high" | "xhigh";
  max_output_tokens: number;
  request_timeout_seconds: number;
};

/** Parse only the host-owned catalog. Upload/model arguments cannot set policies. */
export function selectImportModelPolicy(catalog: string, profile = "baseline-v1", expectedHash?: string): ImportModelPolicy {
  const hash = createHash("sha256").update(catalog).digest("hex");
  if (expectedHash && hash !== expectedHash) throw Error("Import policy changed since session checkpoint");
  const profiles = JSON.parse(catalog).profiles as Record<string, Record<string, unknown>>;
  const value = Object.hasOwn(profiles, profile) ? profiles[profile] : undefined;
  if (!value || typeof value.model !== "string" || !/^[a-zA-Z0-9._-]{1,100}$/.test(value.model) ||
      !["low", "medium", "high", "xhigh"].includes(String(value.reasoning_effort)) ||
      !Number.isInteger(value.max_output_tokens) || Number(value.max_output_tokens) < 1000 || Number(value.max_output_tokens) > 64000 ||
      !Number.isInteger(value.request_timeout_seconds) || Number(value.request_timeout_seconds) < 30 || Number(value.request_timeout_seconds) > 900)
    throw Error("Invalid trusted import model policy");
  return { profile, catalog_sha256: hash, model: value.model,
    reasoning_effort: value.reasoning_effort as ImportModelPolicy["reasoning_effort"],
    max_output_tokens: Number(value.max_output_tokens), request_timeout_seconds: Number(value.request_timeout_seconds) };
}
