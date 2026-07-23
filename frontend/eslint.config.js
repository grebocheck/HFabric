import js from "@eslint/js";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

const browserGlobals = {
  Blob: "readonly",
  ClipboardItem: "readonly",
  File: "readonly",
  FormData: "readonly",
  Headers: "readonly",
  Request: "readonly",
  Response: "readonly",
  URL: "readonly",
  WebSocket: "readonly",
  clearTimeout: "readonly",
  console: "readonly",
  document: "readonly",
  fetch: "readonly",
  globalThis: "readonly",
  localStorage: "readonly",
  location: "readonly",
  navigator: "readonly",
  process: "readonly",
  requestAnimationFrame: "readonly",
  setTimeout: "readonly",
  window: "readonly",
};

const nodeGlobals = {
  console: "readonly",
  process: "readonly",
  URL: "readonly",
};

export default tseslint.config(
  {
    ignores: [
      "coverage",
      "dist",
      "node_modules",
      "playwright-report",
      "test-results",
      "tsconfig.tsbuildinfo",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["scripts/**/*.mjs"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: nodeGlobals,
    },
  },
  {
    files: ["src/**/*.{ts,tsx}", "vite.config.ts"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: browserGlobals,
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      "jsx-a11y": jsxA11y,
      "react-hooks": reactHooks,
    },
    rules: {
      ...jsxA11y.flatConfigs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      // Generated/local preview media has no authored caption track to attach.
      "jsx-a11y/media-has-caption": "off",
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "CallExpression[callee.property.name='catch'][arguments.0.type='ArrowFunctionExpression'][arguments.0.body.type='BlockStatement'][arguments.0.body.body.length=0]",
          message:
            "Do not silently discard promise failures; surface, log, or explicitly document cleanup errors.",
        },
      ],
      "no-undef": "off",
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
  {
    files: ["e2e/**/*.ts", "playwright.config.ts"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: { ...browserGlobals, ...nodeGlobals },
    },
    rules: {
      "no-undef": "off",
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
);
