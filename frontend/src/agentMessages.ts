import { translate } from "./i18n";

type TranslationKey = Parameters<typeof translate>[1];

const AGENT_ERROR_PREFIX = "AGENT_ERROR:";

// The runtime reports failures as stable codes so raw exception text and tool-protocol
// internals never reach the chat; the UI owns the wording in the user's language.
const AGENT_ERROR_KEYS: Record<string, TranslationKey> = {
  DANGEROUS_TOOLS_DISABLED: "errorDangerousToolsDisabled",
  FILE_SCOPE_BLOCKED: "errorFileScopeBlocked",
  INTERPRETER_BLOCKED: "errorInterpreterBlocked",
  ACTION_BLOCKED: "errorActionBlocked",
  TOOL_NOT_ALLOWED: "errorToolNotAllowed",
  MODEL_OUTPUT_UNUSABLE: "errorModelOutputUnusable",
  ACTION_INVALID: "errorActionInvalid",
  PATH_NOT_FOUND: "errorPathNotFound",
  ACTION_TIMEOUT: "errorActionTimeout",
  RUNTIME_ERROR: "errorRuntime",
};

export function agentText(message: string, t: (key: TranslationKey) => string): string {
  if (!message.startsWith(AGENT_ERROR_PREFIX)) return message;
  const key = AGENT_ERROR_KEYS[message.slice(AGENT_ERROR_PREFIX.length).trim()];
  return key ? t(key) : t("errorRuntime");
}
