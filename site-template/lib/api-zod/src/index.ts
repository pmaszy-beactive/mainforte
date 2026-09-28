export * from "./generated/api";
export * from "./generated/types";

// `ForgotPasswordBody`, `LoginBody`, `RegisterBody` and `ResetPasswordBody` are
// emitted both as zod schemas (./generated/api) and as TS interfaces
// (./generated/types), which makes the star re-exports ambiguous. Consumers use
// the zod schemas (`.safeParse(...)`), so explicitly re-export those to resolve it.
export {
  ForgotPasswordBody,
  LoginBody,
  RegisterBody,
  ResetPasswordBody,
} from "./generated/api";
