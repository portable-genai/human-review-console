// The interface tier's three-state environment read.
//
// This is the JavaScript half of `hex_service_kit.netdefaults.read_env_setting`, and it exists
// because the Python three-state scanner walks `src`, `scripts` and `eval` only. No Python AST
// scan can see `ui/`, so the console was the one tier in this repository where a two-state read
// survived: `(process.env.REVIEW_PROFILE || "local") !== "local"` resolved a variable an operator
// had DELIBERATELY EMPTIED to the demo posture and dropped Strict-Transport-Security from every
// response, with nothing in the build or the served headers to show it.
//
// `process.env.X || default` is the JavaScript spelling of `os.environ.get(name, default)` and
// collapses the same three states into two:
//
//     unset          -> nobody expressed an intent, so a documented default may stand
//     set and empty  -> an intent WAS expressed and it names nothing, so fail closed
//     set with value -> use it
//
// The middle state is the dangerous one. Folded into the first, an emptied value inherits the
// default, and where that default is the more permissive branch (a loopback API origin widening
// connect-src, a demo profile withholding HSTS) emptying a variable OPENS the console.
//
// Note the Next.js wrinkle that makes this worse here than in the service tier: `NEXT_PUBLIC_*`
// reads are INLINED AT BUILD TIME, so an emptied value is frozen into the bundle and cannot be
// corrected by fixing the environment at start-up.

/**
 * One environment variable resolved into three states, never two.
 *
 * Exactly one of `isUnset`, `isConfiguredEmpty` and `hasValue` is true.
 *
 * @param {string | undefined} raw The raw `process.env.X`, passed in rather than read here so
 *   this works with Next's build-time inlining, which only substitutes literal member reads.
 * @param {string} name The variable's name, for refusal messages.
 * @returns {{name: string, raw: string | undefined, value: string, isUnset: boolean,
 *   isConfiguredEmpty: boolean, hasValue: boolean}}
 */
export function envSetting(raw, name) {
  const value = raw === undefined || raw === null ? "" : String(raw).trim();
  const isUnset = raw === undefined || raw === null;
  return {
    name,
    raw,
    value,
    isUnset,
    isConfiguredEmpty: !isUnset && value === "",
    hasValue: value !== "",
  };
}

/**
 * The variable's value, the reviewed default when it is unset, and a REFUSAL when it was
 * deliberately emptied.
 *
 * Refusing at config load takes the whole process down rather than one feature, which is
 * accepted and matches the service tier: a console that boots with an emptied security variable
 * serves every request under a posture nobody chose.
 *
 * @param {string | undefined} raw
 * @param {string} name
 * @param {string} fallback The documented default an UNSET variable may take.
 * @returns {string}
 */
export function settingOrDefault(raw, name, fallback) {
  const setting = envSetting(raw, name);
  if (setting.isConfiguredEmpty) {
    throw new Error(
      `${name} is set to an empty value. An emptied variable names nothing, so it cannot ` +
        `inherit the unset default (${JSON.stringify(fallback)}), which is the more permissive ` +
        `branch here. Unset it to take that default deliberately, or give it a real value.`,
    );
  }
  return setting.hasValue ? setting.value : fallback;
}
