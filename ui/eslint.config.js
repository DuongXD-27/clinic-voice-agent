import js from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig(
  globalIgnores(["dist", "coverage", "src/lib/api/schema.d.ts"]),
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      tseslint.configs.strictTypeChecked,
      tseslint.configs.stylisticTypeChecked,
      reactHooks.configs.flat["recommended-latest"],
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    rules: {
      "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
      // Chuỗi rỗng từ ô nhập phải rơi về mặc định, nên `||` là đúng với string.
      "@typescript-eslint/prefer-nullish-coalescing": [
        "error",
        { ignorePrimitives: { string: true } },
      ],
    },
  },
  {
    // Component chỉ hiển thị: nhận dữ liệu qua props, không tự gọi mạng. Gọi API nằm ở
    // features/*/api.ts (bọc lib/api/client.ts) để test component chỉ cần MSW hoặc props.
    files: ["src/components/**/*.{ts,tsx}", "src/features/*/components/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-globals": [
        "error",
        { name: "fetch", message: "Gọi API qua features/*/api.ts, không gọi trong component." },
      ],
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["**/lib/api/client", "**/api"],
              message: "Component nhận dữ liệu qua props; hook/page mới được gọi API.",
            },
          ],
        },
      ],
    },
  },
);
